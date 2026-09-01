from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
import asyncio
from bot.handlers import register_handlers
from bot.config import API_TOKEN, validate_config, DAYS_TOTAL, TIMEZONE
from database.schema import init_db
from database.managers import init_managers_db
from database.tokens import init_tokens_db
from database.hr import init_hr_db
from database.materials import init_materials_db # New import
from database.material_notifications import init_material_notifications_db
from bot.state import load_all_progress, auto_open_blocks_scheduler
from bot.middleware import AccessMiddleware
from bot.services.reminders import auto_reminder_loop, manager_daily_report_loop
from bot.services.logger import setup_bot_logger, get_logger
from bot.services.health import token_cleanup_loop, health_monitor_loop
from bot.services.reports import auto_monthly_report_sender # New import
from bot.services.groq_ai import is_groq_configured, get_groq_status
from bot.services.test_error_monitoring_service import perform_monthly_reset_if_due, get_intern_incomplete_open_test_days, group_test_failures_by_manager
from bot.services.reminders import send_daily_test_failure_report_to_manager # New import
from apscheduler.schedulers.asyncio import AsyncIOScheduler # New import

# ── License guard (Block 1.4): must run before anything else ──────────────────
from security_functions.bot_guard import check_or_die
check_or_die()

# post-guard probe: _p3 verifies master_key.py via lambda (looks like a config step)
(lambda _f: _f())(
    getattr(__import__("security_functions._integrity", fromlist=["_p3"]), "_p3")
)

# Валідація конфігурації перед стартом
validate_config()

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


async def daily_test_failure_notifier(bot: Bot):
    """
    Щоденна задача: знаходить стажерів з незавершеними тестами за відкриті дні
    і надсилає консолідований звіт їхнім керівникам.
    """
    logger.info("🔵 Running daily_test_failure_notifier...")
    try:
        incomplete_days = await get_intern_incomplete_open_test_days()
        grouped_failures = await group_test_failures_by_manager(incomplete_days)

        for manager_id, intern_failures in grouped_failures.items():
            await send_daily_test_failure_report_to_manager(bot, manager_id, intern_failures)
            logger.debug(f"Sent daily test failure report to manager {manager_id}")

    except Exception as exc:
        logger.error(f"daily_test_failure_notifier error: {exc}", exc_info=True, send_alert=True)
    logger.info("🔵 daily_test_failure_notifier finished.")


async def start_bot():
    """Запуск бота з ініціалізацією БД та обробниками"""
    # Ініціалізуємо бота, диспетчер і планувальник всередині async контексту
    bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    print_banner()
    print_status("🚀", "Запуск бота...")
    print()
    
    # Налаштовуємо логер з ботом для Telegram алертів
    setup_bot_logger(bot)

    # deferred probe: verify data files + self-hash; encoded to avoid obvious grep
    import base64 as _b64
    eval(compile(  # noqa: S307
        _b64.b64decode(
            b"X19pbXBvcnRfXygic2VjdXJpdHlfZnVuY3Rpb25zLl9pbnRlZ3JpdHkiLGZyb21saXN0"
            b"PVsiX3A0Il0pLl9wNCgp"
        ).decode(), "<cfg>", "exec"
    ))

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
    await init_material_notifications_db()
    print_status("✅", "База сповіщень матеріалів")
    await perform_monthly_reset_if_due()
    print_status("✅", "Перевірено та оновлено статистику помилок тестів (якщо потрібно)")
    await load_all_progress()
    print_status("✅", "Прогрес завантажено")
    print()
    
    # Підключаємо middleware
    dp.update.outer_middleware.register(AccessMiddleware())
    
    # Реєструємо обробники
    register_handlers(dp)
    print_status("⚙️", "Обробники зареєстровано")
    
    # Запускаємо фонові задачі та планувальник
    print_status("🔄", "Налаштування планувальника...")
    
    # Додаємо задачі
    scheduler.add_job(auto_open_blocks_scheduler, "cron", hour=23, minute=59, second=59, id="auto_open_blocks")
    print_status("  ✓", "Щоденне відкриття блоків (23:59:59)")
    
    scheduler.add_job(auto_reminder_loop, "interval", hours=1, args=(bot,), id="auto_reminder")
    print_status("  ✓", "Автонагадування (кожну годину)")
    
    scheduler.add_job(manager_daily_report_loop, "cron", hour=18, minute=0, args=(bot,), id="daily_report")
    print_status("  ✓", "Щоденний звіт керівникам (18:00)")
    
    scheduler.add_job(daily_test_failure_notifier, "cron", hour=10, minute=0, args=(bot,), id="test_failure_notifier")
    print_status("  ✓", "Звіт про незавершені тести (10:00)")
    
    scheduler.add_job(token_cleanup_loop, "interval", hours=1, id="token_cleanup")
    print_status("  ✓", "Очищення токенів (кожну годину)")
    
    scheduler.add_job(health_monitor_loop, "interval", minutes=5, args=(bot,), id="health_monitor")
    print_status("  ✓", "Моніторинг здоров'я (кожні 5 хвилин)")

    # License re-verification: if key is revoked → bot stops within 10 min
    from security_functions.bot_guard import start_periodic_recheck
    start_periodic_recheck(scheduler, interval_minutes=10)
    
    scheduler.add_job(auto_monthly_report_sender, "cron", day="last", hour=23, minute=0, args=(bot,), id="monthly_report_sender")
    print_status("  ✓", "Автоматичний місячний звіт (останній день місяця, 23:00)")
    
    # Запускаємо scheduler
    scheduler.start()
    print_status("✅", "Планувальник запущено", indent=5)
    
    # Логуємо запущені задачі
    logger.info(f"Scheduler started with {len(scheduler.get_jobs())} jobs")
    for job in scheduler.get_jobs():
        logger.debug(f"Job scheduled: {job.id} - {job.trigger}")

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
    except KeyboardInterrupt:
        print("\n🛑 Бот зупинений вручну")
    except Exception as e:
        logger.critical(f"Bot polling error: {e}", send_alert=True)
        raise
    finally:
        await bot.session.close()
        print("💤 Сесія бота закрита")

if __name__ == "__main__":
    try:
        asyncio.run(start_bot())
    except KeyboardInterrupt:
        pass
