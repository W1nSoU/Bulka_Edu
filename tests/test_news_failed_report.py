import unittest
from unittest.mock import AsyncMock, patch

from bot.services.news_broadcaster import dispatch_news_waves


class TestNewsFailedReport(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot = AsyncMock()

    @patch("bot.services.news_broadcaster.send_news_batch", new_callable=AsyncMock)
    @patch("bot.services.news_broadcaster.update_news_stats", new_callable=AsyncMock)
    async def test_final_report_success_has_no_failed_section(self, mock_stats, mock_batch):
        mock_batch.return_value = (5, 0)

        await dispatch_news_waves(
            bot=self.bot,
            recipient_uids=[1, 2, 3, 4, 5],
            text="Test news",
            admin_chat_id=999,
            news_id=42
        )

        self.bot.send_message.assert_awaited()
        # Find final message sent to admin
        admin_calls = [c for c in self.bot.send_message.call_args_list if c[1].get("chat_id") == 999]
        self.assertTrue(len(admin_calls) > 0)
        final_text = admin_calls[-1][1].get("text")
        self.assertIn("Розсилку новини повністю завершено!", final_text)
        self.assertIn("Успішно доставлено: <b>5</b>", final_text)
        self.assertIn("Не вдалося доставити: <b>0</b>", final_text)
        self.assertNotIn("Не отримали повідомлення:", final_text)

    @patch("bot.services.news_broadcaster.get_news_failed_deliveries_detailed", new_callable=AsyncMock)
    @patch("bot.services.news_broadcaster.send_news_batch", new_callable=AsyncMock)
    @patch("bot.services.news_broadcaster.update_news_stats", new_callable=AsyncMock)
    async def test_final_report_includes_failed_recipients_details(
        self, mock_stats, mock_batch, mock_get_failed
    ):
        mock_batch.return_value = (4, 1)
        mock_get_failed.return_value = [
            {
                "user_id": 12345,
                "full_name": "Іван Тестовий",
                "role": "Пекар",
                "shop": "B-1 вул. Степана Бандери",
                "error_reason": "⛔️ Бот заблокований користувачем"
            }
        ]

        await dispatch_news_waves(
            bot=self.bot,
            recipient_uids=[1, 2, 3, 4, 12345],
            text="Test news",
            admin_chat_id=999,
            news_id=43
        )

        mock_get_failed.assert_awaited_once_with(43)
        admin_calls = [c for c in self.bot.send_message.call_args_list if c[1].get("chat_id") == 999]
        final_text = admin_calls[-1][1].get("text")

        self.assertIn("Не вдалося доставити: <b>1</b>", final_text)
        self.assertIn("⚠️ <b>Не отримали повідомлення:</b>", final_text)
        self.assertIn("Іван Тестовий", final_text)
        self.assertIn("12345", final_text)
        self.assertIn("Пекар, B-1 вул. Степана Бандери", final_text)
        self.assertIn("⛔️ Бот заблокований користувачем", final_text)

    @patch("bot.services.news_broadcaster.get_news_failed_deliveries_detailed", new_callable=AsyncMock)
    @patch("bot.services.news_broadcaster.send_news_batch", new_callable=AsyncMock)
    @patch("bot.services.news_broadcaster.update_news_stats", new_callable=AsyncMock)
    async def test_final_report_limits_to_15_recipients(
        self, mock_stats, mock_batch, mock_get_failed
    ):
        mock_batch.return_value = (0, 20)
        mock_get_failed.return_value = [
            {
                "user_id": 1000 + i,
                "full_name": f"Працівник {i}",
                "role": "Продавець",
                "shop": "B-2",
                "error_reason": "⛔️ Бот заблокований користувачем"
            }
            for i in range(20)
        ]

        await dispatch_news_waves(
            bot=self.bot,
            recipient_uids=list(range(20)),
            text="Test news",
            admin_chat_id=999,
            news_id=44
        )

        admin_calls = [c for c in self.bot.send_message.call_args_list if c[1].get("chat_id") == 999]
        final_text = admin_calls[-1][1].get("text")

        self.assertIn("...та ще 5 осіб", final_text)
        self.assertIn("Працівник 0", final_text)
        self.assertIn("Працівник 14", final_text)
        self.assertNotIn("Працівник 15", final_text)


if __name__ == "__main__":
    unittest.main()
