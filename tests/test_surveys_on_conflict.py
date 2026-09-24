import unittest
import os
import aiosqlite
import tempfile
import json
from database.surveys import (
    init_surveys_db,
    add_survey_question,
    create_survey,
    save_survey_answer,
    get_survey_questions,
    get_survey_answers_for_user
)


class TestSurveyOnConflict(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_users.db")

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    async def test_add_survey_question_on_legacy_table_without_unique_constraint(self):
        # 1. Симулюємо стару таблицю survey_questions БЕЗ UNIQUE constraint
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
            CREATE TABLE surveys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                raw_template TEXT NOT NULL,
                created_by INTEGER NOT NULL,
                target_roles TEXT NOT NULL,
                target_city TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_at TIMESTAMP,
                launched_at TIMESTAMP,
                total_recipients INTEGER DEFAULT 0
            )
            ''')
            # Створюємо survey_questions без UNIQUE
            await db.execute('''
            CREATE TABLE survey_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                survey_id INTEGER NOT NULL,
                question_idx INTEGER NOT NULL,
                text TEXT NOT NULL,
                question_type TEXT NOT NULL,
                options_json TEXT
            )
            ''')
            await db.commit()

        # 2. Викликаємо add_survey_question - вона повинна автоматично створити унікальний індекс і не впасти
        await add_survey_question(
            survey_id=1,
            question_idx=1,
            text="Перше питання?",
            question_type="text",
            options=None,
            db_path=self.db_path
        )

        # 3. Викликаємо ще раз для того самого питання - перевіряємо DO UPDATE
        await add_survey_question(
            survey_id=1,
            question_idx=1,
            text="Оновлене питання?",
            question_type="text",
            options=None,
            db_path=self.db_path
        )

        questions = await get_survey_questions(survey_id=1, db_path=self.db_path)
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]["text"], "Оновлене питання?")

    async def test_create_survey_with_questions_and_recipients(self):
        # Ініціалізація бази
        await init_surveys_db(self.db_path)

        questions = [
            {"question_idx": 1, "text": "Питання 1", "question_type": "text", "options": []},
            {"question_idx": 2, "text": "Питання 2", "question_type": "choice", "options": ["А", "Б"]}
        ]

        survey_id = await create_survey(
            title="Тестове опитування",
            template_text="Шаблон",
            created_by=123,
            target_roles=["Працівник"],
            target_city="Хмельницький",
            questions=questions,
            recipient_uids=[1001, 1002],
            db_path=self.db_path
        )

        self.assertGreater(survey_id, 0)
        saved_qs = await get_survey_questions(survey_id, db_path=self.db_path)
        self.assertEqual(len(saved_qs), 2)

    async def test_save_survey_answer_conflict_update(self):
        await init_surveys_db(self.db_path)

        # Запис першої відповіді
        await save_survey_answer(
            survey_id=1,
            user_id=555,
            question_idx=1,
            answer_text="Перша відповідь",
            db_path=self.db_path
        )

        # Перезапис відповіді користувача на те саме питання
        await save_survey_answer(
            survey_id=1,
            user_id=555,
            question_idx=1,
            answer_text="Друга відповідь",
            db_path=self.db_path
        )

        answers = await get_survey_answers_for_user(survey_id=1, user_id=555, db_path=self.db_path)
        self.assertEqual(len(answers), 1)
        self.assertEqual(answers[0]["answer_text"], "Друга відповідь")


if __name__ == "__main__":
    unittest.main()
