import unittest
import os
import io
import aiosqlite
import tempfile
import json
from datetime import datetime, timedelta
import pytz
import openpyxl

from bot.config import TIMEZONE
from database.news import (
    NEWS_REACTIONS,
    init_news_db,
    create_news,
    update_news_stats,
    record_deliveries_batch,
    get_news_by_id,
    get_news_history_last_6_months,
    upsert_news_reaction,
    get_user_news_reaction,
    get_news_reactions_summary,
    get_news_failed_deliveries_detailed,
    get_news_reactions_detailed
)
from bot.services.news_broadcaster import (
    classify_telegram_error,
    get_news_reaction_keyboard
)
from bot.services.news_excel import generate_news_report_xlsx


class TestNewsReactionsAndHistory(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_news.db")

        # Ініціалізуємо таблицю users для тестів джойнів
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                full_name TEXT,
                username TEXT,
                role TEXT,
                city TEXT,
                shop TEXT,
                created_at TIMESTAMP
            )
            """)
            await db.execute("""
            INSERT INTO users (user_id, full_name, username, role, city, shop)
            VALUES 
                (101, 'Іван Тестовий', 'ivan_test', 'Бармен', 'Луцьк', 'Магазин #1'),
                (102, 'Марія Продавчиня', 'maria_test', 'Продавець', 'Луцьк', 'Магазин #2'),
                (103, 'Петро Блокувальник', 'petro_test', 'Кухар', 'Рівне', 'Магазин #5')
            """)
            await db.commit()

        # Ініціалізуємо схему новин
        await init_news_db(self.db_path)

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    def test_classify_telegram_error(self):
        self.assertEqual(
            classify_telegram_error("Telegram server says - Forbidden: bot was blocked by the user"),
            "⛔️ Бот заблокований користувачем"
        )
        self.assertEqual(
            classify_telegram_error("Telegram server says - Forbidden: user is deactivated"),
            "👤 Акаунт деактивовано / видалено"
        )
        self.assertEqual(
            classify_telegram_error("Bad Request: chat not found"),
            "❓ Чат не знайдено"
        )
        self.assertEqual(
            classify_telegram_error("Flood control exceeded: retry after 42"),
            "⏳ Ліміт запитів Telegram (Flood limit)"
        )
        self.assertTrue(
            classify_telegram_error("Internal server error 500").startswith("⚠️")
        )

    def test_get_news_reaction_keyboard(self):
        # Без обраної реакції
        kb = get_news_reaction_keyboard(news_id=42)
        self.assertEqual(len(kb.inline_keyboard), 1)
        row = kb.inline_keyboard[0]
        self.assertEqual(len(row), 4)
        for i, emoji in enumerate(NEWS_REACTIONS):
            self.assertEqual(row[i].text, emoji)
            self.assertEqual(row[i].callback_data, f"news_react:42:{emoji}")

        # З обраною реакцією '❤️'
        kb_active = get_news_reaction_keyboard(news_id=42, current_reaction="❤️")
        row_active = kb_active.inline_keyboard[0]
        texts = [btn.text for btn in row_active]
        self.assertIn("❤️ ✅", texts)
        self.assertIn("👎", texts)
        self.assertIn("🤔", texts)
        self.assertIn("🔥", texts)

    async def test_create_and_update_news(self):
        news_id = await create_news(
            text="Тестова новина #оголошення",
            photo_file_id="photo123",
            selected_roles=["Бармен", "Кухар"],
            selected_city="Луцьк",
            total_recipients=50,
            total_waves=1,
            created_by=999,
            db_path=self.db_path
        )
        self.assertIsInstance(news_id, int)
        self.assertGreater(news_id, 0)

        news = await get_news_by_id(news_id, db_path=self.db_path)
        self.assertIsNotNone(news)
        self.assertEqual(news["text"], "Тестова новина #оголошення")
        self.assertEqual(news["photo_file_id"], "photo123")
        self.assertEqual(news["selected_roles"], ["Бармен", "Кухар"])
        self.assertEqual(news["selected_city"], "Луцьк")
        self.assertEqual(news["status"], "in_progress")

        await update_news_stats(
            news_id=news_id,
            sent_count=48,
            failed_count=2,
            status="completed",
            db_path=self.db_path
        )

        updated_news = await get_news_by_id(news_id, db_path=self.db_path)
        self.assertEqual(updated_news["sent_count"], 48)
        self.assertEqual(updated_news["failed_count"], 2)
        self.assertEqual(updated_news["status"], "completed")

    async def test_record_deliveries_and_queries(self):
        news_id = await create_news(text="Новина 1", db_path=self.db_path)

        deliveries = [
            {
                "news_id": news_id,
                "user_id": 101,
                "status": "delivered",
                "message_id": 1001
            },
            {
                "news_id": news_id,
                "user_id": 102,
                "status": "delivered",
                "message_id": 1002
            },
            {
                "news_id": news_id,
                "user_id": 103,
                "status": "failed",
                "error_reason": "⛔️ Бот заблокований користувачем",
                "raw_error": "Forbidden: bot was blocked by the user"
            }
        ]
        await record_deliveries_batch(deliveries, db_path=self.db_path)

        failed = await get_news_failed_deliveries_detailed(news_id, db_path=self.db_path)
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["user_id"], 103)
        self.assertEqual(failed[0]["full_name"], "Петро Блокувальник")
        self.assertEqual(failed[0]["shop"], "Магазин #5")
        self.assertEqual(failed[0]["error_reason"], "⛔️ Бот заблокований користувачем")

    async def test_upsert_and_summary_reactions(self):
        news_id = await create_news(text="Новина для реакцій", db_path=self.db_path)

        # 1. Додаємо реакцію від користувача 101
        res1 = await upsert_news_reaction(news_id, 101, "❤️", db_path=self.db_path)
        self.assertTrue(res1)
        self.assertEqual(await get_user_news_reaction(news_id, 101, db_path=self.db_path), "❤️")

        # 2. Додаємо реакцію від користувача 102
        res2 = await upsert_news_reaction(news_id, 102, "🔥", db_path=self.db_path)
        self.assertTrue(res2)

        summary = await get_news_reactions_summary(news_id, db_path=self.db_path)
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["breakdown"]["❤️"], 1)
        self.assertEqual(summary["breakdown"]["🔥"], 1)
        self.assertEqual(summary["breakdown"]["👎"], 0)
        self.assertEqual(summary["breakdown"]["🤔"], 0)

        # 3. Користувач 101 змінює свою реакцію на "🔥"
        res3 = await upsert_news_reaction(news_id, 101, "🔥", db_path=self.db_path)
        self.assertTrue(res3)
        self.assertEqual(await get_user_news_reaction(news_id, 101, db_path=self.db_path), "🔥")

        summary2 = await get_news_reactions_summary(news_id, db_path=self.db_path)
        self.assertEqual(summary2["total"], 2)
        self.assertEqual(summary2["breakdown"]["❤️"], 0)
        self.assertEqual(summary2["breakdown"]["🔥"], 2)

        # 4. Перевіряємо get_news_reactions_detailed
        detailed = await get_news_reactions_detailed(news_id, db_path=self.db_path)
        self.assertEqual(len(detailed), 2)
        user_ids = {d["user_id"] for d in detailed}
        self.assertEqual(user_ids, {101, 102})
        for d in detailed:
            if d["user_id"] == 101:
                self.assertEqual(d["full_name"], "Іван Тестовий")
                self.assertEqual(d["reaction"], "🔥")

    async def test_get_news_history_last_6_months(self):
        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz)

        # 1. Новина сьогодні
        n1 = await create_news(text="Новина сьогодні", db_path=self.db_path)

        # 2. Новина 90 днів тому
        n2 = await create_news(text="Новина 90 днів тому", db_path=self.db_path)
        async with aiosqlite.connect(self.db_path) as db:
            d90 = (now - timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S")
            await db.execute("UPDATE news SET created_at = ? WHERE id = ?", (d90, n2))
            await db.commit()

        # 3. Новина 200 днів тому (повинна бути виключена, бо > 180 днів)
        n3 = await create_news(text="Стара новина 200 днів", db_path=self.db_path)
        async with aiosqlite.connect(self.db_path) as db:
            d200 = (now - timedelta(days=200)).strftime("%Y-%m-%d %H:%M:%S")
            await db.execute("UPDATE news SET created_at = ? WHERE id = ?", (d200, n3))
            await db.commit()

        history = await get_news_history_last_6_months(db_path=self.db_path)
        history_ids = [item["id"] for item in history]
        self.assertIn(n1, history_ids)
        self.assertIn(n2, history_ids)
        self.assertNotIn(n3, history_ids)
        # Сортування DESC (від найновішої)
        self.assertEqual(history[0]["id"], n2)  # останній створений ID з тих, що увійшли

    async def test_generate_news_report_xlsx(self):
        news_id = await create_news(
            text="Свято смаку та знижок! #новини #булка",
            selected_roles=["Бармен"],
            selected_city="Луцьк",
            total_recipients=3,
            total_waves=1,
            db_path=self.db_path
        )
        await update_news_stats(news_id, sent_count=2, failed_count=1, status="completed", db_path=self.db_path)

        # Додаємо 1 невдалу доставку
        await record_deliveries_batch([
            {
                "news_id": news_id,
                "user_id": 103,
                "status": "failed",
                "error_reason": "⛔️ Бот заблокований користувачем",
                "raw_error": "Forbidden: bot was blocked by the user"
            }
        ], db_path=self.db_path)

        # Додаємо 1 реакцію
        await upsert_news_reaction(news_id, 101, "❤️", db_path=self.db_path)

        # Генеруємо звіт
        report_stream = await generate_news_report_xlsx(news_id, db_path=self.db_path)
        self.assertIsInstance(report_stream, io.BytesIO)
        report_bytes = report_stream.getvalue()
        self.assertGreater(len(report_bytes), 1000)

        # Завантажуємо через openpyxl для перевірки аркушів
        wb = openpyxl.load_workbook(io.BytesIO(report_bytes))
        sheet_names = wb.sheetnames
        self.assertEqual(sheet_names, ["Загальний", "Не доставлено", "Реакції"])

        # Перевіряємо аркуш "Загальний"
        ws_gen = wb["Загальний"]
        cell_vals = [cell.value for row in ws_gen.iter_rows() for cell in row if cell.value is not None]
        self.assertTrue(any("Свято смаку" in str(v) for v in cell_vals))
        self.assertTrue(any("Всього отримувачів" in str(v) for v in cell_vals))
        self.assertTrue(any("❤️" in str(v) for v in cell_vals))

        # Перевіряємо аркуш "Не доставлено"
        ws_failed = wb["Не доставлено"]
        failed_vals = [cell.value for row in ws_failed.iter_rows() for cell in row if cell.value is not None]
        self.assertTrue(any("Петро Блокувальник" in str(v) for v in failed_vals))
        self.assertTrue(any("⛔️ Бот заблокований користувачем" in str(v) for v in failed_vals))

        # Перевіряємо аркуш "Реакції" (лише користувачі, що проголосували)
        ws_reactions = wb["Реакції"]
        reaction_vals = [cell.value for row in ws_reactions.iter_rows() for cell in row if cell.value is not None]
        self.assertTrue(any("Іван Тестовий" in str(v) for v in reaction_vals))
        self.assertTrue(any("❤️" in str(v) for v in reaction_vals))
        self.assertFalse(any("Марія Продавчиня" in str(v) for v in reaction_vals))


if __name__ == "__main__":
    unittest.main()
