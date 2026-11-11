import unittest
import os
import aiosqlite
import tempfile
import asyncio
from unittest.mock import AsyncMock, MagicMock

from database.news import (
    NEWS_REACTIONS,
    init_news_db,
    create_news,
    record_deliveries_batch,
    upsert_news_reaction,
    get_news_reactions_summary,
    format_news_reactions_line,
    update_text_with_reactions_line,
    get_delivered_news_messages
)
from bot.services.news_broadcaster import NewsReactionSyncQueue, get_news_reaction_keyboard


class TestNewsLiveReactions(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_news_live.db")
        await init_news_db(self.db_path)

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    def test_news_reactions_order_and_emojis(self):
        """Перевіряє, що дизлайк замінено на сміх та правильний набір емодзі."""
        self.assertEqual(NEWS_REACTIONS, ["🔥", "😁", "❤️", "🤔"])
        self.assertNotIn("👎", NEWS_REACTIONS)

    def test_format_news_reactions_line(self):
        """Перевіряє правильне форматування рядка лічильника."""
        empty_line = format_news_reactions_line({})
        self.assertEqual(empty_line, "0 🔥 | 0 😁 | 0 ❤️ | 0 🤔")

        populated_line = format_news_reactions_line({"🔥": 12, "😁": 5, "❤️": 99, "🤔": 3})
        self.assertEqual(populated_line, "12 🔥 | 5 😁 | 99 ❤️ | 3 🤔")

    def test_update_text_with_reactions_line(self):
        """Перевіряє вставку та оновлення рядка лічильника в тексті новини."""
        original_text = "<b>Увага!</b> Нове меню в пекарні."
        initial_line = "0 🔥 | 0 😁 | 0 ❤️ | 0 🤔"

        # 1. Первинне додавання
        first_pass = update_text_with_reactions_line(original_text, initial_line)
        self.assertEqual(first_pass, f"<b>Увага!</b> Нове меню в пекарні.\n\n{initial_line}")

        # 2. Оновлення існуючого рядка
        updated_line = "5 🔥 | 2 😁 | 1 ❤️ | 0 🤔"
        second_pass = update_text_with_reactions_line(first_pass, updated_line)
        self.assertEqual(second_pass, f"<b>Увага!</b> Нове меню в пекарні.\n\n{updated_line}")

        # 3. Очищення застарілого рядка 'Ваша анонімна реакція: ...'
        legacy_text = f"<b>Увага!</b>\n\nВаша анонімна реакція: 🔥\n\n{initial_line}"
        cleaned = update_text_with_reactions_line(legacy_text, updated_line)
        self.assertNotIn("Ваша анонімна реакція", cleaned)
        self.assertIn(updated_line, cleaned)

    async def test_migration_dislike_to_laugh(self):
        """Перевіряє, що стара реакція 👎 автоматично мігрує у 😁 під час init_news_db."""
        news_id = await create_news(
            text="Новина для міграції",
            photo_file_id=None,
            selected_roles=[],
            selected_city="all",
            total_recipients=1,
            total_waves=1,
            created_by=1,
            db_path=self.db_path
        )
        # Вставляємо старий дизлайк
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO news_reactions (news_id, user_id, reaction, created_at, updated_at) VALUES (?, ?, ?, '2026-01-01', '2026-01-01')",
                (news_id, 888, "👎")
            )
            await db.commit()

        # Викликаємо init_news_db, яка повинна виконати міграцію
        await init_news_db(self.db_path)

        summary = await get_news_reactions_summary(news_id, db_path=self.db_path)
        self.assertEqual(summary["breakdown"]["😁"], 1)
        self.assertEqual(summary["total"], 1)

    async def test_sync_queue_debounced_execution(self):
        """Перевіряє роботу фонової черги з дебаунсом."""
        news_id = await create_news(
            text="Новина про живі реакції",
            photo_file_id=None,
            selected_roles=[],
            selected_city="all",
            total_recipients=3,
            total_waves=1,
            created_by=1,
            db_path=self.db_path
        )

        deliveries = [
            {"news_id": news_id, "user_id": 101, "status": "delivered", "error_reason": None, "raw_error": None, "message_id": 501},
            {"news_id": news_id, "user_id": 102, "status": "delivered", "error_reason": None, "raw_error": None, "message_id": 502},
            {"news_id": news_id, "user_id": 103, "status": "delivered", "error_reason": None, "raw_error": None, "message_id": 503},
        ]
        await record_deliveries_batch(deliveries, db_path=self.db_path)

        # Користувач 101 голосує за вогонь
        await upsert_news_reaction(news_id, 101, "🔥", db_path=self.db_path)

        mock_bot = MagicMock()
        mock_bot.edit_message_text = AsyncMock()

        # Використовуємо чергу з коротким дебаунсом 0.05с для тесту
        queue = NewsReactionSyncQueue(debounce_seconds=0.05, max_wait_seconds=0.1, db_path=self.db_path)

        queue.schedule_sync(mock_bot, news_id, trigger_user_id=101)
        # Чекаємо відпрацювання дебаунсу
        await asyncio.sleep(0.15)

        # Перевіряємо: користувач 101 (автор кліку) пропущений, а 102 та 103 оновлені!
        calls = mock_bot.edit_message_text.call_args_list
        edited_uids = [call.kwargs.get("chat_id") for call in calls]
        self.assertNotIn(101, edited_uids)
        self.assertIn(102, edited_uids)
        self.assertIn(103, edited_uids)

        # Перевіряємо, що в тексті є оновлений лічильник "1 🔥 | 0 😁 | 0 ❤️ | 0 🤔"
        sample_text = calls[0].kwargs.get("text")
        self.assertIn("1 🔥 | 0 😁 | 0 ❤️ | 0 🤔", sample_text)


if __name__ == "__main__":
    unittest.main()
