import aiosqlite
from . import DB_PATH
import os

# Список посад за замовчуванням — використовується лише для початкового заповнення
# Джерело правди — таблиця `positions` у базі даних
_DEFAULT_ROLES = [
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

def _infer_territorial_type(role_name: str) -> str:
    """Автоматично визначає тип посади: 'ВВ' якщо назва починається з 'ВВ ', інакше 'ТЗ'."""
    return "ВВ" if role_name.startswith("ВВ ") else "ТЗ"

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

        # ============================================================
        # Таблиця посад (positions) — нова архітектура (Крок 1)
        # ============================================================
        await db.execute('''
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            days_count INTEGER NOT NULL DEFAULT 5,
            territorial_type TEXT NOT NULL DEFAULT 'ТЗ',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        # Міграція: додаємо колонку territorial_type якщо її немає (ідемпотентно)
        cursor = await db.execute("PRAGMA table_info(positions)")
        pos_columns = [row[1] for row in await cursor.fetchall()]
        if "territorial_type" not in pos_columns:
            await db.execute("ALTER TABLE positions ADD COLUMN territorial_type TEXT NOT NULL DEFAULT 'ТЗ'")
            # Автоматично призначаємо тип на основі назви для вже існуючих посад
            await db.execute(
                "UPDATE positions SET territorial_type = 'ВВ' WHERE name LIKE 'ВВ %'"
            )
            await db.execute(
                "UPDATE positions SET territorial_type = 'ТЗ' WHERE name NOT LIKE 'ВВ %'"
            )

        # Заповнення посад при першому запуску — INSERT OR IGNORE (ідемпотентно)
        for role_name in _DEFAULT_ROLES:
            t_type = _infer_territorial_type(role_name)
            await db.execute(
                "INSERT OR IGNORE INTO positions (name, days_count, territorial_type) VALUES (?, ?, ?)",
                (role_name, 5, t_type)
            )

        # Автоматичне витягування та міграція будь-яких існуючих посад з таблиці users
        try:
            cursor = await db.execute("SELECT DISTINCT role FROM users WHERE role IS NOT NULL AND role != ''")
            existing_user_roles = [row[0] for row in await cursor.fetchall()]
            for role_name in existing_user_roles:
                role_clean = role_name.strip()
                if role_clean and role_clean not in ("Працівник", "Стажер"):
                    t_type = _infer_territorial_type(role_clean)
                    await db.execute(
                        "INSERT OR IGNORE INTO positions (name, days_count, territorial_type) VALUES (?, ?, ?)",
                        (role_clean, 5, t_type)
                    )
        except Exception:
            pass

        # Автоматичне витягування посад з таблиці materials
        try:
            cursor = await db.execute("SELECT DISTINCT role FROM materials WHERE role IS NOT NULL AND role != '' AND role != 'ALL'")
            existing_material_roles = [row[0] for row in await cursor.fetchall()]
            for role_name in existing_material_roles:
                role_clean = role_name.strip()
                if role_clean:
                    t_type = _infer_territorial_type(role_clean)
                    await db.execute(
                        "INSERT OR IGNORE INTO positions (name, days_count, territorial_type) VALUES (?, ?, ?)",
                        (role_clean, 5, t_type)
                    )
        except Exception:
            pass

        # Синхронізація типу посади для фіксованих посад (ВВ -> 'ВВ', інші -> 'ТЗ')
        await db.execute(
            "UPDATE positions SET territorial_type = 'ВВ' WHERE name LIKE 'ВВ %' AND territorial_type != 'ВВ'"
        )
        await db.execute(
            "UPDATE positions SET territorial_type = 'ТЗ' WHERE name NOT LIKE 'ВВ %' AND (territorial_type IS NULL OR territorial_type = '' OR territorial_type != 'ТЗ')"
        )

        # ============================================================
        # Таблиця міст (cities)
        # ============================================================
        await db.execute('''
        CREATE TABLE IF NOT EXISTS cities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        # Ініціалізація стандартних міст (Хмельницький та Камʼянець-Подільський)
        default_cities = ["Хмельницький", "Камʼянець-Подільський"]
        for city_name in default_cities:
            await db.execute(
                "INSERT OR IGNORE INTO cities (name) VALUES (?)",
                (city_name,)
            )

        cursor = await db.execute("SELECT DISTINCT city FROM users WHERE city IS NOT NULL AND city != ''")
        existing_cities = [row[0] for row in await cursor.fetchall()]
        for city_name in existing_cities:
            await db.execute(
                "INSERT OR IGNORE INTO cities (name) VALUES (?)",
                (city_name,)
            )

        await db.commit()
    # print(f"База даних ініціалізована за шляхом: {DB_PATH}")

    # Ініціалізація підсистеми опитувань
    from .surveys import init_surveys_db
    await init_surveys_db(DB_PATH)

    # Ініціалізація підсистеми новин
    from .news import init_news_db
    await init_news_db(DB_PATH)

    # Ініціалізація підсистеми магазинів
    from .shops import init_shops_db
    await init_shops_db()

