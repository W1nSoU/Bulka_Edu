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


if __name__ == "__main__":
    unittest.main()
