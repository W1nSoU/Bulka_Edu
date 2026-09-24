import unittest
from datetime import datetime, timedelta
import pytz
from bot.config import TIMEZONE
from database.users import get_business_days_cutoff


class TestBusinessDaysCutoff(unittest.TestCase):
    def setUp(self):
        self.tz = pytz.timezone(TIMEZONE)

    def test_friday_to_next_week(self):
        # Приклад 1 з вимог:
        # Стажер активний у п'ятницю о 15:00
        friday_15 = self.tz.localize(datetime(2026, 9, 18, 15, 0, 0)) # 2026-09-18 is Friday

        # 1. Понеділок 15:00 (2026-09-21) -> минув 1 робочий день
        monday_15 = self.tz.localize(datetime(2026, 9, 21, 15, 0, 0))
        cutoff_3d = get_business_days_cutoff(monday_15, business_days=3)
        # 3 робочі дні назад від понеділка 15:00 -> середа 15:00 попереднього тижня (2026-09-16)
        self.assertEqual(cutoff_3d, self.tz.localize(datetime(2026, 9, 16, 15, 0, 0)))
        # friday_15 < cutoff_3d -> FALSE (ще не неактивний)
        self.assertFalse(friday_15 < cutoff_3d)

        # 2. Вівторок 15:00 (2026-09-22) -> минуло 2 робочих дні
        tuesday_15 = self.tz.localize(datetime(2026, 9, 22, 15, 0, 0))
        cutoff_3d = get_business_days_cutoff(tuesday_15, business_days=3)
        # 3 робочі дні назад від вівторка 15:00 -> четвер 15:00 попереднього тижня (2026-09-17)
        self.assertEqual(cutoff_3d, self.tz.localize(datetime(2026, 9, 17, 15, 0, 0)))
        self.assertFalse(friday_15 < cutoff_3d)

        # 3. Середа 14:59 (2026-09-23) -> ще не виповнилося 3 робочих дні
        wednesday_1459 = self.tz.localize(datetime(2026, 9, 23, 14, 59, 0))
        cutoff_3d = get_business_days_cutoff(wednesday_1459, business_days=3)
        self.assertEqual(cutoff_3d, self.tz.localize(datetime(2026, 9, 18, 14, 59, 0)))
        self.assertFalse(friday_15 < cutoff_3d)

        # 4. Середа 15:01 (2026-09-23) -> минуло 3 робочих дні!
        wednesday_1501 = self.tz.localize(datetime(2026, 9, 23, 15, 1, 0))
        cutoff_3d = get_business_days_cutoff(wednesday_1501, business_days=3)
        self.assertEqual(cutoff_3d, self.tz.localize(datetime(2026, 9, 18, 15, 1, 0)))
        # friday_15 < cutoff_3d -> TRUE! Стажер стає неактивним саме в середу о 15:00
        self.assertTrue(friday_15 < cutoff_3d)

    def test_wednesday_to_monday_over_weekend(self):
        # Приклад 2 з вимог:
        # Стажер активний у середу о 15:00 (2026-09-16)
        wednesday_15 = self.tz.localize(datetime(2026, 9, 16, 15, 0, 0))

        # Четвер 15:00 -> 1 робочий день
        # П'ятниця 15:00 -> 2 робочих дні
        # Субота 12:00 (2026-09-19) -> заморожено на п'ятницю 12:00 (ще тільки 2 робочих дні)
        saturday_12 = self.tz.localize(datetime(2026, 9, 19, 12, 0, 0))
        cutoff_sat = get_business_days_cutoff(saturday_12, business_days=3)
        self.assertEqual(cutoff_sat, self.tz.localize(datetime(2026, 9, 15, 12, 0, 0))) # Вівторок 12:00
        self.assertFalse(wednesday_15 < cutoff_sat)

        # Неділя 20:00 (2026-09-20) -> заморожено на п'ятницю 20:00 (все ще 2 робочих дні)
        sunday_20 = self.tz.localize(datetime(2026, 9, 20, 20, 0, 0))
        cutoff_sun = get_business_days_cutoff(sunday_20, business_days=3)
        self.assertEqual(cutoff_sun, self.tz.localize(datetime(2026, 9, 15, 20, 0, 0))) # Вівторок 20:00
        self.assertFalse(wednesday_15 < cutoff_sun)

        # Понеділок 14:59 (2026-09-21) -> ще немає 3 робочих днів
        mon_1459 = self.tz.localize(datetime(2026, 9, 21, 14, 59, 0))
        cutoff_mon_before = get_business_days_cutoff(mon_1459, business_days=3)
        self.assertEqual(cutoff_mon_before, self.tz.localize(datetime(2026, 9, 16, 14, 59, 0)))
        self.assertFalse(wednesday_15 < cutoff_mon_before)

        # Понеділок 15:01 (2026-09-21) -> 3 робочих дні виповнилося!
        mon_1501 = self.tz.localize(datetime(2026, 9, 21, 15, 1, 0))
        cutoff_mon_after = get_business_days_cutoff(mon_1501, business_days=3)
        self.assertEqual(cutoff_mon_after, self.tz.localize(datetime(2026, 9, 16, 15, 1, 0)))
        self.assertTrue(wednesday_15 < cutoff_mon_after)



