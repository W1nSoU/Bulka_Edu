# -*- coding: utf-8 -*-
"""
Tests for Admin profile editing across all roles:
- Trainees / Workers (Status toggle)
- Store Managers (Status/Role toggle)
- Territorial Managers (Name, City, Direction ТЗ/ВВ)
- Observers (Name)
- Administrators (Name)
"""

import os
import tempfile
import unittest
import aiosqlite
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.types import CallbackQuery, Message, User, Chat
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey

import database.managers as managers_db
import database.users as users_db

from bot.menus.developer import (
    DeveloperStates,
    developer_toggle_user_status,
    dev_mgr_toggle_status_handler,
    dev_terr_change_name_process,
    dev_terr_process_city_set,
    dev_terr_toggle_type_handler,
    dev_obs_change_name_process,
    dev_admin_change_name_process,
)


class TestAdminEditProfiles(unittest.IsolatedAsyncioTestCase):
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
                    current_block INTEGER,
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
            await db.execute("""
                INSERT INTO users (user_id, username, full_name, role, city, shop, status)
                VALUES (1001, 'trainee_test', 'Тестовий Стажер Посади', 'Касир', 'Хмельницький', 'B-01', 'Стажер')
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
                    territorial_type TEXT DEFAULT 'ТЗ',
                    status TEXT DEFAULT 'active'
                )
            """)
            await db.execute("""
                CREATE TABLE observers (
                    uid INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    responsible_uid INTEGER,
                    status TEXT DEFAULT 'active'
                )
            """)
            # Store manager
            await db.execute("""
                INSERT INTO managers (uid, username, full_name, process, city, shops, status)
                VALUES (2001, 'mgr_test', 'Керівник Магазину Один', 'Керівник', 'Хмельницький', '["B-01"]', 'active')
            """)
            # Territorial manager
            await db.execute("""
                INSERT INTO managers (uid, username, full_name, process, city, territorial_type, status)
                VALUES (3001, 'terr_test', 'Територіал ТЗ Хмельницький', 'Територіал', 'Хмельницький', 'ТЗ', 'active')
            """)
            # Admin developer
            await db.execute("""
                INSERT INTO managers (uid, username, full_name, process, status)
                VALUES (4001, 'admin_test', 'Головний Адміністратор Системи', 'Developer', 'active')
            """)
            # Observer in managers and observers
            await db.execute("""
                INSERT INTO managers (uid, username, full_name, process, responsible_uid, status)
                VALUES (5001, 'obs_test', 'Наглядач Офіс Аудит', 'Наглядач', 4001, 'active')
            """)
            await db.execute("""
                INSERT INTO observers (uid, username, full_name, responsible_uid, status)
                VALUES (5001, 'obs_test', 'Наглядач Офіс Аудит', 4001, 'active')
            """)
            await db.commit()

        self.storage = MemoryStorage()
        self.key = StorageKey(bot_id=1, chat_id=999, user_id=999)
        self.state = FSMContext(storage=self.storage, key=self.key)

    def _create_mock_cb(self, data: str, user_id: int = 999) -> CallbackQuery:
        cb = AsyncMock(spec=CallbackQuery)
        cb.data = data
        cb.from_user = User(id=user_id, is_bot=False, first_name="Admin")
        msg = AsyncMock(spec=Message)
        msg.photo = None
        msg.answer = AsyncMock()
        msg.edit_text = AsyncMock()
        cb.message = msg
        cb.answer = AsyncMock()
        return cb

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    # --- DB Helpers Tests ---
    async def test_database_manager_process_update(self):
        with patch("database.managers.MANAGERS_DB_PATH", self.managers_db_path):
            ok = await managers_db.update_manager_process(2001, "Керівник Стажер")
            self.assertTrue(ok)
            mgr = await managers_db.get_manager_by_uid(2001)
            self.assertEqual(mgr["process"], "Керівник Стажер")

    async def test_database_territorial_city_and_type_update(self):
        with patch("database.managers.MANAGERS_DB_PATH", self.managers_db_path):
            ok_city = await managers_db.update_territorial_city(3001, "🌐 Вся мережа")
            self.assertTrue(ok_city)
            ok_type = await managers_db.update_territorial_type(3001, "ВВ")
            self.assertTrue(ok_type)

            mgr = await managers_db.get_manager_by_uid(3001)
            self.assertEqual(mgr["city"], "🌐 Вся мережа")
            self.assertEqual(mgr["territorial_type"], "ВВ")

    async def test_database_observer_name_update(self):
        with patch("database.managers.MANAGERS_DB_PATH", self.managers_db_path), \
             patch("database.managers.DB_PATH", self.users_db_path):
            ok = await managers_db.update_observer_name(5001, "Новий Наглядач ПІБ")
            self.assertTrue(ok)
            obs = await managers_db.get_observer_by_uid(5001)
            self.assertEqual(obs["full_name"], "Новий Наглядач ПІБ")

    # --- Handler Tests ---
    @patch("bot.menus.developer.DB_PATH")
    @patch("database.users.DB_PATH")
    async def test_developer_toggle_user_status(self, mock_users_db, mock_dev_db):
        mock_users_db.return_value = self.users_db_path
        mock_dev_db.return_value = self.users_db_path
        with patch("database.users.DB_PATH", self.users_db_path), \
             patch("bot.menus.developer.DB_PATH", self.users_db_path):
            cb = self._create_mock_cb("dev_change_status:1001:menu")

            # Toggle from Стажер -> Працівник
            await developer_toggle_user_status(cb, self.state)
            cb.answer.assert_any_call("✅ Статус оновлено: Працівник", show_alert=True)
            u = await users_db.get_user_details(1001)
            self.assertEqual(u["status"], "Працівник")

            # Toggle back: Працівник -> Стажер
            cb2 = self._create_mock_cb("dev_change_status:1001:menu")
            await developer_toggle_user_status(cb2, self.state)
            cb2.answer.assert_any_call("✅ Статус оновлено: Стажер", show_alert=True)
            u2 = await users_db.get_user_details(1001)
            self.assertEqual(u2["status"], "Стажер")

    @patch("bot.menus.developer._check_access", return_value=(True, True, False))
    async def test_dev_mgr_toggle_status_handler(self, mock_access):
        with patch("database.managers.MANAGERS_DB_PATH", self.managers_db_path):
            cb = self._create_mock_cb("dev_mgr_ch_status:2001")

            # Toggle Керівник -> Керівник Стажер
            await dev_mgr_toggle_status_handler(cb, self.state)
            cb.answer.assert_any_call("✅ Роль оновлено: Керівник Стажер", show_alert=True)
            mgr = await managers_db.get_manager_by_uid(2001)
            self.assertEqual(mgr["process"], "Керівник Стажер")

            # Toggle Керівник Стажер -> Керівник
            cb2 = self._create_mock_cb("dev_mgr_ch_status:2001")
            await dev_mgr_toggle_status_handler(cb2, self.state)
            cb2.answer.assert_any_call("✅ Роль оновлено: Керівник", show_alert=True)
            mgr2 = await managers_db.get_manager_by_uid(2001)
            self.assertEqual(mgr2["process"], "Керівник")

    @patch("bot.menus.developer._ensure_developer", return_value=True)
    async def test_dev_terr_change_name_process(self, mock_ensure):
        with patch("database.managers.MANAGERS_DB_PATH", self.managers_db_path), \
             patch("database.managers.DB_PATH", self.users_db_path):
            await self.state.update_data(edit_terr_uid=3001)
            await self.state.set_state(DeveloperStates.waiting_edit_territorial_name)

            msg = AsyncMock(spec=Message)
            msg.text = "Нове ПІБ Територіала"
            msg.answer = AsyncMock()

            await dev_terr_change_name_process(msg, self.state)
            mgr = await managers_db.get_manager_by_uid(3001)
            self.assertEqual(mgr["full_name"], "Нове ПІБ Територіала")
            self.assertIsNone(await self.state.get_state())

    @patch("bot.menus.developer._ensure_developer", return_value=True)
    async def test_dev_terr_change_city_and_type(self, mock_ensure):
        with patch("database.managers.MANAGERS_DB_PATH", self.managers_db_path):
            # Test city change
            cb = self._create_mock_cb("dev_terr_city_set:3001:all_network")

            await dev_terr_process_city_set(cb, self.state)
            cb.answer.assert_any_call("✅ Місто змінено на: 🌐 Вся мережа", show_alert=True)
            mgr = await managers_db.get_manager_by_uid(3001)
            self.assertEqual(mgr["city"], "🌐 Вся мережа")

            # Test direction toggle ТЗ -> ВВ
            cb_type = self._create_mock_cb("dev_terr_ch_type:3001")

            await dev_terr_toggle_type_handler(cb_type, self.state)
            cb_type.answer.assert_any_call("✅ Напрям оновлено: ВВ", show_alert=True)
            mgr2 = await managers_db.get_manager_by_uid(3001)
            self.assertEqual(mgr2["territorial_type"], "ВВ")

    @patch("bot.menus.developer._ensure_developer", return_value=True)
    async def test_dev_obs_change_name_process(self, mock_ensure):
        with patch("database.managers.MANAGERS_DB_PATH", self.managers_db_path), \
             patch("database.managers.DB_PATH", self.users_db_path):
            await self.state.update_data(edit_obs_uid=5001)
            await self.state.set_state(DeveloperStates.waiting_edit_observer_name)

            msg = AsyncMock(spec=Message)
            msg.text = "Новий Наглядач Прізвище"
            msg.answer = AsyncMock()

            await dev_obs_change_name_process(msg, self.state)
            obs = await managers_db.get_observer_by_uid(5001)
            self.assertEqual(obs["full_name"], "Новий Наглядач Прізвище")
            self.assertIsNone(await self.state.get_state())

    @patch("bot.menus.developer._ensure_developer", return_value=True)
    async def test_dev_admin_change_name_process(self, mock_ensure):
        with patch("database.managers.MANAGERS_DB_PATH", self.managers_db_path), \
             patch("database.managers.DB_PATH", self.users_db_path):
            await self.state.update_data(edit_admin_uid=4001)
            await self.state.set_state(DeveloperStates.waiting_edit_developer_name)

            msg = AsyncMock(spec=Message)
            msg.text = "Адміністратор Данііл Дусінський"
            msg.answer = AsyncMock()

            await dev_admin_change_name_process(msg, self.state)
            adm = await managers_db.get_manager_by_uid(4001)
            self.assertEqual(adm["full_name"], "Адміністратор Данііл Дусінський")
            self.assertIsNone(await self.state.get_state())


if __name__ == "__main__":
    unittest.main()
