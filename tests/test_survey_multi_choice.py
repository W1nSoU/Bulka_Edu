import io
import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import openpyxl
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, User

from bot.menus.developer import (
    dev_survey_preview_look,
    dev_survey_process_template,
    dev_survey_toggle_qtype,
)
from bot.menus.survey_taking import (
    SURVEY_COMPLETED_TEXT,
    SurveyTakingState,
    _build_question_render,
    survey_multi_confirm_callback,
    survey_multi_toggle_callback,
    survey_start_callback,
)
from bot.services.survey_excel import generate_survey_results_xlsx
from bot.services.survey_parser import SurveyParser
from database import surveys as surveys_db


class TestSurveyParserMultiChoice(unittest.TestCase):
    def test_parses_all_multi_choice_markers_case_insensitive_and_cleans_text(self):
        markers = [
            "(кілька варіантів)",
            "(ВИБІР КІЛЬКОХ ВАРІАНТІВ)",
            "(Мультивибір)",
            "(множинний вибір)",
            "(можна кілька)",
        ]
        for marker in markers:
            template = (
                f"1. Які напої вам подобаються? {marker}\n"
                "а. Кава\n"
                "б. Чай\n"
                "в. Сік\n"
            )
            questions, err = SurveyParser.parse_template(template)
            self.assertIsNone(err, msg=f"Unexpected error for marker {marker}: {err}")
            self.assertEqual(len(questions), 1)
            self.assertEqual(questions[0].question_type, "multi_choice")
            self.assertEqual(questions[0].text, "Які напої вам подобаються?")
            self.assertEqual(questions[0].options, ["а. Кава", "б. Чай", "в. Сік"])

    def test_parses_mixed_choice_multi_choice_and_text(self):
        template = (
            "1. Оцініть тиждень:\n"
            "а. Добре\n"
            "б. Супер\n\n"
            "2. Що покращити? (кілька варіантів)\n"
            "а. Графік\n"
            "б. Інструкції\n"
            "в. Наставництво\n\n"
            "3. Ваш коментар (вільна відповідь)"
        )
        questions, err = SurveyParser.parse_template(template)
        self.assertIsNone(err)
        self.assertEqual([q.question_type for q in questions], ["choice", "multi_choice", "text"])
        self.assertEqual(questions[1].text, "Що покращити?")

    def test_rejects_conflicting_free_text_and_multi_choice_markers(self):
        template = (
            "1. Спірне питання (вільна відповідь) (кілька варіантів)\n"
            "а. Так\n"
            "б. Ні\n"
        )
        questions, err = SurveyParser.parse_template(template)
        self.assertIsNone(questions)
        self.assertIn("одночасно", err)

    def test_rejects_multi_choice_without_enough_options_or_over_limit(self):
        one_opt = "1. Одне? (кілька варіантів)\nа. Так\n"
        questions, err = SurveyParser.parse_template(one_opt)
        self.assertIsNone(questions)
        self.assertIn("щонайменше 2", err)

        zero_opt = "1. Нуль? (кілька варіантів)\n"
        questions, err = SurveyParser.parse_template(zero_opt)
        self.assertIsNone(questions)
        self.assertIn("щонайменше 2", err)

        too_many_lines = ["1. Багато (кілька варіантів)"]
        letters = "абвгдежзиклмнопрстуфхцчшщюяabcdefghijklmnopqrstuvwxyz"
        for i in range(46):
            too_many_lines.append(f"{letters[i]}. Варіант {i + 1}")
        questions, err = SurveyParser.parse_template("\n".join(too_many_lines))
        self.assertIsNone(questions)
        self.assertIn("45", err)


