"""
database/positions.py
=====================
Сервісний шар для роботи з таблицею `positions`.

Джерело правди для посад у системі — ця таблиця.
`AVAILABLE_ROLES` у `bot/constants.py` залишається як fallback
для зворотної сумісності під час перехідного періоду.
"""

from __future__ import annotations

import aiosqlite

from . import DB_PATH


# ---------------------------------------------------------------------------
# Читання
# ---------------------------------------------------------------------------

async def get_all_positions() -> list[dict]:
    """Повертає всі посади відсортовані за назвою."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, name, days_count, territorial_type, created_at FROM positions ORDER BY name"
        )
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_position_by_id(position_id: int) -> dict | None:
    """Повертає посаду за id або None."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, name, days_count, territorial_type, created_at FROM positions WHERE id = ?",
            (position_id,),
        )
        row = await cursor.fetchone()
    return dict(row) if row else None


async def get_position_by_name(name: str) -> dict | None:
    """Повертає посаду за назвою або None."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, name, days_count, territorial_type, created_at FROM positions WHERE name = ?",
            (name,),
        )
        row = await cursor.fetchone()
    return dict(row) if row else None


async def get_days_count_for_role(role_name: str) -> int:
    """
    Повертає кількість навчальних днів для посади.
    Якщо посади немає в БД — fallback до глобального DAYS_TOTAL.
    """
    from bot.config import DAYS_TOTAL  # локальний імпорт щоб уникнути циклу

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT days_count FROM positions WHERE name = ?",
            (role_name,),
        )
        row = await cursor.fetchone()

    if row:
        return int(row[0])
    return DAYS_TOTAL


# ---------------------------------------------------------------------------
# Запис
# ---------------------------------------------------------------------------

async def add_position(name: str, days_count: int = 5, territorial_type: str = "ТЗ") -> int:
    """
    Додає нову посаду. Повертає id нового запису.
    Raises ValueError якщо посада з такою назвою вже існує.
    territorial_type: 'ТЗ' (торговий зал) або 'ВВ' (власне виробництво)
    """
    if territorial_type not in ("ТЗ", "ВВ"):
        territorial_type = "ВВ" if name.startswith("ВВ ") else "ТЗ"
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            cursor = await db.execute(
                "INSERT INTO positions (name, days_count, territorial_type) VALUES (?, ?, ?)",
                (name, days_count, territorial_type),
            )
            await db.commit()
            return cursor.lastrowid  # type: ignore[return-value]
        except aiosqlite.IntegrityError:
            raise ValueError(f"Посада '{name}' вже існує.")


async def rename_position(position_id: int, new_name: str) -> None:
    """
    Перейменовує посаду та каскадно оновлює всі пов'язані таблиці:
      - materials.role
      - users.role
      - test_errors.role
      - training_events.role
    Все виконується в одній транзакції.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # Отримуємо стару назву
        cursor = await db.execute(
            "SELECT name FROM positions WHERE id = ?", (position_id,)
        )
        row = await cursor.fetchone()
        if not row:
            raise ValueError(f"Посаду з id={position_id} не знайдено.")
        old_name: str = row[0]

        # Оновлюємо саму таблицю positions
        await db.execute(
            "UPDATE positions SET name = ? WHERE id = ?",
            (new_name, position_id),
        )

        # Каскадне оновлення матеріалів
        await db.execute(
            "UPDATE materials SET role = ? WHERE role = ?",
            (new_name, old_name),
        )

        # Каскадне оновлення користувачів
        await db.execute(
            "UPDATE users SET role = ? WHERE role = ?",
            (new_name, old_name),
        )

        # Каскадне оновлення помилок у тестах
        await db.execute(
            "UPDATE test_errors SET role = ? WHERE role = ?",
            (new_name, old_name),
        )

        # Каскадне оновлення подій навчання
        await db.execute(
            "UPDATE training_events SET role = ? WHERE role = ?",
            (new_name, old_name),
        )

        await db.commit()


async def update_days_count(position_id: int, new_days_count: int) -> None:
    """
    Змінює кількість навчальних днів лише для конкретної посади.
    Не впливає на інші посади.
    """
    if new_days_count < 1 or new_days_count > 30:
        raise ValueError(f"days_count має бути від 1 до 30, отримано: {new_days_count}")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE positions SET days_count = ? WHERE id = ?",
            (new_days_count, position_id),
        )
        await db.commit()


async def update_territorial_type(position_id: int, new_type: str) -> None:
    """
    Змінює тип посади: 'ТЗ' або 'ВВ'.
    Raises ValueError якщо переданий невідомий тип.
    """
    if new_type not in ("ТЗ", "ВВ"):
        raise ValueError(f"territorial_type має бути 'ТЗ' або 'ВВ', отримано: '{new_type}'")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE positions SET territorial_type = ? WHERE id = ?",
            (new_type, position_id),
        )
        await db.commit()


# Alias for backward compatibility
update_position_type = update_territorial_type


async def delete_position(position_id: int) -> None:
    """
    Видаляє посаду з таблиці positions.
    Raises ValueError якщо є користувачі з цією посадою (захист від сирітських даних).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # Перевіряємо назву
        cursor = await db.execute(
            "SELECT name FROM positions WHERE id = ?", (position_id,)
        )
        row = await cursor.fetchone()
        if not row:
            raise ValueError(f"Посаду з id={position_id} не знайдено.")
        role_name: str = row[0]

        # Перевіряємо чи є активні користувачі
        cursor = await db.execute(
            "SELECT COUNT(*) FROM users WHERE role = ?", (role_name,)
        )
        count_row = await cursor.fetchone()
        user_count = count_row[0] if count_row else 0
        if user_count > 0:
            raise ValueError(
                f"Неможливо видалити посаду '{role_name}': "
                f"до неї прив'язано {user_count} користувачів."
            )

        await db.execute("DELETE FROM positions WHERE id = ?", (position_id,))
        await db.commit()


# ---------------------------------------------------------------------------
# Статистика
# ---------------------------------------------------------------------------

async def get_position_stats(position_id: int) -> dict:
    """
    Повертає статистику посади:
    - workers_count: кількість активних працівників (role=name, status IS NULL)
    - interns_count: кількість стажерів
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT name FROM positions WHERE id = ?", (position_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return {"workers_count": 0, "interns_count": 0}
        role_name: str = row[0]

        # Стажери — ті, у кого є manager_id і вони ще не завершили навчання
        cursor = await db.execute(
            """
            SELECT COUNT(*) FROM users
            WHERE role = ? AND manager_id IS NOT NULL
            """,
            (role_name,),
        )
        interns_row = await cursor.fetchone()
        interns_count = interns_row[0] if interns_row else 0

        # Працівники — ті, хто завершив (status = 'Працівник')
        cursor = await db.execute(
            "SELECT COUNT(*) FROM users WHERE role = ? AND status = 'Працівник'",
            (role_name,),
        )
        workers_row = await cursor.fetchone()
        workers_count = workers_row[0] if workers_row else 0

    return {"workers_count": workers_count, "interns_count": interns_count}


__all__ = [
    "get_all_positions",
    "get_position_by_id",
    "get_position_by_name",
    "get_days_count_for_role",
    "add_position",
    "rename_position",
    "update_days_count",
    "update_territorial_type",
    "delete_position",
    "get_position_stats",
]
