# -*- coding: utf-8 -*-
"""
Tests for Admin/Developer changing user's full_name with 3-word validation.
"""

import os
import unittest
import tempfile
import aiosqlite
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.types import CallbackQuery, Message, User, Chat, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey

from bot.menus.developer import (
    DeveloperStates,
    developer_user_modify_menu,
    developer_change_fullname_start,
    developer_process_change_fullname
)

class TestChangeUserFullname(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_users.db")

        # Initialize schema
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    first_seen TIMESTAMP,
                    current_block INTEGER,
                    manager_name TEXT,
                    last_activity TIMESTAMP,
                    role TEXT,
                    city TEXT,
                    shop TEXT,
                    manager_id INTEGER,
                    status TEXT
                )
            """)
            await db.execute("""
                INSERT INTO users (user_id, username, full_name, role, city, shop, status)
                VALUES (12345, 'testuser', 'Старе Імʼя', 'Продавець', 'Хмельницький', 'B-01', 'Стажер')
            """)
            await db.commit()

        self.storage = MemoryStorage()
        self.key = StorageKey(bot_id=1, chat_id=100, user_id=100)
        self.state = FSMContext(storage=self.storage, key=self.key)

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    @patch("bot.menus.developer.DB_PATH")
    async def test_modify_menu_has_change_fullname_button(self, mock_db_path):
        mock_db_path.__str__.return_value = self.db_path
        
        callback = MagicMock(spec=CallbackQuery)
        callback.data = "dev_user_modify:12345:menu"
        callback.message = MagicMock(spec=Message)
        callback.message.edit_text = AsyncMock()
        callback.answer = AsyncMock()

        with patch("bot.menus.developer._send_text_screen", new_callable=AsyncMock) as mock_send:
            await developer_user_modify_menu(callback, self.state)
            mock_send.assert_called_once()
            _, kwargs = mock_send.call_args
            kb: InlineKeyboardMarkup = kwargs.get("reply_markup")
            all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
            all_callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
            
            self.assertIn("👤 Змінити ПІБ", all_texts)
            self.assertIn("dev_change_fullname:12345", all_callbacks)

    async def test_change_fullname_start_sets_state(self):
        callback = MagicMock(spec=CallbackQuery)
        callback.data = "dev_change_fullname:12345"
        callback.message = MagicMock(spec=Message)
        callback.message.edit_text = AsyncMock()
        callback.answer = AsyncMock()

        with patch("bot.menus.developer._edit_or_answer", new_callable=AsyncMock) as mock_edit:
            await developer_change_fullname_start(callback, self.state)
            current_state = await self.state.get_state()
            data = await self.state.get_data()
            
            self.assertEqual(current_state, DeveloperStates.waiting_change_fullname.state)
            self.assertEqual(data.get("user_id_to_modify"), 12345)
            mock_edit.assert_called_once()

    async def test_validation_fails_for_less_than_3_words(self):
        await self.state.set_state(DeveloperStates.waiting_change_fullname)
        await self.state.update_data(user_id_to_modify=12345)

        # 1 word
        msg1 = MagicMock(spec=Message)
        msg1.text = "Шевченко"
        msg1.answer = AsyncMock()

        await developer_process_change_fullname(msg1, self.state)
        msg1.answer.assert_called_once()
        self.assertIn("щонайменше 3 слова", msg1.answer.call_args[0][0])
        # State should still be active
        self.assertEqual(await self.state.get_state(), DeveloperStates.waiting_change_fullname.state)

        # 2 words
        msg2 = MagicMock(spec=Message)
        msg2.text = "Шевченко Тарас"
        msg2.answer = AsyncMock()

        await developer_process_change_fullname(msg2, self.state)
        msg2.answer.assert_called_once()
        self.assertIn("щонайменше 3 слова", msg2.answer.call_args[0][0])

    @patch("bot.menus.developer.DB_PATH")
    @patch("bot.menus.developer.get_user_details")
    @patch("bot.menus.developer.get_user_days_report")
    async def test_validation_succeeds_and_updates_db(self, mock_report, mock_details, mock_db_path):
        # Override DB_PATH in developer module
        import bot.menus.developer as dev_mod
        orig_db = dev_mod.DB_PATH
        dev_mod.DB_PATH = self.db_path

        try:
            await self.state.set_state(DeveloperStates.waiting_change_fullname)
            await self.state.update_data(user_id_to_modify=12345)

            mock_details.return_value = {"user_id": 12345, "full_name": "Старе Імʼя"}
            mock_report.return_value = "Звіт по днях для Шевченко Тарас Григорович"

            msg = MagicMock(spec=Message)
            msg.text = "  Шевченко   Тарас   Григорович  "
            msg.answer = AsyncMock()

            await developer_process_change_fullname(msg, self.state)

            # State cleared
            self.assertIsNone(await self.state.get_state())

            # DB updated
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT full_name FROM users WHERE user_id = 12345") as cur:
                    row = await cur.fetchone()
                    self.assertEqual(row["full_name"], "Шевченко Тарас Григорович")

            # Check messages sent
            self.assertTrue(msg.answer.called)
            first_reply = msg.answer.call_args_list[0][0][0]
            self.assertIn("успішно змінено", first_reply)
            self.assertIn("Шевченко Тарас Григорович", first_reply)
        finally:
            dev_mod.DB_PATH = orig_db

if __name__ == "__main__":
    unittest.main()
