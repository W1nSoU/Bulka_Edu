import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import os
import tempfile
import aiosqlite

from database.news import (
    init_news_db,
    create_news,
    get_news_by_id
)
from bot.services.news_broadcaster import (
    send_news_batch,
    dispatch_news_waves
)
from bot.menus.developer import (
    NewsCreationStates,
    dev_news_create_start,
    dev_news_process_content,
    dev_news_ai_improve_handler,
    dev_news_revert_orig_handler
)


class TestNewsMediaBroadcaster(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_news_media.db")
        await init_news_db(self.db_path)

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    async def test_database_news_media_fields(self):
        # 1. Створення новини лише з текстом
        nid_text = await create_news(
            text="Текстова новина",
            selected_roles=["Працівник"],
            selected_city="Луцьк",
            total_recipients=5,
            total_waves=1,
            created_by=999,
            db_path=self.db_path
        )
        news_text = await get_news_by_id(nid_text, db_path=self.db_path)
        self.assertIsNotNone(news_text)
        self.assertIsNone(news_text.get("photo_file_id"))
        self.assertIsNone(news_text.get("video_file_id"))
        self.assertIsNone(news_text.get("media_type"))

        # 2. Створення новини з фото
        nid_photo = await create_news(
            text="Новина з фото",
            photo_file_id="photo_abc_123",
            selected_roles=["Працівник"],
            selected_city="all",
            total_recipients=10,
            total_waves=1,
            created_by=999,
            db_path=self.db_path
        )
        news_photo = await get_news_by_id(nid_photo, db_path=self.db_path)
        self.assertIsNotNone(news_photo)
        self.assertEqual(news_photo.get("photo_file_id"), "photo_abc_123")
        self.assertIsNone(news_photo.get("video_file_id"))
        self.assertEqual(news_photo.get("media_type"), "photo")

        # 3. Створення новини з відео
        nid_video = await create_news(
            text="Новина з відео",
            video_file_id="video_xyz_789",
            selected_roles=["Стажер"],
            selected_city="Рівне",
            total_recipients=8,
            total_waves=1,
            created_by=999,
            db_path=self.db_path
        )
        news_video = await get_news_by_id(nid_video, db_path=self.db_path)
        self.assertIsNotNone(news_video)
        self.assertIsNone(news_video.get("photo_file_id"))
        self.assertEqual(news_video.get("video_file_id"), "video_xyz_789")
        self.assertEqual(news_video.get("media_type"), "video")

    async def test_send_news_batch_text_only(self):
        bot = MagicMock()
        mock_msg = MagicMock()
        mock_msg.message_id = 1001
        bot.send_message = AsyncMock(return_value=mock_msg)
        bot.send_photo = AsyncMock()
        bot.send_video = AsyncMock()

        with patch("bot.services.news_broadcaster.asyncio.sleep", new_callable=AsyncMock):
            with patch("bot.services.news_broadcaster.record_deliveries_batch", new_callable=AsyncMock) as mock_record:
                sent, failed = await send_news_batch(
                    bot=bot,
                    recipient_uids=[11, 22],
                    text="Тестове повідомлення",
                    news_id=1
                )

        self.assertEqual(sent, 2)
        self.assertEqual(failed, 0)
        self.assertEqual(bot.send_message.call_count, 2)
        bot.send_photo.assert_not_called()
        bot.send_video.assert_not_called()
        mock_record.assert_called_once()
        deliveries = mock_record.call_args[0][0]
        self.assertEqual(len(deliveries), 2)
        self.assertEqual(deliveries[0]["message_id"], 1001)

    async def test_send_news_batch_with_photo(self):
        bot = MagicMock()
        mock_photo_msg = MagicMock()
        mock_photo_msg.message_id = 2001
        mock_text_msg = MagicMock()
        mock_text_msg.message_id = 2002
        bot.send_photo = AsyncMock(return_value=mock_photo_msg)
        bot.send_message = AsyncMock(return_value=mock_text_msg)
        bot.send_video = AsyncMock()

        with patch("bot.services.news_broadcaster.asyncio.sleep", new_callable=AsyncMock):
            with patch("bot.services.news_broadcaster.record_deliveries_batch", new_callable=AsyncMock) as mock_record:
                sent, failed = await send_news_batch(
                    bot=bot,
                    recipient_uids=[33],
                    text="Опис до фото",
                    photo_file_id="photo_token_123",
                    news_id=2,
                    media_type="photo"
                )

        self.assertEqual(sent, 1)
        self.assertEqual(failed, 0)
        bot.send_photo.assert_called_once_with(
            chat_id=33,
            photo="photo_token_123"
        )
        bot.send_message.assert_called_once()
        bot.send_video.assert_not_called()

        deliveries = mock_record.call_args[0][0]
        self.assertEqual(deliveries[0]["message_id"], 2002)

    async def test_send_news_batch_with_video(self):
        bot = MagicMock()
        mock_video_msg = MagicMock()
        mock_video_msg.message_id = 3001
        mock_text_msg = MagicMock()
        mock_text_msg.message_id = 3002
        bot.send_video = AsyncMock(return_value=mock_video_msg)
        bot.send_message = AsyncMock(return_value=mock_text_msg)
        bot.send_photo = AsyncMock()

        with patch("bot.services.news_broadcaster.asyncio.sleep", new_callable=AsyncMock):
            with patch("bot.services.news_broadcaster.record_deliveries_batch", new_callable=AsyncMock) as mock_record:
                sent, failed = await send_news_batch(
                    bot=bot,
                    recipient_uids=[44],
                    text="Опис до відео",
                    video_file_id="video_token_456",
                    news_id=3,
                    media_type="video"
                )

        self.assertEqual(sent, 1)
        self.assertEqual(failed, 0)
        bot.send_video.assert_called_once_with(
            chat_id=44,
            video="video_token_456"
        )
        bot.send_message.assert_called_once()
        bot.send_photo.assert_not_called()

        deliveries = mock_record.call_args[0][0]
        self.assertEqual(deliveries[0]["message_id"], 3002)

    async def test_dev_news_process_video_with_caption(self):
        state = MagicMock()
        stored_data = {}

        async def fake_update_data(**kwargs):
            stored_data.update(kwargs)

        async def fake_get_data():
            return stored_data

        state.update_data = AsyncMock(side_effect=fake_update_data)
        state.get_data = AsyncMock(side_effect=fake_get_data)
        state.set_state = AsyncMock()

        message = MagicMock()
        message.video = MagicMock()
        message.video.file_id = "video_file_123"
        message.photo = None
        message.text = None
        message.caption = "Відео огляд процесу"
        message.answer = AsyncMock()

        with patch("bot.menus.developer._check_news_access", new_callable=AsyncMock, return_value=True):
            with patch("bot.menus.developer._show_news_categories_selection", new_callable=AsyncMock) as mock_cats:
                await dev_news_process_content(message, state)

        self.assertEqual(stored_data.get("media_type"), "video")
        self.assertEqual(stored_data.get("video_file_id"), "video_file_123")
        self.assertIsNone(stored_data.get("photo_file_id"))
        self.assertEqual(stored_data.get("text_content"), "Відео огляд процесу")
        state.set_state.assert_called_once_with(NewsCreationStates.selecting_categories)
        mock_cats.assert_called_once()

    async def test_dev_news_process_video_without_caption_then_text(self):
        state = MagicMock()
        stored_data = {}

        async def fake_update_data(**kwargs):
            stored_data.update(kwargs)

        async def fake_get_data():
            return stored_data

        state.update_data = AsyncMock(side_effect=fake_update_data)
        state.get_data = AsyncMock(side_effect=fake_get_data)
        state.set_state = AsyncMock()

        # Крок 1: відправка відео без підпису
        msg_video = MagicMock()
        msg_video.video = MagicMock()
        msg_video.video.file_id = "video_file_456"
        msg_video.photo = None
        msg_video.text = None
        msg_video.caption = None
        msg_video.answer = AsyncMock()

        with patch("bot.menus.developer._check_news_access", new_callable=AsyncMock, return_value=True):
            await dev_news_process_content(msg_video, state)

        self.assertEqual(stored_data.get("media_type"), "video")
        self.assertEqual(stored_data.get("video_file_id"), "video_file_456")
        msg_video.answer.assert_called_once()
        self.assertIn("Медіа збережено", msg_video.answer.call_args[0][0])
        state.set_state.assert_not_called()

        # Крок 2: надсилання тексту окремим повідомленням
        msg_text = MagicMock()
        msg_text.video = None
        msg_text.photo = None
        msg_text.text = "Текст який надіслали після відео"
        msg_text.caption = None
        msg_text.answer = AsyncMock()

        with patch("bot.menus.developer._check_news_access", new_callable=AsyncMock, return_value=True):
            with patch("bot.menus.developer._show_news_categories_selection", new_callable=AsyncMock) as mock_cats:
                await dev_news_process_content(msg_text, state)

        self.assertEqual(stored_data.get("media_type"), "video")
        self.assertEqual(stored_data.get("video_file_id"), "video_file_456")
        self.assertEqual(stored_data.get("text_content"), "Текст який надіслали після відео")
        state.set_state.assert_called_once_with(NewsCreationStates.selecting_categories)
        mock_cats.assert_called_once()

    async def test_dev_news_ai_improve_affects_only_text(self):
        state = MagicMock()
        stored_data = {
            "video_file_id": "video_vid_999",
            "photo_file_id": None,
            "media_type": "video",
            "text_content": "Початковий простий текст",
            "original_text_content": "Початковий простий текст",
            "is_ai_improved": False
        }

        async def fake_update_data(**kwargs):
            stored_data.update(kwargs)

        async def fake_get_data():
            return stored_data

        state.update_data = AsyncMock(side_effect=fake_update_data)
        state.get_data = AsyncMock(side_effect=fake_get_data)

        callback = MagicMock()
        callback.answer = AsyncMock()

        with patch("bot.menus.developer._check_news_access", new_callable=AsyncMock, return_value=True):
            with patch("bot.services.openai_ai.improve_news_text_with_gpt", new_callable=AsyncMock, return_value="Покращений ШІ текст"):
                with patch("bot.menus.developer._show_news_preview", new_callable=AsyncMock) as mock_preview:
                    await dev_news_ai_improve_handler(callback, state)

        # Текст покращено, але медіа не змінилося!
        self.assertEqual(stored_data.get("text_content"), "Покращений ШІ текст")
        self.assertTrue(stored_data.get("is_ai_improved"))
        self.assertEqual(stored_data.get("video_file_id"), "video_vid_999")
        self.assertEqual(stored_data.get("media_type"), "video")
        mock_preview.assert_called_once()

        # Повертаємо свій варіант
        with patch("bot.menus.developer._check_news_access", new_callable=AsyncMock, return_value=True):
            with patch("bot.menus.developer._show_news_preview", new_callable=AsyncMock) as mock_preview_revert:
                await dev_news_revert_orig_handler(callback, state)

        self.assertEqual(stored_data.get("text_content"), "Початковий простий текст")
        self.assertFalse(stored_data.get("is_ai_improved"))
        self.assertEqual(stored_data.get("video_file_id"), "video_vid_999")
        self.assertEqual(stored_data.get("media_type"), "video")
        mock_preview_revert.assert_called_once()


if __name__ == "__main__":
    unittest.main()
