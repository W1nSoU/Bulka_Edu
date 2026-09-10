from __future__ import annotations
import aiosqlite
from database import DB_PATH
import logging
from database.materials import update_materials_role_name

logger = logging.getLogger(__name__)

async def get_all_positions():
    """Повертає список усіх посад з їх даними"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM positions ORDER BY name")
        return [dict(row) for row in await cursor.fetchall()]

async def get_position_by_id(position_id: int):
    """Повертає інформацію про посаду за ID"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM positions WHERE id = ?", (position_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
        
async def get_position_by_name(name: str):
    """Повертає інформацію про посаду за назвою"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM positions WHERE name = ?", (name,))
        row = await cursor.fetchone()
        return dict(row) if row else None

def _infer_territorial_type(name: str) -> str:
    """'ВВ' якщо назва починається з 'ВВ ', інакше 'ТЗ'."""
    return "ВВ" if name.startswith("ВВ ") else "ТЗ"


async def add_position(name: str, days_count: int = 5, territorial_type: str | None = None):
    """Додає нову посаду. territorial_type: 'ТЗ'/'ВВ'; якщо None — визначається автоматично за назвою."""
    t_type = territorial_type if territorial_type in ("ТЗ", "ВВ") else _infer_territorial_type(name)
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO positions (name, days_count, territorial_type) VALUES (?, ?, ?)",
                (name, days_count, t_type)
            )
            await db.commit()
            return True
    except aiosqlite.IntegrityError:
        return False
    except Exception as e:
        logger.error(f"Error adding position: {e}")
        return False


async def update_position_type(position_id: int, new_type: str) -> bool:
    """Змінює тип посади ('ТЗ' або 'ВВ'). Повертає True якщо успішно."""
    if new_type not in ("ТЗ", "ВВ"):
        return False
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE positions SET territorial_type = ? WHERE id = ?",
                (new_type, position_id)
            )
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Error updating position type: {e}")
        return False

async def update_position_days(position_id: int, new_days: int):
    """Оновлює кількість днів навчання для посади"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE positions SET days_count = ? WHERE id = ?",
                (new_days, position_id)
            )
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Error updating position days: {e}")
        return False

async def update_position_name(position_id: int, new_name: str):
    """Оновлює назву посади та робить каскадне оновлення"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Отримуємо стару назву
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT name FROM positions WHERE id = ?", (position_id,))
            row = await cursor.fetchone()
            if not row:
                return False
            
            old_name = row['name']
            
            # 1. Оновлюємо в самій таблиці positions
            await db.execute(
                "UPDATE positions SET name = ? WHERE id = ?",
                (new_name, position_id)
            )
            
            # 2. Каскадне оновлення в users
            await db.execute(
                "UPDATE users SET role = ? WHERE role = ?",
                (new_name, old_name)
            )
            
            # 3. Каскадне оновлення в test_errors
            await db.execute(
                "UPDATE test_errors SET role = ? WHERE role = ?",
                (new_name, old_name)
            )
            
            # 4. Каскадне оновлення в training_events
            await db.execute(
                "UPDATE training_events SET role = ? WHERE role = ?",
                (new_name, old_name)
            )
            
            await db.commit()
            
            # 5. Оновлення файлів матеріалів
            await update_materials_role_name(old_name, new_name)

            # 6. Каскадне оновлення токенів
            try:
                from database.tokens import TOKENS_DB_PATH
                async with aiosqlite.connect(TOKENS_DB_PATH) as tdb:
                    await tdb.execute(
                        "UPDATE tokens SET role = ? WHERE role = ?",
                        (new_name, old_name),
                    )
                    await tdb.commit()
            except Exception as te:
                logger.warning(f"Could not update role in tokens.db: {te}")

            return True
    except aiosqlite.IntegrityError:
        # Посада з такою назвою вже існує
        return False
    except Exception as e:
        logger.error(f"Error updating position name: {e}")
        return False


async def delete_position(position_id: int) -> tuple[bool, str]:
    """
    Видаляє посаду, якщо за нею не закріплено жодного користувача.
    Каскадно видаляє навчальні матеріали та невикористані токени цієї посади.
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT name FROM positions WHERE id = ?", (position_id,))
            row = await cursor.fetchone()
            if not row:
                return False, "Посаду не знайдено."
            role_name = row["name"]

            cursor = await db.execute("SELECT COUNT(*) FROM users WHERE role = ?", (role_name,))
            count_row = await cursor.fetchone()
            user_count = count_row[0] if count_row else 0
            if user_count > 0:
                return False, f"Неможливо видалити посаду '{role_name}': за нею закріплено {user_count} користувачів."

            # Видаляємо матеріали цієї посади
            await db.execute("DELETE FROM materials WHERE role = ?", (role_name,))
            # Видаляємо саму посаду
            await db.execute("DELETE FROM positions WHERE id = ?", (position_id,))
            await db.commit()

        # Видаляємо невикористані токени цієї посади
        try:
            from database.tokens import TOKENS_DB_PATH
            async with aiosqlite.connect(TOKENS_DB_PATH) as tdb:
                await tdb.execute(
                    "DELETE FROM tokens WHERE role = ? AND used_by IS NULL",
                    (role_name,),
                )
                await tdb.commit()
        except Exception as te:
            logger.warning(f"Could not delete tokens for role {role_name}: {te}")

        return True, "Посаду успішно видалено."
    except Exception as e:
        logger.error(f"Error deleting position {position_id}: {e}")
        return False, f"Помилка видалення: {e}"

async def get_position_stats(position_name: str):
    """Повертає статистику по посаді (кількість працівників/стажерів)"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Стажери (ті, хто зараз проходять навчання)
        cursor_interns = await db.execute(
            "SELECT COUNT(*) FROM users WHERE role = ? AND status = 'Стажер'", 
            (position_name,)
        )
        interns_count = (await cursor_interns.fetchone())[0]
        
        # Працівники (ті, хто вже пройшли навчання)
        cursor_workers = await db.execute(
            "SELECT COUNT(*) FROM users WHERE role = ? AND status = 'Працівник'", 
            (position_name,)
        )
        workers_count = (await cursor_workers.fetchone())[0]
        
        return {
            "interns_count": interns_count,
            "workers_count": workers_count,
            "total": interns_count + workers_count
        }
