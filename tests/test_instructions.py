from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import docx
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers import register_handlers
from bot.menus.developer import _admin_study_keyboard
from bot.menus.instructions import (
    InstructionStates,
    dev_inst_add_start_handler,
    dev_inst_delete_do_handler,
    dev_inst_download_template_handler,
    dev_inst_edit_file_start_handler,
    dev_inst_edit_title_start_handler,
    dev_inst_process_edit_file,
    dev_inst_process_edit_title,
    dev_inst_process_new_file,
    dev_inst_process_new_title,
    dev_inst_save_empty_handler,
    dev_inst_view_handler,
    dev_instructions_menu_handler,
    dev_instructions_page_handler,
)
from bot.services.instructions_docx import (
    _extract_text_from_docx_bytes_stdlib,
    _generate_instruction_template_docx_stdlib,
    extract_text_from_docx_bytes,
    generate_instruction_template_docx,
)
from bot.services.openai_ai import answer_remind_topic
from bot.services.semantic_search import hybrid_search_chunks, reset_semantic_search_index
from database.instructions import (
    create_instruction,
    delete_instruction,
    get_all_instructions,
    get_instruction_by_id,
    get_instructions_paginated,
    init_instructions_db,
    update_instruction_file,
    update_instruction_title,
)
from database.knowledge_chunks import get_materials_fingerprint
from database.materials import add_or_update_material, init_materials_db


def _make_docx_bytes(paragraphs: list[str], table_rows: list[tuple[str, str]] | None = None) -> bytes:
    doc = docx.Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    if table_rows:
        tbl = doc.add_table(rows=len(table_rows), cols=2)
        for idx, (c0, c1) in enumerate(table_rows):
            tbl.rows[idx].cells[0].text = c0
            tbl.rows[idx].cells[1].text = c1
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


