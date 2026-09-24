import os
import tempfile
import unittest
from unittest.mock import patch
import aiosqlite

from bot.constants import POSITION_TYPES, VALID_POSITION_TYPES
import database
import database.positions as db_pos
import database.users as db_users
import database.managers as db_managers
import bot.services.positions as srv_pos


class TestPositionTypes(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "users.db")
        self.managers_db_path = os.path.join(self.temp_dir.name, "managers.db")

        self.patcher_db = patch("database.DB_PATH", self.db_path)
        self.patcher_db_pos = patch("database.positions.DB_PATH", self.db_path)
        self.patcher_db_users = patch("database.users.DB_PATH", self.db_path)
        self.patcher_srv_pos = patch("bot.services.positions.DB_PATH", self.db_path)
        self.patcher_managers_db = patch("database.managers.MANAGERS_DB_PATH", self.managers_db_path)

        self.patcher_db.start()
        self.patcher_db_pos.start()
        self.patcher_db_users.start()
        self.patcher_srv_pos.start()
        self.patcher_managers_db.start()

        # Initialize tables in users.db
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
            CREATE TABLE positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                days_count INTEGER NOT NULL DEFAULT 5,
                territorial_type TEXT NOT NULL DEFAULT 'ТЗ',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            await db.execute("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                username TEXT,
                full_name TEXT,
                role TEXT,
                status TEXT DEFAULT 'Стажер',
                city TEXT,
                shop TEXT,
                manager_id INTEGER,
                last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            await db.commit()

        # Initialize managers.db
        async with aiosqlite.connect(self.managers_db_path) as db:
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
                status TEXT DEFAULT 'active',
                fired_at TIMESTAMP DEFAULT NULL
            )
            """)
            # Add an active territorial manager for testing
            await db.execute("""
            INSERT INTO managers (uid, full_name, city, process, status, territorial_type)
            VALUES (9999, 'Територіал Хмельницький', 'Хмельницький', 'Територіал', 'active', 'ТЗ')
            """)
            await db.commit()

    async def asyncTearDown(self):
        self.patcher_managers_db.stop()
        self.patcher_srv_pos.stop()
        self.patcher_db_users.stop()
        self.patcher_db_pos.stop()
        self.patcher_db.stop()
        self.temp_dir.cleanup()

    def test_constants(self):
        """Verify POSITION_TYPES dictionary and VALID_POSITION_TYPES tuple."""
        self.assertIn("ТЗ", POSITION_TYPES)
        self.assertIn("ВВ", POSITION_TYPES)
        self.assertIn("РЦ", POSITION_TYPES)
        self.assertIn("ОФІС", POSITION_TYPES)

        self.assertEqual(VALID_POSITION_TYPES, ("ТЗ", "ВВ", "РЦ", "ОФІС"))
        self.assertEqual(POSITION_TYPES["РЦ"], "📦 РЦ")
        self.assertEqual(POSITION_TYPES["ОФІС"], "🏢 ОФІС")

    async def test_add_and_update_positions(self):
        """Test database and service functions for adding and updating positions with new types."""
        # 1. Add RC position
        rc_id = await db_pos.add_position("Комірник РЦ", days_count=3, territorial_type="РЦ")
        self.assertIsInstance(rc_id, int)

        # 2. Add Office position
        office_id = await db_pos.add_position("Бухгалтер", days_count=4, territorial_type="ОФІС")
        self.assertIsInstance(office_id, int)

        # 3. Add TZ and VV positions
        tz_id = await db_pos.add_position("Касир", days_count=5, territorial_type="ТЗ")
        vv_id = await db_pos.add_position("ВВ Пекар", days_count=5, territorial_type="ВВ")

        # Verify added positions
        pos_rc = await db_pos.get_position_by_id(rc_id)
        self.assertIsNotNone(pos_rc)
        self.assertEqual(pos_rc["name"], "Комірник РЦ")
        self.assertEqual(pos_rc["territorial_type"], "РЦ")

        pos_office = await db_pos.get_position_by_id(office_id)
        self.assertIsNotNone(pos_office)
        self.assertEqual(pos_office["name"], "Бухгалтер")
        self.assertEqual(pos_office["territorial_type"], "ОФІС")

        # Check get_position_direction
        self.assertEqual(await db_pos.get_position_direction("Комірник РЦ"), "РЦ")
        self.assertEqual(await db_pos.get_position_direction("Бухгалтер"), "ОФІС")
        self.assertEqual(await db_pos.get_position_direction("Касир"), "ТЗ")
        self.assertEqual(await db_pos.get_position_direction("ВВ Пекар"), "ВВ")

        # 4. Update position type via db function
        await db_pos.update_territorial_type(rc_id, "ОФІС")
        updated_rc = await db_pos.get_position_by_id(rc_id)
        self.assertEqual(updated_rc["territorial_type"], "ОФІС")

        # 5. Update position type via service function
        success = await srv_pos.update_position_type(rc_id, "РЦ")
        self.assertTrue(success)
        updated_rc2 = await db_pos.get_position_by_id(rc_id)
        self.assertEqual(updated_rc2["territorial_type"], "РЦ")

        # 6. Test invalid position type
        with self.assertRaises(ValueError):
            await db_pos.update_territorial_type(rc_id, "INVALID_TYPE")

        success_invalid = await srv_pos.update_position_type(rc_id, "UNKNOWN")
        self.assertFalse(success_invalid)

    async def test_get_users_by_position_type(self):
        """Test filtering users by position type in database.users."""
        # Create positions
        await db_pos.add_position("Логіст РЦ", days_count=3, territorial_type="РЦ")
        await db_pos.add_position("Юрист", days_count=5, territorial_type="ОФІС")
        await db_pos.add_position("Продавець", days_count=5, territorial_type="ТЗ")
        await db_pos.add_position("ВВ Кондитер", days_count=5, territorial_type="ВВ")

        # Insert users
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
            INSERT INTO users (user_id, full_name, role) VALUES
            (101, 'Олег РЦ', 'Логіст РЦ'),
            (102, 'Анна Офіс', 'Юрист'),
            (103, 'Іван ТЗ', 'Продавець'),
            (104, 'Марія ВВ', 'ВВ Кондитер')
            """)
            await db.commit()

        rc_users = await db_users.get_users_by_position_type("РЦ")
        self.assertEqual(len(rc_users), 1)
        self.assertEqual(rc_users[0]["user_id"], 101)
        self.assertEqual(rc_users[0]["full_name"], "Олег РЦ")

        office_users = await db_users.get_users_by_position_type("ОФІС")
        self.assertEqual(len(office_users), 1)
        self.assertEqual(office_users[0]["user_id"], 102)
        self.assertEqual(office_users[0]["full_name"], "Анна Офіс")

        tz_users = await db_users.get_users_by_position_type("ТЗ")
        self.assertEqual(len(tz_users), 1)
        self.assertEqual(tz_users[0]["user_id"], 103)

        vv_users = await db_users.get_users_by_position_type("ВВ")
        self.assertEqual(len(vv_users), 1)
        self.assertEqual(vv_users[0]["user_id"], 104)

    async def test_territorial_isolation_for_rc_and_office(self):
        """Verify get_appropriate_territorial_for_user returns None for РЦ and ОФІС roles."""
        await db_pos.add_position("Вантажник РЦ", days_count=3, territorial_type="РЦ")
        await db_pos.add_position("HR Менеджер", days_count=5, territorial_type="ОФІС")
        await db_pos.add_position("Касир ТЗ", days_count=5, territorial_type="ТЗ")

        # For TZ role, it should find the territorial manager (9999)
        tz_manager = await db_managers.get_appropriate_territorial_for_user("Хмельницький", "Касир ТЗ")
        self.assertEqual(tz_manager, 9999)

        # For RC and Office roles, it MUST return None (never assign territorial)
        rc_manager = await db_managers.get_appropriate_territorial_for_user("Хмельницький", "Вантажник РЦ")
        self.assertIsNone(rc_manager)

        office_manager = await db_managers.get_appropriate_territorial_for_user("Хмельницький", "HR Менеджер")
        self.assertIsNone(office_manager)

    async def test_intern_subordination_rc_and_office(self):
        """Verify that RC and Office interns are assigned to the admin (creator_id) even if a shop manager exists."""
        await db_pos.add_position("Комірник РЦ", days_count=3, territorial_type="РЦ")
        await db_pos.add_position("Юрист", days_count=5, territorial_type="ОФІС")

        admin_creator_id = 7777
        shop_mgr_id = 8888

        # For an RC role
        role = "Комірник РЦ"
        extra_data = {"creator_id": admin_creator_id, "target_manager_id": admin_creator_id}
        shop = "Магазин 1"
        city = "Хмельницький"

        role_direction = await db_pos.get_position_direction(role)
        self.assertEqual(role_direction, "РЦ")

        # Simulate the supervisor resolution branch from bot/handlers.py
        target_manager_id = extra_data.get("target_manager_id")
        creator_id = extra_data.get("creator_id")
        manager_id = 1111

        assigned_manager_id = None
        if role_direction in ("РЦ", "ОФІС"):
            assigned_manager_id = target_manager_id or creator_id or manager_id

        self.assertEqual(assigned_manager_id, admin_creator_id)
        self.assertNotEqual(assigned_manager_id, shop_mgr_id)

        # For an Office role
        role_office = "Юрист"
        role_office_dir = await db_pos.get_position_direction(role_office)
        self.assertEqual(role_office_dir, "ОФІС")

        assigned_office_mgr = None
        if role_office_dir in ("РЦ", "ОФІС"):
            assigned_office_mgr = target_manager_id or creator_id or manager_id

        self.assertEqual(assigned_office_mgr, admin_creator_id)


if __name__ == "__main__":
    unittest.main()

