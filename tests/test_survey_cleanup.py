import unittest
import os
import aiosqlite
import tempfile
from database.surveys import (
    init_surveys_db,
    create_survey,
    add_survey_question,
    add_survey_recipients,
    save_survey_answer,
    get_survey_by_id,
    get_survey_questions,
    delete_survey,
    get_closed_surveys_count,
    delete_closed_surveys
)


class TestSurveyCleanup(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_surveys.db")
        await init_surveys_db(self.db_path)

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    async def test_delete_survey_cascades_all_data(self):
        # 1. Створюємо перше опитування з питаннями, реципієнтами та відповідями
        survey_1 = await create_survey(
            title="Опитування 1 для видалення",
            template_text="Шаблон 1",
            created_by=111,
            target_roles=["Бармен"],
            questions=[
                {"question_idx": 1, "text": "Питання 1.1", "question_type": "text", "options": []},
                {"question_idx": 2, "text": "Питання 1.2", "question_type": "choice", "options": ["Так", "Ні"]}
            ],
            recipient_uids=[101, 102],
            db_path=self.db_path
        )
        await save_survey_answer(survey_1, 101, 1, "Відповідь юзера 101", db_path=self.db_path)
        await save_survey_answer(survey_1, 102, 1, "Відповідь юзера 102", db_path=self.db_path)

        # 2. Створюємо друге опитування (контрольне, яке НЕ повинно видалитись)
        survey_2 = await create_survey(
            title="Опитування 2 (залишається)",
            template_text="Шаблон 2",
            created_by=222,
            target_roles=["Кухар"],
            questions=[
                {"question_idx": 1, "text": "Питання 2.1", "question_type": "text", "options": []}
            ],
            recipient_uids=[201],
            db_path=self.db_path
        )
        await save_survey_answer(survey_2, 201, 1, "Відповідь юзера 201", db_path=self.db_path)

        # 3. Видаляємо survey_1
        success = await delete_survey(survey_1, db_path=self.db_path)
        self.assertTrue(success)

        # 4. Перевіряємо, що survey_1 повністю відсутнє у всіх таблицях
        self.assertIsNone(await get_survey_by_id(survey_1, db_path=self.db_path))

        async with aiosqlite.connect(self.db_path) as db:
            c = await db.execute("SELECT COUNT(*) FROM survey_questions WHERE survey_id = ?", (survey_1,))
            self.assertEqual((await c.fetchone())[0], 0)

            c = await db.execute("SELECT COUNT(*) FROM survey_recipients WHERE survey_id = ?", (survey_1,))
            self.assertEqual((await c.fetchone())[0], 0)

            c = await db.execute("SELECT COUNT(*) FROM survey_answers WHERE survey_id = ?", (survey_1,))
            self.assertEqual((await c.fetchone())[0], 0)

            # 5. Перевіряємо, що survey_2 ціле та неушкоджене
            c = await db.execute("SELECT COUNT(*) FROM surveys WHERE id = ?", (survey_2,))
            self.assertEqual((await c.fetchone())[0], 1)

            c = await db.execute("SELECT COUNT(*) FROM survey_questions WHERE survey_id = ?", (survey_2,))
            self.assertEqual((await c.fetchone())[0], 1)

            c = await db.execute("SELECT COUNT(*) FROM survey_recipients WHERE survey_id = ?", (survey_2,))
            self.assertEqual((await c.fetchone())[0], 1)

            c = await db.execute("SELECT COUNT(*) FROM survey_answers WHERE survey_id = ?", (survey_2,))
            self.assertEqual((await c.fetchone())[0], 1)

    async def test_get_closed_surveys_count_and_delete_closed_surveys(self):
        # Створюємо 4 опитування з різними статусами
        s_active = await create_survey(title="Активне", db_path=self.db_path)
        s_broadcasting = await create_survey(title="Розсилка", db_path=self.db_path)
        s_closed_1 = await create_survey(title="Закрите 1", db_path=self.db_path)
        s_closed_2 = await create_survey(title="Закрите 2", db_path=self.db_path)

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE surveys SET status = 'active' WHERE id = ?", (s_active,))
            await db.execute("UPDATE surveys SET status = 'broadcasting' WHERE id = ?", (s_broadcasting,))
            await db.execute("UPDATE surveys SET status = 'closed' WHERE id = ?", (s_closed_1,))
            await db.execute("UPDATE surveys SET status = 'closed' WHERE id = ?", (s_closed_2,))
            await db.commit()

        # Додаємо запитання та реципієнтів до закритих опитувань
        await add_survey_question(s_closed_1, 1, "Питання закрите", "text", db_path=self.db_path)
        await add_survey_recipients(s_closed_1, [301, 302], db_path=self.db_path)
        await save_survey_answer(s_closed_1, 301, 1, "Відповідь", db_path=self.db_path)

        # Перевіряємо кількість закритих опитувань
        count = await get_closed_surveys_count(db_path=self.db_path)
        self.assertEqual(count, 2)

        # Видаляємо всі закриті опитування
        deleted_count = await delete_closed_surveys(db_path=self.db_path)
        self.assertEqual(deleted_count, 2)

        # Перевіряємо, що закритих більше немає
        count_after = await get_closed_surveys_count(db_path=self.db_path)
        self.assertEqual(count_after, 0)

        # Перевіряємо, що активне та розсилка залишилися
        self.assertIsNotNone(await get_survey_by_id(s_active, db_path=self.db_path))
        self.assertIsNotNone(await get_survey_by_id(s_broadcasting, db_path=self.db_path))

        # Повторний виклик повертає 0
        deleted_again = await delete_closed_surveys(db_path=self.db_path)
        self.assertEqual(deleted_again, 0)


if __name__ == "__main__":
    unittest.main()
