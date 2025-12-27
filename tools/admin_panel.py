import sys
import os
import asyncio
from datetime import datetime

# Додаємо батьківську директорію в sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.users import get_user_details, get_user_progress, update_progress, delete_user
from database.users import update_user_current_block, get_all_users
from database.mentors import get_mentor_by_uid, add_mentor, init_mentors_db, get_all_mentors
from state import user_progress, initialize_user_progress, load_all_progress
from config import DAYS_TOTAL, TIMEZONE
import pytz
import aiosqlite
from database import DB_PATH

# Функція для очищення консолі
def clear_console():
    """Очищує консоль для кращого відображення меню"""
    os.system('cls' if os.name == 'nt' else 'clear')

# -------- ФУНКЦІЇ ДЛЯ РОБОТИ З ДНЯМИ --------

async def display_user_days_status(user_id):
    """Відображає статус днів для конкретного стажера"""
    # Отримуємо інформацію про користувача
    user_details = await get_user_details(user_id)
    if not user_details:
        print(f"❌ Користувач з ID {user_id} не знайдений")
        input("\nНатисніть Enter, щоб продовжити...")
        return False
        
    # Завантажуємо поточний прогрес
    await load_all_progress()
    initialize_user_progress(user_id)
    
    # Отримуємо прогрес користувача з бази даних
    progress_list = await get_user_progress(user_id)
    
    # Виводимо загальну інформацію про користувача
    print("\n" + "="*50)
    print(f"👤 Інформація про стажера: {user_details['full_name']} (@{user_details.get('username', 'немає')})")
    print(f"🏢 Посада: {user_details.get('role', 'Не вказано')}, Місто: {user_details.get('city', 'Не вказано')}")
    print(f"⏱️ Остання активність: {user_details.get('last_activity', 'Невідомо')}")
    print("="*50)
    print("\n📊 Статус днів навчання:")
    
    # Відображаємо статус кожного дня
    for day in range(1, DAYS_TOTAL + 1):
        # Шукаємо інформацію про день в прогресі
        day_info = next((p for p in progress_list if p['day'] == day), None)
        
        # Перевіряємо, чи день відкритий вручну
        is_manually_opened = user_progress.get(user_id, {}).get(f"day_{day}", {}).get("manual_open", False)
        
        # Визначаємо статус дня
        if day_info and day_info.get('completed'):
            completed_at = day_info.get('completed_at')
            if isinstance(completed_at, str):
                try:
                    completed_at = datetime.fromisoformat(completed_at)
                except ValueError:
                    completed_at = None
            
            if completed_at:
                completed_time = completed_at.strftime("%Y-%m-%d %H:%M:%S") if completed_at else "Невідомо"
                status = f"✅ Завершено ({completed_time})"
            else:
                status = "✅ Завершено"
        elif is_manually_opened:
            status = "🔓 Відкрито вручну"
        elif day == 1:
            status = "🔓 Завжди відкритий (день 1)"
        else:
            status = "🔒 Закритий"
        
        print(f"  День {day}: {status}")
    
    print("="*50)
    input("\nНатисніть Enter, щоб продовжити...")
    return True

async def parse_day_input(day_input, max_day=DAYS_TOTAL):
    """
    Розбирає введення користувача, підтримує діапазони (наприклад, "3-6")
    Повертає список днів
    """
    try:
        if "-" in day_input:
            start, end = map(int, day_input.split("-"))
            if start < 1 or end > max_day or start > end:
                print(f"❌ Некоректний діапазон днів. Повинно бути від 1 до {max_day}, початок < кінець")
                return []
            return list(range(start, end + 1))
        else:
            day = int(day_input)
            if day < 1 or day > max_day:
                print(f"❌ Некоректний номер дня. Повинен бути від 1 до {max_day}")
                return []
            return [day]
    except ValueError:
        print("❌ Некоректний формат дня. Використовуйте число або діапазон (наприклад, 3-6)")
        return []

