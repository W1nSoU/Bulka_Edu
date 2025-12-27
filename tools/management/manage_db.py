#!/usr/bin/env python3
import sys
import os
import asyncio
import aiosqlite

# Добавляем родительскую директорию в sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.mentors import add_mentor, init_mentors_db, get_mentor_by_uid, get_all_mentors
from database.users import register_user, delete_user, get_user_details, set_intern_extra
from database import DB_PATH

async def show_all_mentors():
    print("\n=== Список всіх менторів ===")
    mentors = await get_all_mentors()
    if not mentors:
        print("Немає жодного ментора в базі.")
        return
    print(f"{'ID':<12} {'Username':<20} {'Ім\'я':<30} {'Посада':<20}")
    print("-" * 85)
    for m in mentors:
        print(f"{m.get('uid', ''):<12} @{m.get('username', ''):<19} {m.get('full_name', ''):<30} {m.get('process', ''):<20}")

async def add_new_mentor():
    print("\n=== Додавання нового ментора ===")
    try:
        uid_str = input("Введіть Telegram ID ментора: ").strip()
        if not uid_str.isdigit():
            print("Помилка: Telegram ID має бути цілим числом")
            return
        uid = int(uid_str)
        
        # Перевірка чи вже є цей користувач ментором
        existing_mentor = await get_mentor_by_uid(uid)
        if existing_mentor:
            print(f"Ментор з ID {uid} вже існує в базі!")
            return
            
        position = input("Введіть посаду ментора: ")
        await init_mentors_db()  # Ініціалізуємо базу менторів
        await add_mentor(uid, position)
        print(f"✅ Ментор з ID {uid} успішно доданий!")
    except Exception as e:
        print(f"Помилка при додаванні ментора: {str(e)}")
        
async def add_new_intern():
    print("\n=== Додавання нового стажера ===")
    try:
        uid_str = input("Введіть Telegram ID стажера: ").strip()
        if not uid_str.isdigit():
            print("Помилка: Telegram ID має бути цілим числом")
            return
        uid = int(uid_str)
        
        # Перевірка чи вже існує користувач
        user_details = await get_user_details(uid)
        if user_details:
            print(f"Користувач з ID {uid} вже існує в базі!")
            return
            
        username = input("Введіть username стажера (без @): ")
        full_name = input("Введіть повне ім'я стажера: ")
        
        # Реєструємо користувача
        await register_user(uid, username, full_name)
        
        # Запитуємо додаткову інформацію
        mentor_id_str = input("Введіть ID ментора: ").strip()
        if not mentor_id_str.isdigit():
            print("Помилка: ID ментора має бути цілим числом")
            return
        mentor_id = int(mentor_id_str)
        role = input("Введіть посаду стажера: ")
        city = input("Введіть місто стажера: ")
        
        # Призначаємо ментора і додаткову інформацію
        await set_intern_extra(uid, mentor_id, role, city)
        print(f"✅ Стажер {full_name} з ID {uid} успішно доданий!")
    except Exception as e:
        print(f"Помилка при додаванні стажера: {str(e)}")

async def delete_mentor():
    print("\n=== Видалення ментора ===")
    try:
        uid_str = input("Введіть Telegram ID ментора для видалення: ").strip()
        if not uid_str.isdigit():
            print("Помилка: Telegram ID має бути цілим числом")
            return
        uid = int(uid_str)
        
        # Перевірка чи є такий ментор
        mentor = await get_mentor_by_uid(uid)
        if not mentor:
            print(f"Ментор з ID {uid} не знайдений в базі!")
            return
            
        confirm = input(f"Ви впевнені, що хочете видалити ментора {mentor.get('full_name', uid)}? (y/n): ")
        if confirm.lower() != 'y':
            print("Операцію скасовано")
            return
            
        # Видаляємо ментора з бази
        async with aiosqlite.connect(os.path.join(os.path.dirname(DB_PATH), "mentors.db")) as db:
            await db.execute("DELETE FROM mentors WHERE uid = ?", (uid,))
            await db.commit()
            
        print(f"✅ Ментор з ID {uid} успішно видалений!")
    except Exception as e:
        print(f"Помилка при видаленні ментора: {str(e)}")

async def delete_intern():
    print("\n=== Видалення стажера ===")
    try:
        uid_str = input("Введіть Telegram ID стажера для видалення: ").strip()
        if not uid_str.isdigit():
            print("Помилка: Telegram ID має бути цілим числом")
            return
        uid = int(uid_str)
        
        # Перевірка чи є такий стажер
        user = await get_user_details(uid)
        if not user:
            print(f"Користувач з ID {uid} не знайдений в базі!")
            return
            
        confirm = input(f"Ви впевнені, що хочете видалити стажера {user.get('full_name', uid)}? (y/n): ")
        if confirm.lower() != 'y':
            print("Операцію скасовано")
            return
            
        # Видаляємо стажера
        await delete_user(uid)
        print(f"✅ Стажер з ID {uid} успішно видалений!")
    except Exception as e:
        print(f"Помилка при видаленні стажера: {str(e)}")

async def clear_screen():
    """Очищає термінал для кращого UX"""
    os.system('cls' if os.name == 'nt' else 'clear')

async def main():
    print("="*50)
    print("=== АДМІНІСТРУВАННЯ БАЗОЮ BULKA ===")
    print("="*50)
    print(f"Використовується база даних: {DB_PATH}")
    
    while True:
        await clear_screen()
        print("\nОберіть опцію:")
        print("1. Додати ментора")
        print("2. Додати стажера")
        print("3. Видалити ментора")
        print("4. Видалити стажера")
        print("5. Список всіх менторів")
        print("0. Вихід")
        print("-"*50)
        choice = input("Вкажіть опцію: ").strip()
        print("-"*50)
        if choice == '1':
            await clear_screen()
            await add_new_mentor()
        elif choice == '2':
            await clear_screen()
            await add_new_intern()
        elif choice == '3':
            await clear_screen()
            await delete_mentor()
        elif choice == '4':
            await clear_screen()
            await delete_intern()
        elif choice == '5':
            await clear_screen()
            await show_all_mentors()
        elif choice == '0':
            print("До побачення!")
            break
        else:
            print("Невідома опція. Спробуйте знову.")
        input("\nНатисніть Enter, щоб продовжити...")

if __name__ == "__main__":
    asyncio.run(main())
