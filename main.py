from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
import asyncio
from bot.handlers import register_handlers
from bot.config import API_TOKEN, validate_config, DAYS_TOTAL
from database.schema import init_db
from database.managers import init_managers_db
from database.tokens import init_tokens_db
from database.hr import init_hr_db
from database.materials import init_materials_db # New import
from bot.state import load_all_progress, auto_open_blocks_scheduler
from bot.middleware import AccessMiddleware
from bot.services.reminders import auto_reminder_loop, manager_daily_report_loop
from bot.services.logger import setup_bot_logger, get_logger
from bot.services.health import token_cleanup_loop, health_monitor_loop
from bot.services.groq_ai import is_groq_configured, get_groq_status
from bot.services.test_error_monitoring_service import perform_quarterly_reset_if_due

# Валідація конфігурації перед стартом
validate_config()

# Ініціалізуємо бота і диспетчер
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
logger = get_logger()


def print_banner():
    """Виводить красивий банер при старті."""
    banner = """
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   🍞  BULKA BOT — Навчальна платформа для стажерів  🍞       ║
║                    Developed by WinSoU.                      ║
╚══════════════════════════════════════════════════════════════╝
    """
    print(banner)


def print_status(emoji: str, message: str, indent: int = 5):
    """Виводить статусне повідомлення з відступом."""
    print(" " * indent + f"{emoji} {message}")


async def start_bot():
    """Запуск бота з ініціалізацією БД та обробниками"""
    print_banner()
    print_status("🚀", "Запуск бота...")
    print()
    
    # Налаштовуємо логер з ботом для Telegram алертів
    setup_bot_logger(bot)
    
    # Ініціалізуємо БД
    print_status("📦", "Ініціалізація баз даних...")
    await init_db()
    print_status("✅", "База користувачів")
    # await init_mentors_db()
    print_status("✅", "База менторів")
    await init_tokens_db()
    print_status("✅", "База токенів")
    await init_hr_db()
    print_status("✅", "База HR")
    await init_managers_db()
    print_status("✅", "База керівників")
    await init_materials_db() # New initialization call
    print_status("✅", "База матеріалів")
    await perform_quarterly_reset_if_due()
    print_status("✅", "Перевірено та оновлено статистику помилок тестів (якщо потрібно)")
    await load_all_progress()
    print_status("✅", "Прогрес завантажено")
    print()
    
    # Підключаємо middleware
    dp.update.outer_middleware.register(AccessMiddleware())
    
    # Реєструємо обробники
    register_handlers(dp)
    print_status("⚙️", "Обробники зареєстровано")
    
    # Запускаємо фонові задачі
    asyncio.create_task(auto_open_blocks_scheduler())
    asyncio.create_task(auto_reminder_loop(bot))
    asyncio.create_task(manager_daily_report_loop(bot))
    asyncio.create_task(token_cleanup_loop())
    asyncio.create_task(health_monitor_loop(bot))
    print_status("🔄", "Фонові задачі запущено")
    print()
    
    # Статус AI
    groq_status = get_groq_status()
    if groq_status["configured"]:
        print_status("🤖", f"Groq AI: {groq_status['total_keys']} ключ(ів)")
    else:
        print_status("⚠️", "Groq AI: не налаштовано")
    
    print_status("📚", f"Днів навчання: {DAYS_TOTAL}")
    print()
    
    # Фінальне повідомлення
    print("─" * 60)
    print_status("🍞", "Bulka Bot готовий до роботи!", indent=3)
    print("─" * 60)
    print()
    
    logger.info("🍞 Bulka Bot started successfully")
    
    # Запускаємо бота
    try:
        await dp.start_polling(
            bot,
            skip_updates=True,
            allowed_updates=["message", "callback_query"]
        )
    except Exception as e:
        logger.critical(f"Bot polling error: {e}", send_alert=True)
        raise

if __name__ == "__main__":
    asyncio.run(start_bot())
