from datetime import datetime, timedelta
import pytz
from bot.config import TIMEZONE, DAYS_TOTAL
import asyncio

from aiogram.fsm.state import State, StatesGroup

class TestStates(StatesGroup):
    answering_questions = State()

user_progress = {}
# Змінні для керування повідомленнями
new_blocks_notifications = []
notifications_shown = {}

# Зміна часу відкриття нових блоків (додайте ці константи на початку файлу)
BLOCKS_OPEN_HOUR = 23    # Година відкриття блоків (24-годинний формат)
BLOCKS_OPEN_MINUTE = 59  # Хвилина відкриття блоків
BLOCKS_OPEN_SECOND = 59  # Секунда відкриття блоків

def initialize_user_progress(user_id):
    if user_id not in user_progress:
        user_progress[user_id] = {}

def get_progress(user_id):
    progress = user_progress.get(user_id, {})
    return sum(1 for k, v in progress.items() if v.get("completed"))

def get_available_day(user_id):
    for day in range(1, DAYS_TOTAL + 1):
        if is_day_available(user_id, day):
            return day
    return DAYS_TOTAL

def is_day_available(user_id, day):
    """
    Перевіряє, чи доступний певний день для користувача.
    День 1 завжди доступний.
    Наступні дні стають доступними, якщо:
    1. Попередній день пройдений і ця функція була викликана автоматично, або
    2. День вже був пройдений раніше (тоді він завжди доступний), або
    3. День був вручну відкритий через адмін-панель
    """
    progress = user_progress.get(user_id, {})
    
    # День 1 завжди доступний
    if day == 1:
        return True
    
    # Якщо день вже пройдено, він завжди доступний
    current_day_key = f"day_{day}"
    if progress.get(current_day_key, {}).get("completed"):
        return True
    
    # Перевіряємо, чи пройдений попередній день
    prev_day_key = f"day_{day-1}"
    if not progress.get(prev_day_key, {}).get("completed"):
        return False
        
    # Перевіряємо, чи цей день вже відкритий вручну через автоматичне відкриття
    if progress.get(current_day_key, {}).get("manual_open"):
        return True
    
    # Інакше день НЕ доступний - він має бути відкритий через щоденний планувальник
    return False

# --- Функція для автоматичного відкриття блоків у заданий час ---
async def auto_open_blocks_scheduler():
    """Функція для автоматичного відкриття нових блоків у заданий час"""
    from bot.services.health import health_check
    from bot.services.logger import get_logger
    logger = get_logger()
    
    logger.info(f"🔵 Запущено планувальник відкриття нових блоків")
    logger.info(f"⏰ Час відкриття: {BLOCKS_OPEN_HOUR:02d}:{BLOCKS_OPEN_MINUTE:02d}:{BLOCKS_OPEN_SECOND:02d}")
    
    while True:
        try:
            # Відмічаємо heartbeat
            health_check.heartbeat_scheduler()
            
            # Отримуємо поточний час
            now = datetime.now(pytz.timezone(TIMEZONE))
            
            # Розраховуємо час до наступного запуску
            target_time = now.replace(hour=BLOCKS_OPEN_HOUR, minute=BLOCKS_OPEN_MINUTE, 
                                      second=BLOCKS_OPEN_SECOND, microsecond=0)
            
            # Якщо заданий час вже минув сьогодні, переносимо на завтра
            if now >= target_time:
                target_time = (now + timedelta(days=1)).replace(
                    hour=BLOCKS_OPEN_HOUR, minute=BLOCKS_OPEN_MINUTE, 
                    second=BLOCKS_OPEN_SECOND, microsecond=0
                )
                
            # Розраховуємо скільки секунд треба чекати
            wait_seconds = (target_time - now).total_seconds()
            
            logger.debug(f"Планувальник: наступне відкриття о {target_time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Чекаємо до заданого часу (з heartbeat кожну годину)
            while wait_seconds > 3600:
                await asyncio.sleep(3600)
                health_check.heartbeat_scheduler()
                wait_seconds -= 3600
            
            await asyncio.sleep(wait_seconds)
            
            # Запускаємо процес відкриття нових блоків
            await open_new_blocks_for_all_users()
            
            # Чекаємо 1 секунду, щоб не запустити функцію двічі
            await asyncio.sleep(1)
            
        except Exception as e:
            logger.error(f"Scheduler error: {e}", exc_info=True)
            health_check.record_error()
            await asyncio.sleep(60)  # Чекаємо хвилину перед повторною спробою

async def open_new_blocks_for_all_users():
    """Відкриває нові блоки для всіх користувачів, які пройшли попередні"""
    from bot.services.learning_progress import open_day_auto
    from bot.services.logger import get_logger
    logger = get_logger()
    
    global new_blocks_notifications
    new_blocks_notifications = []  # Очищаємо список повідомлень
    
    logger.info("🔄 Щоденне відкриття нових блоків...")
    
    # Проходимо по всіх користувачах у user_progress
    for user_id, progress in user_progress.items():
        # Знаходимо останній пройдений день
        completed_days = [int(day.split("_")[1]) for day, data in progress.items() 
                         if data.get("completed") and day.startswith("day_")]
        
        if not completed_days:
            continue  # Пропускаємо користувачів без прогресу
            
        last_completed_day = max(completed_days)
        next_day = last_completed_day + 1
        
        # Якщо є наступний день і він менший або рівний DAYS_TOTAL
        if next_day <= DAYS_TOTAL:
            # Встановлюємо цей день як доступний (відкритий)
            await open_day_auto(user_id, next_day)
            progress.setdefault(f"day_{next_day}", {})["notified"] = True
            
            # Додаємо в список для повідомлення
            new_blocks_notifications.append({
                "user_id": user_id,
                "day": next_day,
                "open_time": datetime.now(pytz.timezone(TIMEZONE))
            })
    
    # Логуємо результати
    if new_blocks_notifications:
        logger.info(f"✅ Відкрито блоки для {len(new_blocks_notifications)} користувачів")
    else:
        logger.debug("Немає нових блоків для відкриття")

# --- Синхронізація з базою даних ---
import asyncio
from database.users import get_all_users, get_user_progress

async def load_all_progress():
    """
    Завантажує прогрес усіх користувачів з бази даних у user_progress.
    Викликайте цю функцію при старті бота!
    """
    global user_progress
    user_progress.clear()
    users = await get_all_users()
    for user in users:
        uid = user["user_id"]
        user_progress[uid] = {}
        progress_list = await get_user_progress(uid)
        for p in progress_list:
            entry = {"completed": bool(p["completed"])}
            completed_at = p.get("completed_at")
            if completed_at:
                if isinstance(completed_at, datetime):
                    dt = completed_at
                else:
                    dt = datetime.fromisoformat(completed_at)
                if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
                    dt = pytz.timezone(TIMEZONE).localize(dt)
                entry["completed_at"] = dt
            if p.get("manual_open"):
                entry["manual_open"] = bool(p["manual_open"])
            user_progress[uid][f"day_{p['day']}"] = entry
