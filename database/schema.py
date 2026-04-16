import aiosqlite
from . import DB_PATH
import os

async def init_db():
    """Ініціалізація бази даних"""
    # Переконуємось, що директорія існує
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Створюємо таблицю користувачів
        await db.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            first_seen TIMESTAMP,
            current_block INTEGER DEFAULT 1,
            manager_name TEXT DEFAULT NULL,
            last_activity TIMESTAMP,
            role TEXT DEFAULT NULL,
            city TEXT DEFAULT NULL,
            shop TEXT DEFAULT NULL,
            manager_id INTEGER DEFAULT NULL
        )
        ''')
        
        # Створюємо таблицю для збереження прогресу
        await db.execute('''
        CREATE TABLE IF NOT EXISTS progress (
            user_id INTEGER,
            day INTEGER,
            completed BOOLEAN,
            completed_at TIMESTAMP,
            manual_open INTEGER DEFAULT 0,
            manual_opened_by TEXT DEFAULT NULL,
            PRIMARY KEY (user_id, day),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
        ''')
        
        # Перевіряємо та додаємо колонки до таблиці progress
        cursor = await db.execute("PRAGMA table_info(progress)")
        p_columns = [row[1] for row in await cursor.fetchall()]
        if 'manual_open' not in p_columns:
            await db.execute("ALTER TABLE progress ADD COLUMN manual_open INTEGER DEFAULT 0")
        if 'manual_opened_by' not in p_columns:
            await db.execute("ALTER TABLE progress ADD COLUMN manual_opened_by TEXT DEFAULT NULL")
        
        # Перевіряємо та додаємо колонку last_auto_reminder_at до таблиці users
        cursor = await db.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in await cursor.fetchall()]
        if 'last_auto_reminder_at' not in columns:
            await db.execute("ALTER TABLE users ADD COLUMN last_auto_reminder_at TIMESTAMP")
        if 'day3_question_sent' not in columns:
            await db.execute("ALTER TABLE users ADD COLUMN day3_question_sent BOOLEAN DEFAULT 0")
        if 'shop' not in columns:
            await db.execute("ALTER TABLE users ADD COLUMN shop TEXT DEFAULT NULL")
        if 'status' not in columns:
            await db.execute("ALTER TABLE users ADD COLUMN status TEXT DEFAULT NULL")
        if 'worker_since' not in columns:
            await db.execute("ALTER TABLE users ADD COLUMN worker_since TIMESTAMP")
        # Міграція: старі записи де role='Працівник' → перенести в status
        await db.execute(
            "UPDATE users SET status = 'Працівник' WHERE role = 'Працівник' AND (status IS NULL OR status = '')"
        )

        # Таблиця для відстеження розмов "стажер-керівник"
        await db.execute('''
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            manager_id INTEGER NOT NULL,
            created_at TIMESTAMP NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (manager_id) REFERENCES managers(id)
        )
        ''')

        # Таблиця історії нагадувань
        await db.execute('''
        CREATE TABLE IF NOT EXISTS reminder_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            intern_id INTEGER NOT NULL,
            sender_id INTEGER, -- NULL for auto
            source TEXT NOT NULL, -- 'manager', 'hr', 'auto'
            sent_at TIMESTAMP NOT NULL,
            FOREIGN KEY (intern_id) REFERENCES users(user_id)
        )
        ''')
        
        # Таблиця для відстеження помилок в тестах
        await db.execute('''
        CREATE TABLE IF NOT EXISTS test_errors (
            role TEXT NOT NULL,
            day INTEGER NOT NULL,
            question_idx INTEGER NOT NULL,
            error_count INTEGER DEFAULT 0,
            last_reset_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (role, day, question_idx)
        )
        ''')
        
        # Таблиця для логування запитів до керівників (для звітності)
        await db.execute('''
        CREATE TABLE IF NOT EXISTS support_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
        ''')

        # Історія ключових подій навчального процесу
        await db.execute('''
        CREATE TABLE IF NOT EXISTS training_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            event_type TEXT NOT NULL, -- added | promoted | rejected
            event_at TIMESTAMP NOT NULL,
            actor_id INTEGER,
            full_name TEXT,
            username TEXT,
            city TEXT,
            shop TEXT,
            role TEXT,
            manager_id INTEGER,
            UNIQUE(user_id, event_type)
        )
        ''')

        # Міграція training_events: додаємо колонку shop для аналітики по магазинах
        cursor = await db.execute("PRAGMA table_info(training_events)")
        te_columns = [row[1] for row in await cursor.fetchall()]
        if "shop" not in te_columns:
            await db.execute("ALTER TABLE training_events ADD COLUMN shop TEXT")
        
        await db.commit()
    # print(f"База даних ініціалізована за шляхом: {DB_PATH}")
