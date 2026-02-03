import aiosqlite
from typing import Optional
from datetime import datetime, timedelta
import pytz
from bot.config import TIMEZONE
from . import DB_PATH
from database.managers import MANAGERS_DB_PATH, get_manager_by_uid

async def register_user(user_id, username=None, full_name=None):
    """Реєструє нового користувача або оновлює дані існуючого"""
    now = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")
    
    # Забезпечуємо, що full_name не буде None
    full_name = full_name if full_name else ""
    username = username if username else ""

    async with aiosqlite.connect(DB_PATH) as db:
        # Перевіряємо, чи користувач вже існує
        cursor = await db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        user = await cursor.fetchone()
        
        if user:
            # Оновлюємо існуючого користувача
            await db.execute(
                "UPDATE users SET username = ?, full_name = ?, last_activity = ? WHERE user_id = ?",
                (username, full_name, now, user_id)
            ) 
            # Виводимо в термінал про оновлення користувача в базі
            # Коментуємо, щоб не виводити зайві повідомлення
            # print(
            #     f"Оновлено дані користувача: {user_id}, username: {username}, full_name: {full_name}, last_activity: {now}"
            # )
        else:
            # Додаємо нового користувача
            await db.execute(
                "INSERT INTO users (user_id, username, full_name, first_seen, current_block, last_activity) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, username, full_name, now, 1, now)
            )
            # print(f"Зареєстровано нового користувача: {user_id}, {username}, {full_name}")
        
        await db.commit()

async def update_progress(user_id, day, completed=True):
    """Оновлює прогрес користувача"""
    now = datetime.now(pytz.timezone(TIMEZONE))
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Перевіряємо чи існує запис
        cursor = await db.execute(
            "SELECT * FROM progress WHERE user_id = ? AND day = ?", 
            (user_id, day)
        )
        record = await cursor.fetchone()
        
        if record:
            # Оновлюємо існуючий запис
            await db.execute(
                "UPDATE progress SET completed = ?, completed_at = ? WHERE user_id = ? AND day = ?",
                (completed, now_str, user_id, day)
            )
        else:
            # Створюємо новий запис
            await db.execute(
                "INSERT INTO progress (user_id, day, completed, completed_at) VALUES (?, ?, ?, ?)",
                (user_id, day, completed, now_str)
            )
        
        # Оновлюємо поточний блок навчання користувача
        await db.execute(
            "UPDATE users SET current_block = CASE WHEN current_block < ? THEN ? ELSE current_block END WHERE user_id = ?",
            (day, day, user_id)
        )
        
        await db.commit()
    
    return now  # Повертаємо datetime об'єкт для використання в інших функціях

async def set_manager(user_id, manager_name):
    """Встановлює ім'я керівника для користувача"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET manager_name = ? WHERE user_id = ?",
            (manager_name, user_id)
        )
        await db.commit()

async def get_all_users():
    """Отримує список всіх користувачів"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users ORDER BY last_activity DESC")
        users = await cursor.fetchall()
        return [dict(user) for user in users]

async def get_user_progress(user_id):
    """Отримує прогрес конкретного користувача"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM progress WHERE user_id = ? ORDER BY day", 
            (user_id,)
        )
        progress = await cursor.fetchall()
        return [dict(p) for p in progress]

async def get_manager_students(manager_name):
    """Отримати список користувачів для конкретного керівника"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE manager_name = ? ORDER BY last_activity DESC",
            (manager_name,)
        )
        users = await cursor.fetchall()
        return [dict(user) for user in users]

async def set_intern_extra(user_id, manager_id, role, city, shop=None):
    """Оновлює додаткові поля для стажера: manager_id, role, city, shop"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET manager_id = ?, role = ?, city = ?, shop = ? WHERE user_id = ?",
            (manager_id, role, city, shop, user_id)
        )
        await db.commit()
        # print(f"Оновлено дані стажера: {user_id}, керівник: {manager_id}, посада: {role}, місто: {city}, магазин: {shop}")

async def delete_user(user_id):
    """Видаляє користувача та його прогрес з бази"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM progress WHERE user_id = ?", (user_id,))
        await db.commit()