class TestInstructionsFeature(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "test_users.db")
        self.files_dir = os.path.join(self.tmpdir.name, "instructions_files")
        os.makedirs(self.files_dir, exist_ok=True)
        await init_instructions_db(db_path=self.db_path)

    async def asyncTearDown(self):
        await reset_semantic_search_index()
        self.tmpdir.cleanup()

    def test_docx_template_and_extractor(self):
        tpl_stream = generate_instruction_template_docx("Касова дисципліна")
        tpl_bytes = tpl_stream.getvalue()
        extracted_tpl = extract_text_from_docx_bytes(tpl_bytes)
        self.assertIn("Касова дисципліна", extracted_tpl)
        self.assertIn("Ситуація / Проблема", extracted_tpl)

        custom_bytes = _make_docx_bytes(
            paragraphs=["Загальний регламент повернення товару.", "Крок 1: перевірте чек."],
            table_rows=[("Брак", "Скласти акт списання негайно")],
        )
        extracted = extract_text_from_docx_bytes(custom_bytes)
        self.assertIn("Загальний регламент повернення товару.", extracted)
        self.assertIn("Брак | Скласти акт списання негайно", extracted)

        with self.assertRaises(ValueError):
            extract_text_from_docx_bytes(b"not a valid docx")

    def test_docx_stdlib_fallback_and_cross_compatibility(self):
        stdlib_stream = _generate_instruction_template_docx_stdlib("Резервний режим")
        stdlib_bytes = stdlib_stream.getvalue()

        # Файл, згенерований без python-docx, коректно відкривається як через stdlib, так і через python-docx
        extracted_stdlib = _extract_text_from_docx_bytes_stdlib(stdlib_bytes)
        self.assertIn("Резервний режим", extracted_stdlib)
        self.assertIn("Ситуація / Проблема | Правильна дія співробітника", extracted_stdlib)

        extracted_via_docx = extract_text_from_docx_bytes(stdlib_bytes)
        self.assertIn("Резервний режим", extracted_via_docx)
        self.assertIn("Ситуація / Проблема | Правильна дія співробітника", extracted_via_docx)

        # Публічні функції прозоро працюють без встановленого python-docx
        with patch.dict(sys.modules, {"docx": None}):
            fallback_tpl = generate_instruction_template_docx("Без python-docx").getvalue()
            extracted = extract_text_from_docx_bytes(fallback_tpl)
            self.assertIn("Без python-docx", extracted)
            self.assertIn("Ситуація / Проблема | Правильна дія співробітника", extracted)

        with self.assertRaises(ValueError):
            _extract_text_from_docx_bytes_stdlib(b"not a valid docx")

    async def test_db_crud_and_pagination(self):
        for i in range(1, 11):
            await create_instruction(
                title=f"Інструкція #{i}",
                content=f"Вміст {i}",
                created_by=100,
                db_path=self.db_path,
            )

        items_p1, total, total_pages = await get_instructions_paginated(page=1, page_size=8, db_path=self.db_path)
        self.assertEqual(total, 10)
        self.assertEqual(total_pages, 2)
        self.assertEqual(len(items_p1), 8)

        items_p2, _, _ = await get_instructions_paginated(page=2, page_size=8, db_path=self.db_path)
        self.assertEqual(len(items_p2), 2)

        first_id = items_p1[0]["id"]
        await update_instruction_title(first_id, "Оновлена назва", db_path=self.db_path)
        updated = await get_instruction_by_id(first_id, db_path=self.db_path)
        self.assertEqual(updated["title"], "Оновлена назва")

        old_path = os.path.join(self.files_dir, "old.docx")
        new_path = os.path.join(self.files_dir, "new.docx")
        with open(old_path, "wb") as f:
            f.write(b"old")
        with open(new_path, "wb") as f:
            f.write(b"new")

        await update_instruction_file(first_id, "Текст 1", old_path, "tg1", "old.docx", db_path=self.db_path)
        await update_instruction_file(first_id, "Текст 2", new_path, "tg2", "new.docx", db_path=self.db_path)
        self.assertFalse(os.path.exists(old_path))
        self.assertTrue(os.path.exists(new_path))

        await delete_instruction(first_id, db_path=self.db_path)
        self.assertIsNone(await get_instruction_by_id(first_id, db_path=self.db_path))
        self.assertFalse(os.path.exists(new_path))

    def test_admin_only_visibility_in_study_keyboard(self):
        admin_kb = _admin_study_keyboard(is_observer=False, is_territorial=False)
        admin_cbs = [btn.callback_data for row in admin_kb.inline_keyboard for btn in row]
        self.assertIn("dev_instructions_menu", admin_cbs)

        obs_kb = _admin_study_keyboard(is_observer=True, is_territorial=False)
        obs_cbs = [btn.callback_data for row in obs_kb.inline_keyboard for btn in row]
        self.assertNotIn("dev_instructions_menu", obs_cbs)

        terr_kb = _admin_study_keyboard(is_observer=False, is_territorial=True)
        terr_cbs = [btn.callback_data for row in terr_kb.inline_keyboard for btn in row]
        self.assertNotIn("dev_instructions_menu", terr_cbs)

    async def test_admin_fsm_create_empty_and_with_docx_and_edit_flow(self):
        with (
            patch("database.instructions.DB_PATH", self.db_path),
            patch("database.instructions.INSTRUCTIONS_FILES_DIR", self.files_dir),
            patch("bot.menus.instructions.INSTRUCTIONS_FILES_DIR", self.files_dir),
            patch("bot.menus.instructions._check_instructions_admin", AsyncMock(return_value=True)),
            patch("bot.menus.instructions._schedule_ai_reindex") as mock_reindex,
        ):
            # 1. Start creation
            cb = AsyncMock()
            cb.from_user = MagicMock(id=777)
            cb.message = AsyncMock()
            cb.message.photo = None
            cb.message.video = None
            cb.message.document = None
            cb.answer = AsyncMock()
            state = AsyncMock()

            await dev_inst_add_start_handler(cb, state)
            state.set_state.assert_awaited_with(InstructionStates.waiting_new_title)

            # 2. Enter topic title
            msg_title = AsyncMock()
            msg_title.from_user = MagicMock(id=777)
            msg_title.text = "Правила закриття зміни"
            msg_title.answer = AsyncMock()
            await dev_inst_process_new_title(msg_title, state)
            state.set_state.assert_awaited_with(InstructionStates.waiting_new_file)
            _, kwargs = msg_title.answer.call_args
            cbs = [b.callback_data for row in kwargs["reply_markup"].inline_keyboard for b in row]
            self.assertIn("dev_inst_dl_template", cbs)
            self.assertIn("dev_inst_save_empty", cbs)

            # 3. Download template stays in waiting_new_file
            state.get_data.return_value = {"new_inst_title": "Правила закриття зміни"}
            await dev_inst_download_template_handler(cb, state)
            cb.message.answer_document.assert_awaited()

            # 4. Save empty instruction
            await dev_inst_save_empty_handler(cb, state)
            all_insts = await get_all_instructions(db_path=self.db_path)
            self.assertEqual(len(all_insts), 1)
            empty_id = all_insts[0]["id"]
            self.assertEqual(all_insts[0]["content"], "")

            # 5. View instruction card
            cb.data = f"dev_inst_view:{empty_id}:1"
            cb.message.answer.reset_mock()
            await dev_inst_view_handler(cb, state)
            cb.message.answer.assert_awaited()
            card_kb = cb.message.answer.call_args.kwargs["reply_markup"]
            card_btns = [b.callback_data for row in card_kb.inline_keyboard for b in row]
            self.assertIn(f"dev_inst_edit_file:{empty_id}:1", card_btns)
            self.assertIn(f"dev_inst_edit_title:{empty_id}:1", card_btns)

            # 6. Click "Змінити файл" sends template (+ current if exists) and waits for file
            cb.data = f"dev_inst_edit_file:{empty_id}:1"
            cb.message.answer_document.reset_mock()
            cb.message.answer.reset_mock()
            await dev_inst_edit_file_start_handler(cb, state)
            state.set_state.assert_awaited_with(InstructionStates.waiting_edit_file)
            cb.message.answer_document.assert_awaited()  # template sent

            # Reject plain text during waiting_edit_file
            state.get_data.return_value = {"edit_inst_id": empty_id, "edit_inst_page": 1}
            msg_bad = AsyncMock()
            msg_bad.from_user = MagicMock(id=777)
            msg_bad.text = "Це просто текст, не файл"
            msg_bad.document = None
            msg_bad.answer = AsyncMock()
            await dev_inst_process_edit_file(msg_bad, state)
            self.assertIn("файл інструкції", msg_bad.answer.call_args.args[0].lower())

            # Accept valid .docx upload during waiting_edit_file
            docx_payload = _make_docx_bytes(
                ["Після 22:00 касир зобов'язаний сформувати Z-звіт та інкасацію."]
            )

            async def _fake_download(file_path, destination):
                destination.write(docx_payload)

            msg_doc = AsyncMock()
            msg_doc.from_user = MagicMock(id=777)
            msg_doc.text = None
            msg_doc.document = MagicMock(file_id="tg_doc_123", file_name="zvit.docx", file_size=len(docx_payload))
            msg_doc.bot = MagicMock()
            msg_doc.bot.get_file = AsyncMock(return_value=MagicMock(file_path="docs/zvit.docx"))
            msg_doc.bot.download_file = AsyncMock(side_effect=_fake_download)
            msg_doc.answer = AsyncMock()
            msg_doc.answer_document = AsyncMock()

            await dev_inst_process_edit_file(msg_doc, state)
            updated = await get_instruction_by_id(empty_id, db_path=self.db_path)
            self.assertIn("Z-звіт", updated["content"])
            self.assertEqual(updated["telegram_file_id"], "tg_doc_123")
            self.assertTrue(os.path.exists(updated["file_path"]))
            mock_reindex.assert_called()

            # 7. Rename instruction
            cb.data = f"dev_inst_edit_title:{empty_id}:1"
            await dev_inst_edit_title_start_handler(cb, state)
            state.set_state.assert_awaited_with(InstructionStates.waiting_edit_title)

            msg_rename = AsyncMock()
            msg_rename.from_user = MagicMock(id=777)
            msg_rename.text = "Регламент Z-звіту"
            msg_rename.answer = AsyncMock()
            msg_rename.answer_document = AsyncMock()
            await dev_inst_process_edit_title(msg_rename, state)
            renamed = await get_instruction_by_id(empty_id, db_path=self.db_path)
            self.assertEqual(renamed["title"], "Регламент Z-звіту")

            # 8. Delete instruction
            cb.data = f"dev_inst_del_do:{empty_id}:1"
            await dev_inst_delete_do_handler(cb, state)
            self.assertIsNone(await get_instruction_by_id(empty_id, db_path=self.db_path))

            # 9. Create instruction directly with .docx file (Step 2)
            state.get_data.return_value = {"new_inst_title": "Пряме завантаження"}
            doc2_bytes = _make_docx_bytes(["Інструкція з санітарної обробки обладнання."])

            async def _fake_dl2(file_path, destination):
                destination.write(doc2_bytes)

            msg_new_doc = AsyncMock()
            msg_new_doc.from_user = MagicMock(id=777)
            msg_new_doc.text = None
            msg_new_doc.document = MagicMock(file_id="tg_new_1", file_name="sanitary.docx", file_size=len(doc2_bytes))
            msg_new_doc.bot = MagicMock()
            msg_new_doc.bot.get_file = AsyncMock(return_value=MagicMock(file_path="docs/sanitary.docx"))
            msg_new_doc.bot.download_file = AsyncMock(side_effect=_fake_dl2)
            msg_new_doc.answer = AsyncMock()
            msg_new_doc.answer_document = AsyncMock()

            await dev_inst_process_new_file(msg_new_doc, state)
            created_list = await get_all_instructions(db_path=self.db_path)
            self.assertEqual(len(created_list), 1)
            self.assertIn("санітарної обробки", created_list[0]["content"])

            # 10. Pagination UI test across 2 pages (add 9 more -> total 10)
            for idx in range(2, 11):
                await create_instruction(title=f"Інструкція {idx}", content="Текст", db_path=self.db_path)

            cb.data = "dev_instructions_menu"
            cb.message.edit_text.reset_mock()
            await dev_instructions_menu_handler(cb, state)
            p1_kb = cb.message.edit_text.call_args.kwargs["reply_markup"]
            p1_cbs = [b.callback_data for row in p1_kb.inline_keyboard for b in row]
            self.assertIn("dev_inst_add", p1_cbs)
            self.assertIn("dev_inst_page:2", p1_cbs)
            self.assertIn("dev_main_study", p1_cbs)

            cb.data = "dev_inst_page:2"
            cb.message.edit_text.reset_mock()
            await dev_instructions_page_handler(cb, state)
            p2_kb = cb.message.edit_text.call_args.kwargs["reply_markup"]
            p2_cbs = [b.callback_data for row in p2_kb.inline_keyboard for b in row]
            self.assertIn("dev_inst_page:1", p2_cbs)

        # 11. Verify handlers register without conflicts
        dp = Dispatcher(storage=MemoryStorage())
        register_handlers(dp)

    async def test_non_admin_blocked_from_instructions(self):
        with patch("bot.menus.instructions._check_instructions_admin", AsyncMock(return_value=False)):
            cb = AsyncMock()
            cb.from_user = MagicMock(id=555)
            cb.answer = AsyncMock()
            state = AsyncMock()
            await dev_instructions_menu_handler(cb, state)
            cb.answer.assert_awaited_with("⛔️ Доступ дозволено лише адміністраторам.", show_alert=True)

            cb.data = "dev_inst_page:2"
            await dev_instructions_page_handler(cb, state)
            cb.answer.assert_awaited_with("⛔️ Доступ дозволено лише адміністраторам.", show_alert=True)

    async def test_ai_search_indexes_and_retrieves_both_materials_and_instructions(self):
        with patch("database.materials.DB_PATH", self.db_path):
            await init_materials_db()
            await add_or_update_material(
                role="Пекар",
                day=1,
                content_type="text",
                title="День 1",
                content="Пекар перед початком зміни вмикає піч на 180 градусів та перевіряє тісто.",
                resource_url=None,
            )

        fp_before = await get_materials_fingerprint(self.db_path)
        await create_instruction(
            title="Аварійне відключення світла",
            content="При зникненні електроенергії генератор запускається протягом 3 хвилин, а тісто з печі перекладається у розстійку.",
            created_by=1,
            db_path=self.db_path,
        )
        fp_after = await get_materials_fingerprint(self.db_path)
        self.assertNotEqual(fp_before, fp_after)

        # Offline hybrid search as Пекар should find the instruction directly on Stage 1!
        with (
            patch("bot.services.openai_ai.is_openai_configured", return_value=False),
            patch("bot.services.openai_ai.get_client", return_value=None),
        ):
            res = await hybrid_search_chunks(
                query="Що робити коли зникла електроенергія та як запускати генератор?",
                role_filter="Пекар",
                scope="role",
                db_path=self.db_path,
                client=None,
            )
            self.assertTrue(res["has_relevant_match"])
            labels = [m["sources_label"] for m in res["results"]]
            self.assertTrue(any("Інструкція: Аварійне відключення світла" in lbl for lbl in labels))

            ans = await answer_remind_topic(
                question="Що робити при відключенні світла та генератор?",
                role_filter="Пекар",
                user_id=999,
                db_path=self.db_path,
                client=None,
            )
            self.assertEqual(ans["status"], "fallback_lexical")
            self.assertFalse(ans["used_network_fallback"])
            self.assertIn("Інструкція: Аварійне відключення світла", ans["text"])
            self.assertIn("генератор запускається протягом 3 хвилин", ans["text"])


if __name__ == "__main__":
    unittest.main()
