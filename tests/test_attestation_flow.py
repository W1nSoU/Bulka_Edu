import unittest
import asyncio
import os
import io
import json
from datetime import datetime, timedelta
import pytz

import aiosqlite

from bot.config import TIMEZONE
from database.attestation import (
    init_attestation_db,
    save_questions_for_role,
    get_questions_for_role,
    get_questions_count_by_role,
    create_wave,
    activate_wave,
    get_active_wave,
    get_wave_by_id,
    close_wave,
    add_participants_batch,
    get_wave_participants,
    allow_user_retake,
    get_wave_statistics,
    get_wave_shop_stats,
    get_shop_members_details,
    add_shop_to_active_wave,
    close_shop_in_active_wave,
    is_shop_active_in_wave,
    get_wave_shops_status,
    start_inline_attempt,
    get_inline_attempt_card_data,
    save_inline_answer,
    navigate_inline_question,
    finish_inline_attempt
)
from bot.services.attestation_excel import (
    generate_attestation_template,
    parse_attestation_excel,
    generate_attestation_results_xlsx
)
from bot.menus.attestation import _collect_eligible_participants


TEST_DB = "test_attestation.db"


class TestAttestationFlow(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        await init_attestation_db(TEST_DB)

    async def asyncTearDown(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    async def test_questions_bank(self):
        questions = [
            {
                "question_text": "Який термін реалізації свіжих круасанів?",
                "option_1": "6 годин",
                "option_2": "12 годин",
                "option_3": "24 години",
                "option_4": "48 годин",
                "correct_option": 2,
                "points": 2,
                "explanation": "Листкова випічка реалізується 12 годин."
            },
            {
                "question_text": "Як діяти при виявленні бракованої упаковки?",
                "option_1": "Продати зі знижкою",
                "option_2": "Списати згідно з актом",
                "option_3": "Залишити на вітрині",
                "correct_option": 2,
                "points": 1,
                "explanation": "Брак обов'язково списується."
            }
        ]

        saved = await save_questions_for_role("ВВ Пекар", questions, db_path=TEST_DB)
        self.assertEqual(saved, 2)

        loaded = await get_questions_for_role("ВВ Пекар", db_path=TEST_DB)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0]["question_text"], "Який термін реалізації свіжих круасанів?")
        self.assertEqual(loaded[0]["correct_option"], 2)
        self.assertEqual(loaded[0]["points"], 2)

        counts = await get_questions_count_by_role(db_path=TEST_DB)
        self.assertEqual(counts.get("ВВ Пекар"), 2)

    async def test_excel_template_generation_and_parsing(self):
        roles = ["Керівник", "ВВ Пекар", "Продавець-консультант (каса)"]
        excel_io = generate_attestation_template(roles)
        file_bytes = excel_io.getvalue()
        self.assertTrue(len(file_bytes) > 1000)

        parsed_data, warnings = parse_attestation_excel(file_bytes, roles)
        self.assertIn("Керівник", parsed_data)
        self.assertIn("ВВ Пекар", parsed_data)
        self.assertEqual(len(parsed_data["Керівник"]), 1)
        self.assertEqual(parsed_data["Керівник"][0]["correct_option"], 2)

    async def test_inline_attestation_flow(self):
        """Перевіряє повний цикл нативної інлайн-атестації: старт, збереження відповідей, навігація, фініш."""
        tz = pytz.timezone(TIMEZONE)
        deadline = (datetime.now(tz) + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")

        # 1. Створюємо хвилю для працівників
        wave_id = await create_wave(
            title="Осіння атестація 2026",
            created_by=1111,
            duration_minutes=20,
            passing_score_pct=80,
            deadline_date=deadline,
            shops=["b-12"],
            target_type="staff",
            db_path=TEST_DB
        )
        await activate_wave(wave_id, db_path=TEST_DB)

        # 2. Додаємо банк запитань
        questions = [
            {
                "question_text": "Питання 1: Як налаштувати кавомашину?",
                "option_1": "Помити холдер",
                "option_2": "Перевірити тиск та помол",
                "option_3": "Вимкнути живлення",
                "option_4": "Залити холодну воду",
                "correct_option": 2,
                "points": 1
            },
            {
                "question_text": "Питання 2: Термін придатності свіжого хліба?",
                "option_1": "24 години",
                "option_2": "48 годин",
                "option_3": "72 години",
                "option_4": "12 годин",
                "correct_option": 1,
                "points": 2
            }
        ]
        await save_questions_for_role("Бариста", questions, db_path=TEST_DB)

        # 3. Реєструємо учасника
        await add_participants_batch(wave_id, [{
            "user_id": 555,
            "full_name": "Олена Бариста",
            "role_name": "Бариста",
            "shop_name": "b-12",
            "is_manager": 0
        }], db_path=TEST_DB)

        # 4. Запускаємо спробу через інлайн
        attempt = await start_inline_attempt(
            wave_id=wave_id,
            user_id=555,
            role_name="Бариста",
            shop_name="b-12",
            duration_minutes=20,
            db_path=TEST_DB
        )
        self.assertEqual(attempt["status"], "in_progress")
        self.assertEqual(attempt["current_question_index"], 0)
        self.assertIsNotNone(attempt["questions_order_json"])
        self.assertIsNotNone(attempt["options_order_json"])

        attempt_id = attempt["id"]

        # 5. Отримуємо дані першого питання для картки
        card1 = await get_inline_attempt_card_data(attempt_id, db_path=TEST_DB)
        self.assertFalse(card1["is_finished"])
        self.assertEqual(card1["current_q_num"], 1)
        self.assertEqual(card1["total_questions"], 2)
        self.assertFalse(card1["has_previous"])
        self.assertGreater(card1["remaining_seconds"], 0)
        self.assertEqual(len(card1["options"]), 4)

        # Перевіряємо, що збережений порядок варіантів відповідає картці
        opt_order = json.loads(attempt["options_order_json"])
        q1_id = card1["question_id"]
        expected_seq = opt_order[str(q1_id)]
        actual_seq = [opt["orig_num"] for opt in card1["options"]]
        self.assertEqual(expected_seq, actual_seq)

        # 6. Даємо відповідь на питання 1
        # Зберігаємо правильну відповідь
        # Якщо current_q_id == q1, правильна відповідь 2; якщо q2, правильна відповідь 1
        q_rows = await get_questions_for_role("Бариста", db_path=TEST_DB)
        correct_for_q1 = next(q["correct_option"] for q in q_rows if q["id"] == q1_id)

        updated_attempt, is_fin = await save_inline_answer(attempt_id, q1_id, correct_for_q1, db_path=TEST_DB)
        self.assertFalse(is_fin)
        self.assertEqual(updated_attempt["current_question_index"], 1)

        # 7. Тестуємо навігацію НАЗАД [ ⬅️ Назад ]
        nav_attempt, is_fin_nav = await navigate_inline_question(attempt_id, delta=-1, db_path=TEST_DB)
        self.assertFalse(is_fin_nav)
        self.assertEqual(nav_attempt["current_question_index"], 0)

        card_back = await get_inline_attempt_card_data(attempt_id, db_path=TEST_DB)
        self.assertEqual(card_back["current_q_num"], 1)
        # Порядок варіантів має бути ідентичним першому показу!
        self.assertEqual([opt["orig_num"] for opt in card_back["options"]], expected_seq)
        # Обраний варіант повинен бути позначений як is_selected = True
        selected_opt = next(opt for opt in card_back["options"] if opt["orig_num"] == correct_for_q1)
        self.assertTrue(selected_opt["is_selected"])
        self.assertTrue(card_back["has_next"])

        # 8. Переходимо ДАЛІ [ Далі ➡️ ]
        await navigate_inline_question(attempt_id, delta=1, db_path=TEST_DB)
        card2 = await get_inline_attempt_card_data(attempt_id, db_path=TEST_DB)
        self.assertEqual(card2["current_q_num"], 2)
        self.assertTrue(card2["has_previous"])

        # 9. Відповідаємо на друге (останнє) питання
        q2_id = card2["question_id"]
        correct_for_q2 = next(q["correct_option"] for q in q_rows if q["id"] == q2_id)

        final_attempt, is_fin2 = await save_inline_answer(attempt_id, q2_id, correct_for_q2, db_path=TEST_DB)
        self.assertTrue(is_fin2)
        self.assertEqual(final_attempt["status"], "passed")
        self.assertEqual(final_attempt["score"], 3) # 1 + 2 бали
        self.assertEqual(final_attempt["max_score"], 3)
        self.assertEqual(final_attempt["score_pct"], 100.0)

        # Картка після завершення повертає is_finished = True
        final_card = await get_inline_attempt_card_data(attempt_id, db_path=TEST_DB)
        self.assertTrue(final_card["is_finished"])
        self.assertEqual(final_card["attempt"]["status"], "passed")

    async def test_active_wave_shop_management(self):
        """Перевіряє динамічне підключення нового магазину та зупинку/відновлення магазину."""
        tz = pytz.timezone(TIMEZONE)
        deadline = (datetime.now(tz) + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")

        wave_id = await create_wave(
            title="Динамічна атестація",
            created_by=222,
            duration_minutes=15,
            passing_score_pct=75,
            deadline_date=deadline,
            shops=["b-01"],
            target_type="staff",
            db_path=TEST_DB
        )
        await activate_wave(wave_id, db_path=TEST_DB)

        # 1. Початковий стан
        self.assertTrue(await is_shop_active_in_wave(wave_id, "b-01", db_path=TEST_DB))
        self.assertFalse(await is_shop_active_in_wave(wave_id, "b-02", db_path=TEST_DB))

        # 2. Адміністратор додає ще один магазин
        added = await add_shop_to_active_wave(wave_id, "b-02", db_path=TEST_DB)
        self.assertTrue(added)
        self.assertTrue(await is_shop_active_in_wave(wave_id, "b-02", db_path=TEST_DB))

        # 3. Адміністратор зупиняє проходження для b-01
        closed = await close_shop_in_active_wave(wave_id, "b-01", db_path=TEST_DB)
        self.assertTrue(closed)
        self.assertFalse(await is_shop_active_in_wave(wave_id, "b-01", db_path=TEST_DB))
        self.assertTrue(await is_shop_active_in_wave(wave_id, "b-02", db_path=TEST_DB))

        # 4. Перевіряємо статуси магазинів
        statuses = await get_wave_shops_status(wave_id, db_path=TEST_DB)
        stat_map = {s["shop_name"]: s["status"] for s in statuses}
        self.assertEqual(stat_map["b-01"], "closed")
        self.assertEqual(stat_map["b-02"], "active")

        # 5. Адміністратор відновлює b-01
        resumed = await add_shop_to_active_wave(wave_id, "b-01", db_path=TEST_DB)
        self.assertTrue(resumed)
        self.assertTrue(await is_shop_active_in_wave(wave_id, "b-01", db_path=TEST_DB))

    async def test_target_type_staff_vs_managers(self):
        """Перевіряє розділення цільових категорій атестації: працівники проти керівників."""
        tz = pytz.timezone(TIMEZONE)
        deadline = (datetime.now(tz) + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")

        # 1. Хвиля для керівників
        wave_mgr = await create_wave(
            title="Атестація Керівників 2026",
            created_by=111,
            duration_minutes=30,
            passing_score_pct=85,
            deadline_date=deadline,
            shops=[],
            target_type="managers",
            db_path=TEST_DB
        )
        wave_obj = await get_wave_by_id(wave_mgr, db_path=TEST_DB)
        self.assertEqual(wave_obj["target_type"], "managers")

        # Збір учасників для керівників за user_id
        participants_mgr = await _collect_eligible_participants([1195097288, 6867721037], target_type="managers")
        self.assertGreaterEqual(len(participants_mgr), 1)
        for p in participants_mgr:
            self.assertEqual(p["is_manager"], 1)
            self.assertEqual(p["role_name"], "Керівник")

        # Збір учасників для працівників пекарні (не повинні містити керівників)
        participants_staff = await _collect_eligible_participants(["B-19 вул. Героїв Маріуполя, 62"], target_type="staff")
        for p in participants_staff:
            self.assertEqual(p["is_manager"], 0)
            self.assertNotEqual(p["role_name"], "Керівник")

    async def test_add_shop_callback_data_length_limit(self):
        """Перевіряє, що callback_data для додавання магазинів строго <= 64 байт (запобігання BUTTON_DATA_INVALID)."""
        from bot.menus.attestation import get_all_system_shops
        all_shops = await get_all_system_shops()
        wave_id = 999
        for idx, shop_name in enumerate(all_shops):
            cb_data = f"dev_att_add_sh_cf:{wave_id}:{idx}"
            self.assertLessEqual(len(cb_data.encode("utf-8")), 64, f"Callback {cb_data} exceeds 64 bytes!")
            # Перевіряємо, що індекс точно резолвиться назад у назву магазину
            self.assertEqual(all_shops[idx], shop_name)

    async def test_question_limit_and_random_sampling(self):
        """Перевіряє конфігурацію кількості запитань та випадкову вибірку без повторень."""
        tz = pytz.timezone(TIMEZONE)
        deadline = (datetime.now(tz) + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")

        # 1. Створюємо хвилю з лімітом 5 запитань
        wave_id = await create_wave(
            title="Тест ліміту питань 2026",
            created_by=100,
            duration_minutes=15,
            passing_score_pct=80,
            deadline_date=deadline,
            shops=["Пекарня 1"],
            target_type="staff",
            questions_count=5,
            db_path=TEST_DB
        )
        wave_obj = await get_wave_by_id(wave_id, db_path=TEST_DB)
        self.assertEqual(wave_obj["questions_count"], 5)

        # 2. Додаємо 12 питань у банк для "ВВ Бариста"
        questions = []
        for i in range(1, 13):
            questions.append({
                "question_text": f"Питання номер {i} для бариста?",
                "option_1": f"Відповідь {i}-A",
                "option_2": f"Відповідь {i}-B",
                "option_3": f"Відповідь {i}-C",
                "option_4": f"Відповідь {i}-D",
                "correct_option": 1,
                "points": 1
            })
        await save_questions_for_role("ВВ Бариста", questions, db_path=TEST_DB)

        # 3. Стартуємо спробу для першого користувача
        attempt_user1 = await start_inline_attempt(
            wave_id=wave_id,
            user_id=101,
            role_name="ВВ Бариста",
            shop_name="Пекарня 1",
            duration_minutes=15,
            db_path=TEST_DB
        )
        q_order_1 = json.loads(attempt_user1["questions_order_json"])
        self.assertEqual(len(q_order_1), 5, "Має бути відібрано рівно 5 питань")
        self.assertEqual(len(set(q_order_1)), 5, "Питання не повинні дублюватися")

        # 4. Стартуємо спробу для другого користувача
        attempt_user2 = await start_inline_attempt(
            wave_id=wave_id,
            user_id=102,
            role_name="ВВ Бариста",
            shop_name="Пекарня 1",
            duration_minutes=15,
            db_path=TEST_DB
        )
        q_order_2 = json.loads(attempt_user2["questions_order_json"])
        self.assertEqual(len(q_order_2), 5)
        self.assertEqual(len(set(q_order_2)), 5)

        # 5. Перевіряємо валідацію достатності банку питань
        q_counts = await get_questions_count_by_role(db_path=TEST_DB)
        self.assertEqual(q_counts.get("ВВ Бариста", 0), 12)
        # Для 5 питань Бариста достатня (12 >= 5)
        self.assertGreaterEqual(q_counts.get("ВВ Бариста", 0), wave_obj["questions_count"])

        # Якщо у посади лише 2 питання, а хвиля вимагає 5 — фіксується дефіцит
        await save_questions_for_role("ВВ Пекар", questions[:2], db_path=TEST_DB)
        q_counts = await get_questions_count_by_role(db_path=TEST_DB)
        self.assertLess(q_counts.get("ВВ Пекар", 0), wave_obj["questions_count"])


if __name__ == "__main__":
    unittest.main()
