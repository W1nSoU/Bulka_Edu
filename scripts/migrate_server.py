"""
scripts/migrate_server.py
=========================
Комплексний міграційний та діагностичний скрипт для переходу на v2 на сервері.
Запускається ОДИН РАЗ після git pull перед запуском бота.

Що робить скрипт:
  1. 🛡️  Повний бекап ВСІХ баз даних у папку backups/backup_YYYYMMDD_HHMMSS/
  2. 📚 Міграція навчальних матеріалів з users.db -> materials.db (якщо ще були в users.db)
  3. 💼 Міграція та налаштування посад (positions):
     - Створення таблиці positions (name UNIQUE, days_count, territorial_type)
     - Внесення 15 стандартних посад
     - Автоматичний перенос будь-яких існуючих посад із users.role та materials.role
  4. 🏙️ Міграція міст (cities):
     - Внесення Хмельницький та Камʼянець-Подільський
     - Перенос будь-яких міст з users.city
  5. 🏪 Міграція магазинів (shops):
     - Створення таблиці shops (name UNIQUE, city)
     - Заповнення з AVAILABLE_SHOPS
     - Автоматичний перенос магазинів, прив'язаних до працівників (users.shop)
     - Автоматичний перенос магазинів, прив'язаних до керівників (managers.shops)
  6. 🔧 Ідемпотентна перевірка та додавання відсутніх колонок:
     - training_events: shop
     - positions: territorial_type
     - materials: is_enabled, summary
     - managers: shops
  7. 🔔 Ініціалізація бази сповіщень матеріалів (material_notifications.db)
  8. 📊 Звіт цілісності системи: статистика користувачів, керівників, посад та магазинів.

Запуск на сервері:
  sudo /home/admin1/Bulka_Edu/venv/bin/python3 /home/admin1/Bulka_Edu/scripts/migrate_server.py
"""

import os
import sys
import json
import shutil
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

DB_DIR = os.path.join(BASE_DIR, "database")
USERS_DB = os.path.join(DB_DIR, "users.db")
MANAGERS_DB = os.path.join(DB_DIR, "managers.db")
MATERIALS_DB = os.path.join(DB_DIR, "materials.db")
TOKENS_DB = os.path.join(DB_DIR, "tokens.db")
NOTIFICATIONS_DB = os.path.join(DB_DIR, "material_notifications.db")
BACKUPS_DIR = os.path.join(BASE_DIR, "backups")

try:
    from bot.constants import AVAILABLE_ROLES, AVAILABLE_SHOPS, AVAILABLE_CITIES
except ImportError:
    AVAILABLE_ROLES = [
        "Старший продавець", "Керівник", "Продавець-консультант (каса)",
        "Продавець відділу гастрономії", "Продавець відділу кулінарії",
        "Продавець (сер. зміна)", "Продавець-приймальник", "ВВ Завідувач виробництва",
        "ВВ Старший зміни", "ВВ Пекар", "ВВ Піцейолог", "ВВ Кухар", "ВВ Кондитер",
        "ВВ Бариста", "ВВ Керівник мережі кавʼярень",
    ]
    AVAILABLE_CITIES = ["Хмельницький", "Камʼянець-Подільський"]
    AVAILABLE_SHOPS = {}


def infer_territorial_type(role_name: str) -> str:
    return "ВВ" if role_name.strip().startswith("ВВ ") else "ТЗ"


def step0_create_backups():
    print("\n--- [КРОК 0] Повний бекап баз даних ---")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_dir = os.path.join(BACKUPS_DIR, f"backup_{ts}")
    os.makedirs(target_dir, exist_ok=True)

    db_files = [USERS_DB, MANAGERS_DB, MATERIALS_DB, TOKENS_DB, NOTIFICATIONS_DB]
    # Також перевіримо кореневий users.db якщо є
    root_users = os.path.join(BASE_DIR, "users.db")
    if os.path.exists(root_users):
        db_files.append(root_users)

    backed_up = 0
    for db_path in db_files:
        if os.path.exists(db_path):
            fname = "root_users.db" if db_path == root_users else os.path.basename(db_path)
            dst = os.path.join(target_dir, fname)
            shutil.copy2(db_path, dst)
            size_kb = os.path.getsize(dst) / 1024
            print(f"  ✅ Скопійовано: {fname} ({size_kb:.1f} KB)")
            backed_up += 1

    print(f"  📁 Всі бекапи збережено в: {target_dir} ({backed_up} файлів)")
    return target_dir