async def open_day_for_user(user_id, day):
    """Відкриває вказаний день для користувача"""
    # Перевіряємо, чи існує користувач
    user_details = await get_user_details(user_id)
    if not user_details:
        print(f"❌ Користувач з ID {user_id} не знайдений")
        return False
        
    # Завантажуємо поточний прогрес
    await load_all_progress()
    initialize_user_progress(user_id)
    
    # Відкриваємо день вручну
    if user_id not in user_progress:
        user_progress[user_id] = {}
        
    if f"day_{day}" not in user_progress[user_id]:
        user_progress[user_id][f"day_{day}"] = {}
        
    user_progress[user_id][f"day_{day}"]["manual_open"] = True
    user_progress[user_id][f"day_{day}"]["notified"] = True
    
    print(f"✅ День {day} відкрито для користувача {user_details['full_name']} (ID: {user_id})")
    return True
    
async def close_day_for_user(user_id, day):
    """
    Закриває вказаний день для користувача
    Тепер можна закрити навіть пройдені дні, встановивши їх як непройдені
    """
    if day < 2:  # День 1 не можна закрити
        print(f"❌ День 1 не можна закрити, він завжди доступний.")
        return False
        
    # Перевіряємо, чи існує користувач
    user_details = await get_user_details(user_id)
    if not user_details:
        print(f"❌ Користувач з ID {user_id} не знайдений")
        return False
        
    # Завантажуємо поточний прогрес
    await load_all_progress()
    initialize_user_progress(user_id)
    
    # Закриваємо день (видаляємо ручне відкриття)
    if user_id in user_progress and f"day_{day}" in user_progress[user_id]:
        # Якщо день був пройдений, позначаємо його як непройдений в БД
        if user_progress[user_id][f"day_{day}"].get("completed"):
            # Оновлюємо стан в базі даних
            await update_progress(user_id, day, completed=False)
            # Оновлюємо стан в пам'яті
            user_progress[user_id][f"day_{day}"]["completed"] = False
            print(f"✅ День {day} позначено як непройдений для користувача {user_details['full_name']} (ID: {user_id})")
            
        # Видаляємо ознаку ручного відкриття, якщо є
        if "manual_open" in user_progress[user_id][f"day_{day}"]:
            del user_progress[user_id][f"day_{day}"]["manual_open"]
            print(f"✅ День {day} закрито для користувача {user_details['full_name']} (ID: {user_id})")
            return True
    
    print(f"ℹ️ День {day} і так закритий для користувача {user_details['full_name']} (ID: {user_id})")
    return True

async def update_current_block(user_id, reset_days):
    """Оновлює поточний блок навчання користувача в базі даних"""
    if not reset_days:
        return
        
    # Знаходимо мінімальний день зі скинутих
    min_day = min(reset_days)
    
    # Новий поточний блок - це день перед мінімальним скинутим, але не менше 1
    new_current_block = max(1, min_day - 1)
    
    # Оновлюємо поточний блок в базі даних
    await update_user_current_block(user_id, new_current_block)
    
    print(f"📊 Поточний блок навчання користувача змінено на: День {new_current_block}")

async def reset_user_progress(user_id, days):
    """Скидає прогрес користувача по вказаним дням, позначаючи їх як непройдені"""
    if isinstance(days, int):
        days = [days]
        
    # Перевіряємо, чи існує користувач
    user_details = await get_user_details(user_id)
    if not user_details:
        print(f"❌ Користувач з ID {user_id} не знайдений")
        return False
        
    # Завантажуємо поточний прогрес
    await load_all_progress()
    initialize_user_progress(user_id)
    
    reset_days = []  # Список днів, прогрес яких скинуто
    
    for day in days:
        # Оновлюємо стан в базі даних
        await update_progress(user_id, day, completed=False)
        
        # Оновлюємо стан в пам'яті
        if user_id in user_progress and f"day_{day}" in user_progress[user_id]:
            user_progress[user_id][f"day_{day}"]["completed"] = False
            if "manual_open" in user_progress[user_id][f"day_{day}"]:
                del user_progress[user_id][f"day_{day}"]["manual_open"]
            
            reset_days.append(day)
            print(f"🔄 Прогрес дня {day} скинуто для користувача {user_details['full_name']} (ID: {user_id})")
    
    # Оновлюємо поточний блок користувача в базі даних
    if reset_days:
        await update_current_block(user_id, reset_days)
    
    return True

# -------- ФУНКЦІЇ ДЛЯ РОБОТИ З ЛЮДЬМИ --------

