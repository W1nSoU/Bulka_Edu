#!/usr/bin/env python3
"""
Діагностика проблеми з Health Check на сервері
"""
import sys
import os
from datetime import datetime
import pytz

sys.path.insert(0, '/Users/winsou/All/Dev/Bulka')

print("🔍 ДІАГНОСТИКА HEALTH CHECK")
print("=" * 70)

# Перевірка timezone
from bot.config import TIMEZONE

print(f"\n1️⃣ TIMEZONE CONFIGURATION")
print("-" * 70)
print(f"Configured timezone: {TIMEZONE}")
print(f"Current time (system): {datetime.now()}")
print(f"Current time (config TZ): {datetime.now(pytz.timezone(TIMEZONE))}")
print(f"UTC time: {datetime.utcnow()}")

# Перевірка APScheduler
print(f"\n2️⃣ APSCHEDULER CHECK")
print("-" * 70)
try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    print(f"✅ APScheduler доступний")
    print(f"Scheduler timezone: {scheduler.timezone}")
except Exception as e:
    print(f"❌ APScheduler помилка: {e}")

# Перевірка health check
print(f"\n3️⃣ HEALTH CHECK STATUS")
print("-" * 70)
try:
    from bot.services.health import health_check, get_health_status
    
    status = get_health_status()
    print(f"Status: {status['status']}")
    print(f"Uptime: {status['uptime_human']}")
    print(f"Scheduler healthy: {status['scheduler_healthy']}")
    print(f"Reminder healthy: {status['reminder_healthy']}")
    print(f"Last scheduler heartbeat: {status['last_scheduler_heartbeat']}")
    print(f"Last reminder heartbeat: {status['last_reminder_heartbeat']}")
    print(f"Errors count: {status['errors_count']}")
    
    # Симулюємо heartbeat
    print(f"\n🧪 Симуляція heartbeat...")
    health_check.heartbeat_scheduler()
    status_after = get_health_status()
    print(f"Scheduler healthy after heartbeat: {status_after['scheduler_healthy']}")
    print(f"Last heartbeat: {status_after['last_scheduler_heartbeat']}")
    
except Exception as e:
    print(f"❌ Health check помилка: {e}")
    import traceback
    traceback.print_exc()

# Перевірка конфігурації
print(f"\n4️⃣ ENVIRONMENT CHECK")
print("-" * 70)
try:
    from bot.config import DEV_CHAT_ID
    print(f"DEV_CHAT_ID: {DEV_CHAT_ID or 'NOT SET'}")
    
    if DEV_CHAT_ID:
        print(f"✅ Алерти будуть надсилатися в чат {DEV_CHAT_ID}")
    else:
        print(f"⚠️ DEV_CHAT_ID не налаштований - алерти не надсилатимуться")
except Exception as e:
    print(f"❌ Config помилка: {e}")

# Рекомендації
print(f"\n5️⃣ МОЖЛИВІ ПРОБЛЕМИ ТА РІШЕННЯ")
print("-" * 70)
print("""
Можливі причини помилки "Scheduler: ❌":

1. Scheduler не запущений на сервері
   → Перевірте чи запускається main.py повністю
   → Дивіться логи на наявність помилок scheduler

2. Різниця в timezone між сервером та конфігом
   → Перевірте системний час сервера: date
   → Порівняйте з TIMEZONE в .env

3. AsyncIOScheduler падає з помилкою
   → Перевірте логи на помилки від apscheduler
   → Можливо проблеми з правами доступу

4. Health monitor loop не викликається
   → Scheduler запущений, але job не спрацьовує
   → Перевірте чи є job 'health_monitor' в списку

РІШЕННЯ:
- Додано детальніше логування при старті scheduler
- Змінено логіку перевірки: тепер 10 хвилин замість 65
- Додано діагностичну інформацію в алерти
- Додано логування помилок відправки алертів

Після оновлення коду на сервері:
1. Перезапустіть бота
2. Перевірте логи: tail -f logs/bot.log
3. Дочекайтесь першого heartbeat (5 хвилин)
4. Якщо алерт все ще приходить - дивіться деталі в повідомленні
""")

print("=" * 70)
print("✅ Діагностика завершена")
print("=" * 70)