def step1_migrate_materials():
    print("\n--- [КРОК 1] Перевірка та міграція матеріалів ---")
    if not os.path.exists(USERS_DB):
        print("  ⚠️  users.db не знайдено, пропускаємо крок.")
        return

    src = sqlite3.connect(USERS_DB)
    src.row_factory = sqlite3.Row
    cursor = src.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='materials'")
    has_materials_in_users = cursor.fetchone() is not None

    rows = []
    if has_materials_in_users:
        rows = src.execute("SELECT * FROM materials").fetchall()
    src.close()

    dst = sqlite3.connect(MATERIALS_DB)
    dst.execute("""
        CREATE TABLE IF NOT EXISTS materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            day INTEGER NOT NULL,
            content_type TEXT NOT NULL,
            title TEXT,
            content TEXT,
            resource_url TEXT,
            order_index INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_enabled BOOLEAN DEFAULT 1,
            summary TEXT,
            UNIQUE (role, day, content_type, order_index)
        )
    """)

    # Перевірка додаткових колонок
    col_info = [r[1] for r in dst.execute("PRAGMA table_info(materials)").fetchall()]
    if "is_enabled" not in col_info:
        dst.execute("ALTER TABLE materials ADD COLUMN is_enabled BOOLEAN DEFAULT 1")
    if "summary" not in col_info:
        dst.execute("ALTER TABLE materials ADD COLUMN summary TEXT")

    inserted = 0
    if rows:
        for r in rows:
            try:
                r_dict = dict(r)
                dst.execute(
                    """INSERT OR IGNORE INTO materials
                       (role, day, content_type, title, content, resource_url, order_index, is_enabled)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (r_dict.get("role"), r_dict.get("day"), r_dict.get("content_type"),
                     r_dict.get("title"), r_dict.get("content"), r_dict.get("resource_url"),
                     r_dict.get("order_index", 0), r_dict.get("is_enabled", 1))
                )
                inserted += 1
            except Exception as e:
                pass
        dst.commit()

    total_mats = dst.execute("SELECT COUNT(*) FROM materials").fetchone()[0]
    unique_roles = [r[0] for r in dst.execute("SELECT DISTINCT role FROM materials ORDER BY role").fetchall()]
    dst.close()

    print(f"  ✅ materials.db готовий: {total_mats} матеріалів (ролей: {len(unique_roles)})")


def step2_migrate_positions():
    print("\n--- [КРОК 2] Перевірка та міграція посад (positions) ---")
    if not os.path.exists(USERS_DB):
        return

    conn = sqlite3.connect(USERS_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            days_count INTEGER NOT NULL DEFAULT 5,
            territorial_type TEXT NOT NULL DEFAULT 'ТЗ',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # PRAGMA перевірка
    col_info = [r[1] for r in conn.execute("PRAGMA table_info(positions)").fetchall()]
    if "territorial_type" not in col_info:
        conn.execute("ALTER TABLE positions ADD COLUMN territorial_type TEXT NOT NULL DEFAULT 'ТЗ'")
        conn.execute("UPDATE positions SET territorial_type = 'ВВ' WHERE name LIKE 'ВВ %'")
        conn.execute("UPDATE positions SET territorial_type = 'ТЗ' WHERE name NOT LIKE 'ВВ %'")

    # 1. Заповнення стандартними ролями
    for role in AVAILABLE_ROLES:
        t_type = infer_territorial_type(role)
        conn.execute(
            "INSERT OR IGNORE INTO positions (name, days_count, territorial_type) VALUES (?, ?, ?)",
            (role.strip(), 5, t_type)
        )

    # 2. Органічний збір із існуючих користувачів (users.role)
    try:
        user_roles = [r[0] for r in conn.execute("SELECT DISTINCT role FROM users WHERE role IS NOT NULL AND role != ''").fetchall()]
        for u_role in user_roles:
            u_role_clean = u_role.strip()
            if u_role_clean and u_role_clean not in ("Працівник", "Стажер"):
                t_type = infer_territorial_type(u_role_clean)
                conn.execute(
                    "INSERT OR IGNORE INTO positions (name, days_count, territorial_type) VALUES (?, ?, ?)",
                    (u_role_clean, 5, t_type)
                )
    except Exception as e:
        print(f"  ⚠️  Попередження під час вибірки ролей із users: {e}")

    # 3. Синхронізація territorial_type
    conn.execute("UPDATE positions SET territorial_type = 'ВВ' WHERE name LIKE 'ВВ %' AND territorial_type != 'ВВ'")
    conn.execute("UPDATE positions SET territorial_type = 'ТЗ' WHERE name NOT LIKE 'ВВ %' AND (territorial_type IS NULL OR territorial_type = '' OR territorial_type != 'ТЗ')")

    conn.commit()

    total_positions = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
    pos_list = [r[0] for r in conn.execute("SELECT name FROM positions ORDER BY name").fetchall()]
    conn.close()

    print(f"  ✅ Таблиця positions налаштована: {total_positions} посад.")


def step3_migrate_cities_and_shops():
    print("\n--- [КРОК 3] Перевірка та міграція міст і магазинів ---")
    if not os.path.exists(USERS_DB):
        return

    conn = sqlite3.connect(USERS_DB)
    # Таблиця міст
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    for city in AVAILABLE_CITIES:
        conn.execute("INSERT OR IGNORE INTO cities (name) VALUES (?)", (city.strip(),))

    # Збір міст із користувачів
    try:
        user_cities = [r[0] for r in conn.execute("SELECT DISTINCT city FROM users WHERE city IS NOT NULL AND city != ''").fetchall()]
        for c in user_cities:
            conn.execute("INSERT OR IGNORE INTO cities (name) VALUES (?)", (c.strip(),))
    except Exception:
        pass

    # Таблиця магазинів
    conn.execute("""
        CREATE TABLE IF NOT EXISTS shops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            city TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 1. Заповнення з AVAILABLE_SHOPS
    for city, s_list in AVAILABLE_SHOPS.items():
        for s_name in s_list:
            conn.execute(
                "INSERT OR IGNORE INTO shops (name, city) VALUES (?, ?)",
                (s_name.strip(), city.strip())
            )

    # 2. Органічний збір з працівників (users.shop)
    try:
        user_shops = conn.execute("SELECT DISTINCT shop, city FROM users WHERE shop IS NOT NULL AND shop != ''").fetchall()
        for s_row in user_shops:
            s_name = (s_row[0] or "").strip()
            s_city = (s_row[1] or "Хмельницький").strip()
            if s_name:
                conn.execute(
                    "INSERT OR IGNORE INTO shops (name, city) VALUES (?, ?)",
                    (s_name, s_city)
                )
    except Exception as e:
        print(f"  ⚠️  Попередження під час вибірки магазинів з users: {e}")

    # 3. Органічний збір із керівників (managers.shops)
    if os.path.exists(MANAGERS_DB):
        try:
            m_conn = sqlite3.connect(MANAGERS_DB)
            m_conn.row_factory = sqlite3.Row
            # Перевіряємо наявність колонки shops
            m_cols = [r[1] for r in m_conn.execute("PRAGMA table_info(managers)").fetchall()]
            if "shops" in m_cols:
                m_rows = m_conn.execute("SELECT city, shops FROM managers WHERE shops IS NOT NULL").fetchall()
                for row in m_rows:
                    m_city = (row["city"] or "Хмельницький").strip()
                    m_shops = row["shops"]
                    if not m_shops:
                        continue
                    try:
                        s_list = json.loads(m_shops) if isinstance(m_shops, str) else list(m_shops)
                    except Exception:
                        s_list = [m_shops] if isinstance(m_shops, str) else []
                    for s in s_list:
                        if isinstance(s, str) and s.strip():
                            conn.execute(
                                "INSERT OR IGNORE INTO shops (name, city) VALUES (?, ?)",
                                (s.strip(), m_city)
                            )
            m_conn.close()
        except Exception as e:
            print(f"  ⚠️  Попередження під час вибірки магазинів з managers: {e}")

    conn.commit()

    total_cities = conn.execute("SELECT COUNT(*) FROM cities").fetchone()[0]
    total_shops = conn.execute("SELECT COUNT(*) FROM shops").fetchone()[0]
    conn.close()

    print(f"  ✅ Міста та магазини налаштовані: {total_cities} міст, {total_shops} магазинів.")


def step4_verify_columns_and_tables():
    print("\n--- [КРОК 4] Ідемпотентна перевірка та додавання колонок ---")
    if os.path.exists(USERS_DB):
        conn = sqlite3.connect(USERS_DB)
        # training_events.shop
        has_te = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='training_events'").fetchone() is not None
        if has_te:
            te_cols = [r[1] for r in conn.execute("PRAGMA table_info(training_events)").fetchall()]
            if "shop" not in te_cols:
                conn.execute("ALTER TABLE training_events ADD COLUMN shop TEXT")
                print("  ✅ Додано колонку shop у training_events")

        # users.status
        u_cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "status" not in u_cols:
            conn.execute("ALTER TABLE users ADD COLUMN status TEXT")
            print("  ✅ Додано колонку status у users")

        # Міграція старих записів де role='Працівник' -> status='Працівник'
        conn.execute("UPDATE users SET status = 'Працівник' WHERE role = 'Працівник' AND (status IS NULL OR status = '')")
        conn.commit()
        conn.close()

    # managers.shops та інші колонки
    if os.path.exists(MANAGERS_DB):
        m_conn = sqlite3.connect(MANAGERS_DB)
        m_cols = [r[1] for r in m_conn.execute("PRAGMA table_info(managers)").fetchall()]
        if "shops" not in m_cols:
            m_conn.execute("ALTER TABLE managers ADD COLUMN shops TEXT DEFAULT '[]'")
            print("  ✅ Додано колонку shops у managers")
        if "city" not in m_cols:
            m_conn.execute("ALTER TABLE managers ADD COLUMN city TEXT")
        if "responsible_uid" not in m_cols:
            m_conn.execute("ALTER TABLE managers ADD COLUMN responsible_uid INTEGER")
        if "territorial_type" not in m_cols:
            m_conn.execute("ALTER TABLE managers ADD COLUMN territorial_type TEXT")
        if "status" not in m_cols:
            m_conn.execute("ALTER TABLE managers ADD COLUMN status TEXT DEFAULT 'active'")
            m_conn.execute("UPDATE managers SET status = 'active' WHERE status IS NULL")
            print("  ✅ Додано колонку status у managers")
        if "fired_at" not in m_cols:
            m_conn.execute("ALTER TABLE managers ADD COLUMN fired_at TIMESTAMP DEFAULT NULL")
        m_conn.commit()
        m_conn.close()

    # material_notifications.db
    n_conn = sqlite3.connect(NOTIFICATIONS_DB)
    n_conn.execute("""
        CREATE TABLE IF NOT EXISTS material_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            material_id INTEGER,
            change_type TEXT NOT NULL,
            role TEXT NOT NULL,
            day INTEGER NOT NULL,
            old_title TEXT,
            new_title TEXT,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notified_at TIMESTAMP,
            is_notified BOOLEAN DEFAULT 0
        )
    """)
    n_conn.commit()
    n_conn.close()
    print("  ✅ База material_notifications.db перевірена.")


def step5_health_report():
    print("\n--- [КРОК 5] Звіт цілісності та стану системи ---")
    if os.path.exists(USERS_DB):
        conn = sqlite3.connect(USERS_DB)
        u_total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        workers = conn.execute("SELECT COUNT(*) FROM users WHERE status = 'Працівник'").fetchone()[0]
        trainees = conn.execute("SELECT COUNT(*) FROM users WHERE (status != 'Працівник' OR status IS NULL) AND (role != 'Керівник' OR role IS NULL)").fetchone()[0]
        positions = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
        shops = conn.execute("SELECT COUNT(*) FROM shops").fetchone()[0]
        cities = conn.execute("SELECT COUNT(*) FROM cities").fetchone()[0]

        # Перевірка працівників без прив'язки до магазину
        no_shop = conn.execute("SELECT COUNT(*) FROM users WHERE (shop IS NULL OR shop = '') AND status = 'Працівник'").fetchone()[0]
        conn.close()

        print(f"  👥 Всього користувачів: {u_total}")
        print(f"     • Працівників: {workers}")
        print(f"     • Стажерів: {trainees}")
        if no_shop > 0:
            print(f"     • Працівників без вказаного магазину: {no_shop}")
        print(f"  💼 Зареєстровано посад: {positions}")
        print(f"  🏪 Зареєстровано магазинів: {shops} (міст: {cities})")

    if os.path.exists(MANAGERS_DB):
        m_conn = sqlite3.connect(MANAGERS_DB)
        m_cols = [r[1] for r in m_conn.execute("PRAGMA table_info(managers)").fetchall()]
        m_total = m_conn.execute("SELECT COUNT(*) FROM managers").fetchone()[0]
        if "status" in m_cols:
            m_active = m_conn.execute("SELECT COUNT(*) FROM managers WHERE status = 'active'").fetchone()[0]
            print(f"  👔 Керівників у базі: {m_total} (активних: {m_active})")
        else:
            print(f"  👔 Керівників у базі: {m_total}")
        m_conn.close()


def main():
    print("=" * 60)
    print("  🥐 BULKA EDU — Міграція на v2 (Посади, Магазини, Матеріали)")
    print(f"  Час запуску: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 0. Автоматичний бекап
    step0_create_backups()

    # 1. Матеріали
    step1_migrate_materials()

    # 2. Посади
    step2_migrate_positions()

    # 3. Міста та Магазини
    step3_migrate_cities_and_shops()

    # 4. Колонки та таблиці
    step4_verify_columns_and_tables()

    # 5. Підсумковий звіт
    step5_health_report()

    print("\n" + "=" * 60)
    print("  🎉 Міграція успішно завершена! Тепер можна запускати бота.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
