import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from main import daily_test_failure_notifier


class TestDailyTestFailureNotifier(unittest.IsolatedAsyncioTestCase):
    async def test_daily_test_failure_notifier_success(self):
        mock_bot = MagicMock()
        mock_incomplete = [(101, 1), (102, 2)]
        mock_grouped = {
            12345: [(101, 1)],
            67890: [(102, 2)],
        }

        with patch("main.get_intern_incomplete_open_test_days", new=AsyncMock(return_value=mock_incomplete)), \
             patch("main.group_test_failures_by_manager", new=AsyncMock(return_value=mock_grouped)), \
             patch("main.send_daily_test_failure_report_to_manager", new=AsyncMock(return_value=True)) as mock_send:
            await daily_test_failure_notifier(mock_bot)
            self.assertEqual(mock_send.call_count, 2)
            mock_send.assert_any_call(mock_bot, 12345, [(101, 1)])
            mock_send.assert_any_call(mock_bot, 67890, [(102, 2)])

    async def test_daily_test_failure_notifier_empty(self):
        mock_bot = MagicMock()

        with patch("main.get_intern_incomplete_open_test_days", new=AsyncMock(return_value=[])), \
             patch("main.group_test_failures_by_manager", new=AsyncMock(return_value={})), \
             patch("main.send_daily_test_failure_report_to_manager", new=AsyncMock(return_value=True)) as mock_send:
            await daily_test_failure_notifier(mock_bot)
            mock_send.assert_not_called()

    async def test_get_intern_incomplete_excludes_observers_and_workers(self):
        from bot.services.test_error_monitoring_service import get_intern_incomplete_open_test_days
        from bot.services.learning_progress import DayStatus

        fake_users = [
            {"user_id": 1001, "role": "Продавець", "status": "Стажер"},
            {"user_id": 1002, "role": "Наглядач", "status": None},
            {"user_id": 1003, "role": "Керівник", "status": "Працівник"},
            {"user_id": 1004, "role": "Продавець", "status": "Працівник"},
            {"user_id": 1005, "role": "Пекар", "status": None},  # privileged in managers.db
        ]

        with patch("bot.services.test_error_monitoring_service.get_all_users", new=AsyncMock(return_value=fake_users)), \
             patch("database.users._get_privileged_user_ids", new=AsyncMock(return_value={1005})), \
             patch("bot.services.test_error_monitoring_service.get_days_overview", new=AsyncMock(return_value=[(1, DayStatus.OPEN)])), \
             patch("bot.services.test_error_monitoring_service.get_user_progress", new=AsyncMock(return_value=[])):
            result = await get_intern_incomplete_open_test_days()
            self.assertEqual(result, [(1001, 1)])

    async def test_is_user_without_store_manager_excludes_management_roles(self):
        from database.managers import is_user_without_store_manager

        observer_user = {"user_id": 2001, "role": "Наглядач", "manager_id": None}
        manager_user = {"user_id": 2002, "role": "Керівник", "manager_id": None}
        admin_user = {"user_id": 2003, "role": "Адміністратор", "manager_id": None}

        self.assertFalse(await is_user_without_store_manager(observer_user))
        self.assertFalse(await is_user_without_store_manager(manager_user))
        self.assertFalse(await is_user_without_store_manager(admin_user))


if __name__ == "__main__":
    unittest.main()