async def delete_user_handler():
    """Функція для видалення користувача з бази даних"""
    user_id_input = input("Введіть ID користувача для видалення: ")
    
    try:
        user_id = int(user_id_input)
        
        # Перевіряємо, чи існує користувач
        user_details = await get_user_details(user_id)
        if not user_details:
            print(f"❌ Користувач з ID {user_id} не знайдений в базі.")
            return
            
        print(f"Знайдено користувача: {user_details.get('full_name', 'Ім`я не вказано')} (@{user_details.get('username', 'без username')})")
        confirm = input(f"Ви впевнені, що хочете видалити цього користувача? (y/n): ")
        
        if confirm.lower() == 'y':
            await delete_user(user_id)
            print(f"✅ Користувач {user_id} успішно видалений з бази.")
        else:
            print("❌ Видалення скасовано.")
            
    except ValueError:
        print("❌ Помилка: ID користувача повинен бути цілим числом")

async def add_mentor_handler():
    """Функція для додавання ментора в базу даних"""
    print("\n" + "="*50)
    print("📝 ДОДАВАННЯ НОВОГО МЕНТОРА")
    print("="*50)
    
    # Ініціалізуємо базу даних менторів
    await init_mentors_db()
    
    try:
        # Запитуємо дані від користувача
        mentor_uid_input = input("Введіть Telegram ID ментора: ")
        try:
            mentor_uid = int(mentor_uid_input)
        except ValueError:
            print("❌ Помилка: ID ментора повинен бути цілим числом")
            return
            
        # Перевіряємо, чи користувач існує в базі даних
        user_details = await get_user_details(mentor_uid)
        if not user_details:
            print(f"❌ Користувач з ID {mentor_uid} не знайдений в базі.")
            print("ℹ️ Ментор повинен спочатку взаємодіяти з ботом як звичайний користувач.")
            return
            
        # Перевіряємо, чи не є вже ментором
        mentor_info = await get_mentor_by_uid(mentor_uid)
        if mentor_info:
            print(f"⚠️ Користувач {user_details.get('full_name')} вже є ментором!")
            print(f"Посада: {mentor_info.get('process', 'Не вказано')}")
            return
            
        mentor_position = input("Введіть посаду ментора: ")
        
        # Додаємо ментора
        await add_mentor(mentor_uid, mentor_position)
        print(f"✅ Ментор успішно доданий: {user_details.get('full_name')} ({mentor_position})")
        
    except Exception as e:
        print(f"❌ Виникла непередбачена помилка: {str(e)}")

async def list_all_users():
    """Виводить список всіх користувачів"""
    print("\n" + "="*50)
    print("👥 СПИСОК ВСІХ КОРИСТУВАЧІВ")
    print("="*50)
    
    users = await get_all_users()
    
    if not users:
        print("📝 База даних порожня - немає зареєстрованих користувачів")
        return
        
    print(f"Всього користувачів: {len(users)}\n")
    
    for i, user in enumerate(users, 1):
        # Отримуємо прогрес користувача
        progress_list = await get_user_progress(user['user_id'])
        completed_days = len([p for p in progress_list if p.get('completed')])
        percent = int(completed_days / DAYS_TOTAL * 100) if DAYS_TOTAL > 0 else 0
        
        # Перевіряємо, чи користувач є ментором
        is_mentor = await get_mentor_by_uid(user['user_id'])
        
        # Формуємо рядок з інформацією про користувача
        mentor_badge = "👑 " if is_mentor else ""
        user_info = (
            f"{mentor_badge}#{i}. {user.get('full_name', 'Не вказано')}"
            f" (@{user.get('username', 'без username')}) [ID: {user['user_id']}]\n"
            f"   Прогрес: {percent}% ({completed_days}/{DAYS_TOTAL})\n"
            f"   Остання активність: {user.get('last_activity', 'Невідомо')}\n"
        )
        
        print(user_info)
    
    print("="*50)

