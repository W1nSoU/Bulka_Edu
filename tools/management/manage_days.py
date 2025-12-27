import sys
import os
import asyncio
from datetime import datetime

# Додаємо батьківську директорію в sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.users import get_user_details, get_user_progress, update_progress, update_user_current_block
from state import user_progress, initialize_user_progress, load_all_progress
from config import DAYS_TOTAL, TIMEZONE
import pytz
import aiosqlite
from database import DB_PATH  # Додаємо імпорт шляху до БД

async def display_user_days_status(user_id):
    """Відображає статус днів для конкретного стажера"""
    # Отримуємо інформацію про користувача
    user_details = await get_user_details(user_id)
    if not user_details:
        print(f"❌ Користувач з ID {user_id} не знайдений")
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
    
    # Використовуємо функцію з database/users.py для оновлення поточного блоку
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

async def main():
    """Основна функція для взаємодії з користувачем"""
    print("👋 Інструмент для керування доступом до днів навчання для стажерів")
    print("🔑 Ви можете відкривати та закривати доступ до різних днів для конкретного стажера")
    print("💡 Підтримуються діапазони днів, наприклад: 3-6")
    
    while True:
        print("\n" + "-"*50)
        print("Виберіть дію:")
        print("1. Показати статус днів стажера")
        print("2. Відкрити день(дні) для стажера")
        print("3. Закрити день(дні) для стажера")
        print("4. Скинути прогрес дня для стажера")
        print("0. Вийти")
        
        choice = input("Ваш вибір: ")
        
        if choice == "0":
            break
            
        if choice in ["1", "2", "3", "4"]:
            user_id_input = input("Введіть ID стажера: ")
            try:
                user_id = int(user_id_input)
            except ValueError:
                print("❌ Некоректний ID. Повинен бути цілим числом.")
                continue
                
        if choice == "1":
            await display_user_days_status(user_id)
        elif choice == "2":
            day_input = input(f"Введіть номер дня або діапазон для відкриття (1-{DAYS_TOTAL}), наприклад 3 або 3-6: ")
            days = await parse_day_input(day_input)
            for day in days:
                await open_day_for_user(user_id, day)
        elif choice == "3":
            day_input = input(f"Введіть номер дня або діапазон для закриття (2-{DAYS_TOTAL}), наприклад 3 або 3-6: ")
            days = await parse_day_input(day_input, max_day=DAYS_TOTAL)
            days = [d for d in days if d >= 2]  # Фільтруємо день 1
            for day in days:
                await close_day_for_user(user_id, day)
        elif choice == "4":
            day_input = input(f"Введіть номер дня або діапазон для скидання (1-{DAYS_TOTAL}), наприклад 3 або 3-6: ")
            days = await parse_day_input(day_input)
            if days:  # Перевіряємо, що список не порожній
                await reset_user_progress(user_id, days)
        else:
            print("❌ Невідома команда. Спробуйте ще раз.")

if __name__ == "__main__":
    asyncio.run(main())
