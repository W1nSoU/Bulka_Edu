"""
Міграційний скрипт для переходу з v1 → v2 на сервері.
Запускати ОДИН РАЗ після деплою нового коду, але ДО запуску бота.

Що робить:
  1. Копіює матеріали з users.db → materials.db
  2. Перевіряє та попереджає про process='Developer' в managers.db
  3. Перевіряє hr_users (нічого не робить, тільки звітує)

Запуск:
  sudo /home/admin1/Bulka_Edu/venv/bin/python3 /home/admin1/Bulka_Edu/scripts/migrate_server.py
"""

import sqlite3
import os
import shutil
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_DIR = os.path.join(BASE_DIR, "database")

USERS_DB   = os.path.join(DB_DIR, "users.db")
MATERIALS_DB = os.path.join(DB_DIR, "materials.db")
MANAGERS_DB  = os.path.join(DB_DIR, "managers.db")


def backup(path: str):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{path}.backup_{ts}"
    shutil.copy2(path, backup_path)
    print(f"  ✅ Backup: {backup_path}")
    return backup_path


def step1_migrate_materials():
    print("\n=== КРОК 1: Міграція матеріалів users.db → materials.db ===")

    # Читаємо з users.db
    src = sqlite3.connect(USERS_DB)
    src.row_factory = sqlite3.Row
    rows = src.execute("SELECT * FROM materials").fetchall()
    src.close()

    if not rows:
        print("  ⚠️  Матеріалів в users.db не знайдено — нічого мігрувати.")
        return

    print(f"  Знайдено {len(rows)} матеріалів для міграції.")

    # Бекап materials.db якщо існує
    if os.path.exists(MATERIALS_DB) and os.path.getsize(MATERIALS_DB) > 0:
        backup(MATERIALS_DB)

    # Записуємо в materials.db
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
            UNIQUE (role, day, content_type, order_index)
        )
    """)

    inserted = 0
    skipped = 0
    for r in rows:
        try:
            dst.execute(
                """INSERT OR IGNORE INTO materials
                   (role, day, content_type, title, content, resource_url, order_index, is_enabled)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (r["role"], r["day"], r["content_type"], r["title"],
                 r["content"], r["resource_url"], r["order_index"], r["is_enabled"])
            )
            inserted += 1
        except Exception as e:
            print(f"  ⚠️  Пропущено запис id={r['id']}: {e}")
            skipped += 1

    dst.commit()
    dst.close()

    print(f"  ✅ Мігровано: {inserted}, пропущено: {skipped}")

    # Перевірка
    check = sqlite3.connect(MATERIALS_DB)
    count = check.execute("SELECT COUNT(*) FROM materials").fetchone()[0]
    roles = check.execute("SELECT DISTINCT role FROM materials ORDER BY role").fetchall()
    check.close()
    print(f"  ✅ В materials.db тепер {count} записів.")
    print(f"  Ролі: {[r[0] for r in roles]}")


def step2_check_managers():
    print("\n=== КРОК 2: Перевірка managers.db ===")
    conn = sqlite3.connect(MANAGERS_DB)
    rows = conn.execute("SELECT uid, full_name, process, status FROM managers").fetchall()
    conn.close()

    known_processes = {'Керівник', 'Керівник Стажер', 'Наглядач', 'Територіал'}
    problems = [r for r in rows if r[2] not in known_processes]

    if not problems:
        print("  ✅ Всі process-значення сумісні з новим кодом.")
    else:
        print(f"  🔴 Знайдено {len(problems)} записів з невідомим process:")
        for r in problems:
            print(f"     uid={r[0]}, name={r[1]}, process={r[2]}, status={r[3]}")
        print()
        print("  ⚠️  Ці користувачі НЕ матимуть доступу до адмін-меню після деплою.")
        print("  Якщо 'Developer' — це адміністратор бота, додай його uid в .env як DEVELOPER_ID")
        print("  або виправ вручну:")
        for r in problems:
            print(f"     UPDATE managers SET process='Керівник' WHERE uid={r[0]};  -- якщо це керівник")


def step3_check_hr_users():
    print("\n=== КРОК 3: Перевірка hr_users ===")
    conn = sqlite3.connect(USERS_DB)
    count = conn.execute("SELECT COUNT(*) FROM hr_users").fetchone()[0]
    conn.close()
    print(f"  ℹ️  hr_users: {count} записів. Нова версія цю таблицю не використовує — дані збережуться, але ігноруватимуться.")


def main():
    print("=" * 50)
    print("  BULKA EDU — Міграція v1 → v2")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    # Бекап перед всім
    print("\n--- Backup ---")
    backup(USERS_DB)
    backup(MANAGERS_DB)

    step1_migrate_materials()
    step2_check_managers()
    step3_check_hr_users()

    print("\n" + "=" * 50)
    print("  Міграція завершена. Тепер можна запускати бота.")
    print("=" * 50)


if __name__ == "__main__":
    main()
