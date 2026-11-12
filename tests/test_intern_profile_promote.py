import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.types import CallbackQuery, Message, User

from bot.menus.manager import (
    _show_intern_details,
    manager_promote_prompt_handler,
    manager_promote_confirm_handler,
)
from bot.menus.developer import (
    _show_user_profile_card,
    developer_user_promote_prompt_handler,
    developer_user_promote_confirm_handler,
)


class TestInternProfilePromote(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot = AsyncMock()
        self.user = User(id=777, is_bot=False, first_name="Manager")

    @patch("bot.menus.manager.get_user_days_report", new_callable=AsyncMock)
    @patch("bot.menus.manager.get_user_details", new_callable=AsyncMock)
    @patch("bot.menus.manager._send_or_edit_card_photo", new_callable=AsyncMock)
    @patch("bot.menus.manager.get_user_avatar_input", new_callable=AsyncMock)
    async def test_manager_card_shows_promote_button_for_intern(
        self, mock_avatar, mock_send, mock_details, mock_report
    ):
        mock_report.return_value = "Report text"
        mock_avatar.return_value = None
        mock_details.return_value = {"user_id": 101, "status": "Стажер", "full_name": "Іван Тест"}

        cb = MagicMock(spec=CallbackQuery)
        cb.bot = self.bot
        cb.from_user = self.user

        await _show_intern_details(cb, 101, back_callback="mgr_my_team")

        # Verify that _send_or_edit_card_photo received reply_markup with promote button
        self.assertTrue(mock_send.called)
        _, kwargs = mock_send.call_args
        kb = kwargs.get("reply_markup")
        all_buttons = [b.text for row in kb.inline_keyboard for b in row]
        self.assertIn("🎓 Перевести у працівники", all_buttons)

    @patch("bot.menus.manager.get_user_days_report", new_callable=AsyncMock)
    @patch("bot.menus.manager.get_user_details", new_callable=AsyncMock)
    @patch("bot.menus.manager._send_or_edit_card_photo", new_callable=AsyncMock)
    @patch("bot.menus.manager.get_user_avatar_input", new_callable=AsyncMock)
    async def test_manager_card_hides_promote_button_for_worker(
        self, mock_avatar, mock_send, mock_details, mock_report
    ):
        mock_report.return_value = "Report text"
        mock_avatar.return_value = None
        mock_details.return_value = {"user_id": 102, "status": "Працівник", "full_name": "Ольга Працівник"}

        cb = MagicMock(spec=CallbackQuery)
        cb.bot = self.bot
        cb.from_user = self.user

        await _show_intern_details(cb, 102, back_callback="mgr_my_team")

        self.assertTrue(mock_send.called)
        _, kwargs = mock_send.call_args
        kb = kwargs.get("reply_markup")
        all_buttons = [b.text for row in kb.inline_keyboard for b in row]
        self.assertNotIn("🎓 Перевести у працівники", all_buttons)

    @patch("bot.menus.manager._ensure_manager", new_callable=AsyncMock)
    @patch("bot.menus.manager.get_user_details", new_callable=AsyncMock)
    @patch("bot.menus.manager._edit_menu_message", new_callable=AsyncMock)
    async def test_manager_promote_prompt(self, mock_edit, mock_details, mock_ensure):
        mock_ensure.return_value = True
        mock_details.return_value = {"user_id": 103, "full_name": "Петро Стажер"}

        cb = MagicMock(spec=CallbackQuery)
        cb.data = "mgr_promote_prompt:103:mgr_my_team"
        cb.message = MagicMock()
        cb.answer = AsyncMock()

        await manager_promote_prompt_handler(cb)

        self.assertTrue(mock_edit.called)
        args, kwargs = mock_edit.call_args
        text = args[1]
        self.assertIn("Петро Стажер", text)
        self.assertIn("Переведення у статус Працівника", text)
        kb = kwargs.get("reply_markup")
        all_cb_data = [b.callback_data for row in kb.inline_keyboard for b in row]
        self.assertIn("mgr_promote_confirm:103:mgr_my_team", all_cb_data)

    @patch("bot.menus.manager._ensure_manager", new_callable=AsyncMock)
    @patch("bot.menus.manager.get_user_details", new_callable=AsyncMock)
    @patch("bot.menus.manager.update_user_role", new_callable=AsyncMock)
    @patch("bot.menus.manager._show_intern_details", new_callable=AsyncMock)
    async def test_manager_promote_confirm(
        self, mock_show, mock_update, mock_details, mock_ensure
    ):
        mock_ensure.return_value = True
        mock_details.return_value = {"user_id": 104, "full_name": "Марія Стажер"}

        cb = MagicMock(spec=CallbackQuery)
        cb.data = "mgr_promote_confirm:104:mgr_my_team"
        cb.from_user = self.user
        cb.bot = self.bot
        cb.answer = AsyncMock()

        await manager_promote_confirm_handler(cb)

        mock_update.assert_awaited_once_with(104, "Працівник", actor_id=777)
        self.bot.send_message.assert_awaited_once()
        sent_uid = self.bot.send_message.call_args[0][0]
        self.assertEqual(sent_uid, 104)
        mock_show.assert_awaited_once_with(cb, 104, back_callback="mgr_my_team")

    @patch("bot.menus.developer.is_observer_user", new_callable=AsyncMock)
    @patch("bot.menus.developer.get_user_details", new_callable=AsyncMock)
    @patch("bot.menus.developer.get_user_days_report", new_callable=AsyncMock)
    @patch("bot.menus.developer._send_or_edit_card_photo", new_callable=AsyncMock)
    @patch("bot.menus.developer.get_user_avatar_input", new_callable=AsyncMock)
    async def test_developer_card_promote_button(
        self, mock_avatar, mock_send, mock_report, mock_details, mock_obs
    ):
        mock_obs.return_value = False
        mock_report.return_value = "Dev report"
        mock_avatar.return_value = None
        mock_details.return_value = {"user_id": 105, "status": "Стажер"}

        cb = MagicMock(spec=CallbackQuery)
        cb.bot = self.bot
        cb.from_user = self.user

        await _show_user_profile_card(cb, 105, ret_code="staff")

        self.assertTrue(mock_send.called)
        _, kwargs = mock_send.call_args
        kb = kwargs.get("reply_markup")
        all_buttons = [b.text for row in kb.inline_keyboard for b in row]
        self.assertIn("🎓 Перевести у працівники", all_buttons)

    @patch("bot.menus.developer.get_user_details", new_callable=AsyncMock)
    @patch("database.users.update_user_role", new_callable=AsyncMock)
    @patch("bot.menus.developer._rebuild_user_profile_view", new_callable=AsyncMock)
    async def test_developer_promote_confirm(
        self, mock_rebuild, mock_update, mock_details
    ):
        mock_details.return_value = {"user_id": 106, "full_name": "Денис Стажер"}

        cb = MagicMock(spec=CallbackQuery)
        cb.data = "dev_u_promote_confirm:106:menu"
        cb.from_user = self.user
        cb.bot = self.bot
        cb.answer = AsyncMock()
        state = MagicMock()

        await developer_user_promote_confirm_handler(cb, state)

        mock_update.assert_awaited_once_with(106, "Працівник", actor_id=777)
        self.bot.send_message.assert_awaited_once()
        self.assertEqual(self.bot.send_message.call_args[0][0], 106)
        mock_rebuild.assert_awaited_once_with(cb, 106, state, ret_code="menu")


if __name__ == "__main__":
    unittest.main()
