import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from aiogram.types import FSInputFile, User, Chat, UserProfilePhotos, PhotoSize
from bot.menus.developer import (
    get_user_avatar_input,
    _format_identity,
    _build_dev_team_view,
    _build_manager_card,
    developer_territorial_view,
    developer_admin_view,
    _build_managers_team_view,
)
from bot.config import MAIN_DEVELOPER_ID
from database.schema import init_db
from database.managers import init_managers_db, add_manager, get_manager_by_uid
from database import DB_PATH

class TestInlineCardsAndAvatar(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        await init_managers_db()

    async def asyncTearDown(self):
        import aiosqlite
        from database.managers import MANAGERS_DB_PATH
        async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
            await db.execute("DELETE FROM managers WHERE uid IN (5550001, 7770001)")
            await db.commit()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM users WHERE user_id IN (99901, 99902, 88801, 88802, 88803, 88804)")
            await db.commit()

    async def test_get_user_avatar_fallback(self):
        """When bot has no photos or fails, returns FSInputFile('img/ava.png')."""
        mock_bot = MagicMock()
        mock_bot.get_user_profile_photos = AsyncMock(side_effect=Exception("Chat not found"))
        
        avatar = await get_user_avatar_input(mock_bot, 999999999)
        self.assertIsInstance(avatar, FSInputFile)
        self.assertTrue(str(avatar.path).endswith("ava.png"))

    async def test_get_user_avatar_success(self):
        """When user has profile photos, returns highest resolution file_id."""
        mock_bot = MagicMock()
        mock_photos = UserProfilePhotos(
            total_count=1,
            photos=[[
                PhotoSize(file_id="small_photo", file_unique_id="u1", width=100, height=100),
                PhotoSize(file_id="large_photo", file_unique_id="u2", width=800, height=800)
            ]]
        )
        mock_bot.get_user_profile_photos = AsyncMock(return_value=mock_photos)
        
        avatar = await get_user_avatar_input(mock_bot, 123456789)
        self.assertEqual(avatar, "large_photo")

    async def test_format_identity_with_telegram_sync(self):
        """When username is missing in DB, _format_identity calls bot.get_chat and updates DB."""
        mock_bot = MagicMock()
        mock_chat = MagicMock()
        mock_chat.username = "test_developer_tg"
        mock_chat.first_name = "Даниїл"
        mock_chat.last_name = "Дусінський"
        mock_bot.get_chat = AsyncMock(return_value=mock_chat)

        name, username = await _format_identity(
            MAIN_DEVELOPER_ID,
            fallback_name="Головний Адміністратор",
            fallback_username=None,
            bot=mock_bot
        )
        self.assertEqual(username, "@test_developer_tg")
        self.assertIn("Даниїл", name)

    async def test_admin_team_view_buttons(self):
        """_build_dev_team_view produces inline buttons for each admin."""
        text, kb = await _build_dev_team_view()
        self.assertIn("Команда Адміністраторів", text)
        # Check that there is at least one button pointing to dev_admin_view:{MAIN_DEVELOPER_ID}
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data]
        self.assertTrue(any(c.startswith(f"dev_admin_view:{MAIN_DEVELOPER_ID}") for c in callbacks))

    async def test_manager_card_analytics(self):
        """_build_manager_card properly counts interns and workers and formats shop limit."""
        import aiosqlite
        test_mgr_uid = 5550001
        await add_manager(test_mgr_uid, process="Керівник", full_name="Менеджер Тест", username="mgr_test", city="Хмельницький", shops=["ТРЦ Оазис (ХМ-1)"])

        async with aiosqlite.connect(DB_PATH) as db:
            # Add 1 intern and 1 worker
            await db.execute(
                "INSERT OR REPLACE INTO users (user_id, username, full_name, city, manager_id, status) VALUES (?, ?, ?, ?, ?, ?)",
                (99901, "u_intern", "Стажер 1", "Хмельницький", test_mgr_uid, "Стажер")
            )
            await db.execute(
                "INSERT OR REPLACE INTO users (user_id, username, full_name, city, manager_id, status) VALUES (?, ?, ?, ?, ?, ?)",
                (99902, "u_worker", "Працівник 1", "Хмельницький", test_mgr_uid, "Працівник")
            )
            await db.commit()

        card = await _build_manager_card(test_mgr_uid, is_admin=True, is_territorial=False)
        self.assertIsNotNone(card)
        text, kb = card
        self.assertIn("Менеджер Тест", text)
        self.assertIn("Стажерів: 1", text)
        self.assertIn("Працівників: 1", text)
        self.assertIn("Всього: 2", text)
        self.assertIn("Магазини (1/5):", text)

    async def test_territorial_view_analytics_by_type_and_city(self):
        """developer_territorial_view calculates workers/trainees filtered strictly by city and VV/TZ type."""
        import aiosqlite
        t_uid_tz = 7770001
        await add_manager(t_uid_tz, process="Територіал", full_name="Територіал ТЗ", username="territorial_tz", city="Камʼянець-Подільський", territorial_type="ТЗ")

        async with aiosqlite.connect(DB_PATH) as db:
            # User 1: Камʼянець-Подільський, ТЗ role (e.g. "Керуючий"), status = "Працівник"
            await db.execute(
                "INSERT OR REPLACE INTO users (user_id, username, full_name, city, role, status) VALUES (?, ?, ?, ?, ?, ?)",
                (88801, "tz_work", "ТЗ Працівник", "Камʼянець-Подільський", "Керуючий", "Працівник")
            )
            # User 2: Камʼянець-Подільський, ТЗ role, status = "Стажер"
            await db.execute(
                "INSERT OR REPLACE INTO users (user_id, username, full_name, city, role, status) VALUES (?, ?, ?, ?, ?, ?)",
                (88802, "tz_intern", "ТЗ Стажер", "Камʼянець-Подільський", "Керуючий", "Стажер")
            )
            # User 3: Камʼянець-Подільський, ВВ role (e.g. "ВВ Пекар"), status = "Працівник" -> SHOULD NOT count for ТЗ!
            await db.execute(
                "INSERT OR REPLACE INTO users (user_id, username, full_name, city, role, status) VALUES (?, ?, ?, ?, ?, ?)",
                (88803, "vv_work", "ВВ Працівник", "Камʼянець-Подільський", "ВВ Пекар", "Працівник")
            )
            # User 4: Хмельницький (different city), ТЗ role -> SHOULD NOT count for КП!
            await db.execute(
                "INSERT OR REPLACE INTO users (user_id, username, full_name, city, role, status) VALUES (?, ?, ?, ?, ?, ?)",
                (88804, "hm_work", "ХМ Працівник", "Хмельницький", "Керуючий", "Працівник")
            )
            await db.commit()

        mock_cb = MagicMock()
        mock_cb.data = f"dev_territorial_view:{t_uid_tz}"
        mock_cb.from_user.id = MAIN_DEVELOPER_ID
        mock_cb.message = MagicMock()
        mock_cb.message.photo = None
        mock_cb.message.answer_photo = AsyncMock()
        mock_cb.message.delete = AsyncMock()
        mock_cb.answer = AsyncMock()
        mock_cb.bot = MagicMock()
        mock_cb.bot.get_user_profile_photos = AsyncMock(side_effect=Exception("No photo"))

        with patch("bot.menus.developer._ensure_developer", return_value=True):
            await developer_territorial_view(mock_cb)

        self.assertTrue(mock_cb.message.answer_photo.called)
        sent_caption = mock_cb.message.answer_photo.call_args.kwargs.get("caption") or mock_cb.message.answer_photo.call_args[1].get("caption")
        self.assertIn("Камʼянець-Подільський", sent_caption)
        self.assertIn("Стажерів (ТЗ): 1", sent_caption)
        self.assertIn("Працівників (ТЗ): 1", sent_caption)
        self.assertIn("Торговий зал (ТЗ)", sent_caption)

    async def test_developer_menus_render_without_error(self):
        """Test developer_dev_team_menu, developer_territorials_menu, developer_observers_menu."""
        from bot.menus.developer import (
            developer_dev_team_menu,
            developer_manage_managers_menu,
            developer_territorials_menu,
            developer_observers_menu
        )
        mock_cb = MagicMock()
        mock_cb.from_user.id = MAIN_DEVELOPER_ID
        mock_cb.message = MagicMock()
        mock_cb.message.photo = None
        mock_cb.message.answer_photo = AsyncMock()
        mock_cb.message.answer = AsyncMock()
        mock_cb.message.delete = AsyncMock()
        mock_cb.answer = AsyncMock()
        mock_cb.bot = MagicMock()
        mock_cb.bot.get_chat = AsyncMock(side_effect=Exception("No chat"))
        mock_state = MagicMock()
        mock_state.update_data = AsyncMock()

        with patch("bot.menus.developer._ensure_developer", return_value=True), \
             patch("bot.menus.developer._check_access", return_value=(True, True, False)):
            await developer_dev_team_menu(mock_cb, mock_state)
            await developer_manage_managers_menu(mock_cb, mock_state)
            await developer_territorials_menu(mock_cb)
            await developer_observers_menu(mock_cb)

    async def test_user_and_manager_and_developer_profile_avatars(self):
        """Test that developer_profile_handler, manager_profile_handler, and profile_handler_new_message render avatars."""
        from bot.handlers import (
            developer_profile_handler,
            manager_profile_handler,
            profile_handler_new_message,
            manager_intern_profile_handler
        )
        mock_cb = MagicMock()
        mock_cb.from_user.id = MAIN_DEVELOPER_ID
        mock_cb.from_user.full_name = "Розробник"
        mock_cb.from_user.username = "dev_tg"
        mock_cb.message = MagicMock()
        mock_cb.message.photo = None
        mock_cb.message.answer_photo = AsyncMock()
        mock_cb.message.answer = AsyncMock()
        mock_cb.message.delete = AsyncMock()
        mock_cb.answer = AsyncMock()
        mock_cb.bot = MagicMock()
        mock_cb.bot.get_user_profile_photos = AsyncMock(side_effect=Exception("No photo"))

        # 1. Developer Profile
        await developer_profile_handler(mock_cb)
        self.assertTrue(mock_cb.message.answer_photo.called)
        caption = mock_cb.message.answer_photo.call_args.kwargs.get("caption")
        self.assertIn("Профіль адміністратора", caption)

        # 2. Manager Profile
        mock_cb.message.answer_photo.reset_mock()
        await manager_profile_handler(mock_cb)
        self.assertTrue(mock_cb.message.answer_photo.called)
        caption = mock_cb.message.answer_photo.call_args.kwargs.get("caption")
        self.assertIn("Профіль керівника-Булочки", caption)

        # 3. Regular User Profile
        mock_cb.message.answer_photo.reset_mock()
        mock_cb.from_user.id = 12345
        with patch("bot.handlers.get_user_details", return_value={'user_id': 12345, 'full_name': 'Тестовий Юзер', 'role': 'Стажер', 'manager_id': None}), \
             patch("bot.handlers.get_progress", return_value=1), \
             patch("bot.handlers.get_available_day", return_value=2):
            await profile_handler_new_message(mock_cb)
            self.assertTrue(mock_cb.message.answer_photo.called)
            caption = mock_cb.message.answer_photo.call_args.kwargs.get("caption")
            self.assertIn("Персональний профіль", caption)

        # 4. Manager Intern Profile
        mock_cb.message.answer_photo.reset_mock()
        mock_cb.data = "manager_intern_profile_12345"
        with patch("bot.handlers.get_user_details", return_value={'user_id': 12345, 'full_name': 'Тестовий Юзер', 'role': 'Стажер', 'city': 'Київ', 'shop': 'Магазин 1'}), \
             patch("bot.handlers.get_user_progress", return_value=[]):
            await manager_intern_profile_handler(mock_cb)
            self.assertTrue(mock_cb.message.answer_photo.called)
            caption = mock_cb.message.answer_photo.call_args.kwargs.get("caption")
            self.assertIn("Булка Котиків", caption)

if __name__ == "__main__":
    unittest.main()
