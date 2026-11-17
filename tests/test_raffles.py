import io
import os
import tempfile
import unittest
import zipfile
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import openpyxl
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers import register_handlers
from bot.keyboards import main_menu_keyboard
from bot.services.raffle_exporter import (
    dispatch_raffle_announcement_waves,
    generate_raffle_media_zips,
    generate_raffle_report_xlsx,
    sanitize_participant_filename,
    validate_raffle_text_submission,
)
from database.raffles import (
    add_raffle_submission,
    cleanup_expired_raffle_media,
    complete_raffle,
    create_raffle,
    delete_raffle,
    get_active_raffle,
    get_current_kyiv_dt,
    get_latest_raffle,
    get_raffle_by_id,
    get_raffle_history_last_60_days,
    get_raffle_submissions_detailed,
    init_raffles_db,
    is_user_eligible_for_active_raffle,
)


class TestRafflesSystem(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_raffles.db")
        self.managers_db_path = os.path.join(self.temp_dir.name, "test_managers.db")
        self.media_root = os.path.join(self.temp_dir.name, "raffles_media")
        os.makedirs(self.media_root, exist_ok=True)

        async with aiosqlite.connect(self.managers_db_path) as m_db:
            await m_db.execute(
                """
                CREATE TABLE IF NOT EXISTS managers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uid INTEGER UNIQUE,
                    process TEXT,
                    full_name TEXT,
                    username TEXT,
                    shops TEXT,
                    city TEXT,
                    status TEXT DEFAULT 'active'
                )
                """
            )
            await m_db.commit()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    role TEXT,
                    city TEXT,
                    shop TEXT,
                    status TEXT
                )
                """
            )
            await db.executemany(
                """
                INSERT INTO users (user_id, username, full_name, role, city, shop, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (1001, "ivan_p", "Іваненко Петро Олегович", "Пекар", "Хмельницький", "Булка #1", "Працівник"),
                    (1002, "ivan_p2", "Іваненко Петро Олегович", "Касир", "Хмельницький", "Булка #2", "Працівник"),
                    (1003, "maria_l", "Коваль Марія Іванівна", "Бариста", "Луцьк", "Булка #5", "Працівник"),
                    (1004, "oleh_s", "Сидоренко Олег Петрович", "Стажер", "Хмельницький", "Булка #1", "Стажер"),
                ],
            )
            await db.commit()

        await init_raffles_db(self.db_path)

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    def _future_deadline(self, days: int = 3) -> str:
        return (get_current_kyiv_dt() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    def _past_deadline(self, minutes: int = 10) -> str:
        return (get_current_kyiv_dt() - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")

    async def test_single_active_raffle_lifecycle_and_expiration(self):
        r1 = await create_raffle(
            title="Весняний розіграш",
            text="Умови акції",
            participation_type="button",
            selected_roles=["Працівник"],
            selected_city="Хмельницький",
            deadline=self._future_deadline(2),
            created_by=999,
            db_path=self.db_path,
        )
        active = await get_active_raffle(self.db_path)
        self.assertIsNotNone(active)
        self.assertEqual(active["id"], r1)

        with self.assertRaises(ValueError):
            await create_raffle(
                title="Другий активний",
                text="Заборонено",
                participation_type="text",
                selected_roles=["Працівник"],
                deadline=self._future_deadline(1),
                created_by=999,
                db_path=self.db_path,
            )

        stopped = await complete_raffle(r1, db_path=self.db_path)
        self.assertTrue(stopped)
        self.assertIsNone(await get_active_raffle(self.db_path))

        # Автоматичне завершення за дедлайном
        await create_raffle(
            title="Швидкий дедлайн",
            text="Завершиться сам",
            participation_type="button",
            selected_roles=["Працівник"],
            deadline=self._past_deadline(5),
            created_by=999,
            db_path=self.db_path,
        )
        self.assertIsNone(await get_active_raffle(self.db_path))

    async def test_eligibility_and_main_menu_button(self):
        with patch("database.managers.MANAGERS_DB_PATH", self.managers_db_path):
            rid = await create_raffle(
                title="Тільки Хмельницький Працівники",
                text="Умови",
                participation_type="button",
                selected_roles=["Працівник"],
                selected_city="Хмельницький",
                deadline=self._future_deadline(5),
                created_by=999,
                db_path=self.db_path,
            )

            self.assertIsNotNone(await is_user_eligible_for_active_raffle(1001, db_path=self.db_path))
            self.assertIsNone(await is_user_eligible_for_active_raffle(1003, db_path=self.db_path))  # інше місто
            self.assertIsNone(await is_user_eligible_for_active_raffle(1004, db_path=self.db_path))  # стажер

            kb_on = main_menu_keyboard(has_active_raffle=True)
            texts_on = [btn.text for row in kb_on.inline_keyboard for btn in row]
            self.assertIn("🎁 Розіграш", texts_on)

            await complete_raffle(rid, db_path=self.db_path)
            self.assertIsNone(await is_user_eligible_for_active_raffle(1001, db_path=self.db_path))

            kb_off = main_menu_keyboard(has_active_raffle=False)
            texts_off = [btn.text for row in kb_off.inline_keyboard for btn in row]
            self.assertNotIn("🎁 Розіграш", texts_off)

    def test_text_format_validators(self):
        # Free text / any
        ok, val, _ = validate_raffle_text_submission(" Привіт BULKA ", "text")
        self.assertTrue(ok)
        self.assertEqual(val, "Привіт BULKA")

        ok_empty, _, _ = validate_raffle_text_submission("   ", "formatted_text", "any")
        self.assertFalse(ok_empty)

        # Numeric
        ok_num1, val1, _ = validate_raffle_text_submission("42", "formatted_text", "numeric")
        self.assertTrue(ok_num1)
        self.assertEqual(val1, "42")

        ok_num2, val2, _ = validate_raffle_text_submission("-12.5", "formatted_text", "numeric")
        self.assertTrue(ok_num2)
        self.assertEqual(val2, "-12.5")

        bad_num, _, _ = validate_raffle_text_submission("12abc", "formatted_text", "numeric")
        self.assertFalse(bad_num)

        # Score
        ok_score, s_val, _ = validate_raffle_text_submission(" 2 : 1 ", "formatted_text", "score")
        self.assertTrue(ok_score)
        self.assertEqual(s_val, "2:1")

        bad_score, _, _ = validate_raffle_text_submission("2-1", "formatted_text", "score")
        self.assertFalse(bad_score)

    async def test_single_submission_and_xlsx_export(self):
        rid = await create_raffle(
            title="Вгадай рахунок",
            text="<b>Напишіть рахунок матчу!</b>",
            participation_type="formatted_text",
            text_format="score",
            selected_roles=["Працівник", "Стажер"],
            deadline=self._future_deadline(3),
            created_by=999,
            db_path=self.db_path,
        )

        ok1, _, sub_id = await add_raffle_submission(
            raffle_id=rid,
            user_id=1001,
            submission_text="2:1",
            db_path=self.db_path,
        )
        self.assertTrue(ok1)
        self.assertIsNotNone(sub_id)

        # Повторна участь заблокована
        ok2, msg2, _ = await add_raffle_submission(
            raffle_id=rid,
            user_id=1001,
            submission_text="3:0",
            db_path=self.db_path,
        )
        self.assertFalse(ok2)
        self.assertIn("вже берете участь", msg2)

        await add_raffle_submission(
            raffle_id=rid,
            user_id=1004,
            submission_text="0:0",
            db_path=self.db_path,
        )

        xlsx_stream = await generate_raffle_report_xlsx(rid, db_path=self.db_path)
        wb = openpyxl.load_workbook(xlsx_stream)
        self.assertIn("Загальний", wb.sheetnames)
        self.assertIn("Учасники", wb.sheetnames)

        ws_p = wb["Учасники"]
        rows = [[cell.value for cell in row] for row in ws_p.iter_rows(min_row=4, values_only=False)]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][1], "Іваненко Петро Олегович")
        self.assertEqual(rows[0][6], "2:1")
        self.assertEqual(rows[1][1], "Сидоренко Олег Петрович")
        self.assertEqual(rows[1][6], "0:0")

    async def test_media_zip_renaming_and_chunk_splitting(self):
        raffle_id = await create_raffle(
            title="Фото конкурс",
            text="Надішліть фото!",
            participation_type="media",
            selected_roles=["Працівник", "Стажер"],
            deadline=self._future_deadline(4),
            created_by=999,
            db_path=self.db_path,
        )

        raffle_dir = os.path.join(self.media_root, str(raffle_id))
        os.makedirs(raffle_dir, exist_ok=True)

        # 4 учасники, перші двоє мають однакове ПІБ для перевірки дедуплікації назв
        payloads = {}
        for uid, ext in [(1001, ".jpg"), (1002, ".jpg"), (1003, ".mp4"), (1004, ".png")]:
            data = os.urandom(420)  # не стискається deflate
            fpath = os.path.join(raffle_dir, f"raw_{uid}{ext}")
            with open(fpath, "wb") as f:
                f.write(data)
            payloads[uid] = data
            ok, _, _ = await add_raffle_submission(
                raffle_id=raffle_id,
                user_id=uid,
                media_type="video" if ext == ".mp4" else "photo",
                file_id=f"tg_{uid}",
                local_file_path=fpath,
                file_size=len(data),
                db_path=self.db_path,
            )
            self.assertTrue(ok)

        # Встановлюємо ліміт 950 байт -> 4 файли по ~420Б гарантовано розіб'ються на кілька ZIP
        zips = await generate_raffle_media_zips(raffle_id, max_zip_bytes=950, db_path=self.db_path)
        self.assertGreater(len(zips), 1)

        archived_files = {}
        for zname, zbytes in zips:
            self.assertIn(f"Розіграш_{raffle_id}_частина_", zname)
            self.assertLessEqual(len(zbytes), 950)
            with zipfile.ZipFile(io.BytesIO(zbytes), "r") as zf:
                for member in zf.namelist():
                    archived_files[member] = zf.read(member)

        self.assertEqual(len(archived_files), 4)
        self.assertIn("Іваненко_Петро_Олегович.jpg", archived_files)
        self.assertIn("Іваненко_Петро_Олегович_1002.jpg", archived_files)
        self.assertIn("Коваль_Марія_Іванівна.mp4", archived_files)
        self.assertIn("Сидоренко_Олег_Петрович.png", archived_files)

        self.assertEqual(archived_files["Іваненко_Петро_Олегович.jpg"], payloads[1001])
        self.assertEqual(archived_files["Іваненко_Петро_Олегович_1002.jpg"], payloads[1002])
        self.assertEqual(archived_files["Коваль_Марія_Іванівна.mp4"], payloads[1003])
        self.assertEqual(archived_files["Сидоренко_Олег_Петрович.png"], payloads[1004])

    async def test_60_day_history_and_media_cleanup_and_delete(self):
        # Свіжий розіграш (10 днів тому)
        rid_recent = await create_raffle(
            title="Нещодавній розіграш",
            text="Умови",
            participation_type="media",
            selected_roles=["Працівник"],
            deadline=self._future_deadline(1),
            created_by=999,
            db_path=self.db_path,
        )
        await complete_raffle(rid_recent, db_path=self.db_path)
        recent_dir = os.path.join(self.media_root, str(rid_recent))
        os.makedirs(recent_dir, exist_ok=True)
        recent_file = os.path.join(recent_dir, "recent.jpg")
        with open(recent_file, "wb") as f:
            f.write(b"recent-data")

        # Старий розіграш (65 днів тому)
        rid_old = await create_raffle(
            title="Архівний розіграш",
            text="Старі умови",
            participation_type="media",
            selected_roles=["Працівник"],
            deadline=self._future_deadline(1),
            created_by=999,
            db_path=self.db_path,
        )
        await complete_raffle(rid_old, db_path=self.db_path)
        old_dir = os.path.join(self.media_root, str(rid_old))
        os.makedirs(old_dir, exist_ok=True)
        old_file = os.path.join(old_dir, "old.jpg")
        with open(old_file, "wb") as f:
            f.write(b"old-data")

        old_date_str = (get_current_kyiv_dt() - timedelta(days=65)).strftime("%Y-%m-%d %H:%M:%S")
        recent_date_str = (get_current_kyiv_dt() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
        now_str = get_current_kyiv_dt().strftime("%Y-%m-%d %H:%M:%S")

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE raffles SET completed_at = ?, deadline = ?, created_at = ? WHERE id = ?",
                (old_date_str, old_date_str, old_date_str, rid_old),
            )
            await db.execute(
                "UPDATE raffles SET completed_at = ?, deadline = ?, created_at = ? WHERE id = ?",
                (recent_date_str, recent_date_str, recent_date_str, rid_recent),
            )
            await db.execute(
                """
                INSERT INTO raffle_submissions (raffle_id, user_id, submission_text, media_type, file_id, local_file_path, file_size, created_at)
                VALUES (?, ?, '', 'photo', 'f_old', ?, 8, ?)
                """,
                (rid_old, 1001, old_file, now_str),
            )
            await db.commit()

        history = await get_raffle_history_last_60_days(db_path=self.db_path)
        history_ids = [r["id"] for r in history]
        self.assertIn(rid_recent, history_ids)
        self.assertNotIn(rid_old, history_ids)

        latest = await get_latest_raffle(db_path=self.db_path)
        self.assertIsNotNone(latest)
        self.assertEqual(latest["id"], rid_recent)

        cleaned = await cleanup_expired_raffle_media(
            days=60, db_path=self.db_path, media_root=self.media_root
        )
        self.assertEqual(cleaned, 1)
        self.assertFalse(os.path.exists(old_dir))
        self.assertTrue(os.path.exists(recent_file))

        old_raffle = await get_raffle_by_id(rid_old, db_path=self.db_path)
        self.assertTrue(old_raffle["media_cleaned"])
        subs_old = await get_raffle_submissions_detailed(rid_old, db_path=self.db_path)
        self.assertIsNone(subs_old[0]["local_file_path"])

        # Ручне видалення свіжого розіграшу
        deleted = await delete_raffle(rid_recent, db_path=self.db_path, media_root=self.media_root)
        self.assertTrue(deleted)
        self.assertFalse(os.path.exists(recent_dir))
        self.assertIsNone(await get_raffle_by_id(rid_recent, db_path=self.db_path))

    async def test_announcement_waves_and_handler_registration(self):
        mock_bot = AsyncMock()
        raffle_dict = {
            "id": 7,
            "title": "Анонс",
            "text": "<b>Умови</b>",
            "participation_type": "button",
            "text_format": None,
            "deadline": "2026-12-01 18:00:00",
            "media_type": None,
            "photo_file_id": None,
            "video_file_id": None,
        }
        sent, failed = await dispatch_raffle_announcement_waves(
            bot=mock_bot,
            recipient_uids=[1001, 1002],
            raffle=raffle_dict,
            admin_chat_id=999,
            wave_size=1,
            wave_delay_sec=0.0,
        )
        self.assertEqual(sent, 2)
        self.assertEqual(failed, 0)
        # 2 повідомлення користувачам + 1 звіт адміну
        self.assertEqual(mock_bot.send_message.await_count, 3)

        dp = Dispatcher(storage=MemoryStorage())
        register_handlers(dp)
        self.assertEqual(sanitize_participant_filename("Іваненко Петро!", 5), "Іваненко_Петро")

    async def test_news_reaction_keyboard_with_extra_buttons(self):
        from aiogram.types import InlineKeyboardButton
        from bot.services.news_broadcaster import get_news_reaction_keyboard

        extra = [[InlineKeyboardButton(text="🎁 Взяти участь у розіграші", callback_data="user_raffle_menu")]]
        kb = get_news_reaction_keyboard(news_id=77, current_reaction="🔥", extra_buttons=extra)
        self.assertEqual(len(kb.inline_keyboard), 2)
        self.assertEqual(kb.inline_keyboard[0][0].callback_data, "user_raffle_menu")
        self.assertTrue(any("✅" in btn.text for btn in kb.inline_keyboard[1]))

    async def test_raffle_launch_creates_news_and_broadcasts_by_default(self):
        from bot.menus.raffles import dev_raffle_launch_handler

        callback = AsyncMock()
        callback.from_user = MagicMock(id=999)
        callback.message = MagicMock()
        callback.message.chat = MagicMock(id=999)
        callback.bot = MagicMock()
        callback.answer = AsyncMock()

        state = AsyncMock()
        # send_announcement не задано -> має бути True за замовчуванням
        state.get_data.return_value = {
            "title": "Тестовий розіграш",
            "text_content": "Умови розіграшу",
            "participation_type": "text",
            "selected_roles": ["Працівник"],
            "selected_city": "all",
            "deadline": "2026-12-01 18:00:00",
        }

        raffle_mock = {
            "id": 10,
            "title": "Тестовий розіграш",
            "text": "Умови розіграшу",
            "participation_type": "text",
            "text_format": None,
            "deadline": "2026-12-01 18:00:00",
            "media_type": None,
            "photo_file_id": None,
            "video_file_id": None,
        }

        with (
            patch("bot.menus.raffles._check_raffle_write_access", AsyncMock(return_value=True)),
            patch("bot.menus.raffles.create_raffle", AsyncMock(return_value=10)),
            patch("bot.menus.raffles.get_raffle_by_id", AsyncMock(return_value=raffle_mock)),
            patch("bot.menus.raffles.get_matching_news_recipients", AsyncMock(return_value=[101, 102])),
            patch("bot.menus.raffles.create_news", AsyncMock(return_value=55)) as mock_create_news,
            patch("bot.menus.raffles.start_news_wave_broadcast") as mock_broadcast,
            patch("bot.menus.raffles._render_admin_raffle_card", AsyncMock()),
        ):
            await dev_raffle_launch_handler(callback, state)

            mock_create_news.assert_awaited_once()
            _, news_kwargs = mock_create_news.call_args
            self.assertIn("СТАРТУВАВ НОВИЙ РОЗІГРАШ!", news_kwargs["text"])
            self.assertEqual(news_kwargs["total_recipients"], 2)

            mock_broadcast.assert_called_once()
            _, b_kwargs = mock_broadcast.call_args
            self.assertEqual(b_kwargs["news_id"], 55)
            self.assertEqual(b_kwargs["recipient_uids"], [101, 102])
            self.assertIsNotNone(b_kwargs["extra_buttons"])
            self.assertEqual(b_kwargs["extra_buttons"][0][0].callback_data, "user_raffle_menu")

    async def test_confirm_sub_rejects_empty_text_when_state_lost(self):
        from bot.menus.raffles import user_raffle_confirm_sub_handler

        callback = AsyncMock()
        callback.from_user = MagicMock(id=501, username="u501", full_name="Тест Юзер")
        callback.message = MagicMock()
        callback.answer = AsyncMock()

        state = AsyncMock()
        state.get_data.return_value = {"active_raffle_id": 10}  # draft_text втрачено

        raffle_mock = {
            "id": 10,
            "title": "Тестовий розіграш",
            "text": "Введіть число",
            "participation_type": "text",
            "text_format": None,
            "deadline": "2026-12-01 18:00:00",
        }

        with (
            patch("bot.menus.raffles.is_user_eligible_for_active_raffle", AsyncMock(return_value=raffle_mock)),
            patch("bot.menus.raffles.get_user_raffle_submission", AsyncMock(return_value=None)),
            patch("bot.menus.raffles.add_raffle_submission", AsyncMock()) as mock_add,
            patch("bot.menus.raffles._show_user_raffle_screen", AsyncMock()),
        ):
            await user_raffle_confirm_sub_handler(callback, state)
            mock_add.assert_not_awaited()
            callback.answer.assert_awaited_with(
                "⚠️ Текст відповіді не знайдено. Надішліть відповідь ще раз.",
                show_alert=True,
            )


if __name__ == "__main__":
    unittest.main()
