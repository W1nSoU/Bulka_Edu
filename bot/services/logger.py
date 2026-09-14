"""
Централізований сервіс логування для Bulka Bot.
Підтримує: stdout, файл, Telegram алерти для помилок (ERROR / CRITICAL) з анти-спамом.
"""

import logging
import sys
import asyncio
import html
import time
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import traceback

from bot.config import LOG_TO_FILE, LOG_FILE_PATH, DEV_CHAT_ID, MAIN_DEVELOPER_ID, TIMEZONE, DEBUG
import pytz



class TelegramLoggingHandler(logging.Handler):
    """
    Стандартний Handler для logging, приєднаний до кореневого (root) логера.
    Перехоплює будь-які ERROR та CRITICAL записи з усіх модулів проекту та сторонніх бібліотек,
    застосовує анти-спам (cooldown 60 секунд) та безпечно надсилає алерти в DEV_CHAT_ID.
    """

    def __init__(self, bot=None, cooldown_seconds: int = 60):
        super().__init__(level=logging.ERROR)
        self.bot = bot
        self.cooldown_seconds = cooldown_seconds
        # Ключ помилки -> {"last_sent": float, "suppressed_count": int}
        self._error_cache: Dict[Tuple, Dict[str, Any]] = {}
        self._last_cleanup = time.time()

    def set_bot(self, bot):
        self.bot = bot

    def emit(self, record: logging.LogRecord):
        # 1. Пропускаємо, якщо бот або DEV_CHAT_ID не налаштовані
        if not self.bot or not DEV_CHAT_ID:
            return

        # 2. Якщо в записі вказано пропустити Telegram алерт
        if getattr(record, "skip_tg_alert", False):
            return

        # 3. Захист від нескінченної рекурсії
        if record.name.startswith("bot.services.logger") or "Telegram alert" in str(record.msg):
            return

        # 4. Пропускаємо типові безпечні винятки Telegram мережі
        msg_str = record.getMessage().lower()
        if any(term in msg_str for term in [
            "query is too old",
            "message is not modified",
            "message can't be deleted for everyone",
            "message to delete not found",
            "bot was blocked by the user",
            "user is deactivated"
        ]):
            return

        try:
            now = time.time()

            # Очищення кешу раз на 10 хвилин від записів старших за 30 хвилин
            if now - self._last_cleanup > 600:
                self._last_cleanup = now
                expired_keys = [k for k, v in self._error_cache.items() if now - v["last_sent"] > 1800]
                for k in expired_keys:
                    self._error_cache.pop(k, None)

            # Сигнатура помилки (Error Key) для анти-спаму
            exc_name = record.exc_info[0].__name__ if (record.exc_info and record.exc_info[0]) else None
            if record.exc_info and len(record.exc_info) > 2 and record.exc_info[2]:
                tb_list = traceback.extract_tb(record.exc_info[2])
                if tb_list:
                    last_tb = tb_list[-1]
                    file_name = Path(last_tb.filename).name
                    lineno = last_tb.lineno
                else:
                    file_name = Path(record.pathname).name if record.pathname else "unknown"
                    lineno = record.lineno
            else:
                file_name = Path(record.pathname).name if record.pathname else "unknown"
                lineno = record.lineno

            msg_prefix = record.getMessage()[:120]
            error_key = (record.name, file_name, lineno, exc_name, msg_prefix)

            # Анти-спам (дедуплікація)
            cached = self._error_cache.get(error_key)
            if cached:
                elapsed = now - cached["last_sent"]
                if elapsed < self.cooldown_seconds:
                    cached["suppressed_count"] += 1
                    return
                else:
                    suppressed_count = cached["suppressed_count"]
                    cached["last_sent"] = now
                    cached["suppressed_count"] = 0
            else:
                suppressed_count = 0
                self._error_cache[error_key] = {"last_sent": now, "suppressed_count": 0}

            # Форматування сповіщення
            alert_text = self._format_alert(record, suppressed_count)

            # Відправка через поточний event loop
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                loop.create_task(self._async_send(alert_text))
        except Exception as e:
            # Тільки в sys.stderr, щоб ніколи не тригерити рекурсивний алерт
            sys.stderr.write(f"[TelegramLoggingHandler.emit] Internal error: {e}\n")

    def _format_alert(self, record: logging.LogRecord, suppressed_count: int) -> str:
        level_icon = "🚨 <b>CRITICAL</b>" if record.levelno >= logging.CRITICAL else "⚠️ <b>ERROR</b>"
        now_str = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")
        file_loc = f"{Path(record.pathname).name}:{record.lineno}" if record.pathname else "unknown"

        tg_context = getattr(record, "tg_context", None)

        raw_msg = record.getMessage()
        if len(raw_msg) > 1200:
            safe_msg = html.escape(raw_msg[:1200]) + "..."
        else:
            safe_msg = html.escape(raw_msg)

        parts = [
            f"{level_icon} | {now_str}",
            f"<b>Модуль:</b> <code>{html.escape(record.name)}</code> ({file_loc})",
        ]

        if tg_context:
            parts.append(f"<b>Контекст:</b> {html.escape(str(tg_context))}")

        parts.append(f"\n<b>Повідомлення:</b>\n<code>{safe_msg}</code>")

        # Трейсбек
        if record.exc_info and record.exc_info[1]:
            tb_formatted = "".join(traceback.format_exception(*record.exc_info))
            if len(tb_formatted) > 1500:
                tb_formatted = "..." + tb_formatted[-1500:]
            parts.append(f"\n<b>Traceback:</b>\n<pre>{html.escape(tb_formatted)}</pre>")
        elif getattr(record, "stack_info", None):
            st_info = str(record.stack_info)
            if len(st_info) > 1000:
                st_info = "..." + st_info[-1000:]
            parts.append(f"\n<b>Stack:</b>\n<pre>{html.escape(st_info)}</pre>")

        if suppressed_count > 0:
            parts.append(f"\n🔁 <i>[Помилка повторилася ще {suppressed_count} разів за останню хвилину]</i>")

        return "\n".join(parts)

    async def _send_to_chat(self, chat_id: int, text: str):
        """Допоміжний метод відправки з fallback на звичайний текст при помилці HTML."""
        try:
            await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML"
            )
        except Exception as e:
            err_str = str(e).lower()
            if "can't parse entities" in err_str or "bad request" in err_str:
                plain_text = re.sub(r'<[^>]+>', '', text)
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=plain_text[:4000]
                )
            else:
                raise

    async def _async_send(self, alert_text: str):
        if not self.bot:
            return

        target_chat_id = None
        if DEV_CHAT_ID:
            try:
                chat_id_str = str(DEV_CHAT_ID).strip().split()[0]
                if chat_id_str and chat_id_str != "-.":
                    target_chat_id = int(chat_id_str)
            except Exception:
                target_chat_id = None

        # Якщо DEV_CHAT_ID не вказано, пробуємо MAIN_DEVELOPER_ID
        if target_chat_id is None:
            if MAIN_DEVELOPER_ID:
                try:
                    target_chat_id = int(MAIN_DEVELOPER_ID)
                except Exception:
                    return
            else:
                return

        try:
            await self._send_to_chat(target_chat_id, alert_text)
        except Exception as e:
            err_str = str(e).lower()
            sys.stderr.write(f"[TelegramLoggingHandler] Failed to send alert to {target_chat_id}: {e}\n")

            # Якщо чат не знайдено чи бота заблоковано в групі, надсилаємо безпосередньо розробнику в ПП
            if MAIN_DEVELOPER_ID and target_chat_id != int(MAIN_DEVELOPER_ID) and any(term in err_str for term in ["chat not found", "forbidden", "chat_id is empty", "migrated"]):
                try:
                    dev_id = int(MAIN_DEVELOPER_ID)
                    fallback_text = (
                        f"⚠️ <i>[УВАГА: DEV_CHAT_ID={target_chat_id} недоступний ({e}). Додайте бота @Winsou_bot у групу!]\n\n</i>"
                        + alert_text
                    )
                    await self._send_to_chat(dev_id, fallback_text)
                    sys.stderr.write(f"[TelegramLoggingHandler] Alert successfully forwarded to MAIN_DEVELOPER_ID ({dev_id})\n")
                except Exception as fb_err:
                    sys.stderr.write(f"[TelegramLoggingHandler] Fallback to MAIN_DEVELOPER_ID failed: {fb_err}\n")



