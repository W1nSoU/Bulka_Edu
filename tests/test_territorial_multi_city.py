import unittest
import os
import aiosqlite
import tempfile
from unittest.mock import patch

from database.managers import (
    get_territorials_by_city,
    get_potential_managers_to_reassign,
    reassign_direction_managers_to_territorial
)
from database.users import get_users_by_city
from database.surveys import get_matching_survey_recipients


class TestTerritorialMultiCity(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.users_db = os.path.join(self.temp_dir.name, "users.db")
        self.managers_db = os.path.join(self.temp_dir.name, "managers.db")

        # Mock database paths
        self.p_m = patch("database.managers.MANAGERS_DB_PATH", self.managers_db)
        self.p_u = patch("database.managers.DB_PATH", self.users_db)
        self.p_u2 = patch("database.users.DB_PATH", self.users_db)
        self.p_s = patch("database.surveys.DB_PATH", self.users_db)

        self.p_m.start()
        self.p_u.start()
        self.p_u2.start()
        self.p_s.start()

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
                    last_activity TIMESTAMP
                )
            """)
            await db.commit()

    async def asyncTearDown(self):
        self.p_m.stop()
        self.p_u.stop()
        self.p_u2.stop()
        self.p_s.stop()
        self.temp_dir.cleanup()

    async def test_territorial_network_lookup(self):
        """Перевіряє, що мережевий територіал (Всі міста) повертається для будь-якого міста."""
        async with aiosqlite.connect(self.managers_db) as db:
            await db.execute("""
                INSERT INTO managers (uid, full_name, process, city, territorial_type, status)
                VALUES (777, 'Топ Керівник ВВ', 'Територіал', 'Всі міста', 'ВВ', 'active')
            """)
            await db.commit()

        khm = await get_territorials_by_city("Хмельницький")
        kam = await get_territorials_by_city("Камʼянець-Подільський")
        all_c = await get_territorials_by_city("Всі міста")

        self.assertTrue(any(t["uid"] == 777 for t in khm))
        self.assertTrue(any(t["uid"] == 777 for t in kam))
        self.assertTrue(any(t["uid"] == 777 for t in all_c))

    async def test_reassign_vv_managers(self):
        """Перевіряє перенесення керівників цехів ВВ під Територіала ВВ."""
        async with aiosqlite.connect(self.managers_db) as db:
            # Створюємо територіала ВВ
            await db.execute("""
                INSERT INTO managers (uid, full_name, process, city, territorial_type, status)
                VALUES (1000, 'Головний ВВ', 'Територіал', 'Всі міста', 'ВВ', 'active')
            """)
            # Створюємо керівників: 2 цехових ВВ і 1 звичайний ТЗ маркет
            await db.execute("""
                INSERT INTO managers (uid, full_name, process, city, shops, status)
                VALUES 
                    (1001, 'Керівник ВЦ Хмельницький', 'Керівник', 'ВЦ Хмельницький', '[]', 'active'),
                    (1002, 'Керівник Кондитерка', 'Керівник', 'Кондитерський цех', '[]', 'active'),
                    (1003, 'Керівник ТЗ B-04', 'Керівник', 'Хмельницький', '["B-04"]', 'active')
            """)
            await db.commit()

        potential = await get_potential_managers_to_reassign(1000)
        uids = [m["uid"] for m in potential]

        self.assertIn(1001, uids)
        self.assertIn(1002, uids)
        self.assertNotIn(1003, uids)  # Звичайний магазин не повинен потрапляти у ВВ

        count, names = await reassign_direction_managers_to_territorial(1000)
        self.assertEqual(count, 2)

        # Перевіряємо оновлення в базі
        async with aiosqlite.connect(self.managers_db) as db:
            db.row_factory = aiosqlite.Row
            rows = await (await db.execute("SELECT uid, responsible_uid FROM managers WHERE uid IN (1001, 1002, 1003)")).fetchall()
            status_map = {r["uid"]: r["responsible_uid"] for r in rows}

        self.assertEqual(status_map[1001], 1000)
        self.assertEqual(status_map[1002], 1000)
        self.assertIsNone(status_map[1003])

    async def test_news_broadcast_includes_network_territorial(self):
        """Перевіряє, що розсилка на конкретне місто доходить до мережевого Територіала."""
        async with aiosqlite.connect(self.managers_db) as db:
            await db.execute("""
                INSERT INTO managers (uid, full_name, process, city, territorial_type, status)
                VALUES (999, 'Мережевий Територіал', 'Територіал', 'Всі міста', 'ВВ', 'active')
            """)
            await db.commit()

        recipients_khm = await get_matching_survey_recipients(
            target_roles=["Територіал"],
            target_city="Хмельницький",
            db_path=self.users_db
        )
        self.assertIn(999, recipients_khm)


if __name__ == "__main__":
    unittest.main()
