import aiosqlite
from . import DB_PATH
import json

MANAGERS_DB_PATH = DB_PATH.replace("users.db", "managers.db")

async def init_managers_db():
    """Ініціалізація бази даних керівників"""
    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        await db.execute('''
        CREATE TABLE IF NOT EXISTS managers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid INTEGER UNIQUE,
            process TEXT,
            full_name TEXT,
            username TEXT,
            shops TEXT
        )
        ''')
        
        # Add `shops` column if it does not exist
        try:
            await db.execute("SELECT shops FROM managers LIMIT 1")
        except aiosqlite.OperationalError:
            await db.execute("ALTER TABLE managers ADD COLUMN shops TEXT")
            print("Added `shops` column to `managers` table.")

        await db.commit()

async def add_manager(uid, process, full_name=None, username=None, shops: list = None):
    """
    Додає керівника вручну за UID та посадою.
    Якщо full_name та username не передані, вони підтягуються з таблиці users.
    """
    shops_json = json.dumps(shops) if shops else None
    async with aiosqlite.connect(DB_PATH) as users_db, aiosqlite.connect(MANAGERS_DB_PATH) as managers_db:
        # Якщо ім'я або username не надані, спробувати отримати їх з таблиці users
        if full_name is None or username is None:
            cursor = await users_db.execute("SELECT username, full_name FROM users WHERE user_id = ?", (uid,))
            row = await cursor.fetchone()
            if row:
                username_from_db, full_name_from_db = row
                if username is None:
                    username = username_from_db
                if full_name is None:
                    full_name = full_name_from_db

        # Забезпечуємо, що значення не будуть None
        username = username if username else ""
        full_name = full_name if full_name else ""

        await managers_db.execute(
            "INSERT OR REPLACE INTO managers (uid, username, full_name, process, shops) VALUES (?, ?, ?, ?, ?)",
            (uid, username, full_name, process, shops_json)
        )
        await managers_db.commit()
        print(f"Керівник доданий/оновлений: {uid}, @{username}, {full_name}, {process}")

async def get_manager_by_uid(uid):
    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM managers WHERE uid = ?", (uid,))
        manager_row = await cursor.fetchone()
        if not manager_row:
            return None
        
        manager = dict(manager_row)
        if manager.get("shops"):
            try:
                manager["shops"] = json.loads(manager["shops"])
            except (json.JSONDecodeError, TypeError):
                manager["shops"] = []
        else:
            manager["shops"] = []
            
        return manager

async def get_all_managers():
    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM managers")
        manager_rows = await cursor.fetchall()
        managers = []
        for row in manager_rows:
            manager = dict(row)
            if manager.get("shops"):
                try:
                    manager["shops"] = json.loads(manager["shops"])
                except (json.JSONDecodeError, TypeError):
                    manager["shops"] = []
            else:
                manager["shops"] = []
            managers.append(manager)
        return managers

async def delete_manager_by_uid(uid):
    """Видаляє керівника за його Telegram ID."""
    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        await db.execute("DELETE FROM managers WHERE uid = ?", (uid,))
        await db.commit()
        cursor = await db.execute("SELECT * FROM managers WHERE uid = ?", (uid,))
        manager = await cursor.fetchone()
        return dict(manager) if manager else None

async def get_all_developers():
    """Отримує список всіх керівників з роллю 'Developer'."""
    managers = await get_all_managers()
    return [m for m in managers if m.get("process") == "Developer"]

async def get_all_kerivnyky():
    """Отримує список всіх керівників з роллю 'Керівник'."""
    managers = await get_all_managers()
    return [m for m in managers if m.get("process") == "Керівник"]

async def is_manager_user(user_id: int) -> bool:
    """Перевіряє, чи користувач є керівником (role='Керівник') у таблиці managers."""
    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        cursor = await db.execute("SELECT uid FROM managers WHERE uid = ? AND process = 'Керівник'", (user_id,))
        return bool(await cursor.fetchone())