class BotLogger:
    """Централізований логер для бота."""

    _instance: Optional["BotLogger"] = None
    _bot = None
    telegram_handler: Optional[TelegramLoggingHandler] = None

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
        """Налаштовує кореневий та локальний logging handlers."""
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)

        self.logger = logging.getLogger("bulka_bot")
        self.logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)

        # Формат логів
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )

        # Перевіряємо, чи вже є StreamHandler на root, щоб не дублювати
        has_console = any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in root_logger.handlers)
        if not has_console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.DEBUG if DEBUG else logging.INFO)
            console_handler.setFormatter(formatter)
            root_logger.addHandler(console_handler)

        # File handler (якщо увімкнено)
        if LOG_TO_FILE:
            has_file = any(isinstance(h, logging.FileHandler) for h in root_logger.handlers)
            if not has_file:
                log_path = Path(LOG_FILE_PATH)
                log_path.parent.mkdir(parents=True, exist_ok=True)

                file_handler = logging.FileHandler(log_path, encoding="utf-8")
                file_handler.setLevel(logging.DEBUG)  # Файл завжди DEBUG
                file_handler.setFormatter(formatter)
                root_logger.addHandler(file_handler)

    def set_bot(self, bot):
        """Встановлює екземпляр бота для Telegram алертів."""
        self._bot = bot
        if self.telegram_handler:
            self.telegram_handler.set_bot(bot)

    def _get_timestamp(self) -> str:
        """Повертає поточний час у форматі для логів."""
        return datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")

    def debug(self, message: str, **kwargs):
        """Debug рівень логування."""
        self.logger.debug(message, **kwargs)

    def info(self, message: str, **kwargs):
        """Info рівень логування."""
        self.logger.info(message, **kwargs)

    def info_alert(self, message: str, exc_info: bool = False, is_critical: bool = False):
        """Надсилає інформаційне/технічне сповіщення в Telegram групу."""
        self.logger.info(message, exc_info=exc_info)
        if self._bot and DEV_CHAT_ID:
            asyncio.create_task(self._send_manual_telegram_alert(message, is_critical=is_critical, exc_info=exc_info, is_info=True))

    def warning(self, message: str, **kwargs):
        """Warning рівень логування."""
        self.logger.warning(message, **kwargs)

    def error(self, message: str, exc_info: bool = True, send_alert: bool = True, **kwargs):
        """Error рівень логування. Автоматично відправляється в Telegram через TelegramLoggingHandler."""
        extra = kwargs.pop("extra", {})
        if not send_alert:
            extra["skip_tg_alert"] = True
        self.logger.error(message, exc_info=exc_info, extra=extra, **kwargs)

    def critical(self, message: str, exc_info: bool = True, send_alert: bool = True, **kwargs):
        """Critical рівень логування. Автоматично відправляється в Telegram через TelegramLoggingHandler."""
        extra = kwargs.pop("extra", {})
        if not send_alert:
            extra["skip_tg_alert"] = True
        self.logger.critical(message, exc_info=exc_info, extra=extra, **kwargs)

    def exception(self, message: str, send_alert: bool = True, **kwargs):
        """Логує exception з traceback."""
        self.error(message, exc_info=True, send_alert=send_alert, **kwargs)

    async def _send_manual_telegram_alert(self, message: str, is_critical: bool = False, exc_info: bool = False, is_info: bool = False):
        """Ручна відправка (наприклад, для info_alert)."""
        if not DEV_CHAT_ID or not self._bot:
            return
        try:
            chat_id_str = str(DEV_CHAT_ID).strip().split()[0]
            if not chat_id_str or chat_id_str == "-.":
                return
            chat_id_int = int(chat_id_str)

            header = "🚨 <b>CRITICAL</b>" if is_critical else ("ℹ️ <b>INFO</b>" if is_info else "⚠️ <b>Error</b>")
            safe_message = html.escape(message[:1800])
            if len(message) > 1800:
                safe_message += "..."

            alert_text = f"{header} | {self._get_timestamp()}\n{safe_message}"
            if exc_info:
                tb_message = html.escape(traceback.format_exc()[-1000:])
                alert_text += f"\n\n<b>Traceback:</b>\n<pre>{tb_message}</pre>"

            await self._bot.send_message(
                chat_id=chat_id_int,
                text=alert_text,
                parse_mode="HTML"
            )
        except Exception as e:
            sys.stderr.write(f"[BotLogger._send_manual_telegram_alert] Failed: {e}\n")


# Глобальний екземпляр логера
logger = BotLogger()


# Зручні функції для імпорту
def get_logger() -> BotLogger:
    """Повертає глобальний екземпляр логера."""
    return logger


def setup_bot_logger(bot):
    """Налаштовує логер з екземпляром бота для Telegram алертів."""
    root_logger = logging.getLogger()
    # Видаляємо попередній TelegramLoggingHandler, якщо він був доданий раніше
    root_logger.handlers = [h for h in root_logger.handlers if not isinstance(h, TelegramLoggingHandler)]

    telegram_handler = TelegramLoggingHandler(bot=bot)
    root_logger.addHandler(telegram_handler)

    logger.telegram_handler = telegram_handler
    logger.set_bot(bot)

