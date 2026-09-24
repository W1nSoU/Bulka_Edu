import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import aiosqlite

from database.users import (
    get_interns_in_progress_for_manager,
    get_inactive_interns_for_manager
)


class TestManagerInterns(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "users.db")
        self.patcher_db = patch("database.users.DB_PATH", self.db_path)
        self.patcher_db.start()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
            CREATE TABLE users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                role TEXT,
                status TEXT,
                city TEXT,
                shop TEXT,
                manager_id INTEGER,
                last_activity TIMESTAMP,
                current_block INTEGER DEFAULT 1
            )
            """)
            await db.execute("""
            CREATE TABLE progress (
                user_id INTEGER,
                day INTEGER,
                completed BOOLEAN,
                completed_at TIMESTAMP,
                PRIMARY KEY (user_id, day)
            )
            """)
            await db.execute("""
            CREATE TABLE positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                days_total INTEGER DEFAULT 5,
                position_type TEXT DEFAULT 'intern'
            )
            """)
            # Insert positions
            await db.execute("INSERT INTO positions (name, days_total) VALUES ('Пекар', 5)")
            await db.commit()

    async def asyncTearDown(self):
        self.patcher_db.stop()
        self.temp_dir.cleanup()

    async def test_get_interns_in_progress_returns_dicts_without_row_error(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO users (user_id, username, full_name, role, status, manager_id, last_activity, current_block)
                VALUES (101, 'intern1', 'Іван Стажер', 'Пекар', 'Стажер', 999, datetime('now'), 1)
                """
            )
            await db.commit()

        # Should execute without: AttributeError: 'sqlite3.Row' object has no attribute 'get'
        interns = await get_interns_in_progress_for_manager(999, active_only=True)
        self.assertEqual(len(interns), 1)
        self.assertIsInstance(interns[0], dict)
        self.assertEqual(interns[0]["user_id"], 101)
        self.assertEqual(interns[0].get("role"), "Пекар")

    async def test_get_inactive_interns_returns_dicts_without_row_error(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO users (user_id, username, full_name, role, status, manager_id, last_activity, current_block)
                VALUES (102, 'intern2', 'Петро Стажер', 'Пекар', 'Стажер', 999, datetime('now', '-5 days'), 1)
                """
            )
            await db.commit()

        inactive = await get_inactive_interns_for_manager(999, days=3)
        self.assertEqual(len(inactive), 1)
        self.assertIsInstance(inactive[0], dict)
        self.assertEqual(inactive[0]["user_id"], 102)
        self.assertEqual(inactive[0].get("role"), "Пекар")


if __name__ == "__main__":
    unittest.main()
