from aiogram import Dispatcher
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext

from bot.state import TestStates, initialize_user_progress, user_progress
from bot.services.testing_service import get_test_data, render_test_question
from database.users import update_progress, get_user_details
from bot.services.reminders import notify_manager_test_failed
import aiosqlite
from database import DB_PATH
from datetime import datetime

async def start_test_handler(callback: CallbackQuery, state: FSMContext):
    """Starts the test for the given day."""
    user_id = callback.from_user.id
    # data format: dayX_test
    try:
        day = int(callback.data.replace("day", "").replace("_test", ""))
    except ValueError:
        await callback.answer("Помилка ідентифікації дня.")
        return

    user_details = await get_user_details(user_id)
    role = user_details.get("role", "ALL") if user_details else "ALL"
    
    questions = await get_test_data(role, day)
    
    if not questions:
        # Fallback if no test is found in DB
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Завершити день", callback_data=f"complete_day_{day}")]
        ])
        await callback.message.edit_text(
            f"📝 <b>Тест для Дня {day}</b>\n\n"
            "На даний момент тестування проходить оновлення.\n"
            "Ви можете позначити цей день як завершений автоматично, щоб продовжити навчання.",
            reply_markup=kb
        )
        return

    # Initialize state
    await state.set_state(TestStates.answering_questions)
    await state.update_data(
        test_questions=questions,
        current_q_idx=0,
        test_day=day,
        test_role=role
    )
    
    text, kb = await render_test_question(questions, 0, day)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

async def process_test_answer_handler(callback: CallbackQuery, state: FSMContext):
    """Processes an answer to a test question."""
    data = await state.get_data()
    questions = data.get("test_questions")
    current_idx = data.get("current_q_idx")
    day = data.get("test_day")
    role = data.get("test_role", "ALL")
    
    if not questions or current_idx is None:
        await callback.answer("Помилка сесії тестування. Почніть спочатку.")
        await state.clear()
        return

    # callback_data format: test_ans:{day}:{question_idx}:{answer_idx}
    try:
        _, _, _, answer_idx = callback.data.split(":")
        answer_idx = int(answer_idx)
    except (ValueError, IndexError):
        return

    correct_idx = questions[current_idx]["correct_index"]
    
    if answer_idx == correct_idx:
        # Correct answer
        next_idx = current_idx + 1
        if next_idx < len(questions):
            # Move to next question
            await state.update_data(current_q_idx=next_idx)
            text, kb = await render_test_question(questions, next_idx, day)
            await callback.message.edit_text(text, reply_markup=kb)
            await callback.answer("Вірно! ✅", show_alert=False)
        else:
            # Test finished successfully
            await _finish_test_successfully(callback, state, day)
    else:
        # Wrong answer
        await callback.answer("Невірно! ❌ Спробуйте ще раз.", show_alert=True)
        # Increment error count
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT INTO test_errors (role, day, question_idx, error_count, last_reset_at)
                VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(role, day, question_idx) DO UPDATE SET
                    error_count = error_count + 1
                """,
                (role, day, current_idx)
            )
            await db.commit()

async def _finish_test_successfully(callback: CallbackQuery, state: FSMContext, day: int):
    """Handles the successful completion of the test."""
    user_id = callback.from_user.id
    initialize_user_progress(user_id)
    
    # Update progress in DB
    completed_at = await update_progress(user_id, day, True)
    
    # Update local cache
    if user_id not in user_progress:
        user_progress[user_id] = {}
    
    user_progress[user_id][f"day_{day}"] = {
        "completed": True,
        "completed_at": completed_at
    }
    
    await callback.answer("Тест успішно пройдено! 🎉", show_alert=True)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Повернутися до блоків навчання", callback_data="continue_learning")]
    ])
    
    await callback.message.edit_text(
        f"🎉 <b>Вітаємо! Тест за День {day} пройдено.</b>\n\n"
        "Ваш прогрес збережено. Ви можете переходити до наступного дня.",
        reply_markup=kb
    )
    await state.clear()

def register_day_handlers(dp: Dispatcher):
    # Dynamic handler for any day start test
    dp.callback_query.register(start_test_handler, lambda c: c.data and c.data.startswith("day") and c.data.endswith("_test"))
    # Handler for test answers
    dp.callback_query.register(process_test_answer_handler, lambda c: c.data and c.data.startswith("test_ans:"), TestStates.answering_questions)