async def get_user_details(user_id):
    """Отримує детальну інформацію про користувача"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE user_id = ?", 
            (user_id,)
        )
        user = await cursor.fetchone()
        return dict(user) if user else None

async def get_manager_interns(manager_id):

    """Отримує список всіх стажерів конкретного керівника"""

    async with aiosqlite.connect(DB_PATH) as db:

        db.row_factory = aiosqlite.Row

        cursor = await db.execute(

            "SELECT * FROM users WHERE manager_id = ? ORDER BY last_activity DESC",

            (manager_id,)

        )

        interns = await cursor.fetchall()

        return [dict(intern) for intern in interns]

async def get_all_active_users(days=3):
    """Отримує список всіх активних користувачів (активні протягом останніх N днів)"""
    cutoff_date = (datetime.now(pytz.timezone(TIMEZONE)) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE last_activity >= ? ORDER BY last_activity DESC",
            (cutoff_date,)
        )
        users = await cursor.fetchall()
        return [dict(user) for user in users]

async def get_all_inactive_users(days=3):
    """Отримує список всіх неактивних користувачів (не активні більше N днів)"""
    cutoff_date = (datetime.now(pytz.timezone(TIMEZONE)) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE last_activity < ? ORDER BY last_activity ASC",
            (cutoff_date,)
        )
        users = await cursor.fetchall()
        return [dict(user) for user in users]

async def get_inactive_interns_for_manager(manager_id, days=1):
    """Отримує список стажерів, які не були активні вказану кількість днів"""
    cutoff_date = (datetime.now(pytz.timezone(TIMEZONE)) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE manager_id = ? AND last_activity < ? ORDER BY last_activity ASC",
            (manager_id, cutoff_date)
        )
        interns = await cursor.fetchall()
        return [dict(intern) for intern in interns]

async def get_interns_in_progress_for_manager(manager_id):
    """Отримує список стажерів, які не завершили всі дні навчання"""
    from bot.config import DAYS_TOTAL  # Імпортуємо тут, щоб уникнути циклічного імпорту
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Знаходимо стажерів цього керівника
        cursor = await db.execute(
            "SELECT u.* FROM users u WHERE u.manager_id = ?",
            (manager_id,)
        )
        interns = await cursor.fetchall()
        
        # Готуємо список стажерів, які ще навчаються
        in_progress = []
        
        for intern in interns:
            # Рахуємо кількість завершених днів для кожного стажера
            cursor = await db.execute(
                "SELECT COUNT(*) as completed_days FROM progress WHERE user_id = ? AND completed = 1",
                (intern['user_id'],)
            )
            result = await cursor.fetchone()
            completed_days = result['completed_days']
            
            # Якщо завершених днів менше загальної кількості - стажер ще в процесі
            if completed_days < DAYS_TOTAL:
                in_progress.append(dict(intern))
        
        return in_progress

async def update_last_activity(user_id):
    """Оновлює час останньої активності користувача"""
    now = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET last_activity = ? WHERE user_id = ?",
            (now, user_id)
        )
        await db.commit()

async def update_user_current_block(user_id, new_block):
    """Безпосередньо оновлює поточний блок навчання користувача"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Виводимо додаткові дані для діагностики
        cursor = await db.execute("SELECT current_block FROM users WHERE user_id = ?", (user_id,))
        old_block = await cursor.fetchone()
        old_block_value = old_block[0] if old_block else "не знайдено"
        
        # Виконуємо оновлення блоку
        await db.execute(
            "UPDATE users SET current_block = ? WHERE user_id = ?",
            (new_block, user_id)
        )
        await db.commit()
        
        # Перевіряємо, чи відбулося оновлення
        cursor = await db.execute("SELECT current_block FROM users WHERE user_id = ?", (user_id,))
        updated_block = await cursor.fetchone()
        updated_block_value = updated_block[0] if updated_block else "не знайдено"
        
        print(f"📝 Оновлення поточного блоку для користувача {user_id}: {old_block_value} -> {updated_block_value}")
        return updated_block_value

MAX_OPEN_CONVERSATIONS = 2

async def can_start_conversation(user_id: int) -> bool:
    """Перевіряє, чи може стажер почати нову розмову."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM conversations WHERE user_id = ? AND status = 'open'",
            (user_id,)
        )
        result = await cursor.fetchone()
        return result[0] < MAX_OPEN_CONVERSATIONS if result else True

async def create_conversation(user_id: int, manager_id: int) -> None:
    """Створює новий запис про відкриту розмову."""
    now = datetime.now(pytz.timezone(TIMEZONE))
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO conversations (user_id, manager_id, created_at, status) VALUES (?, ?, ?, 'open')",
            (user_id, manager_id, now)
        )
        await db.commit()

async def close_conversation(user_id: int, manager_id: int) -> None:
    """Закриває останню відкриту розмову між стажером та керівником."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Знаходимо останню відкриту розмову, щоб закрити саме її
        cursor = await db.execute(
            "SELECT id FROM conversations WHERE user_id = ? AND manager_id = ? AND status = 'open' ORDER BY created_at DESC LIMIT 1",
            (user_id, manager_id)
        )
        last_conversation = await cursor.fetchone()
        
        if last_conversation:
            await db.execute(
                "UPDATE conversations SET status = 'closed' WHERE id = ?",
                (last_conversation[0],)
            )
            await db.commit()

