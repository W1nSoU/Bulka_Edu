import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.types import CallbackQuery, Message, User, Chat, InlineKeyboardMarkup, InputMediaPhoto, FSInputFile

from bot.menus.manager import (
    _decode_manager_card_back,
    _edit_menu_message,
    _show_intern_details,
    manager_view_intern,
    _list_interns_generic,
    MANAGER_PHOTO_PATH
)

class TestManagerPhotoAndCard(unittest.IsolatedAsyncioTestCase):

    def test_decode_manager_card_back(self):
        self.assertEqual(_decode_manager_card_back("team"), "mgr_my_team")
        self.assertEqual(_decode_manager_card_back("active"), "mgr_active")
        self.assertEqual(_decode_manager_card_back("completed"), "mgr_completed")
        self.assertEqual(_decode_manager_card_back("inactive"), "mgr_inactive")
        self.assertEqual(_decode_manager_card_back("filters"), "mgr_filters_menu")
        self.assertEqual(_decode_manager_card_back("all"), "mgr_all_workers_menu")
        self.assertEqual(_decode_manager_card_back("all_in"), "mgr_all_workers_menu")
        self.assertEqual(_decode_manager_card_back("role_3"), "mgr_filter_role:3")
        self.assertEqual(_decode_manager_card_back("city_1"), "mgr_filter_city:1")
        self.assertEqual(_decode_manager_card_back("in_2"), "mgr_interns_list:2")
        self.assertEqual(_decode_manager_card_back("wk_0"), "mgr_workers_list:0")
        self.assertEqual(_decode_manager_card_back(""), "mgr_my_team")
        self.assertEqual(_decode_manager_card_back("mgr_custom_cb"), "mgr_custom_cb")

    @patch("bot.menus.manager.get_user_days_report", new_callable=AsyncMock)
    @patch("bot.menus.manager.get_user_avatar_input", new_callable=AsyncMock)
    @patch("bot.menus.manager._send_or_edit_card_photo", new_callable=AsyncMock)
    async def test_show_intern_details(self, mock_send_card, mock_avatar, mock_report):
        mock_report.return_value = "<b>User Report</b>"
        mock_avatar.return_value = "fake_file_id_123"

        bot_mock = MagicMock()
        callback = MagicMock(spec=CallbackQuery)
        callback.bot = bot_mock
        callback.message = MagicMock(spec=Message)

        await _show_intern_details(callback, 999, back_callback="mgr_active")

        mock_report.assert_awaited_once_with(999, bot=bot_mock)
        mock_avatar.assert_awaited_once_with(bot_mock, 999)
        mock_send_card.assert_awaited_once()

        # Check that keyboard includes back button to mgr_active
        _, kwargs = mock_send_card.call_args
        kb = kwargs.get("reply_markup") or mock_send_card.call_args[0][3]
        buttons_cbs = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        self.assertIn("mgr_active", buttons_cbs)
        self.assertIn("mgr_my_team", buttons_cbs)
        self.assertIn("manager_menu", buttons_cbs)

    @patch("bot.menus.manager._ensure_manager", new_callable=AsyncMock)
    @patch("bot.menus.manager._show_intern_details", new_callable=AsyncMock)
    async def test_manager_view_intern_variations(self, mock_show, mock_ensure):
        mock_ensure.return_value = True
        state = MagicMock()

        # 1. Simple format
        cb1 = MagicMock(spec=CallbackQuery)
        cb1.data = "mgr_view_intern_1001"
        cb1.answer = AsyncMock()
        await manager_view_intern(cb1, state)
        mock_show.assert_awaited_with(cb1, 1001, back_callback="mgr_my_team")

        # 2. Format with :active
        cb2 = MagicMock(spec=CallbackQuery)
        cb2.data = "mgr_view_intern_1002:active"
        cb2.answer = AsyncMock()
        await manager_view_intern(cb2, state)
        mock_show.assert_awaited_with(cb2, 1002, back_callback="mgr_active")

        # 3. Format with :role_2
        cb3 = MagicMock(spec=CallbackQuery)
        cb3.data = "mgr_view_intern_1003:role_2"
        cb3.answer = AsyncMock()
        await manager_view_intern(cb3, state)
        mock_show.assert_awaited_with(cb3, 1003, back_callback="mgr_filter_role:2")

        # 4. Format with colons mgr_view_intern:1004:in_1
        cb4 = MagicMock(spec=CallbackQuery)
        cb4.data = "mgr_view_intern:1004:in_1"
        cb4.answer = AsyncMock()
        await manager_view_intern(cb4, state)
        mock_show.assert_awaited_with(cb4, 1004, back_callback="mgr_interns_list:1")

    @patch("bot.menus.manager._edit_menu_message", new_callable=AsyncMock)
    async def test_list_interns_generic_creates_callbacks(self, mock_edit):
        cb = MagicMock(spec=CallbackQuery)
        cb.message = MagicMock(spec=Message)
        cb.answer = AsyncMock()
        interns = [{"user_id": 555, "full_name": "Тест Стажер", "role": "Бариста", "current_block": 2}]
        await _list_interns_generic(
            cb, interns, "Title", "Empty",
            back_callback="mgr_filters_menu", ret_code="active"
        )
        mock_edit.assert_awaited_once()
        kb = mock_edit.call_args[0][2]
        cbs = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        self.assertIn("mgr_view_intern_555:active", cbs)
        self.assertIn("mgr_filters_menu", cbs)

if __name__ == "__main__":
    unittest.main()
