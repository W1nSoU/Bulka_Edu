"""
scripts/rollback_server.py
==========================
Скрипт для швидкого та безпечного відновлення баз даних з бекапу.

Використання:
  1. Автоматично відновити останній бекап:
     sudo /home/admin1/Bulka_Edu/venv/bin/python3 /home/admin1/Bulka_Edu/scripts/rollback_server.py --latest

  2. Інтерактивний вибір із списку збережених бекапів:
     sudo /home/admin1/Bulka_Edu/venv/bin/python3 /home/admin1/Bulka_Edu/scripts/rollback_server.py
"""

import os
import sys
import glob
import shutil
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_DIR = os.path.join(BASE_DIR, "database")
BACKUPS_DIR = os.path.join(BASE_DIR, "backups")


def list_backups() -> list[dict]:
    backups = []
    if os.path.exists(BACKUPS_DIR):
        for entry in os.listdir(BACKUPS_DIR):
            full_path = os.path.join(BACKUPS_DIR, entry)
            if os.path.isdir(full_path) and entry.startswith("backup_"):
                files = os.listdir(full_path)
                db_files = [f for f in files if f.endswith(".db")]
                try:
                    # Формат: backup_YYYYMMDD_HHMMSS
                    ts_str = entry.replace("backup_", "")
                    dt = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
                    formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    formatted_time = entry

                backups.append({
                    "path": full_path,
                    "name": entry,
                    "time": formatted_time,
                    "files": db_files,
                })

    # Сортуємо: найновіші першими
    backups.sort(key=lambda b: b["name"], reverse=True)
    return backups


def restore_from_directory(backup_dir: str):
    print(f"\n🔄 Відновлення файлів із: {backup_dir}")
    os.makedirs(DB_DIR, exist_ok=True)

    restored_count = 0
    for fname in os.listdir(backup_dir):
        if not fname.endswith(".db"):
            continue

        src_path = os.path.join(backup_dir, fname)
        if not os.path.isfile(src_path):
            continue

        if fname == "root_users.db":
            # Відновлюємо в корінь якщо був root_users.db
            dst_path = os.path.join(BASE_DIR, "users.db")
        else:
            dst_path = os.path.join(DB_DIR, fname)

        shutil.copy2(src_path, dst_path)
        size_kb = os.path.getsize(dst_path) / 1024
        print(f"  ✅ Відновлено: {os.path.relpath(dst_path, BASE_DIR)} ({size_kb:.1f} KB)")
        restored_count += 1

    print(f"\n🎉 Успішно відновлено {restored_count} баз даних!")
    print("\nНаступні кроки:")
    print("  1. Якщо потрібно відкотити версію коду в Git: git reset --hard HEAD~1")
    print("  2. Запусти бота: sudo systemctl start bulka-edu")
    print("  3. Перевір логи: sudo journalctl -u bulka-edu -f -n 50\n")


def main():
    print("=" * 60)
    print("  🥐 BULKA EDU — Відновлення бази даних з бекапу")
    print("=" * 60)

    backups = list_backups()
    if not backups:
        print("\n❌ Жодної резервної копії не знайдено у папці backups/")
        print("Перевірте наявність файлів вручну: ls -la backups/")
        return

    # Якщо передано аргумент --latest
    if "--latest" in sys.argv or "-l" in sys.argv:
        latest = backups[0]
        print(f"\n⚡ Обрано останній бекап: {latest['name']} ({latest['time']})")
        restore_from_directory(latest["path"])
        return

    print("\nЗнайдені точки відновлення:")
    for idx, b in enumerate(backups, start=1):
        latest_mark = " 🌟 [НАЙСВІЖІШИЙ]" if idx == 1 else ""
        print(f"  [{idx}] {b['time']} — {len(b['files'])} файлів ({', '.join(b['files'])}){latest_mark}")

    print("\nВведіть номер бекапу для відновлення [за замовчуванням 1]: ", end="")
    try:
        user_input = input().strip()
        if not user_input:
            chosen_idx = 1
        else:
            chosen_idx = int(user_input)

        if chosen_idx < 1 or chosen_idx > len(backups):
            print("❌ Некоректний номер бекапу.")
            return

        chosen_backup = backups[chosen_idx - 1]
        print(f"\nВи обрали: {chosen_backup['name']} ({chosen_backup['time']})")
        restore_from_directory(chosen_backup["path"])

    except KeyboardInterrupt:
        print("\nОперацію скасовано.")
    except Exception as e:
        print(f"\n❌ Помилка: {e}")


if __name__ == "__main__":
    main()
