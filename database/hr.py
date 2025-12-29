import aiosqlite
from . import DB_PATH
from datetime import datetime
import pytz
from bot.config import TIMEZONE
from database.managers import MANAGERS_DB_PATH, is_manager_user # Import is_manager_user

HR_ROLES = ["HR", "Керівник", "Developer"]  # Ролі, які мають доступ до HR-панелі
MANAGERS_DB_PATH = DB_PATH.replace("users.db", "managers.db")

PROTECTED_ROLES = ["Керівник", "Developer"]  # Ролі, які мають додатковий захист

async def init_hr_db():
    """Ініціалізація таблиці HR-ів"""
    # print(f"Ініціалізація HR таблиці за шляхом: {DB_PATH}")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
        CREATE TABLE IF NOT EXISTS hr_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            username TEXT,
            full_name TEXT,
            role TEXT,
            added_at TIMESTAMP
        )
        ''')
        await db.commit()
    # print(f"HR таблиця ініціалізована за шляхом: {DB_PATH}")

async def is_hr_user(user_id):
    """
    Перевіряє, чи має користувач права HR або Керівника.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT role FROM hr_users WHERE user_id = ? AND role IN ('HR', 'Керівник')", (user_id,))
        return bool(await cursor.fetchone())

async def add_hr(user_id, username=None, full_name=None, role="HR"):
    """Додати користувача як HR"""
    now = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")
    
    # Забезпечуємо, що username та full_name не будуть None
    username = username if username else ""
    full_name = full_name if full_name else ""

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO hr_users (user_id, username, full_name, role, added_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, full_name, role, now)
        )
        await db.commit()
    print(f"Додано HR: {user_id}, @{username}, {full_name}, {role}")

async def remove_hr(user_id):
    """Видалити користувача з HR"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM hr_users WHERE user_id = ?", (user_id,))
        await db.commit()
    print(f"Видалено HR: {user_id}")

async def get_all_hrs():
    """Отримати список всіх HR"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM hr_users WHERE role = 'HR' ORDER BY added_at DESC")
        hrs = await cursor.fetchall()
        return [dict(hr) for hr in hrs]

async def get_all_developers():
    """Отримати список всіх розробників"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM hr_users WHERE role = 'Developer' ORDER BY added_at DESC")
        developers = await cursor.fetchall()
        return [dict(dev) for dev in developers]

async def is_privileged_user(user_id):
    """
    Перевіряє, чи користувач має підвищені привілеї (Керівник або Developer)
    """
    from bot.config import MAIN_DEVELOPER_ID
    if user_id == MAIN_DEVELOPER_ID:
        return True
    
    # Тепер перевіряємо також роль Керівника з таблиці managers
    return await is_developer_user(user_id) or await is_hr_user(user_id) or await is_manager_user(user_id)

async def get_user_role(user_id):
    """
    Отримує роль користувача з бази даних
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # 1. Спочатку перевіряємо в hr_users
        cursor = await db.execute("SELECT role FROM hr_users WHERE user_id = ?", (user_id,))
        hr_record = await cursor.fetchone()
        if hr_record and hr_record[0]:
            return hr_record[0]

        # 2. Якщо немає в hr_users, перевіряємо в users
        cursor = await db.execute("SELECT role FROM users WHERE user_id = ?", (user_id,))
        user_record = await cursor.fetchone()
        if user_record and user_record[0]:
            return user_record[0]
            
    # 3. Якщо немає в users, перевіряємо в managers
    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        cursor = await db.execute("SELECT process FROM managers WHERE uid = ?", (user_id,))
        manager_record = await cursor.fetchone()
        if manager_record and manager_record[0]:
            return manager_record[0]
            
    return None

async def get_filtered_managers():
    """
    Отримує список керівників без керівників і розробників
    """
    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM managers WHERE process NOT IN (?, ?) ORDER BY full_name",
            ("Керівник", "Developer")
        )
        managers = await cursor.fetchall()
        return [dict(m) for m in managers]

async def is_developer_user(user_id):
    """
    Перевіряє, чи має користувач права розробника.
    """
    from bot.config import MAIN_DEVELOPER_ID
    if user_id == MAIN_DEVELOPER_ID:
        return True
        
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT role FROM hr_users WHERE user_id = ? AND role = 'Developer'", (user_id,))
        if bool(await cursor.fetchone()):
            return True
    
    # Додаткова перевірка в таблиці managers
    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        cursor = await db.execute("SELECT process FROM managers WHERE uid = ? AND process = 'Developer'", (user_id,))
        return bool(await cursor.fetchone())

async def add_developer_user(user_id, username=None, full_name=None):
    """Додати користувача як Розробника (Developer)"""
    await add_hr(user_id, username, full_name, role="Developer")

async def remove_developer_user(user_id):
    """Видалити користувача з ролі Розробника (Developer)"""
    await remove_hr(user_id)