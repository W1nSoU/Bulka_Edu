import unittest
import os
import aiosqlite
import json
import tempfile
from unittest.mock import patch, AsyncMock

from database.managers import (
    promote_manager_trainee,
    update_manager_city,
    get_manager_by_uid
)
from bot.menus.developer import _build_manager_card


class TestManagerCityAndPromotion(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.users_db = os.path.join(self.temp_dir.name, "users.db")
        self.managers_db = os.path.join(self.temp_dir.name, "managers.db")

        # Mock database paths
        self.p_m = patch("database.managers.MANAGERS_DB_PATH", self.managers_db)
        self.p_u = patch("database.managers.DB_PATH", self.users_db)
        self.p_u2 = patch("bot.menus.developer.DB_PATH", self.users_db)

        self.p_m.start()
        self.p_u.start()
        self.p_u2.start()

        # Initialize tables
        async with aiosqlite.connect(self.managers_db) as db:
            await db.execute("""
                CREATE TABLE managers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uid INTEGER UNIQUE,
                    process TEXT,
                    full_name TEXT,
                    username TEXT,
                    shops TEXT,
                    city TEXT,
                    responsible_uid INTEGER,
                    territorial_type TEXT,
                    status TEXT DEFAULT 'active'
                )
            """)
            await db.commit()

        async with aiosqlite.connect(self.users_db) as db:
            await db.execute("""
                CREATE TABLE users (
                    user_id INTEGER PRIMARY KEY,
                    full_name TEXT,
                    username TEXT,
                    role TEXT,
                    status TEXT,
                    city TEXT,
                    shop TEXT,
                    manager_id INTEGER,
                    current_block INTEGER DEFAULT 1
                )
            """)
            await db.execute("""
                CREATE TABLE conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    manager_id INTEGER,
                    user_id INTEGER,
                    status TEXT DEFAULT 'open'
                )
            """)
            await db.commit()

    async def asyncTearDown(self):
        self.p_m.stop()
        self.p_u.stop()
        self.p_u2.stop()
        self.temp_dir.cleanup()

    async def test_update_manager_city_resets_shops_and_reassigns_users(self):
        # 1. Створюємо Територіала для Хмельницького
        async with aiosqlite.connect(self.managers_db) as db:
            await db.execute("""
                INSERT INTO managers (uid, process, full_name, city, territorial_type, status)
                VALUES (999, 'Територіал', 'Територіал Хмельницький', 'Хмельницький', 'ТЗ', 'active')
            """)
            # Створюємо керівника в Хмельницькому з магазином "Булочна 1"
            await db.execute("""
                INSERT INTO managers (uid, process, full_name, city, shops, status)
                VALUES (101, 'Керівник', 'Іван Менеджер', 'Хмельницький', ?, 'active')
            """, (json.dumps(["Булочна 1"]),))
            await db.commit()

        # Створюємо працівника під цим менеджером
        async with aiosqlite.connect(self.users_db) as db:
            await db.execute("""
                INSERT INTO users (user_id, full_name, role, status, city, shop, manager_id)
                VALUES (201, 'Петро Працівник', 'Продавець', 'Працівник', 'Хмельницький', 'Булочна 1', 101)
            """)
            # Також створимо запис самого менеджера в users
            await db.execute("""
                INSERT INTO users (user_id, full_name, role, status, city, shop, manager_id)
                VALUES (101, 'Іван Менеджер', 'Керівник', 'Працівник', 'Хмельницький', NULL, 999)
            """)
            await db.commit()

        # 2. Змінюємо місто керівника на "Кам'янець-Подільський"
        res = await update_manager_city(101, "Кам'янець-Подільський")
        self.assertTrue(res)

        # 3. Перевіряємо managers.db
        mgr = await get_manager_by_uid(101)
        self.assertEqual(mgr["city"], "Кам'янець-Подільський")
        self.assertEqual(mgr["shops"], [])

        # 4. Перевіряємо users.db для керівника
        async with aiosqlite.connect(self.users_db) as db:
            cur = await db.execute("SELECT city FROM users WHERE user_id = 101")
            row = await cur.fetchone()
            self.assertEqual(row[0], "Кам'янець-Подільський")

            # 5. Перевіряємо, що працівник відкріпленого магазину переведений до Територіала (uid 999)
            cur = await db.execute("SELECT manager_id FROM users WHERE user_id = 201")
            row = await cur.fetchone()
            self.assertEqual(row[0], 999)

    async def test_promote_manager_trainee_updates_both_dbs(self):
        # 1. Створюємо керівника-стажера в managers та users
        async with aiosqlite.connect(self.managers_db) as db:
            await db.execute("""
                INSERT INTO managers (uid, process, full_name, city, shops, status)
                VALUES (301, 'Керівник Стажер', 'Мирослав Стажер', 'Хмельницький', '[]', 'active')
            """)
            await db.commit()

        async with aiosqlite.connect(self.users_db) as db:
            await db.execute("""
                INSERT INTO users (user_id, full_name, role, status, city, shop, manager_id)
                VALUES (301, 'Мирослав Стажер', 'Керівник', 'Стажер', 'Хмельницький', NULL, 999)
            """)
            await db.commit()

        # 2. Перший виклик - успішне підвищення
        first_call = await promote_manager_trainee(301)
        self.assertTrue(first_call)

        # Перевірка managers.db
        mgr = await get_manager_by_uid(301)
        self.assertEqual(mgr["process"], "Керівник")

        # Перевірка users.db
        async with aiosqlite.connect(self.users_db) as db:
            cur = await db.execute("SELECT status FROM users WHERE user_id = 301")
            row = await cur.fetchone()
            self.assertEqual(row[0], "Працівник")

        # 3. Другий виклик (повторне натискання) повертає False (захист)
        second_call = await promote_manager_trainee(301)
        self.assertFalse(second_call)

    async def test_build_manager_card_shows_promote_button_only_for_trainee(self):
        # Додаємо стажера та звичайного керівника
        async with aiosqlite.connect(self.managers_db) as db:
            await db.execute("""
                INSERT INTO managers (uid, process, full_name, city, shops, status)
                VALUES (401, 'Керівник Стажер', 'Стажер Василь', 'Хмельницький', '[]', 'active'),
                       (402, 'Керівник', 'Керівник Петро', 'Хмельницький', '[]', 'active')
            """)
            await db.commit()

        # 1. Для стажера (401) кнопка переведення повинна бути присутня
        with patch("bot.menus.developer.get_user_details", new=AsyncMock(return_value={"current_block": 2})), \
             patch("database.positions.get_days_count_for_role", new=AsyncMock(return_value=5)):
            text_trainee, kb_trainee = await _build_manager_card(401, is_admin=True, is_territorial=False)
            trainee_callbacks = [btn.callback_data for row in kb_trainee.inline_keyboard for btn in row]
            self.assertIn("dev_mgr_promote_ask:401", trainee_callbacks)
            self.assertIn("dev_days_manage:401:mgr_team", trainee_callbacks)
            self.assertIn("dev_mgr_edit_menu:401", trainee_callbacks)

        # 2. Для повноцінного керівника (402) кнопки переведення НЕ повинно бути
        text_mgr, kb_mgr = await _build_manager_card(402, is_admin=True, is_territorial=False)
        mgr_callbacks = [btn.callback_data for row in kb_mgr.inline_keyboard for btn in row]
        self.assertNotIn("dev_mgr_promote_ask:402", mgr_callbacks)
        self.assertNotIn("dev_days_manage:402:mgr_team", mgr_callbacks)
        self.assertIn("dev_mgr_edit_menu:402", mgr_callbacks)


if __name__ == "__main__":
    unittest.main()
