import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bot.menus.developer import (
    _users_menu_keyboard,
    developer_users_add_start,
    developer_users_add_city,
    developer_users_add_shop,
    developer_users_add_role,
)
from bot.config import MAIN_DEVELOPER_ID
from database.schema import init_db
from database.managers import init_managers_db
from database.tokens import init_tokens_db, get_token_data

class TestAddUserInviteLink(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        await init_managers_db()
        await init_tokens_db()

    def test_users_menu_keyboard_has_add_button(self):
        """Admin and Territorial keyboards should have '➕ Додати' button."""
        admin_kb = _users_menu_keyboard(is_admin=True, is_territorial=False, is_observer=False)
        admin_callbacks = [b.callback_data for row in admin_kb.inline_keyboard for b in row]
        self.assertIn("dev_users_add", admin_callbacks)

        terr_kb = _users_menu_keyboard(is_admin=False, is_territorial=True, is_observer=False)
        terr_callbacks = [b.callback_data for row in terr_kb.inline_keyboard for b in row]
        self.assertIn("dev_users_add", terr_callbacks)

        obs_kb = _users_menu_keyboard(is_admin=False, is_territorial=False, is_observer=True)
        obs_callbacks = [b.callback_data for row in obs_kb.inline_keyboard for b in row]
        self.assertNotIn("dev_users_add", obs_callbacks)

    async def test_full_add_user_invite_flow(self):
        """Test the end-to-end wizard flow: Start -> City -> Shop -> Role -> Token Link."""
        mock_cb = MagicMock()
        mock_cb.from_user.id = MAIN_DEVELOPER_ID
        mock_cb.message = MagicMock()
        mock_cb.message.photo = None
        mock_cb.message.edit_text = AsyncMock()
        mock_cb.message.answer = AsyncMock()
        mock_cb.answer = AsyncMock()
        
        mock_bot_user = MagicMock()
        mock_bot_user.username = "Bulka_Test_Bot"
        mock_cb.bot = MagicMock()
        mock_cb.bot.get_me = AsyncMock(return_value=mock_bot_user)

        state_data = {}
        mock_state = MagicMock()
        mock_state.clear = AsyncMock(side_effect=lambda: state_data.clear())
        mock_state.update_data = AsyncMock(side_effect=lambda **kwargs: state_data.update(kwargs))
        mock_state.get_data = AsyncMock(side_effect=lambda: state_data)

        with patch("bot.menus.developer._check_access", return_value=(True, True, False)):
            # 1. Start: choose city
            await developer_users_add_start(mock_cb, mock_state)
            self.assertTrue(mock_cb.message.edit_text.called or mock_cb.message.answer.called)

            # 2. Choose city: Кам'янець-Подільський
            mock_cb.data = "dev_users_add_city:Кам'янець-Подільський"
            await developer_users_add_city(mock_cb, mock_state)
            self.assertEqual(state_data.get("dev_add_city"), "Кам'янець-Подільський")

            # 3. Choose shop: index 0
            mock_cb.data = "dev_users_add_shop:0"
            await developer_users_add_shop(mock_cb, mock_state)
            self.assertIsNotNone(state_data.get("dev_add_shop"))

            # 4. Choose role: index 0
            mock_cb.data = "dev_users_add_role:0"
            mock_cb.message.edit_text.reset_mock()
            mock_cb.message.answer.reset_mock()

            await developer_users_add_role(mock_cb, mock_state)
            
            # Check output message
            if mock_cb.message.edit_text.called:
                sent_text = mock_cb.message.edit_text.call_args[0][0]
            else:
                sent_text = mock_cb.message.answer.call_args[0][0]

            self.assertIn("Посилання створено!", sent_text)
            self.assertIn("https://t.me/Bulka_Test_Bot?start=", sent_text)
            self.assertIn("Посилання діє 24 години", sent_text)

            # Extract token from text
            # Format: https://t.me/Bulka_Test_Bot?start={creator_id}-{token}
            start_param = sent_text.split("start=")[1].split("</code>")[0]
            creator_id_str, token_str = start_param.split("-")
            self.assertEqual(int(creator_id_str), MAIN_DEVELOPER_ID)

            # Verify token in database
            token_info = await get_token_data(token_str)
            self.assertEqual(token_info["status"], "ok")
            self.assertEqual(token_info["manager_id"], MAIN_DEVELOPER_ID)
            self.assertEqual(token_info["city"], "Кам'янець-Подільський")

if __name__ == "__main__":
    unittest.main()
