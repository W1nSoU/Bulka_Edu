import sqlite3
import os

# Скрипт автоматично визначає шлях до бази даних у папці database
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "database", "users.db")

# Мапа замін: "Стара назва": "Нова назва"
ROLES_MAPPING = {
    "ТЗ Старший продавець": "Старший продавець",
    "ТЗ Продавець-консультант (каса)": "Продавець-консультант (каса)",
    "ТЗ Продавець відділу гастрономії": "Продавець відділу гастрономії",
    "ТЗ Продавець відділу кулінарії": "Продавець відділу кулінарії",
    "ТЗ Продавець (сер. зміна)": "Продавець (сер. зміна)",
    "ТЗ Продавець-приймальник": "Продавець-приймальник",
}

def migrate():
    if not os.path.exists(DB_PATH):
        print(f"❌ Помилка: Файл бази даних не знайдено за шляхом: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print(f"🚀 Початок міграції посад у базі даних...")
    print("-" * 60)

    try:
        for old_role, new_role in ROLES_MAPPING.items():
            print(f"🔄 Оновлення: '{old_role}' -> '{new_role}'")
            
            # 1. Оновлюємо таблицю користувачів
            cursor.execute("UPDATE users SET role = ? WHERE role = ?", (new_role, old_role))
            u_count = cursor.rowcount
            
            # 2. Оновлюємо таблицю матеріалів
            cursor.execute("UPDATE materials SET role = ? WHERE role = ?", (new_role, old_role))
            m_count = cursor.rowcount
            
            # 3. Оновлюємо таблицю помилок тестів
            cursor.execute("UPDATE test_errors SET role = ? WHERE role = ?", (new_role, old_role))
            e_count = cursor.rowcount
            
            print(f"   ✅ Результат: Користувачів: {u_count}, Матеріалів: {m_count}, Помилок: {e_count}")

        conn.commit()
        print("-" * 60)
        print("🎉 Міграція завершена! Всі назви посад оновлено.")
        
    except Exception as e:
        conn.rollback()
        print(f"💥 Помилка: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
