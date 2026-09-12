import unittest
from unittest.mock import AsyncMock, patch
import asyncio
import logging
import time
from bot.services.logger import TelegramLoggingHandler, setup_bot_logger, get_logger
from aiogram.types import ErrorEvent, Update, Message, CallbackQuery, User


class TestBugAlertsSystem(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_bot = AsyncMock()
        self.mock_bot.send_message = AsyncMock()

    async def test_root_logger_intercepts_any_module_error(self):
        """Будь-який модуль, що викликає standard logging.getLogger(__name__).error(...), має викликати алерт."""
        with patch("bot.services.logger.DEV_CHAT_ID", "-100123456789"):
            setup_bot_logger(self.mock_bot)

            test_logger = logging.getLogger("bot.menus.some_random_menu")
            test_logger.error("Something went wrong in the random menu!")

            # Дозволяємо asyncio task виконатися
            await asyncio.sleep(0.05)

            self.assertTrue(self.mock_bot.send_message.called)
            args, kwargs = self.mock_bot.send_message.call_args
            self.assertEqual(kwargs["chat_id"], -100123456789)
            self.assertIn("Something went wrong in the random menu!", kwargs["text"])
            self.assertIn("bot.menus.some_random_menu", kwargs["text"])
            self.assertEqual(kwargs["parse_mode"], "HTML")

    async def test_anti_spam_throttles_burst_errors(self):
        """10 однакових помилок підряд мають викликати лише 1 відправку в Telegram."""
        with patch("bot.services.logger.DEV_CHAT_ID", "-100123456789"):
            setup_bot_logger(self.mock_bot)

            test_logger = logging.getLogger("database.burst_module")
            for i in range(10):
                test_logger.error("Repeated database connection timeout")

            await asyncio.sleep(0.05)

            # Рівно 1 повідомлення має бути надіслано
            self.assertEqual(self.mock_bot.send_message.call_count, 1)

    async def test_anti_spam_reports_suppressed_count_after_cooldown(self):
        """Після спливу кулдауну наступний алерт повинен містити лічильник повторень."""
        with patch("bot.services.logger.DEV_CHAT_ID", "-100123456789"):
            handler = TelegramLoggingHandler(bot=self.mock_bot, cooldown_seconds=1)
            root = logging.getLogger()
            root.handlers = [h for h in root.handlers if not isinstance(h, TelegramLoggingHandler)]
            root.addHandler(handler)

            test_logger = logging.getLogger("service.intermittent")
            def trigger_flaky():
                test_logger.error("Flaky network call")

            # 1st error -> sent immediately, 2nd & 3rd -> suppressed
            for _ in range(3):
                trigger_flaky()

            await asyncio.sleep(0.05)
            self.assertEqual(self.mock_bot.send_message.call_count, 1)

            # Чекаємо закінчення кулдауну (1.1 сек)
            await asyncio.sleep(1.1)

            # 4th error -> should be sent with suppressed count notice
            trigger_flaky()
            await asyncio.sleep(0.05)

            self.assertEqual(self.mock_bot.send_message.call_count, 2)
            second_call_text = self.mock_bot.send_message.call_args_list[1][1]["text"]
            self.assertIn("Помилка повторилася ще 2 разів", second_call_text)


    async def test_html_escaping_and_traceback_safety(self):
        """Помилка з небезпечними символами HTML (<bad_tag>, &) має безпечно екрануватися."""
        with patch("bot.services.logger.DEV_CHAT_ID", "-100123456789"):
            setup_bot_logger(self.mock_bot)

            test_logger = logging.getLogger("security.test")
            try:
                raise ValueError("<dangerous_tag> & 'unescaped_quotes'")
            except ValueError:
                test_logger.exception("Error with <xml> payload & <scripts>")

            await asyncio.sleep(0.05)

            self.assertTrue(self.mock_bot.send_message.called)
            text = self.mock_bot.send_message.call_args[1]["text"]
            self.assertNotIn("<dangerous_tag>", text)
            self.assertIn("&lt;dangerous_tag&gt;", text)
            self.assertIn("&lt;xml&gt;", text)
            self.assertIn("ValueError", text)
            # Переконуємось, що довжина в межах лімітів Telegram
            self.assertLess(len(text), 4096)

    async def test_skip_tg_alert_parameter(self):
        """Коли send_alert=False, повідомлення не має відправлятися в Telegram."""
        with patch("bot.services.logger.DEV_CHAT_ID", "-100123456789"):
            setup_bot_logger(self.mock_bot)

            logger = get_logger()
            logger.error("Silent internal error", send_alert=False)

            await asyncio.sleep(0.05)
            self.assertFalse(self.mock_bot.send_message.called)

    async def test_aiogram_global_error_handler_context(self):
        """Aiogram global_error_handler повинен витягувати контекст користувача та надсилати в алерт."""
        from bot.handlers import global_error_handler

        with patch("bot.services.logger.DEV_CHAT_ID", "-100123456789"):
            setup_bot_logger(self.mock_bot)

            user = User(id=999888, is_bot=False, first_name="Олександр", username="olex_test")
            callback = CallbackQuery(
                id="123",
                from_user=user,
                chat_instance="test",
                data="att_wave_select:42"
            )
            update = Update(update_id=1, callback_query=callback)
            event = ErrorEvent(update=update, exception=KeyError("invalid_wave_key"))

            await global_error_handler(event)
            await asyncio.sleep(0.05)

            self.assertTrue(self.mock_bot.send_message.called)
            text = self.mock_bot.send_message.call_args[1]["text"]
            self.assertIn("@olex_test", text)
            self.assertIn("999888", text)
            self.assertIn("att_wave_select:42", text)
            self.assertIn("KeyError", text)


if __name__ == "__main__":
    unittest.main()
