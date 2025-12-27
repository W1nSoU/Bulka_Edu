import aiosqlite
from . import DB_PATH

MANAGERS_DB_PATH = DB_PATH.replace("users.db", "managers.db")

async def init_managers_db():
    """Ініціалізація бази даних керівників"""
    # print(f"Ініціалізація бази керівників за шляхом: {MANAGERS_DB_PATH}")
    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        await db.execute('''
        CREATE TABLE IF NOT EXISTS managers (
            manager_id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid INTEGER UNIQUE,
            username TEXT,
            full_name TEXT,
            process TEXT
        )
        ''')
        await db.commit()
    # print(f"База керівників ініціалізована за шляхом: {MANAGERS_DB_PATH}")

async def add_manager(uid, process):
    """
    Додає керівника вручну за UID та посадою.
    Username та full_name автоматично підтягуються з таблиці users.
    """
    async with aiosqlite.connect(DB_PATH) as users_db, aiosqlite.connect(MANAGERS_DB_PATH) as managers_db:
        # Отримуємо username та full_name з users
        cursor = await users_db.execute("SELECT username, full_name FROM users WHERE user_id = ?", (uid,))
        row = await cursor.fetchone()
        if not row:
            raise ValueError(f"Користувач з uid={uid} не знайдений у базі users.")
        username, full_name = row
        await managers_db.execute(
            "INSERT OR IGNORE INTO managers (uid, username, full_name, process) VALUES (?, ?, ?, ?)",
            (uid, username, full_name, process)
        )
        await managers_db.commit()
        print(f"Керівник доданий: {uid}, @{username}, {full_name}, {process}")

async def get_manager_by_uid(uid):
    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM managers WHERE uid = ?", (uid,))
        manager = await cursor.fetchone()
        return dict(manager) if manager else None

async def get_all_managers():
    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM managers")
        managers = await cursor.fetchall()
        return [dict(m) for m in managers]

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
    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM managers WHERE process = 'Developer' ORDER BY full_name")
        developers = await cursor.fetchall()
        return [dict(d) for d in developers]

async def get_all_kerivnyky():
    """Отримує список всіх керівників з роллю 'Керівник'."""
    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM managers WHERE process = 'Керівник' ORDER BY full_name")
        kerivnyky = await cursor.fetchall()
        return [dict(k) for k in kerivnyky]

