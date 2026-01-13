#!/usr/bin/env python3
"""
Тест для перевірки callback кнопки "Нагадати всім"
"""
import sys
sys.path.insert(0, '/Users/winsou/All/Dev/Bulka')

print("🧪 ТЕСТ CALLBACK 'mgr_remind_all_lagging'")
print("=" * 60)

# Перевіряємо реєстрацію обробника
print("\n1️⃣ Перевірка реєстрації")
print("-" * 40)

try:
    from aiogram import Dispatcher
    from bot.menus.manager import register_manager_handlers
    
    dp = Dispatcher()
    register_manager_handlers(dp)
    
    # Отримуємо всі зареєстровані обробники
    handlers = []
    for handler in dp.callback_query.handlers:
        if hasattr(handler, 'filters'):
            for f in handler.filters:
                if hasattr(f, 'callback'):
                    handlers.append(str(f.callback))
    
    print(f"Зареєстровано {len(dp.callback_query.handlers)} callback обробників")
    
    # Шукаємо наш конкретний обробник
    found = False
    for handler in dp.callback_query.handlers:
        # Aiogram 3.x використовує filters
        handler_str = str(handler)
        if 'mgr_remind_all_lagging' in handler_str:
            found = True
            print(f"✅ Знайдено обробник: {handler}")
            break
    
    if not found:
        print("❌ Обробник 'mgr_remind_all_lagging' НЕ зареєстрований!")
    else:
        print("✅ Обробник 'mgr_remind_all_lagging' зареєстрований")
        
except Exception as e:
    print(f"❌ Помилка перевірки реєстрації: {e}")
    import traceback
    traceback.print_exc()

# Перевіряємо функцію
print("\n2️⃣ Перевірка функції manager_remind_all_lagging")
print("-" * 40)

try:
    from bot.menus.manager import manager_remind_all_lagging
    import inspect
    
    # Отримуємо сигнатуру функції
    sig = inspect.signature(manager_remind_all_lagging)
    print(f"✅ Функція існує")
    print(f"Параметри: {sig}")
    
    # Перевіряємо чи це async функція
    if inspect.iscoroutinefunction(manager_remind_all_lagging):
        print(f"✅ Функція async (правильно)")
    else:
        print(f"❌ Функція НЕ async (помилка!)")
    
    # Показуємо початок функції
    source = inspect.getsource(manager_remind_all_lagging)
    lines = source.split('\n')[:10]
    print(f"\nПерші 10 рядків функції:")
    for line in lines:
        print(f"  {line}")
    
except Exception as e:
    print(f"❌ Помилка перевірки функції: {e}")
    import traceback
    traceback.print_exc()

# Перевіряємо залежності
print("\n3️⃣ Перевірка залежностей")
print("-" * 40)

try:
    from bot.services.reminders import send_intern_reminder
    print("✅ send_intern_reminder доступний")
    
    from database.users import get_interns_in_progress_for_manager, get_user_progress
    print("✅ get_interns_in_progress_for_manager доступний")
    print("✅ get_user_progress доступний")
    
    from bot.services.logger import get_logger
    print("✅ get_logger доступний")
    
except Exception as e:
    print(f"❌ Помилка імпорту: {e}")

# Перевіряємо формат повідомлення
print("\n4️⃣ Перевірка формату повідомлення")
print("-" * 40)

try:
    from bot.services.reminders import send_manager_lagging_report
    import inspect
    
    source = inspect.getsource(send_manager_lagging_report)
    
    if 'mgr_remind_all_lagging' in source:
        print("✅ Callback 'mgr_remind_all_lagging' присутній в коді")
    else:
        print("❌ Callback 'mgr_remind_all_lagging' ВІДСУТНІЙ!")
    
    if 'parse_mode="HTML"' in source or "parse_mode='HTML'" in source:
        print("✅ parse_mode='HTML' встановлений")
    else:
        print("⚠️ parse_mode не встановлений (може працювати неправильно)")
    
except Exception as e:
    print(f"❌ Помилка: {e}")

# Рекомендації
print("\n5️⃣ ДІАГНОСТИКА")
print("-" * 40)
print("""
Можливі причини проблеми "не працює кнопка":

1. ❌ Обробник не зареєстрований
   → Перевірте чи викликається register_manager_handlers(dp)
   → Перевірте логи при старті

2. ❌ Callback data не збігається
   → В кнопці: callback_data="mgr_remind_all_lagging"
   → В обробнику: lambda c: c.data == "mgr_remind_all_lagging"
   → Має бути точне співпадіння!

3. ❌ Функція падає з помилкою
   → Дивіться логи: tail -f logs/bot.log | grep -i remind
   → Додано обробку помилок з логуванням

4. ❌ Користувач не є менеджером
   → _ensure_manager повертає False
   → Перевірте чи є користувач в таблиці managers

5. ❌ Bot не передається правильно
   → callback.bot може бути None
   → Додано перевірку та логування

ВИПРАВЛЕННЯ:
✅ Додано детальне логування
✅ Додано parse_mode="HTML"
✅ Додано обробку помилок
✅ Додано підрахунок успішних/невдалих нагадувань
✅ Додано callback.answer() з повідомленням

ТЕСТУВАННЯ:
1. Перезапустіть бота
2. Дочекайтесь щоденного звіту о 18:00
3. Натисніть "🔔 Нагадати всім"
4. Перевірте логи: grep "Manager.*initiating reminders" logs/bot.log
5. Має з'явитися повідомлення "✅ Нагадування відправлено"
""")

print("=" * 60)
print("✅ Тестування завершено")
print("=" * 60)