async def list_all_mentors():
    """Виводить список всіх менторів"""
    print("\n" + "="*50)
    print("👑 СПИСОК ВСІХ МЕНТОРІВ")
    print("="*50)
    
    mentors = await get_all_mentors()
    
    if not mentors:
        print("📝 Ще немає зареєстрованих менторів")
        return
        
    print(f"Всього менторів: {len(mentors)}\n")
    
    for i, mentor in enumerate(mentors, 1):
        # Отримуємо інформацію про стажерів ментора
        mentor_id = mentor['uid']
        
        user_info = (
            f"#{i}. {mentor.get('full_name', 'Не вказано')}"
            f" (@{mentor.get('username', 'без username')}) [ID: {mentor_id}]\n"
            f"   Посада: {mentor.get('process', 'Не вказано')}\n"
        )
        
        print(user_info)
    
    print("="*50)

async def find_user():
    """Пошук користувача за ID або ім'ям користувача"""
    print("\n" + "="*50)
    print("🔍 ПОШУК КОРИСТУВАЧА")
    print("="*50)
    
    search_type = input("Оберіть тип пошуку:\n1. За ID\n2. За ім'ям користувача\nВаш вибір: ")
    
    if search_type == "1":
        user_id_input = input("Введіть ID користувача: ")
        try:
            user_id = int(user_id_input)
            user_details = await get_user_details(user_id)
            if user_details:
                print(f"\nЗнайдено користувача: {user_details.get('full_name', 'Ім`я не вказано')} (@{user_details.get('username', 'без username')})")
                print(f"ID: {user_id}")
                print(f"Роль: {user_details.get('role', 'Не вказано')}")
                print(f"Місто: {user_details.get('city', 'Не вказано')}")
                print(f"Остання активність: {user_details.get('last_activity', 'Невідомо')}")
                
                # Перевіряємо, чи користувач є ментором
                mentor_info = await get_mentor_by_uid(user_id)
                if mentor_info:
                    print(f"👑 Користувач є ментором")
                    print(f"Посада ментора: {mentor_info.get('process', 'Не вказано')}")
            else:
                print(f"❌ Користувач з ID {user_id} не знайдений.")
        except ValueError:
            print("❌ Помилка: ID користувача повинен бути цілим числом")
    elif search_type == "2":
        username = input("Введіть ім'я користувача (без @): ")
        
        # Шукаємо всіх користувачів і фільтруємо за username
        users = await get_all_users()
        found_users = [u for u in users if u.get('username') == username]
        
        if found_users:
            print(f"\nЗнайдено {len(found_users)} користувачів з ім'ям @{username}:")
            for i, user in enumerate(found_users, 1):
                print(f"{i}. {user.get('full_name', 'Не вказано')} (ID: {user['user_id']})")
                print(f"   Роль: {user.get('role', 'Не вказано')}")
                print(f"   Місто: {user.get('city', 'Не вказано')}")
                print(f"   Остання активність: {user.get('last_activity', 'Невідомо')}")
                
                # Перевіряємо, чи користувач є ментором
                mentor_info = await get_mentor_by_uid(user['user_id'])
                if mentor_info:
                    print(f"   👑 Користувач є ментором")
                    print(f"   Посада ментора: {mentor_info.get('process', 'Не вказано')}")
                print()
        else:
            print(f"❌ Користувач з ім'ям @{username} не знайдений.")
    else:
        print("❌ Невірний вибір. Спробуйте ще раз.")

# -------- ГОЛОВНЕ МЕНЮ АДМІНІСТРАТИВНОЇ ПАНЕЛІ --------

async def show_people_management_menu():
    """Показує меню для роботи з людьми"""
    while True:
        clear_console()
        print("\n" + "-"*50)
        print("👥 РОБОТА З ЛЮДЬМИ")
        print("-"*50)
        print("1. Список всіх користувачів")
        print("2. Список всіх менторів")
        print("3. Пошук користувача")
        print("4. Додати ментора")
        print("5. Видалити користувача")
        print("6. Видалити ментора з бази mentors")
        print("0. Повернутися в головне меню")
        
        choice = input("\nВаш вибір: ")
        
        if choice == "0":
            break
        elif choice == "1":
            clear_console()
            await list_all_users()
            input("\nНатисніть Enter, щоб повернутися до меню...")
        elif choice == "2":
            clear_console()
            await list_all_mentors()
            input("\nНатисніть Enter, щоб повернутися до меню...")
        elif choice == "3":
            clear_console()
            await find_user()
            input("\nНатисніть Enter, щоб повернутися до меню...")
        elif choice == "4":
            clear_console()
            await add_mentor_handler()
            input("\nНатисніть Enter, щоб повернутися до меню...")
        elif choice == "5":
            clear_console()
            await delete_user_handler()
            input("\nНатисніть Enter, щоб повернутися до меню...")
        elif choice == "6":
            clear_console()
            await delete_mentor_handler()
            input("\nНатисніть Enter, щоб повернутися до меню...")
        else:
            print("❌ Невірний вибір. Спробуйте ще раз.")
            input("\nНатисніть Enter, щоб продовжити...")

