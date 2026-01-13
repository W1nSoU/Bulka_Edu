#!/usr/bin/env python3
"""
Тест регістронезалежного пошуку користувачів
"""
import sys
import os
import asyncio

sys.path.insert(0, '/Users/winsou/All/Dev/Bulka')

from database.users import get_user_by_username, get_users_by_full_name

async def test_search():
    print("🧪 ТЕСТ ПОШУКУ КОРИСТУВАЧІВ")
    print("=" * 60)
    
    # Тест 1: Пошук по username
    print("\n1️⃣ ТЕСТ: Пошук по username (регістронезалежний)")
    print("-" * 60)
    
    test_usernames = [
        "@TestUser",
        "@testuser",
        "@TESTUSER",
        "@tEsTuSeR",
        "TestUser",  # без @
        "testuser",
    ]
    
    print("Тестові username варіанти:")
    for username in test_usernames:
        try:
            user = await get_user_by_username(username)
            if user:
                print(f"  ✅ '{username}' → Знайдено: {user.get('full_name')} (ID: {user.get('user_id')})")
            else:
                print(f"  ❌ '{username}' → Не знайдено")
        except Exception as e:
            print(f"  ❌ '{username}' → Помилка: {e}")
    
    # Тест 2: Пошук по ПІБ
    print("\n2️⃣ ТЕСТ: Пошук по ПІБ (регістронезалежний)")
    print("-" * 60)
    
    test_names = [
        "Іванов",
        "іванов",
        "ІВАНОВ",
        "Іван",
        "іван",
        "Петров Петро",
        "петров петро",
        "ПЕТРОВ ПЕТРО",
    ]
    
    print("Тестові ПІБ варіанти:")
    for name in test_names:
        try:
            users = await get_users_by_full_name(name)
            if users:
                print(f"  ✅ '{name}' → Знайдено {len(users)} користувачів:")
                for user in users[:3]:  # Показуємо перші 3
                    print(f"     • {user.get('full_name')} (ID: {user.get('user_id')})")
                if len(users) > 3:
                    print(f"     ... та ще {len(users) - 3}")
            else:
                print(f"  ℹ️ '{name}' → Не знайдено (можливо, немає таких користувачів)")
        except Exception as e:
            print(f"  ❌ '{name}' → Помилка: {e}")
    
    # Тест 3: Часткове співпадіння
    print("\n3️⃣ ТЕСТ: Часткове співпадіння ПІБ")
    print("-" * 60)
    
    partial_names = [
        "ів",  # знайде всіх з "ів" у імені (Іванов, Петрів тощо)
        "ан",  # знайде Іван, Оксана тощо
        "а",   # знайде багато
    ]
    
    for name in partial_names:
        try:
            users = await get_users_by_full_name(name)
            print(f"  '{name}' → Знайдено {len(users)} користувачів")
            if users and len(users) <= 5:
                for user in users:
                    print(f"     • {user.get('full_name')}")
        except Exception as e:
            print(f"  ❌ '{name}' → Помилка: {e}")
    
    # Перевірка SQL запитів
    print("\n4️⃣ ПЕРЕВІРКА SQL ЗАПИТІВ")
    print("-" * 60)
    
    import sqlite3
    
    try:
        conn = sqlite3.connect('/Users/winsou/All/Dev/Bulka/database/users.db')
        cursor = conn.cursor()
        
        # Перевіряємо чи є користувачі взагалі
        cursor.execute("SELECT COUNT(*) FROM users")
        total = cursor.fetchone()[0]
        print(f"Всього користувачів в БД: {total}")
        
        # Перевіряємо приклад регістронезалежного пошуку
        if total > 0:
            cursor.execute("SELECT full_name FROM users LIMIT 1")
            example_name = cursor.fetchone()[0]
            
            print(f"\nПриклад з БД: '{example_name}'")
            
            # Тест регістронезалежного пошуку
            variations = [
                example_name,
                example_name.lower() if example_name else "",
                example_name.upper() if example_name else "",
            ]
            
            for variant in variations:
                if not variant:
                    continue
                cursor.execute(
                    "SELECT COUNT(*) FROM users WHERE LOWER(full_name) LIKE LOWER(?)",
                    (f"%{variant}%",)
                )
                count = cursor.fetchone()[0]
                print(f"  '{variant}' → Знайдено: {count}")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Помилка SQL тесту: {e}")
    
    # Рекомендації
    print("\n5️⃣ РЕЗУЛЬТАТИ ТА РЕКОМЕНДАЦІЇ")
    print("-" * 60)
    print("""
ВИПРАВЛЕННЯ:
✅ get_user_by_username - додано LOWER() для регістронезалежного пошуку
✅ get_users_by_full_name - додано LOWER() для регістронезалежного пошуку
✅ Оновлено текст в UI про можливість пошуку по ПІБ

ОСОБЛИВОСТІ:
• Username пошук: "@TestUser" = "@testuser" = "@TESTUSER"
• ПІБ пошук: "Іванов" = "іванов" = "ІВАНОВ"
• Часткове співпадіння: "іван" знайде "Іванов", "Іванова", "Оліванський"

ПРИКЛАДИ ВИКОРИСТАННЯ:
Dev панель > 👥 Користувачі > 🔍 Пошук

Можна ввести:
1. ID: 123456
2. Username: @username (або @Username, @USERNAME)
3. ПІБ: Іванов Іван (або іванов іван, ІВАНОВ ІВАН)
4. Частина ПІБ: Іван (знайде всіх з "іван" у імені)

ТЕСТУВАННЯ В БОТІ:
1. Відкрийте Dev панель > 👥 Користувачі > 🔍 Пошук
2. Введіть username з різним регістром
3. Перевірте що знаходить одного й того ж користувача
4. Введіть ПІБ з малих літер
5. Перевірте що знаходить користувачів
""")
    
    print("=" * 60)
    print("✅ Тестування завершено")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_search())