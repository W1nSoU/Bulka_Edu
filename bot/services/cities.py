import aiosqlite
from database import DB_PATH
import logging

logger = logging.getLogger(__name__)

async def get_all_cities():
    """Повертає список усіх міст"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM cities ORDER BY name")
        return [dict(row) for row in await cursor.fetchall()]

async def get_city_by_id(city_id: int):
    """Повертає інформацію про місто за ID"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM cities WHERE id = ?", (city_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
        
async def get_city_by_name(name: str):
    """Повертає інформацію про місто за назвою"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM cities WHERE name = ?", (name,))
        row = await cursor.fetchone()
        return dict(row) if row else None

async def add_city(name: str):
    """Додає нове місто"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO cities (name) VALUES (?)",
                (name,)
            )
            await db.commit()
            return True
    except aiosqlite.IntegrityError:
        # Таке місто вже існує
        return False
    except Exception as e:
        logger.error(f"Error adding city: {e}")
        return False

async def update_city_name(city_id: int, new_name: str):
    """Оновлює назву міста та робить каскадне оновлення"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Отримуємо стару назву
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT name FROM cities WHERE id = ?", (city_id,))
            row = await cursor.fetchone()
            if not row:
                return False
            
            old_name = row['name']
            
            # 1. Оновлюємо в самій таблиці cities
            await db.execute(
                "UPDATE cities SET name = ? WHERE id = ?",
                (new_name, city_id)
            )
            
            # 2. Каскадне оновлення в users
            await db.execute(
                "UPDATE users SET city = ? WHERE city = ?",
                (new_name, old_name)
            )
            
            # 3. Каскадне оновлення в training_events
            await db.execute(
                "UPDATE training_events SET city = ? WHERE city = ?",
                (new_name, old_name)
            )
            
            await db.commit()
            return True
    except aiosqlite.IntegrityError:
        # Місто з такою назвою вже існує
        return False
    except Exception as e:
        logger.error(f"Error updating city name: {e}")
        return False

async def delete_city(city_id: int):
    """Видаляє місто. Не видаляє його у користувачів (вони залишаться зі старою назвою, яку зможуть змінити)"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "DELETE FROM cities WHERE id = ?",
                (city_id,)
            )
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Error deleting city: {e}")
        return False