async def show_days_management_menu():
    """Показує меню для роботи з днями навчання"""
    while True:
        clear_console()
        print("\n" + "-"*50)
        print("📅 РОБОТА З ДНЯМИ НАВЧАННЯ")
        print("-"*50)
        print("1. Показати статус днів стажера")
        print("2. Відкрити день(дні) для стажера")
        print("3. Закрити день(дні) для стажера")
        print("4. Скинути прогрес дня для стажера")
        print("0. Повернутися в головне меню")
        
        choice = input("\nВаш вибір: ")
        
        if choice == "0":
            break
            
        if choice in ["1", "2", "3", "4"]:
            user_id_input = input("Введіть ID стажера: ")
            try:
                user_id = int(user_id_input)
            except ValueError:
                print("❌ Некоректний ID. Повинен бути цілим числом.")
                input("\nНатисніть Enter, щоб продовжити...")
                continue
                
        if choice == "1":
            clear_console()
            await display_user_days_status(user_id)
        elif choice == "2":
            clear_console()
            day_input = input(f"Введіть номер дня або діапазон для відкриття (1-{DAYS_TOTAL}), наприклад 3 або 3-6: ")
            days = await parse_day_input(day_input)
            for day in days:
                await open_day_for_user(user_id, day)
            input("\nНатисніть Enter, щоб повернутися до меню...")
        elif choice == "3":
            clear_console()
            day_input = input(f"Введіть номер дня або діапазон для закриття (2-{DAYS_TOTAL}), наприклад 3 або 3-6: ")
            days = await parse_day_input(day_input, max_day=DAYS_TOTAL)
            days = [d for d in days if d >= 2]  # Фільтруємо день 1
            for day in days:
                await close_day_for_user(user_id, day)
            input("\nНатисніть Enter, щоб повернутися до меню...")
        elif choice == "4":
            clear_console()
            day_input = input(f"Введіть номер дня або діапазон для скидання (1-{DAYS_TOTAL}), наприклад 3 або 3-6: ")
            days = await parse_day_input(day_input)
            if days:  # Перевіряємо, що список не порожній
                await reset_user_progress(user_id, days)
            input("\nНатисніть Enter, щоб повернутися до меню...")
        else:
            print("❌ Невідома команда. Спробуйте ще раз.")
            input("\nНатисніть Enter, щоб продовжити...")

async def main():
    """Головна функція адміністративної панелі"""
    # Завантажуємо прогрес при старті
    await load_all_progress()
    
    while True:
        clear_console()
        print("\n" + "="*70)
        print("👋 АДМІНІСТРАТИВНА ПАНЕЛЬ БУЛКА-БОТ".center(70))
        print("="*70)
        print("Ця утиліта дозволяє керувати користувачами та днями навчання.".center(70))
        print("="*70)
        print(f"Використовується база даних: {DB_PATH}")
        
        print("\n" + "-"*50)
        print("🏠 ГОЛОВНЕ МЕНЮ")
        print("-"*50)
        print("1. Робота з людьми")
        print("2. Робота з днями навчання")
        print("0. Вийти")
        
        choice = input("\nВаш вибір: ")
        
        if choice == "0":
            clear_console()
            print("👋 Дякую за використання адміністративної панелі!")
            break
        elif choice == "1":
            await show_people_management_menu()
        elif choice == "2":
            await show_days_management_menu()
        else:
            print("❌ Невірний вибір. Спробуйте ще раз.")
            input("\nНатисніть Enter, щоб продовжити...")

if __name__ == "__main__":
    asyncio.run(main())
