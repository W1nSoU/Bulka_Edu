import unittest
import asyncio
import os
import io
import json
import hmac
import hashlib
import urllib.parse
from datetime import datetime, timedelta
import pytz

import aiosqlite

from bot.config import TIMEZONE, API_TOKEN
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
    start_user_attempt,
    submit_user_attempt,
    allow_user_retake,
    get_wave_statistics,
    get_wave_shop_stats,
    get_shop_members_details
)
from bot.services.attestation_excel import (
    generate_attestation_template,
    parse_attestation_excel,
    generate_attestation_results_xlsx
)
from web_server import validate_telegram_init_data


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
        # In template each sheet has 1 sample row
        self.assertEqual(len(parsed_data["Керівник"]), 1)
        self.assertEqual(parsed_data["Керівник"][0]["correct_option"], 2)

    async def test_wave_lifecycle_and_attempts(self):
        tz = pytz.timezone(TIMEZONE)
        deadline = (datetime.now(tz) + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")

        # 1. Create wave
        wave_id = await create_wave(
            title="Тестова осіння атестація",
            created_by=9999,
            duration_minutes=20,
            passing_score_pct=80,
            deadline_date=deadline,
            shops=["b-12", "b-15"],
            db_path=TEST_DB
        )
        self.assertGreater(wave_id, 0)

        # 2. Activate wave
        await activate_wave(wave_id, db_path=TEST_DB)
        active = await get_active_wave(db_path=TEST_DB)
        self.assertIsNotNone(active)
        self.assertEqual(active["id"], wave_id)
        self.assertIn("b-12", active["shops"])

        # 3. Add questions
        await save_questions_for_role("Касир", [
            {"question_text": "Q1", "option_1": "A", "option_2": "B", "correct_option": 1, "points": 1},
            {"question_text": "Q2", "option_1": "A", "option_2": "B", "correct_option": 2, "points": 1}
        ], db_path=TEST_DB)

        # 4. Add participants
        await add_participants_batch(wave_id, [
            {"user_id": 101, "full_name": "Іван Касир", "role_name": "Касир", "shop_name": "b-12", "is_manager": 0},
            {"user_id": 102, "full_name": "Марія Менеджер", "role_name": "Керівник", "shop_name": "b-12", "is_manager": 1}
        ], db_path=TEST_DB)

        participants = await get_wave_participants(wave_id, db_path=TEST_DB)
        self.assertEqual(len(participants), 2)

        # 5. Start attempt for user 101
        attempt = await start_user_attempt(wave_id, 101, "Касир", "b-12", db_path=TEST_DB)
        self.assertEqual(attempt["status"], "in_progress")
        attempt_id = attempt["id"]

        # Retrieve all questions to get their IDs
        qs = await get_questions_for_role("Касир", db_path=TEST_DB)
        q1_id = str(qs[0]["id"])
        q2_id = str(qs[1]["id"])

        # 6. Submit correct answers (2 out of 2 = 100% -> passed)
        answers = {q1_id: 1, q2_id: 2}
        result = await submit_user_attempt(attempt_id, answers, db_path=TEST_DB)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["score"], 2)
        self.assertEqual(result["max_score"], 2)
        self.assertEqual(result["score_pct"], 100.0)

        # 7. Check stats
        stats = await get_wave_statistics(wave_id, db_path=TEST_DB)
        self.assertEqual(stats["total_participants"], 2)
        self.assertEqual(stats["completed_count"], 1)
        self.assertEqual(stats["passed_count"], 1)
        self.assertEqual(stats["failed_count"], 0)

        # 8. Test retake mechanism
        attempt_again = await start_user_attempt(wave_id, 101, "Касир", "b-12", db_path=TEST_DB)
        self.assertEqual(attempt_again["status"], "passed")

        # Admin grants retake
        retake_ok = await allow_user_retake(wave_id, 101, admin_id=9999, db_path=TEST_DB)
        self.assertTrue(retake_ok)

        # User 101 starts now -> new in_progress attempt created!
        new_attempt = await start_user_attempt(wave_id, 101, "Касир", "b-12", db_path=TEST_DB)
        self.assertNotEqual(new_attempt["id"], attempt_id)
        self.assertEqual(new_attempt["status"], "in_progress")

        # Submit failed answers (0 out of 2 = 0% -> failed)
        fail_res = await submit_user_attempt(new_attempt["id"], {q1_id: 2, q2_id: 1}, db_path=TEST_DB)
        self.assertEqual(fail_res["status"], "failed")
        self.assertEqual(fail_res["score"], 0)

        # 9. Close wave
        await close_wave(wave_id, db_path=TEST_DB)
        active_after_close = await get_active_wave(db_path=TEST_DB)
        self.assertIsNone(active_after_close)

    async def test_manager_participant_collection(self):
        from bot.menus.attestation import _collect_eligible_participants
        # Test with shops that have managers in database
        shops = ['B-19 вул. Героїв Маріуполя, 62', 'B-31 вул. Юрія Руфа, 5', 'B-04 вул. Проскурівська, 15']
        participants = await _collect_eligible_participants(shops)
        
        # Managers must be collected
        manager_uids = [p["user_id"] for p in participants if p["is_manager"] == 1]
        self.assertIn(1195097288, manager_uids) # Зубенко Михал Петрович
        self.assertIn(6867721037, manager_uids) # цв цв цв
        self.assertIn(990006, manager_uids)     # Максим Шевченко Андрійович

        # Check manager role
        for p in participants:
            if p["is_manager"] == 1:
                self.assertEqual(p["role_name"], "Керівник")
                self.assertIsNotNone(p["shop_name"])

    async def test_one_day_attestation_deadline(self):
        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz)
        deadline_dt = now + timedelta(days=1)
        deadline_str = deadline_dt.strftime("%Y-%m-%d 23:59:59")
        
        wave_id = await create_wave(
            title="Одноденна атестація",
            created_by=111,
            duration_minutes=20,
            passing_score_pct=80,
            deadline_date=deadline_str,
            shops=["B-19 вул. Героїв Маріуполя, 62"],
            db_path=TEST_DB
        )
        wave = await get_wave_by_id(wave_id, db_path=TEST_DB)
        self.assertEqual(wave["deadline_date"], deadline_str)


class TestTelegramSecurity(unittest.TestCase):

    def test_telegram_hmac_validation(self):
        bot_token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
        user_json = json.dumps({"id": 885061584, "first_name": "Daniil", "username": "danil"})

        # Prepare data pairs
        auth_date = "1726050000"
        query_id = "AAHdF6IQAAAAAN0XohDhrOrc"

        pairs = [
            f"auth_date={auth_date}",
            f"query_id={query_id}",
            f"user={user_json}"
        ]
        pairs.sort()
        data_check_string = "\n".join(pairs)

        secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
        calc_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

        init_data_valid = f"query_id={urllib.parse.quote(query_id)}&user={urllib.parse.quote(user_json)}&auth_date={auth_date}&hash={calc_hash}"

        validated = validate_telegram_init_data(init_data_valid, bot_token=bot_token)
        self.assertIsNotNone(validated)
        self.assertEqual(validated["id"], 885061584)
        self.assertEqual(validated["username"], "danil")

        # Test invalid hash
        init_data_invalid = f"query_id={urllib.parse.quote(query_id)}&user={urllib.parse.quote(user_json)}&auth_date={auth_date}&hash=invalidhash123"
        self.assertIsNone(validate_telegram_init_data(init_data_invalid, bot_token=bot_token))


if __name__ == "__main__":
    unittest.main()
