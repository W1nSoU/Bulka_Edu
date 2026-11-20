import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
from aiogram.exceptions import TelegramForbiddenError

import database.material_notifications as mn
import bot.services.wave_broadcaster as wb


class MaterialNotificationsFlowTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.users_db = os.path.join(self.tmpdir.name, "users.db")
        self.managers_db = os.path.join(self.tmpdir.name, "managers.db")
        self.notif_db = os.path.join(self.tmpdir.name, "material_notifications.db")

        self._orig_db_path = mn.DB_PATH
        self._orig_mgr_path = mn.MANAGERS_DB_PATH
        self._orig_notif_path = mn.NOTIFICATIONS_DB_PATH
        self._orig_notif_alias = mn.NOTIF_DB_PATH

        mn.DB_PATH = self.users_db
        mn.MANAGERS_DB_PATH = self.managers_db
        mn.NOTIFICATIONS_DB_PATH = self.notif_db
        mn.NOTIF_DB_PATH = self.notif_db
        wb._active_event_ids.clear()

        await mn.init_material_notifications_db()

        async with aiosqlite.connect(self.users_db) as db:
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
            await db.commit()

        async with aiosqlite.connect(self.managers_db) as db:
            await db.execute(
                """
                CREATE TABLE managers (
                    uid INTEGER PRIMARY KEY,
                    full_name TEXT,
                    username TEXT,
                    shops TEXT,
                    city TEXT,
                    process TEXT,
                    territorial_type TEXT,
                    status TEXT
                )
                """
            )
            await db.commit()

    async def asyncTearDown(self):
        mn.DB_PATH = self._orig_db_path
        mn.MANAGERS_DB_PATH = self._orig_mgr_path
        mn.NOTIFICATIONS_DB_PATH = self._orig_notif_path
        mn.NOTIF_DB_PATH = self._orig_notif_alias
        wb._active_event_ids.clear()
        self.tmpdir.cleanup()

    async def test_drafts_crud_and_isolation(self):
        items_1 = [{"text": "Стор 1", "change_type": "added", "day": 1}]
        items_2 = [{"text": "Стор 2", "photo": "photo_123", "change_type": "modified", "day": 2}]

        cnt1 = await mn.append_draft_items(100, "Продавець", items_1)
        self.assertEqual(cnt1, 1)

        cnt2 = await mn.append_draft_items(100, "Продавець", items_2)
        self.assertEqual(cnt2, 2)

        # Інша посада / інший адмін ізольовані
        self.assertEqual(await mn.get_draft_items(100, "Пекар"), [])
        self.assertEqual(await mn.get_draft_items(200, "Продавець"), [])

        loaded = await mn.get_draft_items(100, "Продавець")
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0]["change_type"], "added")
        self.assertEqual(loaded[1]["photo"], "photo_123")

        await mn.clear_draft(100, "Продавець")
        self.assertEqual(await mn.get_draft_items(100, "Продавець"), [])

    def test_normalization_formatting_and_limits(self):
        raw_pages = [
            "Стара текстова сторінка",
            {"text": "Нова сторінка", "photo": "file_photo_1", "change_type": "added", "day": 2, "comment": "Додали стандарти"},
            {"text": "❌ ВИДАЛЕНО Старий пункт", "change_type": "deleted", "day": 3},
            {"text": "x" * 1500, "photo": "file_photo_2", "change_type": "modified", "day": 1},
        ]
        norm = wb.normalize_change_pages(raw_pages, default_day=1)
        self.assertEqual(len(norm), 4)
        self.assertEqual(norm[0]["text"], "Стара текстова сторінка")
        self.assertEqual(norm[1]["change_type"], "added")
        self.assertEqual(norm[2]["change_type"], "deleted")

        summary = wb.summarize_change_pages(norm)
        self.assertIn("+1 дод.", summary)
        self.assertIn("1 зм.", summary)
        self.assertIn("1 вид.", summary)

        # Comment appears only on page 0
        p0_with_comment = dict(norm[1])
        txt0 = wb.format_material_notification_text("Продавець", 1, p0_with_comment, 0, 4, is_media=True)
        self.assertIn("Коментар:", txt0)
        self.assertIn("🆕 <b>Додано</b>", txt0)

        txt1 = wb.format_material_notification_text("Продавець", 1, p0_with_comment, 1, 4, is_media=True)
        self.assertNotIn("Коментар:", txt1)

        # Long media caption safely truncated <= 1024
        long_caption = wb.format_material_notification_text("Продавець", 1, norm[3], 3, 4, is_media=True)
        self.assertLessEqual(len(long_caption), 1024)

    def test_keyboard_ack_unlocks_only_on_last_page(self):
        # 3-page event: page 0 and page 1 must NOT show ack button
        kb0 = wb.build_material_notification_keyboard(10, 99, 0, 3, is_acknowledged=False)
        flat0 = [btn.callback_data for row in kb0.inline_keyboard for btn in row]
        self.assertIn("mat_ch_pag:10:99:1", flat0)
        self.assertFalse(any(cb.startswith("mat_ch_ack:") for cb in flat0))

        kb1 = wb.build_material_notification_keyboard(10, 99, 1, 3, is_acknowledged=False)
        flat1 = [btn.callback_data for row in kb1.inline_keyboard for btn in row]
        self.assertIn("mat_ch_pag:10:99:0", flat1)
        self.assertIn("mat_ch_pag:10:99:2", flat1)
        self.assertFalse(any(cb.startswith("mat_ch_ack:") for cb in flat1))

        # Last page unlocks ack button
        kb2 = wb.build_material_notification_keyboard(10, 99, 2, 3, is_acknowledged=False)
        flat2 = [btn.callback_data for row in kb2.inline_keyboard for btn in row]
        self.assertIn("mat_ch_ack:10:99", flat2)

        # Acknowledged state switches label and removes ack callback
        kb2_ack = wb.build_material_notification_keyboard(10, 99, 2, 3, is_acknowledged=True)
        texts2_ack = [btn.text for row in kb2_ack.inline_keyboard for btn in row]
        self.assertIn("✅ Ви ознайомлені зі змінами", texts2_ack)

        # 1-page event shows ack immediately without pagination arrows
        kb_single = wb.build_material_notification_keyboard(10, 99, 0, 1, is_acknowledged=False)
        self.assertEqual(len(kb_single.inline_keyboard), 1)
        self.assertEqual(kb_single.inline_keyboard[0][0].callback_data, "mat_ch_ack:10:99")

    async def test_recipients_waves_40_per_4min_and_late_ack(self):
        # Verify wave constants match Danik's spec: 40 users / 4 min (240s)
        self.assertEqual(mn.WAVE_BATCH_SIZE, 40)
        self.assertEqual(wb.WAVE_INTERVAL_SECONDS, 240)

        # Seed 45 users of role "Продавець" (35 workers, 10 interns)
        async with aiosqlite.connect(self.users_db) as db:
            for i in range(1, 46):
                status = "Працівник" if i <= 35 else "Стажер"
                await db.execute(
                    "INSERT INTO users (user_id, full_name, username, role, city, shop, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (1000 + i, f"User {i}", f"u{i}", "Продавець", "Київ", "b-1", status),
                )
            await db.commit()

        # Seed 1 manager, 1 territorial ТЗ, 1 territorial ВВ (excluded), 1 observer (excluded, even if also in users!)
        async with aiosqlite.connect(self.managers_db) as db:
            await db.execute(
                "INSERT INTO managers VALUES (2001, 'Mgr 1', 'm1', '[\"b-1\"]', 'Київ', 'Керівник', '', 'active')"
            )
            await db.execute(
                "INSERT INTO managers VALUES (2002, 'Terr TZ', 't1', '', 'Київ', 'Територіал', 'ТЗ', 'active')"
            )
            await db.execute(
                "INSERT INTO managers VALUES (2003, 'Terr VV', 't2', '', 'Київ', 'Територіал', 'ВВ', 'active')"
            )
            await db.execute(
                "INSERT INTO managers VALUES (1001, 'Observer', 'obs', '', 'Київ', 'Наглядач', '', 'active')"
            )
            await db.commit()

        with patch("database.positions.get_position_direction", new=AsyncMock(return_value="ТЗ")):
            stats = await mn.get_recipients_preview_stats("Продавець")
            # 45 users - 1 excluded observer (1001) + 1 manager (2001) + 1 territorial ТЗ (2002) = 46
            self.assertEqual(stats["total"], 46)
            self.assertEqual(stats["workers"], 34)
            self.assertEqual(stats["interns"], 10)
            self.assertEqual(stats["managers"], 1)
            self.assertEqual(stats["territorials"], 1)
            self.assertEqual(stats["waves"], 2)

            event_id = await mn.create_material_change_event(
                "Продавець",
                1,
                "text",
                "Авто: +1 дод.",
                [{"text": "Прийом яєць", "change_type": "added", "day": 1}],
            )
            created = await mn.create_recipients_for_event(event_id, "Продавець")
            self.assertEqual(created, 46)

        w1 = await mn.get_pending_wave_recipients(wave_number=1, event_id=event_id)
        w2 = await mn.get_pending_wave_recipients(wave_number=2, event_id=event_id)
        self.assertEqual(len(w1), 40)
        self.assertEqual(len(w2), 6)
        self.assertEqual(await mn.get_events_with_pending_recipients(), [event_id])

        # Mark recipient 1002 sent recently -> ack should be on time (is_late=False)
        rec_on_time = await mn.get_recipient_by_user_and_event(event_id, 1002)
        await mn.mark_recipient_sent(rec_on_time["id"], message_id=555)
        ok, is_late = await mn.mark_recipient_acknowledged(event_id, 1002)
        self.assertTrue(ok)
        self.assertFalse(is_late)

        # Mark recipient 1003 sent 80 hours ago -> ack should be late (is_late=True)
        rec_late = await mn.get_recipient_by_user_and_event(event_id, 1003)
        old_ts = (datetime.utcnow() - timedelta(hours=80)).strftime("%Y-%m-%d %H:%M:%S")
        async with aiosqlite.connect(self.notif_db) as db:
            await db.execute(
                "UPDATE material_change_recipients SET status='sent', sent_at=? WHERE id=?",
                (old_ts, rec_late["id"]),
            )
            await db.commit()
        ok_late, is_late_flag = await mn.mark_recipient_acknowledged(event_id, 1003)
        self.assertTrue(ok_late)
        self.assertTrue(is_late_flag)

    async def test_wave_dispatch_media_and_resume(self):
        event_id = await mn.create_material_change_event(
            "Продавець",
            1,
            "mixed",
            "Тест медіа",
            [
                {"text": "Фото сторінка", "photo": "photo_id_1", "change_type": "added", "day": 1},
                {"text": "Текстова сторінка", "change_type": "modified", "day": 1},
            ],
        )
        async with aiosqlite.connect(self.notif_db) as db:
            await db.execute(
                "INSERT INTO material_change_recipients (event_id, user_id, role_type, shop, city, wave_number, status) VALUES (?, ?, 'працівник', 'b-1', 'Київ', 1, 'pending')",
                (event_id, 5001),
            )
            await db.execute(
                "INSERT INTO material_change_recipients (event_id, user_id, role_type, shop, city, wave_number, status) VALUES (?, ?, 'працівник', 'b-1', 'Київ', 1, 'pending')",
                (event_id, 5002),
            )
            await db.commit()

        fake_bot = MagicMock()
        sent_msg = MagicMock(message_id=777)

        async def _send_photo(**kwargs):
            if kwargs["chat_id"] == 5002:
                raise TelegramForbiddenError(method=MagicMock(), message="Forbidden: bot was blocked by the user")
            return sent_msg

        fake_bot.send_photo = AsyncMock(side_effect=_send_photo)

        with patch.object(wb, "PER_MESSAGE_DELAY_SECONDS", 0):
            await wb.dispatch_event_waves(fake_bot, event_id)

        self.assertEqual(fake_bot.send_photo.await_count, 2)
        r1 = await mn.get_recipient_by_user_and_event(event_id, 5001)
        r2 = await mn.get_recipient_by_user_and_event(event_id, 5002)
        self.assertEqual(r1["status"], "sent")
        self.assertEqual(r1["message_id"], 777)
        self.assertEqual(r2["status"], "failed")

        ev = await mn.get_event_by_id(event_id)
        self.assertEqual(ev["status"], "completed")
        self.assertEqual(await mn.get_events_with_pending_recipients(), [])

    async def test_edit_or_replace_switches_text_and_media_cleanly(self):
        pages = [
            {"text": "Текстова 1", "change_type": "added", "day": 1},
            {"text": "Фото 2", "photo": "photo_xyz", "change_type": "modified", "day": 1},
        ]
        kb = wb.build_material_notification_keyboard(1, 1, 1, 2)

        # Simulate switching from text message -> photo page
        msg = MagicMock()
        msg.photo = None
        msg.video = None
        msg.document = None
        msg.chat.id = 999
        msg.delete = AsyncMock()
        new_sent = MagicMock(message_id=888)
        msg.bot.send_photo = AsyncMock(return_value=new_sent)

        res_msg, replaced = await wb.edit_or_replace_change_page(
            msg, role="Продавець", default_day=1, pages=pages, page_idx=1, reply_markup=kb
        )
        self.assertTrue(replaced)
        self.assertEqual(res_msg.message_id, 888)
        msg.bot.send_photo.assert_awaited_once()
        msg.delete.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
