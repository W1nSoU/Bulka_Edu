# -*- coding: utf-8 -*-
"""
Tests for Manager promoting an intern to worker directly from the intern's profile card.
"""

import os
import tempfile
import unittest
import aiosqlite
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.types import CallbackQuery, Message, User, Chat, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey

import database.users as users_db
import database.managers as managers_db

from bot.handlers import manager_intern_profile_handler
from bot.menus.manager import (
    manager_promote_prompt_handler,
    manager_promote_confirm_handler
)


class TestManagerInternPromoteFromProfile(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.users_db_path = os.path.join(self.temp_dir.name, "test_users.db")
        self.managers_db_path = os.path.join(self.temp_dir.name, "test_managers.db")

        # Set up users.db
        async with aiosqlite.connect(self.users_db_path) as db:
            await db.execute("""
                CREATE TABLE users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    first_seen TIMESTAMP,
                    current_block INTEGER DEFAULT 1,
                    manager_name TEXT,
                    last_activity TIMESTAMP,
                    role TEXT,
                    city TEXT,
                    shop TEXT,
                    manager_id INTEGER,
                    status TEXT,
                    worker_since TIMESTAMP
                )
            """)
            await db.execute("""
                CREATE TABLE progress (
                    user_id INTEGER,
                    day INTEGER,
                    completed INTEGER DEFAULT 0,
                    completed_at TIMESTAMP,
                    manual_open INTEGER DEFAULT 0,
                    manual_opened_by TEXT,
                    PRIMARY KEY (user_id, day)
                )
            """)
            await db.execute("""
                CREATE TABLE training_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    event_type TEXT,
                    event_at TIMESTAMP,
                    actor_id INTEGER,
                    full_name TEXT,
                    username TEXT,
                    city TEXT,
                    shop TEXT,
                    role TEXT,
                    manager_id INTEGER
                )
            """)
            # Trainee 1001
            await db.execute("""
                INSERT INTO users (user_id, username, full_name, role, city, shop, manager_id, status)
                VALUES (1001, 'trainee_cat', 'Булка Стажер Олексій', 'Касир', 'Хмельницький', 'B-01', 2001, 'Стажер')
            """)
            # Worker 1002
            await db.execute("""
                INSERT INTO users (user_id, username, full_name, role, city, shop, manager_id, status)
                VALUES (1002, 'worker_cat', 'Булка Працівник Марія', 'Касир', 'Хмельницький', 'B-01', 2001, 'Працівник')
            """)
            await db.commit()

        # Set up managers.db
        async with aiosqlite.connect(self.managers_db_path) as db:
            await db.execute("""
                CREATE TABLE managers (
                    uid INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    process TEXT,
                    city TEXT,
                    shops TEXT,
                    responsible_uid INTEGER,
                    status TEXT DEFAULT 'active'
                )
            """)
            await db.execute("""
                INSERT INTO managers (uid, username, full_name, process, city, shops, status)
                VALUES (2001, 'mgr_user', 'Керівник Магазину', 'Керівник', 'Хмельницький', '["B-01"]', 'active')
            """)
            await db.commit()

        self.storage = MemoryStorage()
        self.key = StorageKey(bot_id=1, chat_id=2001, user_id=2001)
        self.state = FSMContext(storage=self.storage, key=self.key)

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    def _create_mock_cb(self, data: str, user_id: int = 2001) -> CallbackQuery:
        cb = AsyncMock(spec=CallbackQuery)
        cb.data = data
        cb.from_user = User(id=user_id, is_bot=False, first_name="Manager")
        msg = AsyncMock(spec=Message)
        msg.photo = None
        msg.answer = AsyncMock()
        msg.edit_text = AsyncMock()
        msg.edit_caption = AsyncMock()
        cb.message = msg
        cb.answer = AsyncMock()
        cb.bot = AsyncMock()
        return cb

    @patch("bot.handlers.DB_PATH")
    @patch("database.users.DB_PATH")
    @patch("database.managers.MANAGERS_DB_PATH")
    async def test_trainee_profile_has_promote_button(self, mock_mgr_db, mock_u_db, mock_h_db):
        mock_mgr_db.return_value = self.managers_db_path
        mock_u_db.return_value = self.users_db_path
        mock_h_db.return_value = self.users_db_path
        with patch("database.users.DB_PATH", self.users_db_path), \
             patch("database.managers.MANAGERS_DB_PATH", self.managers_db_path), \
             patch("bot.handlers.DB_PATH", self.users_db_path), \
             patch("bot.utils.get_user_avatar_input", return_value=None), \
             patch("bot.utils._send_or_edit_card_photo") as mock_send_card:

            cb = self._create_mock_cb("manager_intern_profile_1001")
            await manager_intern_profile_handler(cb)

            self.assertTrue(mock_send_card.called)
            args, kwargs = mock_send_card.call_args
            kb = kwargs.get("reply_markup") or args[3]
            buttons = [btn for row in kb.inline_keyboard for btn in row]
            
            promote_btn = next((b for b in buttons if b.callback_data == "mgr_promote_prompt:1001:profile"), None)
            self.assertIsNotNone(promote_btn, "Button '🎓 Перевести на працівника' should exist for intern")
            self.assertEqual(promote_btn.text, "🎓 Перевести на працівника")

    @patch("bot.handlers.DB_PATH")
    @patch("database.users.DB_PATH")
    @patch("database.managers.MANAGERS_DB_PATH")
    async def test_worker_profile_has_no_promote_button(self, mock_mgr_db, mock_u_db, mock_h_db):
        with patch("database.users.DB_PATH", self.users_db_path), \
             patch("database.managers.MANAGERS_DB_PATH", self.managers_db_path), \
             patch("bot.handlers.DB_PATH", self.users_db_path), \
             patch("bot.utils.get_user_avatar_input", return_value=None), \
             patch("bot.utils._send_or_edit_card_photo") as mock_send_card:

            cb = self._create_mock_cb("manager_intern_profile_1002")
            await manager_intern_profile_handler(cb)

            self.assertTrue(mock_send_card.called)
            args, kwargs = mock_send_card.call_args
            kb = kwargs.get("reply_markup") or args[3]
            buttons = [btn for row in kb.inline_keyboard for btn in row]
            
            promote_btn = next((b for b in buttons if "mgr_promote_prompt:" in b.callback_data), None)
            self.assertIsNone(promote_btn, "Promote button should NOT exist for worker")

    @patch("bot.menus.manager._ensure_manager", return_value=True)
    async def test_promote_prompt_screen_and_cancellation(self, mock_ensure):
        with patch("database.users.DB_PATH", self.users_db_path), \
             patch("database.managers.MANAGERS_DB_PATH", self.managers_db_path), \
             patch("bot.menus.manager._edit_menu_message") as mock_edit_menu:

            cb = self._create_mock_cb("mgr_promote_prompt:1001:profile")
            await manager_promote_prompt_handler(cb)

            self.assertTrue(mock_edit_menu.called)
            args, kwargs = mock_edit_menu.call_args
            reply_markup = kwargs.get("reply_markup") or args[2]
            buttons = [btn for row in reply_markup.inline_keyboard for btn in row]

            confirm_btn = next((b for b in buttons if b.callback_data == "mgr_promote_confirm:1001:profile"), None)
            cancel_btn = next((b for b in buttons if b.callback_data == "manager_intern_profile_1001"), None)

            self.assertIsNotNone(confirm_btn, "Confirm button should be present")
            self.assertIsNotNone(cancel_btn, "Cancel button should link back to manager_intern_profile_1001")

    @patch("bot.menus.manager._ensure_manager", return_value=True)
    async def test_promote_confirm_updates_user_and_refreshes_profile(self, mock_ensure):
        with patch("database.users.DB_PATH", self.users_db_path), \
             patch("database.managers.MANAGERS_DB_PATH", self.managers_db_path), \
             patch("bot.handlers.DB_PATH", self.users_db_path), \
             patch("bot.utils.get_user_avatar_input", return_value=None), \
             patch("bot.utils._send_or_edit_card_photo") as mock_refresh_card:

            cb = self._create_mock_cb("mgr_promote_confirm:1001:profile")
            await manager_promote_confirm_handler(cb)

            # Check database update
            u = await users_db.get_user_details(1001)
            self.assertEqual(u["status"], "Працівник")
            self.assertIsNotNone(u["worker_since"])

            # Check notification sent to intern
            self.assertTrue(cb.bot.send_message.called)
            send_args, send_kwargs = cb.bot.send_message.call_args
            self.assertEqual(send_args[0], 1001)
            self.assertIn("🎉 <b>Вітаємо! Ви стали Працівником Bulka!</b>", send_args[1])

            # Check profile refresh
            self.assertTrue(mock_refresh_card.called)


if __name__ == "__main__":
    unittest.main()
