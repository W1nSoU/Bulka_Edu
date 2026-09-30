import unittest
import os
import aiosqlite
import tempfile
from unittest.mock import patch

from database.news import get_matching_news_recipients
from database.surveys import get_matching_survey_recipients


class TestNewsTerritorialRecipients(unittest.IsolatedAsyncioTestCase):
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
            # Додаємо тестових користувачів
            await db.execute("""
                INSERT INTO users (user_id, full_name, username, role, status, city, shop)
                VALUES
                    (101, 'Працівник Львів', 'worker_lviv', 'Працівник', 'Працівник', 'Львів', 'Пекарня 1'),
                    (102, 'Стажер Львів', 'intern_lviv', NULL, NULL, 'Львів', 'Пекарня 1'),
                    (103, 'Керівник Львів', 'manager_lviv', 'Керівник', NULL, 'Львів', 'Пекарня 1'),
                    (201, 'Територіал з Users', 'terr_user', 'Територіал', NULL, 'Львів', NULL)
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
            # Додаємо тестових менеджерів
            await m_db.execute("""
                INSERT INTO managers (uid, username, full_name, process, city, status)
                VALUES
                    (301, 'terr_lviv_active', 'Територіал Львів Активний', 'Територіал', 'Львів', 'active'),
                    (302, 'terr_tern_active', 'Територіал Тернопіль', 'Територіал', 'Тернопіль', 'active'),
                    (303, 'terr_lviv_fired', 'Територіал Львів Звільнений', 'Територіал', 'Львів', 'fired'),
                    (304, 'manager_active', 'Керівник Львів', 'Керівник', 'Львів', 'active')
            """)
            await m_db.commit()

        self.patch_mgr = patch("database.managers.MANAGERS_DB_PATH", self.managers_db_path)
        self.patch_mgr.start()

    async def asyncTearDown(self):
        self.patch_mgr.stop()
        self.temp_dir.cleanup()

    async def test_territorial_all_cities(self):
        """Перевіряє вибірку всіх активних територіалів для всіх міст."""
        recipients = await get_matching_news_recipients(["Територіал"], target_city="all", db_path=self.db_path)
        # Очікуємо: 201 (з users), 301 (активний Львів), 302 (активний Тернопіль).
        # Звільнений 303 НЕ має увійти.
        self.assertIn(201, recipients)
        self.assertIn(301, recipients)
        self.assertIn(302, recipients)
        self.assertNotIn(303, recipients)
        self.assertNotIn(101, recipients)
        self.assertNotIn(102, recipients)
        self.assertNotIn(103, recipients)
        self.assertNotIn(304, recipients)

    async def test_territorial_specific_city(self):
        """Перевіряє фільтрацію територіалів за конкретним містом."""
        recipients_lviv = await get_matching_news_recipients(["Територіал"], target_city="Львів", db_path=self.db_path)
        self.assertIn(201, recipients_lviv)
        self.assertIn(301, recipients_lviv)
        self.assertNotIn(302, recipients_lviv)  # Тернопіль не має потрапити
        self.assertNotIn(303, recipients_lviv)  # Звільнений не має потрапити

        recipients_ternopil = await get_matching_news_recipients(["Територіал"], target_city="Тернопіль", db_path=self.db_path)
        self.assertIn(302, recipients_ternopil)
        self.assertNotIn(301, recipients_ternopil)

    async def test_territorial_and_manager_combined(self):
        """Перевіряє комбіновану вибірку Керівник + Територіал."""
        recipients = await get_matching_news_recipients(["Керівник", "Територіал"], target_city="Львів", db_path=self.db_path)
        # Має містити керівників Львова (103, 304) та територіалів Львова (201, 301)
        self.assertIn(103, recipients)
        self.assertIn(304, recipients)
        self.assertIn(201, recipients)
        self.assertIn(301, recipients)
        self.assertNotIn(302, recipients)  # Тернопіль
        self.assertNotIn(303, recipients)  # Звільнений
        self.assertNotIn(101, recipients)  # Працівник
        self.assertNotIn(102, recipients)  # Стажер


if __name__ == "__main__":
    unittest.main()
