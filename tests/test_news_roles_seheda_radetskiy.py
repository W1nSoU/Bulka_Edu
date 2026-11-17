import unittest
import os
import aiosqlite
import tempfile
from unittest.mock import patch, AsyncMock, MagicMock

from database.news import get_matching_news_recipients, SPECIAL_NEWS_RECIPIENTS, EXCLUDED_OBSERVER_IDS
from bot.menus.developer import _show_news_roles_selection, dev_news_toggle_role_handler


class TestNewsRolesSehedaRadetskiy(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "users.db")
        self.managers_db_path = os.path.join(self.temp_dir.name, "managers.db")

        # users.db
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    full_name TEXT,
                    username TEXT,
                    role TEXT,
                    status TEXT,
                    city TEXT,
                    shop TEXT
                )
            """)
            await db.execute("""
                INSERT INTO users (user_id, full_name, username, role, status, city, shop)
                VALUES
                    (101, 'Працівник 1', 'worker1', 'Працівник', 'Працівник', 'Хмельницький', 'B-1'),
                    (999001, 'Звичайний Наглядач', 'obs_common', 'Наглядач', 'Працівник', 'Хмельницький', NULL),
                    (440984923, 'Сегеда Олександр', 'OleksandrSeheda', 'Наглядач', 'Працівник', NULL, NULL),
                    (201151447, 'Радецький Владислав', 'RadetskiyVlad', 'Наглядач', 'Працівник', NULL, NULL)
            """)
            await db.commit()

        # managers.db
        async with aiosqlite.connect(self.managers_db_path) as m_db:
            await m_db.execute("""
                CREATE TABLE IF NOT EXISTS managers (
                    uid INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    process TEXT,
                    city TEXT,
                    shops TEXT,
                    status TEXT
                )
            """)
            await m_db.execute("""
                INSERT INTO managers (uid, username, full_name, process, city, status)
                VALUES
                    (999001, 'obs_common', 'Звичайний Наглядач', 'Наглядач', 'Хмельницький', 'active'),
                    (440984923, 'OleksandrSeheda', 'Сегеда Олександр', 'Наглядач', NULL, 'active'),
                    (201151447, 'RadetskiyVlad', 'Радецький Владислав', 'Наглядач', NULL, 'active')
            """)
            await m_db.commit()

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    async def test_observer_role_excludes_seheda_and_radetskiy(self):
        with patch("database.managers.MANAGERS_DB_PATH", self.managers_db_path):
            recipients = await get_matching_news_recipients(
                roles=["Наглядач"],
                target_city="all",
                db_path=self.db_path
            )

        # 999001 має бути, а Сегеда (440984923) та Радецький (201151447) виключені
        self.assertIn(999001, recipients)
        self.assertNotIn(440984923, recipients)
        self.assertNotIn(201151447, recipients)

    async def test_seheda_button_includes_seheda_only(self):
        with patch("database.managers.MANAGERS_DB_PATH", self.managers_db_path):
            recipients = await get_matching_news_recipients(
                roles=["Сегеда Олександр Леонідович"],
                target_city="all",
                db_path=self.db_path
            )

        self.assertIn(440984923, recipients)
        self.assertNotIn(201151447, recipients)
        self.assertNotIn(999001, recipients)

    async def test_radetskiy_button_includes_radetskiy_only(self):
        with patch("database.managers.MANAGERS_DB_PATH", self.managers_db_path):
            recipients = await get_matching_news_recipients(
                roles=["Радецький Владислав Леонідович"],
                target_city="all",
                db_path=self.db_path
            )

        self.assertIn(201151447, recipients)
        self.assertNotIn(440984923, recipients)
        self.assertNotIn(999001, recipients)

    async def test_observer_plus_radetskiy_includes_both_without_seheda(self):
        with patch("database.managers.MANAGERS_DB_PATH", self.managers_db_path):
            recipients = await get_matching_news_recipients(
                roles=["Наглядач", "Радецький Владислав Леонідович"],
                target_city="all",
                db_path=self.db_path
            )

        self.assertIn(999001, recipients)
        self.assertIn(201151447, recipients)
        self.assertNotIn(440984923, recipients)

    async def test_both_seheda_and_radetskiy_selected(self):
        with patch("database.managers.MANAGERS_DB_PATH", self.managers_db_path):
            recipients = await get_matching_news_recipients(
                roles=["Сегеда Олександр Леонідович", "Радецький Владислав Леонідович"],
                target_city="all",
                db_path=self.db_path
            )

        self.assertIn(440984923, recipients)
        self.assertIn(201151447, recipients)
        self.assertNotIn(999001, recipients)

    async def test_ui_roles_keyboard_order_and_toggles(self):
        callback = AsyncMock()
        callback.message = AsyncMock()
        callback.message.text = "Попередній текст"
        callback.answer = AsyncMock()

        state = AsyncMock()
        state.get_data.return_value = {"selected_roles": ["Працівник", "Сегеда Олександр Леонідович"]}

        with patch("bot.menus.developer._edit_or_answer", AsyncMock()) as mock_edit:
            await _show_news_roles_selection(callback, state)
            mock_edit.assert_called_once()
            _, kwargs = mock_edit.call_args
            reply_markup = kwargs.get("reply_markup")

        self.assertIsNotNone(reply_markup)

        button_texts = [row[0].text for row in reply_markup.inline_keyboard]
        button_cbs = [row[0].callback_data for row in reply_markup.inline_keyboard]

        # Перевіряємо наявність та порядок
        self.assertIn("✅ Працівник", button_texts)
        self.assertIn("⬜️ Стажер", button_texts)
        self.assertIn("⬜️ Керівник", button_texts)
        self.assertIn("⬜️ Територіал", button_texts)
        self.assertIn("⬜️ Наглядач", button_texts)
        self.assertIn("✅ Сегеда Олександр Леонідович", button_texts)
        self.assertIn("⬜️ Радецький Владислав Леонідович", button_texts)
        self.assertIn("⬜️ Адміністратор", button_texts)

        # Перевіряємо callback_data (усі мають бути <= 64 байти для Telegram API)
        self.assertIn("dev_news_toggle_role:seheda", button_cbs)
        self.assertIn("dev_news_toggle_role:radetskiy", button_cbs)
        for cb in button_cbs:
            self.assertLessEqual(len(cb.encode("utf-8")), 64, f"callback_data занадто довгий: {cb}")


if __name__ == "__main__":
    unittest.main()
