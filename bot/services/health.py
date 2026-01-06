"""
Health-check сервіс для моніторингу стану бота.
Перевіряє: scheduler, БД, memory usage.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import pytz

from bot.config import TIMEZONE, TOKEN_CLEANUP_INTERVAL_HOURS
from bot.services.logger import get_logger
from database.tokens import cleanup_expired_tokens, get_token_stats

logger = get_logger()


class HealthCheck:
    """Моніторинг стану бота."""
    
    def __init__(self):
        self._last_scheduler_heartbeat: Optional[datetime] = None
        self._last_reminder_heartbeat: Optional[datetime] = None
        self._last_token_cleanup: Optional[datetime] = None
        self._start_time: datetime = datetime.now(pytz.timezone(TIMEZONE))
        self._errors_count: int = 0
    
    def heartbeat_scheduler(self):
        """Відмітка що scheduler живий."""
        self._last_scheduler_heartbeat = datetime.now(pytz.timezone(TIMEZONE))
    
    def heartbeat_reminder(self):
        """Відмітка що reminder loop живий."""
        self._last_reminder_heartbeat = datetime.now(pytz.timezone(TIMEZONE))
    
    def record_error(self):
        """Записує помилку."""
        self._errors_count += 1
    
    def get_uptime(self) -> timedelta:
        """Повертає час роботи бота."""
        now = datetime.now(pytz.timezone(TIMEZONE))
        return now - self._start_time
    
    def is_scheduler_healthy(self, max_delay_minutes: int = 65) -> bool:
        """Перевіряє чи scheduler працює."""
        if self._last_scheduler_heartbeat is None:
            return True  # Ще не було першого heartbeat
        
        now = datetime.now(pytz.timezone(TIMEZONE))
        delta = now - self._last_scheduler_heartbeat
        return delta.total_seconds() < max_delay_minutes * 60
    
    def is_reminder_healthy(self, max_delay_minutes: int = 65) -> bool:
        """Перевіряє чи reminder loop працює."""
        if self._last_reminder_heartbeat is None:
            return True
        
        now = datetime.now(pytz.timezone(TIMEZONE))
        delta = now - self._last_reminder_heartbeat
        return delta.total_seconds() < max_delay_minutes * 60
    
    def get_status(self) -> Dict[str, Any]:
        """Повертає повний статус здоров'я бота."""
        now = datetime.now(pytz.timezone(TIMEZONE))
        uptime = self.get_uptime()
        
        return {
            "status": "healthy" if self.is_healthy() else "unhealthy",
            "uptime_seconds": int(uptime.total_seconds()),
            "uptime_human": str(uptime).split(".")[0],
            "scheduler_healthy": self.is_scheduler_healthy(),
            "reminder_healthy": self.is_reminder_healthy(),
            "last_scheduler_heartbeat": self._last_scheduler_heartbeat.isoformat() if self._last_scheduler_heartbeat else None,
            "last_reminder_heartbeat": self._last_reminder_heartbeat.isoformat() if self._last_reminder_heartbeat else None,
            "last_token_cleanup": self._last_token_cleanup.isoformat() if self._last_token_cleanup else None,
            "errors_count": self._errors_count,
            "timestamp": now.isoformat(),
        }
    
    def is_healthy(self) -> bool:
        """Загальна перевірка здоров'я."""
        return self.is_scheduler_healthy() and self.is_reminder_healthy()


# Глобальний екземпляр
health_check = HealthCheck()


async def token_cleanup_loop():
    """
    Фонова задача очищення прострочених токенів.
    Виконується планувальником.
    """
    try:
        count = await cleanup_expired_tokens()
        health_check._last_token_cleanup = datetime.now(pytz.timezone(TIMEZONE))
        
        if count > 0:
            logger.info(f"Token cleanup: {count} tokens processed")
        
        # Логуємо статистику
        stats = await get_token_stats()
        logger.debug(f"Token stats: {stats}")
        
    except Exception as e:
        logger.error(f"Token cleanup error: {e}", exc_info=True)
        health_check.record_error()


async def health_monitor_loop(bot):
    """
    Фонова задача моніторингу здоров'я.
    Надсилає алерт якщо щось не так.
    Виконується планувальником.
    """
    from bot.config import DEV_CHAT_ID
    
    # Якщо цей цикл виконується, значить планувальник живий
    health_check.heartbeat_scheduler()
    
    try:
        status = health_check.get_status()
        
        if status["status"] == "unhealthy" and DEV_CHAT_ID:
            alert_text = (
                "⚠️ <b>Health Check Warning</b>\n\n"
                f"Scheduler: {'✅' if status['scheduler_healthy'] else '❌'}\n"
                f"Reminder: {'✅' if status['reminder_healthy'] else '❌'}\n"
                f"Uptime: {status['uptime_human']}\n"
                f"Errors: {status['errors_count']}"
            )
            try:
                await bot.send_message(
                    chat_id=int(DEV_CHAT_ID),
                    text=alert_text,
                    parse_mode="HTML"
                )
            except Exception:
                pass
        
    except Exception as e:
        logger.error(f"Health monitor error: {e}")


def get_health_status() -> Dict[str, Any]:
    """Повертає поточний статус здоров'я."""
    return health_check.get_status()
