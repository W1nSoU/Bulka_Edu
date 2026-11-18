from __future__ import annotations

import io
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import docx
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers import process_keyword_search, register_handlers
from bot.menus.developer import _admin_study_keyboard
from bot.menus.instructions import (
    InstructionStates,
    dev_inst_add_start_handler,
    dev_inst_back_to_step2_handler,
    dev_inst_delete_do_handler,
    dev_inst_download_template_handler,
    dev_inst_edit_file_start_handler,
    dev_inst_edit_orig_start_handler,
    dev_inst_edit_title_start_handler,
    dev_inst_process_edit_file,
    dev_inst_process_edit_orig_file,
    dev_inst_process_edit_title,
    dev_inst_process_new_file,
    dev_inst_process_new_original_file,
    dev_inst_process_new_title,
    dev_inst_replace_menu_handler,
    dev_inst_save_empty_handler,
    dev_inst_skip_original_handler,
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
from bot.services.openai_ai import _extract_used_instruction_ids, answer_remind_topic
from bot.services.semantic_search import hybrid_search_chunks, reset_semantic_search_index
from database.instructions import (
    create_instruction,
    delete_instruction,
    get_all_instructions,
    get_instruction_by_id,
    get_instructions_paginated,
    get_instructions_with_original_by_ids,
    init_instructions_db,
    update_instruction_file,
    update_instruction_original_file,
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

    async def test_db_original_migration_and_crud(self):
        legacy_db = os.path.join(self.tmpdir.name, "legacy.db")
        conn = sqlite3.connect(legacy_db)
        conn.execute(
            """
            CREATE TABLE instructions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT DEFAULT '',
                file_path TEXT DEFAULT NULL,
                telegram_file_id TEXT DEFAULT NULL,
                file_name TEXT DEFAULT NULL,
                created_by INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute("INSERT INTO instructions (title, content) VALUES ('Стара інструкція', 'Текст')")
        conn.commit()
        conn.close()

        await init_instructions_db(db_path=legacy_db)
        conn = sqlite3.connect(legacy_db)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(instructions)").fetchall()}
        conn.close()
        self.assertIn("original_file_path", cols)
        self.assertIn("original_telegram_file_id", cols)
        self.assertIn("original_file_name", cols)

        ai_path = os.path.join(self.files_dir, "ai_1.docx")
        orig_old = os.path.join(self.files_dir, "orig_old.pdf")
        orig_new = os.path.join(self.files_dir, "orig_new.pdf")
        for p in (ai_path, orig_old, orig_new):
            with open(p, "wb") as f:
                f.write(b"data")

        id_with_orig = await create_instruction(
            title="З оригіналом",
            content="Текст для ШІ",
            file_path=ai_path,
            telegram_file_id="tg_ai_1",
            file_name="ai_1.docx",
            original_file_path=orig_old,
            original_telegram_file_id="tg_orig_old",
            original_file_name="orig_old.pdf",
            db_path=legacy_db,
        )
        id_without_orig = await create_instruction(
            title="Без оригіналу",
            content="Лише текст",
            db_path=legacy_db,
        )

        ok_orig = await update_instruction_original_file(
            id_with_orig, orig_new, "tg_orig_new", "orig_new.pdf", db_path=legacy_db
        )
        self.assertTrue(ok_orig)
        self.assertFalse(os.path.exists(orig_old))
        self.assertTrue(os.path.exists(orig_new))

        matched = await get_instructions_with_original_by_ids(
            [id_without_orig, id_with_orig, id_with_orig, 99999],
            db_path=legacy_db,
        )
        self.assertEqual([m["id"] for m in matched], [id_with_orig])
        self.assertEqual(matched[0]["original_file_name"], "orig_new.pdf")

        await delete_instruction(id_with_orig, db_path=legacy_db)
        self.assertFalse(os.path.exists(ai_path))
        self.assertFalse(os.path.exists(orig_new))

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
            state_data = {}

            async def _update_data(**kwargs):
                state_data.update(kwargs)

            async def _get_data():
                return dict(state_data)

            async def _clear():
                state_data.clear()

            # 1. Start creation (Step 1/3)
            cb = AsyncMock()
            cb.from_user = MagicMock(id=777)
            cb.message = AsyncMock()
            cb.message.photo = None
            cb.message.video = None
            cb.message.document = None
            cb.answer = AsyncMock()
            state = AsyncMock()
            state.update_data.side_effect = _update_data
            state.get_data.side_effect = _get_data
            state.clear.side_effect = _clear

            await dev_inst_add_start_handler(cb, state)
            state.set_state.assert_awaited_with(InstructionStates.waiting_new_title)

            # 2. Enter topic title -> Step 2/3 (waiting_new_file)
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
            await dev_inst_download_template_handler(cb, state)
            cb.message.answer_document.assert_awaited()

            # 4. Skip AI file -> Step 3/3 (waiting_new_original_file), then skip original -> empty instruction
            await dev_inst_save_empty_handler(cb, state)
            state.set_state.assert_awaited_with(InstructionStates.waiting_new_original_file)
            await dev_inst_skip_original_handler(cb, state)

            all_insts = await get_all_instructions(db_path=self.db_path)
            self.assertEqual(len(all_insts), 1)
            empty_id = all_insts[0]["id"]
            self.assertEqual(all_insts[0]["content"], "")
            self.assertIsNone(all_insts[0]["original_file_path"])

            # 5. View instruction card -> button "🔄 Замінити файл" opens replace submenu
            cb.data = f"dev_inst_view:{empty_id}:1"
            cb.message.answer.reset_mock()
            await dev_inst_view_handler(cb, state)
            cb.message.answer.assert_awaited()
            card_kb = cb.message.answer.call_args.kwargs["reply_markup"]
            card_btns = [b.callback_data for row in card_kb.inline_keyboard for b in row]
            self.assertIn(f"dev_inst_replace_menu:{empty_id}:1", card_btns)
            self.assertIn(f"dev_inst_edit_title:{empty_id}:1", card_btns)

            cb.data = f"dev_inst_replace_menu:{empty_id}:1"
            cb.message.answer.reset_mock()
            cb.message.edit_text.reset_mock()
            await dev_inst_replace_menu_handler(cb, state)
            rep_kb = cb.message.edit_text.call_args.kwargs["reply_markup"]
            rep_btns = [b.callback_data for row in rep_kb.inline_keyboard for b in row]
            self.assertIn(f"dev_inst_edit_file:{empty_id}:1", rep_btns)
            self.assertIn(f"dev_inst_edit_orig:{empty_id}:1", rep_btns)

            # 6. Click "Замінити інструкцію" sends template (+ current if exists) and waits for .docx
            cb.data = f"dev_inst_edit_file:{empty_id}:1"
            cb.message.answer_document.reset_mock()
            cb.message.answer.reset_mock()
            await dev_inst_edit_file_start_handler(cb, state)
            state.set_state.assert_awaited_with(InstructionStates.waiting_edit_file)
            cb.message.answer_document.assert_awaited()  # template sent

            # Reject plain text during waiting_edit_file
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

            # 6b. Replace original file ("Замінити оригінал інструкції") with .pdf
            cb.data = f"dev_inst_edit_orig:{empty_id}:1"
            cb.message.answer.reset_mock()
            cb.message.answer_document.reset_mock()
            await dev_inst_edit_orig_start_handler(cb, state)
            state.set_state.assert_awaited_with(InstructionStates.waiting_edit_original_file)

            pdf_payload = b"%PDF-1.4 fake full original document"

            async def _fake_pdf_dl(file_path, destination):
                destination.write(pdf_payload)

            msg_orig = AsyncMock()
            msg_orig.from_user = MagicMock(id=777)
            msg_orig.text = None
            msg_orig.document = MagicMock(file_id="tg_pdf_456", file_name="zvit_original.pdf", file_size=len(pdf_payload))
            msg_orig.bot = MagicMock()
            msg_orig.bot.get_file = AsyncMock(return_value=MagicMock(file_path="docs/zvit_original.pdf"))
            msg_orig.bot.download_file = AsyncMock(side_effect=_fake_pdf_dl)
            msg_orig.answer = AsyncMock()
            msg_orig.answer_document = AsyncMock()

            await dev_inst_process_edit_orig_file(msg_orig, state)
            with_orig = await get_instruction_by_id(empty_id, db_path=self.db_path)
            self.assertEqual(with_orig["original_telegram_file_id"], "tg_pdf_456")
            self.assertEqual(with_orig["original_file_name"], "zvit_original.pdf")
            self.assertTrue(os.path.exists(with_orig["original_file_path"]))
            # Card sent 2 files sequentially (1: AI docx, 2: PDF original with card keyboard)
            self.assertEqual(msg_orig.answer_document.await_count, 2)
            second_kb = msg_orig.answer_document.call_args_list[1].kwargs["reply_markup"]
            second_btns = [b.callback_data for row in second_kb.inline_keyboard for b in row]
            self.assertIn(f"dev_inst_replace_menu:{empty_id}:1", second_btns)

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

            # 8. Delete instruction removes DB row and both files on disk
            old_ai_path = renamed["file_path"]
            old_orig_path = renamed["original_file_path"]
            cb.data = f"dev_inst_del_do:{empty_id}:1"
            await dev_inst_delete_do_handler(cb, state)
            self.assertIsNone(await get_instruction_by_id(empty_id, db_path=self.db_path))
            self.assertFalse(os.path.exists(old_ai_path))
            self.assertFalse(os.path.exists(old_orig_path))

            # 9. Full 3-step creation: Step 1 Title -> Step 2 .docx -> Step 3 original .pdf (and test Back->Step2 cleanup)
            state_data.clear()
            state_data["new_inst_title"] = "Пряме завантаження"
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
            state.set_state.assert_awaited_with(InstructionStates.waiting_new_original_file)
            self.assertEqual(len(await get_all_instructions(db_path=self.db_path)), 0)
            temp_ai_path = state_data["new_inst_file_path"]
            self.assertTrue(os.path.exists(temp_ai_path))

            # Test back from Step 3 to Step 2 cleans temp file and keeps title
            await dev_inst_back_to_step2_handler(cb, state)
            state.set_state.assert_awaited_with(InstructionStates.waiting_new_file)
            self.assertFalse(os.path.exists(temp_ai_path))

            # Re-upload AI .docx on Step 2, then upload PDF original on Step 3
            await dev_inst_process_new_file(msg_new_doc, state)
            msg_new_orig = AsyncMock()
            msg_new_orig.from_user = MagicMock(id=777)
            msg_new_orig.text = None
            msg_new_orig.document = MagicMock(file_id="tg_orig_new_1", file_name="sanitary_orig.pdf", file_size=len(pdf_payload))
            msg_new_orig.bot = MagicMock()
            msg_new_orig.bot.get_file = AsyncMock(return_value=MagicMock(file_path="docs/sanitary_orig.pdf"))
            msg_new_orig.bot.download_file = AsyncMock(side_effect=_fake_pdf_dl)
            msg_new_orig.answer = AsyncMock()
            msg_new_orig.answer_document = AsyncMock()

            await dev_inst_process_new_original_file(msg_new_orig, state)
            created_list = await get_all_instructions(db_path=self.db_path)
            self.assertEqual(len(created_list), 1)
            self.assertIn("санітарної обробки", created_list[0]["content"])
            self.assertEqual(created_list[0]["original_file_name"], "sanitary_orig.pdf")
            self.assertTrue(os.path.exists(created_list[0]["original_file_path"]))
            self.assertEqual(msg_new_orig.answer_document.await_count, 2)

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
        orig_pdf_path = os.path.join(self.files_dir, "blackout_original.pdf")
        with open(orig_pdf_path, "wb") as f:
            f.write(b"%PDF-1.4 blackout full")

        inst_id = await create_instruction(
            title="Аварійне відключення світла",
            content="При зникненні електроенергії генератор запускається протягом 3 хвилин, а тісто з печі перекладається у розстійку.",
            original_file_path=orig_pdf_path,
            original_telegram_file_id="tg_orig_blackout",
            original_file_name="Аварійне_відключення.pdf",
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
            self.assertEqual(ans["used_instruction_ids"], [inst_id])

        # Перевіряємо логування instruction_chunks/instruction_sources та інструкції цитування у GPT-промпті
        captured_messages = []

        async def _fake_create(**kwargs):
            captured_messages.append(kwargs["messages"])
            msg_obj = MagicMock()
            msg_obj.content = "Діяти згідно з [Інструкція: Аварійне відключення світла]."
            choice = MagicMock()
            choice.message = msg_obj
            resp = MagicMock()
            resp.choices = [choice]
            resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)
            return resp

        fake_client = MagicMock()
        fake_client.chat.completions.create = AsyncMock(side_effect=_fake_create)
        fake_client.embeddings.create = AsyncMock(return_value=MagicMock(data=[]))

        with (
            patch("bot.services.openai_ai.is_openai_configured", return_value=True),
            patch("bot.services.openai_ai.logger") as mock_ai_logger,
        ):
            gpt_ans = await answer_remind_topic(
                question="Що робити при відключенні світла та генератор?",
                role_filter=None,
                user_id=1001,
                db_path=self.db_path,
                client=fake_client,
            )
            self.assertEqual(gpt_ans["status"], "ok")
            self.assertEqual(gpt_ans["used_instruction_ids"], [inst_id])
            self.assertIn("Інструкція: Аварійне відключення світла", gpt_ans["text"])
            self.assertTrue(captured_messages)
            sys_prompt = captured_messages[0][0]["content"]
            self.assertIn("[Інструкція: Назва теми]", sys_prompt)
            logged_lines = [call.args[0] for call in mock_ai_logger.info.call_args_list if call.args]
            self.assertTrue(
                any(
                    "instruction_chunks=1" in line
                    and "Інструкція: Аварійне відключення світла" in line
                    for line in logged_lines
                ),
                f"Expected instruction telemetry in GPT logs, got: {logged_lines}",
            )

    def test_extract_used_instruction_ids_rules(self):
        fake_results = [
            {
                "sources": [
                    {"material_id": -10, "day": 0, "title": "Інструкція: Касова дисципліна"},
                ]
            },
            {
                "sources": [
                    {"material_id": -20, "day": 0, "title": "Інструкція: Списання товару"},
                    {"material_id": 5, "day": 2, "title": "День 2"},
                ]
            },
        ]
        # 1. Explicit citation selects only cited instruction
        self.assertEqual(
            _extract_used_instruction_ids(fake_results, "Використовуйте правила [Інструкція: Списання товару]."),
            [20],
        )
        # 2. No explicit citation -> falls back to top-1 if top-1 is instruction
        self.assertEqual(
            _extract_used_instruction_ids(fake_results, "Потрібно перевіряти чек."),
            [10],
        )
        # 3. No explicit citation and top-1 is regular material -> []
        mat_first_results = [fake_results[1], fake_results[0]]
        mat_first_only = [{"sources": [{"material_id": 5, "day": 2, "title": "День 2"}]}, fake_results[0]]
        self.assertEqual(_extract_used_instruction_ids(mat_first_only, "Без згадки"), [])
        self.assertEqual(len(_extract_used_instruction_ids(mat_first_results, "Текст без цитати")), 1)

    async def test_remind_topic_sends_original_document_for_used_instructions(self):
        orig_pdf_path = os.path.join(self.files_dir, "transfer_full.pdf")
        with open(orig_pdf_path, "wb") as f:
            f.write(b"%PDF-1.4 transfer instructions")

        inst_id = await create_instruction(
            title="Переміщення товару",
            content="Переміщення оформлюється через ТЗД.",
            original_file_path=orig_pdf_path,
            original_telegram_file_id="tg_orig_transfer",
            original_file_name="Переміщення_товару.pdf",
            created_by=1,
            db_path=self.db_path,
        )

        thinking_msg = AsyncMock()
        thinking_msg.delete = AsyncMock()
        final_text_msg = AsyncMock()

        msg = AsyncMock()
        msg.from_user = MagicMock(id=777)
        msg.text = "Як оформити переміщення?"
        msg.answer = AsyncMock(side_effect=[thinking_msg, final_text_msg])
        msg.answer_document = AsyncMock()

        state = AsyncMock()
        state.get_data = AsyncMock(return_value={"mode": "dev_test", "role": None})
        state.clear = AsyncMock()

        with (
            patch("database.instructions.DB_PATH", self.db_path),
            patch("bot.handlers.is_developer_user", AsyncMock(return_value=True)),
            patch(
                "bot.handlers.answer_remind_topic",
                AsyncMock(
                    return_value={
                        "status": "ok",
                        "text": "Оформлюйте переміщення через ТЗД [Інструкція: Переміщення товару].",
                        "used_network_fallback": False,
                        "used_gpt": True,
                        "matches": [],
                        "used_instruction_ids": [inst_id],
                    }
                ),
            ),
        ):
            await process_keyword_search(msg, state)

        # Text answer sent without keyboard, original document sent with keyboard attached
        self.assertEqual(msg.answer.await_count, 2)
        text_call_kwargs = msg.answer.call_args_list[1].kwargs
        self.assertIsNone(text_call_kwargs.get("reply_markup"))
        self.assertIn("Оформлюйте переміщення", msg.answer.call_args_list[1].args[0])

        msg.answer_document.assert_awaited_once()
        doc_kwargs = msg.answer_document.call_args.kwargs
        self.assertIn("Оригінал інструкції", doc_kwargs["caption"])
        self.assertIn("Переміщення товару", doc_kwargs["caption"])
        self.assertIsNotNone(doc_kwargs.get("reply_markup"))
        cbs = [b.callback_data for row in doc_kwargs["reply_markup"].inline_keyboard for b in row]
        self.assertIn("remind_topic_global", cbs)
        self.assertIn("main_menu", cbs)

    async def test_typo_query_prioritizes_matching_instruction_over_incidental_materials(self):
        with patch("database.materials.DB_PATH", self.db_path):
            await init_materials_db()
            await add_or_update_material(
                role="Старший продавець",
                day=4,
                content_type="text",
                title="День 4",
                content=(
                    "Увечері товар із транзитної зони переноситься на склад СНТ. "
                    "Також проводиться переміщення простроченого товару у списання."
                ),
                resource_url=None,
            )

        orig_pdf_path = os.path.join(self.files_dir, "transfer_typo.pdf")
        with open(orig_pdf_path, "wb") as f:
            f.write(b"%PDF-1.4 transfer")

        inst_id = await create_instruction(
            title="Інструкція з переміщення товару",
            content="Переміщення товару між ТТ та РЦ оформлюється через ТЗД у розділі Документи.",
            original_file_path=orig_pdf_path,
            original_telegram_file_id="tg_typo_transfer",
            original_file_name="Інструкція_переміщення.pdf",
            created_by=1,
            db_path=self.db_path,
        )

        # Офлайн-перевірка з одруківкою «Перміщення товару» (пропущено 'е')
        with (
            patch("bot.services.openai_ai.is_openai_configured", return_value=False),
            patch("bot.services.openai_ai.get_client", return_value=None),
        ):
            res = await hybrid_search_chunks(
                query="Перміщення товару",
                role_filter=None,
                scope="global",
                db_path=self.db_path,
                client=None,
            )
            self.assertTrue(res["has_relevant_match"])
            self.assertGreaterEqual(len(res["results"]), 1)
            self.assertIn("Інструкція: Інструкція з переміщення товару", res["results"][0]["sources_label"])

            ans = await answer_remind_topic(
                question="Перміщення товару",
                role_filter=None,
                user_id=777,
                db_path=self.db_path,
                client=None,
            )
            self.assertEqual(ans["used_instruction_ids"], [inst_id])

        # Перевірка форматування контексту у GPT без [Джерело N]
        captured = []

        async def _fake_create(**kwargs):
            captured.append(kwargs["messages"])
            msg_obj = MagicMock()
            msg_obj.content = "Переміщення товару оформлюється через ТЗД [Інструкція: Інструкція з переміщення товару]."
            choice = MagicMock()
            choice.message = msg_obj
            resp = MagicMock()
            resp.choices = [choice]
            resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)
            return resp

        fake_client = MagicMock()
        fake_client.chat.completions.create = AsyncMock(side_effect=_fake_create)
        fake_client.embeddings.create = AsyncMock(return_value=MagicMock(data=[]))

        with patch("bot.services.openai_ai.is_openai_configured", return_value=True):
            gpt_ans = await answer_remind_topic(
                question="Перміщення товару",
                role_filter=None,
                user_id=777,
                db_path=self.db_path,
                client=fake_client,
            )
            self.assertEqual(gpt_ans["used_instruction_ids"], [inst_id])
            sys_prompt = captured[0][0]["content"]
            self.assertIn("Фрагмент 1 [Інструкція: Інструкція з переміщення товару]:", sys_prompt)
            self.assertIn("НЕ пиши [Джерело N]", sys_prompt)


if __name__ == "__main__":
    unittest.main()
