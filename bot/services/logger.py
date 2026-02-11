"""
Централізований сервіс логування для Bulka Bot.
Підтримує: stdout, файл, Telegram алерти для критичних помилок.
"""

import logging
import sys
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional
import traceback

from bot.config import LOG_TO_FILE, LOG_FILE_PATH, DEV_CHAT_ID, TIMEZONE, DEBUG
import pytz


class BotLogger:
    """Централізований логер для бота."""
    
    _instance: Optional["BotLogger"] = None
    _bot = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        self._setup_logging()
    
    def _setup_logging(self):
        """Налаштовує logging handlers."""
        self.logger = logging.getLogger("bulka_bot")
        self.logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)
        
        # Формат логів
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        
        # Console handler (stdout)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG if DEBUG else logging.INFO)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        # File handler (якщо увімкнено)
        if LOG_TO_FILE:
            log_path = Path(LOG_FILE_PATH)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
            file_handler.setLevel(logging.DEBUG)  # Файл завжди DEBUG
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
    
    def set_bot(self, bot):
        """Встановлює екземпляр бота для Telegram алертів."""
        self._bot = bot
    
    def _get_timestamp(self) -> str:
        """Повертає поточний час у форматі для логів."""
        return datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")
    
    def debug(self, message: str, **kwargs):
        """Debug рівень логування."""
        self.logger.debug(message, **kwargs)
    
    def info(self, message: str, **kwargs):
        """Info рівень логування."""
        self.logger.info(message, **kwargs)
    
    def info_alert(self, message: str):
        """Надсилає інформаційне сповіщення в Telegram групу."""
        self.logger.info(f"ALERT: {message}")
        if self._bot and DEV_CHAT_ID:
            asyncio.create_task(self._send_telegram_alert(f"ℹ️ <b>INFO</b> | {message}", is_critical=False))
    
    def warning(self, message: str, **kwargs):
        """Warning рівень логування."""
        self.logger.warning(message, **kwargs)
    
    def error(self, message: str, exc_info: bool = False, send_alert: bool = True, **kwargs):
        """Error рівень логування. Автоматично надсилає стислий алерт."""
        self.logger.error(message, exc_info=exc_info, **kwargs)
        
        if send_alert and DEV_CHAT_ID and self._bot:
            asyncio.create_task(self._send_telegram_alert(message, is_critical=False))
    
    def critical(self, message: str, exc_info: bool = True, send_alert: bool = True, **kwargs):
        """
        Critical рівень логування.
        Автоматично надсилає Telegram алерт якщо налаштовано.
        """
        self.logger.critical(message, exc_info=exc_info, **kwargs)
        
        if send_alert and DEV_CHAT_ID and self._bot:
            asyncio.create_task(self._send_telegram_alert(message, is_critical=True))
    
    async def _send_telegram_alert(self, message: str, is_critical: bool = False):
        """Надсилає алерт в Telegram чат розробників."""
        if not DEV_CHAT_ID or not self._bot:
            return
        
        try:
            # Безпечна конвертація ID (обробка дефолтного "-. ")
            chat_id_str = str(DEV_CHAT_ID).strip()
            # Беремо першу частину до пробілу, якщо там є коментарі або сміття
            chat_id_str = chat_id_str.split()[0]
            if not chat_id_str or chat_id_str == "-.":
                return
            chat_id_int = int(chat_id_str)

            header = "🚨 <b>CRITICAL</b>" if is_critical else "⚠️ <b>Error</b>"
            
            alert_text = (
                f"{header} | {self._get_timestamp()}\n"
                f"{message[:2000]}"
            )
            await self._bot.send_message(
                chat_id=chat_id_int,
                text=alert_text,
                parse_mode="HTML"
            )
        except Exception as e:
            self.logger.error(f"Failed to send Telegram alert: {e}", send_alert=False)
    
    def exception(self, message: str, send_alert: bool = True):
        """Логує exception з traceback. Надсилає стисле повідомлення."""
        tb = traceback.format_exc()
        full_message = f"{message}\n{tb}"
        self.logger.error(full_message)
        
        if send_alert and DEV_CHAT_ID and self._bot:
            # Формуємо стисле повідомлення: Текст + Тип помилки + Файл
            try:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                error_type = exc_type.__name__ if exc_type else "Exception"
                
                # Знаходимо файл, де сталася помилка (останній у трейсбеку нашого коду)
                tb_list = traceback.extract_tb(exc_traceback)
                if tb_list:
                    last_call = tb_list[-1]
                    file_name = Path(last_call.filename).name
                    line_no = last_call.lineno
                    location = f"{file_name}:{line_no}"
                else:
                    location = "unknown"

                short_msg = (
                    f"<b>Повідомлення:</b> {message}\n"
                    f"<b>Файл:</b> {location}\n"
                    f"<b>Помилка:</b> {error_type}: {exc_value}"
                )
            except Exception:
                # Fallback якщо не вдалося розпарсити
                short_msg = f"{message}\nSee logs for traceback."

            asyncio.create_task(self._send_telegram_alert(short_msg, is_critical=False))


# Глобальний екземпляр логера
logger = BotLogger()


# Зручні функції для імпорту
def get_logger() -> BotLogger:
    """Повертає глобальний екземпляр логера."""
    return logger


def setup_bot_logger(bot):
    """Налаштовує логер з екземпляром бота для Telegram алертів."""
    logger.set_bot(bot)
