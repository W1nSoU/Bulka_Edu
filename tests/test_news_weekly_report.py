import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import openpyxl
import pytz

from bot.config import TIMEZONE
import database.news as news_db
import bot.services.news_excel as news_excel


class NewsHtmlAndWeeklyReportTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "users.db")

        await news_db.init_news_db(db_path=self.db_path)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE users (
                    user_id INTEGER PRIMARY KEY,
                    full_name TEXT,
                    username TEXT,
                    role TEXT,
                    city TEXT,
                    shop TEXT,
                    status TEXT
                )
                """
            )
            await db.execute(
                "INSERT INTO users VALUES (101, 'Іван Петренко', 'ivan', 'Продавець', 'Київ', 'b-12', 'Працівник')"
            )
            await db.execute(
                "INSERT INTO users VALUES (102, 'Олена Коваль', 'olena', 'Пекар', 'Львів', 'b-05', 'Працівник')"
            )
            await db.commit()

    async def asyncTearDown(self):
        self.tmpdir.cleanup()

    def test_safe_news_media_caption_prevents_unclosed_html_tags(self):
        # Reproduce the exact failure mode: long HTML body with <b>/<i>/<a> tags right around 1024 chars
        body = (
            "<b>Велика новина мережі BULKA!</b>\n"
            + ("<i>Детальний опис змін & нових стандартів <a href='https://bulka.ua'>посилання</a></i> " * 25)
        )
        stats_block = (
            "📊 <b>Статистика новини:</b>\n"
            "📅 Дата публікації: <b>2026-11-20 12:00:00</b>\n"
            "👥 Аудиторія: <b>Всі (Усі міста)</b>\n"
            "📬 Всього отримувачів: <b>250</b>\n"
            "✅ Успішно доставлено: <b>245</b> (98.0%)\n"
            "❌ Не вдалося доставити: <b>5</b> (2.0%)\n"
            "💬 Отримано реакцій: <b>120</b> (49.0%)\n\n"
            "<b>Емоції:</b>\n"
            "👍 30  |  🔥 40  |  😁 10  |  ❤️ 35  |  🤔 5"
        )

        caption = news_excel.build_safe_news_media_caption(26, body, stats_block, limit=1024)
        self.assertLessEqual(len(caption), 1024)
        self.assertIn("Статистика новини:", caption)
        self.assertIn("👍 30", caption)

        # Must parse as valid XML/HTML with zero unclosed tags!
        ET.fromstring(f"<root>{caption}</root>")

        # Also test force_escape_body=True for broken unclosed tags in short text
        broken_short = "<b>Незакритий тег без пари"
        safe_short = news_excel.build_safe_news_media_caption(
            26, broken_short, stats_block, limit=1024, force_escape_body=True
        )
        self.assertLessEqual(len(safe_short), 1024)
        ET.fromstring(f"<root>{safe_short}</root>")

    async def test_weekly_report_data_and_xlsx_generation(self):
        tz = pytz.timezone(TIMEZONE)
        fixed_now = tz.localize(datetime(2026, 11, 20, 9, 0, 0))
        recent_1 = (fixed_now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        recent_2 = (fixed_now - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
        old_news = (fixed_now - timedelta(days=12)).strftime("%Y-%m-%d %H:%M:%S")

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO news (id, text, selected_roles, selected_city, total_recipients, sent_count, failed_count, total_waves, status, created_at, created_by)
                VALUES
                  (10, '<b>Новина тижня #1</b>', '["Продавець"]', 'all', 100, 95, 5, 2, 'completed', ?, 1),
                  (11, 'Новина тижня #2', '["Пекар"]', 'Львів', 50, 50, 0, 1, 'completed', ?, 1),
                  (9,  'Стара новина (12 днів тому)', '[]', 'all', 200, 190, 10, 4, 'completed', ?, 1)
                """,
                (recent_1, recent_2, old_news),
            )
            await db.execute(
                """
                INSERT INTO news_reactions (news_id, user_id, reaction, created_at, updated_at)
                VALUES
                  (10, 101, '🔥', ?, ?),
                  (10, 102, '👍', ?, ?),
                  (11, 102, '❤️', ?, ?),
                  (9,  101, '🔥', ?, ?)
                """,
                (recent_1, recent_1, recent_1, recent_1, recent_2, recent_2, old_news, old_news),
            )
            await db.execute(
                """
                INSERT INTO news_deliveries (news_id, user_id, status, error_reason, raw_error, delivered_at)
                VALUES
                  (10, 102, 'failed', 'Бот заблокований користувачем', 'Forbidden', ?),
                  (9,  101, 'failed', 'Стара помилка', 'Forbidden', ?)
                """,
                (recent_1, old_news),
            )
            await db.commit()

        stream, data = await news_excel.generate_weekly_news_report_xlsx(
            days=7, db_path=self.db_path, now_dt=fixed_now
        )

        # Only news #10 and #11 fall within 7 days (news #9 excluded)
        self.assertEqual(data["news_count"], 2)
        self.assertEqual(data["total_recipients"], 150)
        self.assertEqual(data["sent_count"], 145)
        self.assertEqual(data["failed_count"], 5)
        self.assertEqual(data["total_reactions"], 3)
        self.assertEqual(data["reactions_breakdown"]["🔥"], 1)
        self.assertEqual(data["reactions_breakdown"]["👍"], 1)
        self.assertEqual(data["reactions_breakdown"]["❤️"], 1)
        self.assertEqual(data["top_news"]["id"], 10)
        self.assertEqual(len(data["reactions_detailed"]), 3)
        self.assertEqual(len(data["failed_deliveries"]), 1)

        # Verify valid 3-sheet Excel workbook
        wb_loaded = openpyxl.load_workbook(stream)
        self.assertEqual(wb_loaded.sheetnames, ["Зведення тижня", "Реакції за тиждень", "Не доставлено"])
        self.assertEqual(wb_loaded["Реакції за тиждень"].max_row, 3 + 3)  # 3 header rows + 3 reactions
        self.assertEqual(wb_loaded["Не доставлено"].max_row, 3 + 1)  # 3 header rows + 1 failure

        caption = news_excel.format_weekly_news_summary_caption(data)
        self.assertIn("Опубліковано новин: <b>2</b>", caption)
        self.assertIn("Топ-новина:", caption)
        ET.fromstring(f"<root>{caption}</root>")

    async def test_auto_weekly_sender_skips_empty_and_sends_when_present(self):
        fake_bot = MagicMock()
        fake_bot.send_document = AsyncMock()

        # Empty week -> skips sending
        empty_data = {"news_count": 0}
        with patch.object(
            news_excel,
            "generate_weekly_news_report_xlsx",
            new=AsyncMock(return_value=(MagicMock(getvalue=lambda: b"xlsx"), empty_data)),
        ):
            sent_empty = await news_excel.auto_weekly_news_report_sender(fake_bot)
            self.assertEqual(sent_empty, 0)
            fake_bot.send_document.assert_not_awaited()

        # Non-empty week -> sends to all admins & observers
        populated_data = {
            "period_label": "13.11.2026 — 20.11.2026",
            "news_count": 2,
            "total_recipients": 100,
            "sent_count": 98,
            "sent_pct": 98.0,
            "failed_count": 2,
            "total_reactions": 40,
            "reaction_pct": 40.8,
            "reactions_breakdown": {"👍": 10, "🔥": 15, "😁": 5, "❤️": 8, "🤔": 2},
            "top_news": {"id": 26, "reactions_total": 25, "text": "Новина"},
        }
        with patch.object(
            news_excel,
            "generate_weekly_news_report_xlsx",
            new=AsyncMock(return_value=(MagicMock(getvalue=lambda: b"xlsx-bytes"), populated_data)),
        ), patch.object(
            news_excel,
            "get_news_report_recipient_ids",
            new=AsyncMock(return_value=[738460434, 1001226587]),
        ):
            sent = await news_excel.auto_weekly_news_report_sender(fake_bot)
            self.assertEqual(sent, 2)
            self.assertEqual(fake_bot.send_document.await_count, 2)


if __name__ == "__main__":
    unittest.main()
