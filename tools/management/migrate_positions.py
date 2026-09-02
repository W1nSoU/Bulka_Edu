#!/usr/bin/env python3
"""
tools/management/migrate_positions.py
======================================
Ідемпотентна міграція: заповнення таблиці `positions` з DEFAULT_ROLES.

Безпечно запускати на живому сервері без зупинки бота.
При повторному запуску — не дублює дані (INSERT OR IGNORE).

Використання:
    python tools/management/migrate_positions.py

    # З вказівкою шляху до БД (для тестів):
    BULKA_DB_PATH=/path/to/users.db python tools/management/migrate_positions.py
"""

import asyncio
import os
import sys

# Додаємо корінь проекту до шляху, щоб можна було запускати зі скрипта
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import aiosqlite

# Шлях до БД — можна перевизначити через змінну оточення
_DB_PATH_ENV = os.environ.get("BULKA_DB_PATH", "")
if _DB_PATH_ENV:
    DB_PATH = _DB_PATH_ENV
else:
    from database import DB_PATH  # type: ignore

# Список посад за замовчуванням (15 ролей)
DEFAULT_ROLES = [
    "Старший продавець",
    "Керівник",
    "Продавець-консультант (каса)",
    "Продавець відділу гастрономії",
    "Продавець відділу кулінарії",
    "Продавець (сер. зміна)",
    "Продавець-приймальник",
    "ВВ Завідувач виробництва",
    "ВВ Старший зміни",
    "ВВ Пекар",
    "ВВ Піцейолог",
    "ВВ Кухар",
    "ВВ Кондитер",
    "ВВ Бариста",
    "ВВ Керівник мережі кавʼярень",
]


async def run_migration() -> None:
    print(f"📦 Підключення до БД: {DB_PATH}")

    if not os.path.exists(DB_PATH):
        print(f"❌ Файл БД не знайдено: {DB_PATH}")
        sys.exit(1)

    async with aiosqlite.connect(DB_PATH) as db:
        # 1. Створення таблиці якщо не існує
        await db.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            days_count INTEGER NOT NULL DEFAULT 5,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        await db.commit()
        print("✅ Таблиця positions — перевірено/створено.")

        # 2. Заповнення посад (INSERT OR IGNORE — ідемпотентно)
        inserted = 0
        skipped = 0
        for role_name in DEFAULT_ROLES:
            cursor = await db.execute(
                "INSERT OR IGNORE INTO positions (name, days_count) VALUES (?, ?)",
                (role_name, 5),
            )
            if cursor.rowcount > 0:
                print(f"  ➕ Додано: {role_name}")
                inserted += 1
            else:
                print(f"  ⏩ Вже існує: {role_name}")
                skipped += 1

        await db.commit()

        # 3. Підсумок
        cursor = await db.execute("SELECT COUNT(*) FROM positions")
        total_row = await cursor.fetchone()
        total = total_row[0] if total_row else 0

        print(f"\n📊 Результат:")
        print(f"   Додано нових: {inserted}")
        print(f"   Вже існували: {skipped}")
        print(f"   Всього посад у БД: {total}")
        print("\n✅ Міграція завершена успішно.")


if __name__ == "__main__":
    asyncio.run(run_migration())