class TestSurveyMultiChoiceDbAndExcel(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_surveys_mc.db")
        await surveys_db.init_surveys_db(self.db_path)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    role TEXT,
                    shop TEXT,
                    city TEXT
                )
                """
            )
            await db.executemany(
                "INSERT INTO users (user_id, username, full_name, role, shop, city) VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (101, "u1", "Іваненко Іван", "Продавець", "Магазин 1", "Хмельницький"),
                    (102, "u2", "Петренко Петро", "Продавець", "Магазин 1", "Хмельницький"),
                    (103, "u3", "Сидоренко Оля", "Касир", "Магазин 2", "Вінниця"),
                    (104, "u4", "Коваль Олег", "Касир", "Магазин 2", "Вінниця"),
                ],
            )
            await db.commit()

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    def test_parse_multi_choice_answer_edge_cases(self):
        self.assertEqual(
            surveys_db.parse_multi_choice_answer('["а. Кава, чай", "б. Сік; вода", "а. Кава, чай"]'),
            ["а. Кава, чай", "б. Сік; вода"],
        )
        self.assertEqual(surveys_db.parse_multi_choice_answer("а. Один"), ["а. Один"])
        self.assertEqual(surveys_db.parse_multi_choice_answer("[не json"), ["[не json"])
        self.assertEqual(surveys_db.parse_multi_choice_answer(""), [])
        self.assertEqual(surveys_db.parse_multi_choice_answer(None), [])

    async def test_stats_and_excel_percentage_by_respondents(self):
        opts = ["а. Кава, капучино", "б. Чай; трав'яний", "в. Сендвіч"]
        survey_id = await surveys_db.create_survey(
            title="Зручність перерв",
            template_text="...",
            created_by=1,
            target_roles=["Працівник"],
            questions=[
                {"question_idx": 1, "text": "Обрати все підходяще", "question_type": "multi_choice", "options": opts},
                {"question_idx": 2, "text": "Загалом ок?", "question_type": "choice", "options": ["а. Так", "б. Ні"]},
            ],
            recipient_uids=[101, 102, 103, 104],
            db_path=self.db_path,
        )

        # u1: а, б
        # u2: а, б, в
        # u3: а
        # u4: б, в
        # Разом: 4 респонденти, 8 позначок (а=3 -> 75.0%, б=3 -> 75.0%, в=2 -> 50.0%)
        answers_by_user = {
            101: [opts[0], opts[1]],
            102: [opts[0], opts[1], opts[2]],
            103: [opts[0]],
            104: [opts[1], opts[2]],
        }
        for uid, chosen in answers_by_user.items():
            await surveys_db.save_survey_answer(
                survey_id, uid, 1, json.dumps(chosen, ensure_ascii=False), db_path=self.db_path
            )
            await surveys_db.save_survey_answer(survey_id, uid, 2, "а. Так", db_path=self.db_path)
            await surveys_db.mark_survey_recipient_completed(survey_id, uid, db_path=self.db_path)

        q_stats = await surveys_db.get_survey_question_stats(survey_id, 1, db_path=self.db_path)
        self.assertEqual(q_stats, {opts[0]: 3, opts[1]: 3, opts[2]: 2})

        detailed = await surveys_db.get_survey_detailed_results(survey_id, db_path=self.db_path)
        mc_stat = detailed["question_stats"][1]
        self.assertEqual(mc_stat["total_answers"], 4)
        self.assertEqual(mc_stat["total_selections"], 8)
        self.assertEqual(mc_stat["option_percentages"][opts[0]], 75.0)
        self.assertEqual(mc_stat["option_percentages"][opts[1]], 75.0)
        self.assertEqual(mc_stat["option_percentages"][opts[2]], 50.0)

        shop1_u1 = next(r for r in detailed["shops"]["Магазин 1"] if r["user_id"] == 101)
        self.assertEqual(shop1_u1["answers"][1], f"{opts[0]}; {opts[1]}")

        xlsx_buf = await generate_survey_results_xlsx(survey_id, db_path=self.db_path)
        wb = openpyxl.load_workbook(io.BytesIO(xlsx_buf.getvalue()))
        ws_sum = wb["Загальні результати"]
        sum_values = [cell.value for row in ws_sum.iter_rows() for cell in row if cell.value is not None]

        self.assertIn("Питання №1: Обрати все підходяще [Вибір кількох варіантів]", sum_values)
        self.assertIn("% від респондентів", sum_values)
        self.assertIn("75.0%", sum_values)
        self.assertIn("50.0%", sum_values)
        self.assertIn("Всього відповіли респондентів", sum_values)
        self.assertIn("Всього позначок: 8", sum_values)
        self.assertIn("Питання №2: Загалом ок? [Вибір варіанту]", sum_values)

        ws_shop1 = wb["Магазин 1"]
        shop1_cells = [cell.value for row in ws_shop1.iter_rows() for cell in row if cell.value is not None]
        self.assertIn(f"{opts[0]}; {opts[1]}", shop1_cells)


class TestSurveyMultiChoiceHandlers(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_handlers_mc.db")
        await surveys_db.init_surveys_db(self.db_path)

        self.storage = MemoryStorage()
        self.state = FSMContext(storage=self.storage, key=StorageKey(bot_id=1, chat_id=500, user_id=500))

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    def _make_callback(self, data: str, user_id: int = 500) -> MagicMock:
        cb = MagicMock(spec=CallbackQuery)
        cb.data = data
        cb.from_user = MagicMock(spec=User)
        cb.from_user.id = user_id
        cb.message = MagicMock(spec=Message)
        cb.message.edit_text = AsyncMock()
        cb.message.edit_reply_markup = AsyncMock()
        cb.message.answer = AsyncMock()
        cb.answer = AsyncMock()
        return cb

    async def test_developer_wizard_toggle_qtype_and_preview(self):
        msg = MagicMock(spec=Message)
        msg.text = (
            "1. Оцінка графіку\n"
            "а. Зручний\n"
            "б. Потребує правок\n\n"
            "2. Коментар (вільна відповідь)"
        )
        msg.answer = AsyncMock()

        await self.state.update_data(title="Тест перемикача")
        await dev_survey_process_template(msg, self.state)

        data = await self.state.get_data()
        self.assertIsInstance(data["questions"][0], dict)
        self.assertEqual(data["questions"][0]["question_type"], "choice")

        # Перевіряємо наявність кнопки перемикання на summary
        _, kwargs = msg.answer.call_args
        kb: InlineKeyboardMarkup = kwargs["reply_markup"]
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        self.assertIn("dev_survey_toggle_qtype:1", callbacks)
        self.assertNotIn("dev_survey_toggle_qtype:2", callbacks)

        # Перемикаємо П1 на multi_choice
        cb_toggle = self._make_callback("dev_survey_toggle_qtype:1")
        with patch("bot.menus.developer._edit_or_answer", new_callable=AsyncMock) as mock_edit:
            await dev_survey_toggle_qtype(cb_toggle, self.state)
            mock_edit.assert_called_once()
            _, preview_kwargs = mock_edit.call_args
            btn_texts = [btn.text for row in preview_kwargs["reply_markup"].inline_keyboard for btn in row]
            self.assertIn("☑️ П1: Кілька варіантів", btn_texts)

        updated = await self.state.get_data()
        self.assertEqual(updated["questions"][0]["question_type"], "multi_choice")

        # Перевіряємо попередній перегляд
        cb_preview = self._make_callback("dev_survey_preview_look")
        with patch("bot.menus.developer._edit_or_answer", new_callable=AsyncMock) as mock_preview:
            await dev_survey_preview_look(cb_preview, self.state)
            rendered_text = mock_preview.call_args[0][1]
            self.assertIn("Можна обрати кілька варіантів", rendered_text)
            self.assertIn("⬜️ а. Зручний", rendered_text)

    async def test_respondent_toggle_confirm_and_duplicate_protection(self):
        survey_id = await surveys_db.create_survey(
            title="Опитування команди",
            template_text="...",
            created_by=1,
            target_roles=["Працівник"],
            questions=[
                {
                    "question_idx": 1,
                    "text": "Які зміни зручні?",
                    "question_type": "multi_choice",
                    "options": ["а. Ранок", "б. День", "в. Вечір"],
                },
                {
                    "question_idx": 2,
                    "text": "Додатковий коментар",
                    "question_type": "text",
                    "options": [],
                },
            ],
            recipient_uids=[500],
            db_path=self.db_path,
        )
        await surveys_db.update_survey_status(survey_id, "active", db_path=self.db_path)

        def bind_db(fn):
            async def _wrapped(*args, **kwargs):
                kwargs.setdefault("db_path", self.db_path)
                return await fn(*args, **kwargs)
            return _wrapped

        with (
            patch("bot.menus.survey_taking.get_survey_by_id", side_effect=bind_db(surveys_db.get_survey_by_id)),
            patch("bot.menus.survey_taking.get_survey_questions", side_effect=bind_db(surveys_db.get_survey_questions)),
            patch("bot.menus.survey_taking.get_survey_recipient", side_effect=bind_db(surveys_db.get_survey_recipient)),
            patch(
                "bot.menus.survey_taking.update_survey_recipient_progress",
                side_effect=bind_db(surveys_db.update_survey_recipient_progress),
            ),
            patch(
                "bot.menus.survey_taking.mark_survey_recipient_completed",
                side_effect=bind_db(surveys_db.mark_survey_recipient_completed),
            ),
            patch("bot.menus.survey_taking.save_survey_answer", side_effect=bind_db(surveys_db.save_survey_answer)),
            patch(
                "bot.menus.survey_taking.get_survey_answers_for_user",
                side_effect=bind_db(surveys_db.get_survey_answers_for_user),
            ),
        ):
            # 1. Старт опитування: показує 3 чекбокси з маскою 0
            cb_start = self._make_callback(f"survey_start:{survey_id}", user_id=500)
            await survey_start_callback(cb_start, self.state)
            start_kb: InlineKeyboardMarkup = cb_start.message.edit_text.call_args.kwargs["reply_markup"]
            start_callbacks = [row[0].callback_data for row in start_kb.inline_keyboard]
            self.assertEqual(
                start_callbacks,
                [
                    f"survey_mt:{survey_id}:1:1",
                    f"survey_mt:{survey_id}:1:2",
                    f"survey_mt:{survey_id}:1:4",
                    f"survey_mc:{survey_id}:1:0",
                ],
            )

            # 2. Спроба підтвердити з порожнім вибором (mask=0)
            cb_empty = self._make_callback(f"survey_mc:{survey_id}:1:0", user_id=500)
            await survey_multi_confirm_callback(cb_empty, self.state)
            cb_empty.answer.assert_awaited_with("⚠️ Оберіть хоча б один варіант!", show_alert=True)
            self.assertEqual(await surveys_db.get_survey_answers_for_user(survey_id, 500, db_path=self.db_path), [])

            # 3. Перемикаємо 1-й і 3-й варіанти (mask=1 -> mask=5)
            cb_toggle1 = self._make_callback(f"survey_mt:{survey_id}:1:1", user_id=500)
            await survey_multi_toggle_callback(cb_toggle1, self.state)
            kb_after_1: InlineKeyboardMarkup = cb_toggle1.message.edit_reply_markup.call_args.kwargs["reply_markup"]
            self.assertTrue(kb_after_1.inline_keyboard[0][0].text.startswith("✅"))
            self.assertTrue(kb_after_1.inline_keyboard[1][0].text.startswith("⬜️"))
            self.assertEqual(kb_after_1.inline_keyboard[3][0].text, "✅ Підтвердити (1)")

            # Перевірка стійкості до TelegramBadRequest("message is not modified")
            cb_dup_toggle = self._make_callback(f"survey_mt:{survey_id}:1:5", user_id=500)
            cb_dup_toggle.message.edit_reply_markup.side_effect = TelegramBadRequest(
                method=MagicMock(), message="Bad Request: message is not modified"
            )
            await survey_multi_toggle_callback(cb_dup_toggle, self.state)
            cb_dup_toggle.answer.assert_awaited_once()

            # 4. Підтверджуємо вибір mask=5 ("а. Ранок" і "в. Вечір")
            cb_confirm = self._make_callback(f"survey_mc:{survey_id}:1:5", user_id=500)
            await survey_multi_confirm_callback(cb_confirm, self.state)

            saved = await surveys_db.get_survey_answers_for_user(survey_id, 500, db_path=self.db_path)
            self.assertEqual(len(saved), 1)
            self.assertEqual(json.loads(saved[0]["answer_text"]), ["а. Ранок", "в. Вечір"])
            self.assertEqual(await self.state.get_state(), SurveyTakingState.waiting_for_free_text.state)

            # 5. Захист від повторного натискання на вже пройдене питання 1
            cb_reconfirm = self._make_callback(f"survey_mc:{survey_id}:1:2", user_id=500)
            await survey_multi_confirm_callback(cb_reconfirm, self.state)
            cb_reconfirm.answer.assert_awaited_with("Ви вже відповіли на це питання.", show_alert=True)
            saved_after = await surveys_db.get_survey_answers_for_user(survey_id, 500, db_path=self.db_path)
            self.assertEqual(json.loads(saved_after[0]["answer_text"]), ["а. Ранок", "в. Вечір"])

    def test_build_question_render_confirmation_count_and_bits(self):
        survey = {"id": 42, "title": "Опитування"}
        q = {
            "question_idx": 1,
            "text": "Оберіть дні",
            "question_type": "multi_choice",
            "options": ["а. Пн", "б. Вт", "в. Ср"],
        }
        text, kb = _build_question_render(survey, q, 1, 1, selected_mask=6)
        self.assertIn("Можна обрати кілька варіантів", text)
        self.assertEqual(kb.inline_keyboard[0][0].text, "⬜️ а. Пн")
        self.assertEqual(kb.inline_keyboard[1][0].text, "✅ б. Вт")
        self.assertEqual(kb.inline_keyboard[2][0].text, "✅ в. Ср")
        self.assertEqual(kb.inline_keyboard[3][0].text, "✅ Підтвердити (2)")
        self.assertEqual(kb.inline_keyboard[3][0].callback_data, "survey_mc:42:1:6")

    async def test_developer_toggle_blocks_over_limit_and_uses_compact_rows(self):
        # > 45 варіантів не можна перемкнути на multi_choice
        await self.state.update_data(
            title="Багато опцій",
            questions=[
                {
                    "question_idx": 1,
                    "text": "Список",
                    "question_type": "choice",
                    "options": [f"Опція {i}" for i in range(46)],
                }
            ],
        )
        cb_over = self._make_callback("dev_survey_toggle_qtype:1")
        await dev_survey_toggle_qtype(cb_over, self.state)
        cb_over.answer.assert_awaited()
        self.assertTrue(cb_over.answer.call_args.kwargs.get("show_alert"))
        self.assertEqual((await self.state.get_data())["questions"][0]["question_type"], "choice")

        # > 4 питань з варіантами -> компактна розкладка по 2 кнопки в ряд
        many_qs = [
            {
                "question_idx": idx,
                "text": f"Питання {idx}",
                "question_type": "choice",
                "options": ["а. Так", "б. Ні"],
            }
            for idx in range(1, 6)
        ]
        await self.state.update_data(title="Компактні кнопки", questions=many_qs)
        cb_compact = self._make_callback("dev_survey_toggle_qtype:2")
        with patch("bot.menus.developer._edit_or_answer", new_callable=AsyncMock) as mock_edit:
            await dev_survey_toggle_qtype(cb_compact, self.state)
            kb: InlineKeyboardMarkup = mock_edit.call_args.kwargs["reply_markup"]
            toggle_rows = [
                row for row in kb.inline_keyboard
                if any(btn.callback_data.startswith("dev_survey_toggle_qtype:") for btn in row)
            ]
            self.assertEqual([len(r) for r in toggle_rows], [2, 2, 1])
            flat_texts = [btn.text for row in toggle_rows for btn in row]
            self.assertIn("☑️ П2: Кілька", flat_texts)

    async def test_full_mixed_flow_completion_after_multi_choice(self):
        from bot.menus.survey_taking import survey_choice_answer_callback

        survey_id = await surveys_db.create_survey(
            title="Змішане фінал-мульти",
            template_text="...",
            created_by=1,
            target_roles=["Працівник"],
            questions=[
                {
                    "question_idx": 1,
                    "text": "Все влаштовує?",
                    "question_type": "choice",
                    "options": ["а. Так", "б. Ні"],
                },
                {
                    "question_idx": 2,
                    "text": "Які бонуси додати?",
                    "question_type": "multi_choice",
                    "options": ["а. Кава", "б. Знижки"],
                },
            ],
            recipient_uids=[500],
            db_path=self.db_path,
        )
        await surveys_db.update_survey_status(survey_id, "active", db_path=self.db_path)

        def bind_db(fn):
            async def _wrapped(*args, **kwargs):
                kwargs.setdefault("db_path", self.db_path)
                return await fn(*args, **kwargs)
            return _wrapped

        with (
            patch("bot.menus.survey_taking.get_survey_by_id", side_effect=bind_db(surveys_db.get_survey_by_id)),
            patch("bot.menus.survey_taking.get_survey_questions", side_effect=bind_db(surveys_db.get_survey_questions)),
            patch("bot.menus.survey_taking.get_survey_recipient", side_effect=bind_db(surveys_db.get_survey_recipient)),
            patch(
                "bot.menus.survey_taking.update_survey_recipient_progress",
                side_effect=bind_db(surveys_db.update_survey_recipient_progress),
            ),
            patch(
                "bot.menus.survey_taking.mark_survey_recipient_completed",
                side_effect=bind_db(surveys_db.mark_survey_recipient_completed),
            ),
            patch("bot.menus.survey_taking.save_survey_answer", side_effect=bind_db(surveys_db.save_survey_answer)),
            patch(
                "bot.menus.survey_taking.get_survey_answers_for_user",
                side_effect=bind_db(surveys_db.get_survey_answers_for_user),
            ),
        ):
            # Відповідь на 1-ше питання (choice) -> перехід на 2-ге (multi_choice)
            cb1 = self._make_callback(f"survey_ans:{survey_id}:1:0", user_id=500)
            await survey_choice_answer_callback(cb1, self.state)
            self.assertIn("Які бонуси додати?", cb1.message.edit_text.call_args[0][0])

            # Підтвердження 2-го питання (mask=3: обидва варіанти) -> завершення опитування
            cb2 = self._make_callback(f"survey_mc:{survey_id}:2:3", user_id=500)
            await survey_multi_confirm_callback(cb2, self.state)
            self.assertEqual(cb2.message.edit_text.call_args[0][0], SURVEY_COMPLETED_TEXT)

            rec = await surveys_db.get_survey_recipient(survey_id, 500, db_path=self.db_path)
            self.assertEqual(rec["status"], "completed")
            answers = await surveys_db.get_survey_answers_for_user(survey_id, 500, db_path=self.db_path)
            self.assertEqual(answers[0]["answer_text"], "а. Так")
            self.assertEqual(json.loads(answers[1]["answer_text"]), ["а. Кава", "б. Знижки"])


if __name__ == "__main__":
    unittest.main()