class TestAutoDeleteWorkflow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import tempfile
        import os
        import aiosqlite
        from unittest.mock import patch

        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "users.db")
        self.managers_db_path = os.path.join(self.temp_dir.name, "managers.db")

        self.patcher_db = patch("database.users.DB_PATH", self.db_path)
        self.patcher_rem_db = patch("bot.services.reminders.delete_user")
        self.patcher_managers_db = patch("database.users.MANAGERS_DB_PATH", self.managers_db_path)

        self.patcher_db.start()
        self.patcher_managers_db.start()

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
                last_auto_reminder_at TIMESTAMP,
                day3_question_sent INTEGER DEFAULT 0,
                first_seen TIMESTAMP,
                current_block INTEGER DEFAULT 1
            )
            """)
            await db.execute("""
            CREATE TABLE reminder_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                intern_id INTEGER,
                source TEXT,
                sender_id INTEGER,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
            await db.execute("INSERT INTO positions (name, days_total) VALUES ('Пекар', 5)")
            await db.execute("""
            CREATE TABLE hr_users (
                user_id INTEGER PRIMARY KEY
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
            await db.commit()

        async with aiosqlite.connect(self.managers_db_path) as mdb:
            await mdb.execute("CREATE TABLE managers (uid INTEGER PRIMARY KEY)")
            await mdb.commit()

    async def asyncTearDown(self):
        self.patcher_db.stop()
        self.patcher_managers_db.stop()
        self.temp_dir.cleanup()

    async def test_auto_delete_query_skips_weekends(self):
        import aiosqlite
        from database.users import get_inactive_interns_for_auto_delete
        from unittest.mock import patch

        # Додаємо стажера, активного у п'ятницю 15:00 (2026-09-18 15:00:00)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO users (user_id, username, full_name, role, status, manager_id, last_activity, current_block)
                VALUES (201, 'intern_fri', 'Оксана Стажер', 'Пекар', 'Стажер', 777, '2026-09-18 15:00:00', 1)
                """
            )
            await db.commit()

        # 1. Симулюємо понеділок 15:00 (2026-09-21 15:00:00)
        tz = pytz.timezone(TIMEZONE)
        monday_now = tz.localize(datetime(2026, 9, 21, 15, 0, 0))
        with patch("database.users.datetime") as mock_dt:
            mock_dt.now.return_value = monday_now
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            candidates = await get_inactive_interns_for_auto_delete(days=3)
            # В понеділок ще не минуло 3 робочих дні!
            self.assertEqual(len(candidates), 0)

        # 2. Симулюємо середу 16:00 (2026-09-23 16:00:00)
        wednesday_now = tz.localize(datetime(2026, 9, 23, 16, 0, 0))
        with patch("database.users.datetime") as mock_dt:
            mock_dt.now.return_value = wednesday_now
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            candidates = await get_inactive_interns_for_auto_delete(days=3)
            # В середу після 15:00 - виповнилося 3 робочих дні!
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["user_id"], 201)

    async def test_auto_reminder_loop_deletes_and_notifies_manager(self):
        import aiosqlite
        from unittest.mock import AsyncMock, patch
        from bot.services.reminders import auto_reminder_loop

        # Додаємо неактивного стажера
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO users (user_id, username, full_name, role, status, manager_id, last_activity, current_block, city, shop)
                VALUES (202, 'stale_user', 'Андрій Неактивний', 'Пекар', 'Стажер', 777, '2026-09-10 10:00:00', 1, 'Хмельницький', 'B-1')
                """
            )
            await db.commit()

        bot = AsyncMock()

        # Симулюємо середу (робочий день)
        tz = pytz.timezone(TIMEZONE)
        wednesday_now = tz.localize(datetime(2026, 9, 23, 16, 0, 0))

        with patch("bot.services.reminders.datetime") as mock_rem_dt, \
             patch("database.users.datetime") as mock_usr_dt, \
             patch("bot.services.reminders.delete_user", new_callable=AsyncMock) as mock_delete, \
             patch("bot.services.access.is_privileged_user", new_callable=AsyncMock, return_value=False):

            mock_rem_dt.now.return_value = wednesday_now
            mock_rem_dt.fromisoformat = datetime.fromisoformat
            mock_usr_dt.now.return_value = wednesday_now
            mock_usr_dt.fromisoformat = datetime.fromisoformat

            await auto_reminder_loop(bot)

            # Перевіряємо, що стажера було видалено
            mock_delete.assert_awaited_once_with(202)

            # Перевіряємо, що керівнику (id 777) було надіслано сповіщення
            bot.send_message.assert_awaited()
            calls = [c for c in bot.send_message.await_args_list if c.args[0] == 777]
            self.assertTrue(len(calls) > 0)
            self.assertIn("Стажера видалено через неактивність", calls[0].args[1])
            self.assertIn("Андрій Неактивний", calls[0].args[1])


if __name__ == "__main__":
    unittest.main()