async def get_inactive_interns_for_auto_reminder(now: datetime, inactive_days: int, cooldown_hours: int) -> list[dict]:
    """Повертає стажерів, які відповідають критеріям для автоматичного нагадування."""
    from bot.config import DAYS_TOTAL
    
    inactive_cutoff = now - timedelta(days=inactive_days)
    cooldown_cutoff = now - timedelta(hours=cooldown_hours)
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # Знаходимо user_id тих, хто завершив курс
        cursor = await db.execute(
            "SELECT user_id FROM progress WHERE completed = 1 GROUP BY user_id HAVING COUNT(day) >= ?",
            (DAYS_TOTAL,)
        )
        completed_users = {row[0] for row in await cursor.fetchall()}
        
        # Отримуємо всіх користувачів
        cursor = await db.execute("SELECT * FROM users")
        all_users = await cursor.fetchall()
        
        eligible_users = []
        for user_row in all_users:
            user = dict(user_row)
            user_id = user["user_id"]
            
            # Пропускаємо, якщо користувач завершив курс
            if user_id in completed_users:
                continue
            
            # Перевірка неактивності
            last_activity_str = user.get("last_activity")
            if not last_activity_str:
                continue
            
            try:
                last_activity_dt = datetime.fromisoformat(last_activity_str).astimezone(pytz.timezone(TIMEZONE))
                if last_activity_dt > inactive_cutoff:
                    continue
            except (ValueError, TypeError):
                continue

            # Перевірка кулдауну
            last_reminder_str = user.get("last_auto_reminder_at")
            if last_reminder_str:
                try:
                    last_reminder_dt = datetime.fromisoformat(last_reminder_str).astimezone(pytz.timezone(TIMEZONE))
                    if last_reminder_dt > cooldown_cutoff:
                        continue
                except (ValueError, TypeError):
                    pass
            
            eligible_users.append(user)
            
        return eligible_users

async def touch_auto_reminder(user_id: int, now: datetime) -> None:
    """Оновлює час останнього автоматичного нагадування для користувача."""
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET last_auto_reminder_at = ? WHERE user_id = ?",
            (now_str, user_id)
        )
        await db.commit()

async def is_day3_question_sent(user_id: int) -> bool:
    """Перевіряє, чи було надіслано питання 3-го дня."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT day3_question_sent FROM users WHERE user_id = ?", (user_id,))
        result = await cursor.fetchone()
        return result[0] == 1 if result else False

async def mark_day3_question_sent(user_id: int) -> None:
    """Позначає, що питання 3-го дня було надіслано."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET day3_question_sent = 1 WHERE user_id = ?", (user_id,))
        await db.commit()

async def get_user_by_username(username: str) -> Optional[dict]:
    """Отримує детальну інформацію про користувача за його username.
    
    Пошук не чутливий до регістру.
    Наприклад, "@Username", "@username", "@USERNAME" - всі знайдуть того самого користувача.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Використовуємо LOWER() для регістронезалежного пошуку
        cursor = await db.execute(
            "SELECT * FROM users WHERE LOWER(username) = LOWER(?)", 
            (username.lstrip('@'),)
        )
        user = await cursor.fetchone()
        return dict(user) if user else None

async def log_reminder(intern_id: int, source: str, sender_id: Optional[int] = None) -> None:
    """Logs a reminder sent to an intern."""
    now = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO reminder_history (intern_id, sender_id, source, sent_at) VALUES (?, ?, ?, ?)",
            (intern_id, sender_id, source, now)
        )
        await db.commit()

async def get_reminder_history(limit: int = 50, offset: int = 0) -> list[dict]:
    """Retrieves the global reminder history, ordered by date descending."""
    history_records = []
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = """
            SELECT rh.*, 
                   u.full_name as intern_name 
            FROM reminder_history rh
            LEFT JOIN users u ON rh.intern_id = u.user_id
            ORDER BY rh.sent_at DESC
            LIMIT ? OFFSET ?
        """
        cursor = await db.execute(query, (limit, offset))
        rows = await cursor.fetchall()
        
        for row in rows:
            record = dict(row)
            # Fetch sender details separately if sender_id exists
            if record["sender_id"]:
                manager_info = await get_manager_by_uid(record["sender_id"])
                if manager_info:
                    record["sender_name"] = manager_info.get("full_name")
                    record["sender_role"] = manager_info.get("process")
                else:
                    record["sender_name"] = None
                    record["sender_role"] = None
            else:
                record["sender_name"] = None
                record["sender_role"] = None
            history_records.append(record)
            
        return history_records

async def get_users_by_city(city: str) -> list[dict]:
    """Retrieves a list of users filtered by city."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE city = ? ORDER BY last_activity DESC",
            (city,)
        )
        users = await cursor.fetchall()
        return [dict(user) for user in users]
    """Retrieves a list of users matching a full name (case-insensitive).
    
    Пошук не чутливий до регістру та знаходить часткові збіги.
    Наприклад, "іван" знайде "Іванов Іван Іванович", "ІВАНОВ", "іванова" тощо.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Використовуємо LOWER() для регістронезалежного пошуку
        cursor = await db.execute(
            "SELECT * FROM users WHERE LOWER(full_name) LIKE LOWER(?)", 
            (f'%{full_name}%',)
        )
        users = await cursor.fetchall()
        return [dict(user) for user in users]

