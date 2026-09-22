from __future__ import annotations
import html
import logging
from typing import Optional, List, Dict, Any

from aiogram import Dispatcher, Bot, types
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from database.surveys import (
    get_survey_by_id,
    get_survey_questions,
    get_survey_recipient,
    update_survey_recipient_progress,
    mark_survey_recipient_completed,
    save_survey_answer,
    get_survey_answers_for_user
)

logger = logging.getLogger(__name__)


class SurveyTakingState(StatesGroup):
    waiting_for_free_text = State()


def _build_question_render(
    survey: Dict[str, Any],
    question: Dict[str, Any],
    current_q_idx: int,
    total_q: int
) -> tuple[str, InlineKeyboardMarkup]:
    """Будує текст та інлайн-клавіатуру для поточного запитання опитування."""
    title = survey.get("title", "Опитування BULKA")
    q_text = question.get("text", "")
    q_type = question.get("question_type", "choice")
    options = question.get("options", [])
    survey_id = survey["id"]

    text = (
        f"📋 <b>Опитування:</b> {html.escape(title)}\n"
        f"───────────────────\n"
        f"Питання <b>{current_q_idx}</b> з <b>{total_q}</b>:\n\n"
        f"<b>{html.escape(q_text)}</b>\n"
    )

    buttons = []
    if q_type == "choice":
        for opt_idx, opt_text in enumerate(options):
            buttons.append([InlineKeyboardButton(
                text=opt_text,
                callback_data=f"survey_ans:{survey_id}:{current_q_idx}:{opt_idx}"
            )])
    else:
        text += "\n✍️ <i>Будь ласка, напишіть вашу відповідь звичайним повідомленням у цей чат:</i>"

    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


async def survey_start_callback(callback: CallbackQuery, state: FSMContext):
    """Початок проходження опитування респондентом."""
    user_id = callback.from_user.id
    parts = callback.data.split(":")
    survey_id = int(parts[1])

    survey = await get_survey_by_id(survey_id)
    if not survey:
        await callback.answer("Опитування не знайдено або воно вже завершене.", show_alert=True)
        return

    recipient = await get_survey_recipient(survey_id, user_id)
    if recipient and recipient.get("status") == "completed":
        await callback.answer("Ви вже пройшли це опитування! Дякуємо за вашу активність. 🎉", show_alert=True)
        return

    questions = await get_survey_questions(survey_id)
    if not questions:
        await callback.answer("У цьому опитуванні немає активних питань.", show_alert=True)
        return

    # Перевіряємо вже збережені відповіді
    existing_answers = await get_survey_answers_for_user(survey_id, user_id)
    answered_indices = {a["question_idx"] for a in existing_answers}

    # Знаходимо перше запитання, на яке ще немає відповіді
    target_q = None
    for q in questions:
        if q["question_idx"] not in answered_indices:
            target_q = q
            break

    if not target_q:
        # Всі запитання вже мають відповіді
        await mark_survey_recipient_completed(survey_id, user_id)
        await callback.message.edit_text(
            "🎉 <b>Дякуємо за участь в опитуванні!</b>\n\n"
            "Ми цінуємо вашу думку та щодня стараємось, аби сімʼя BULKA ставала ще кращою. 🥐✨"
        )
        await callback.answer()
        return

    current_q_idx = target_q["question_idx"]
    total_q = len(questions)

    await update_survey_recipient_progress(survey_id, user_id, current_q_idx)
    text, kb = _build_question_render(survey, target_q, current_q_idx, total_q)

    if target_q["question_type"] == "text":
        await state.set_state(SurveyTakingState.waiting_for_free_text)
        await state.update_data(
            survey_id=survey_id,
            q_idx=current_q_idx,
            total_q=total_q
        )

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


async def survey_choice_answer_callback(callback: CallbackQuery, state: FSMContext):
    """Обробка відповіді на запитання з варіантами вибору."""
    user_id = callback.from_user.id
    # Format: survey_ans:{survey_id}:{q_idx}:{opt_idx}
    parts = callback.data.split(":")
    survey_id = int(parts[1])
    q_idx = int(parts[2])
    opt_idx = int(parts[3])

    survey = await get_survey_by_id(survey_id)
    questions = await get_survey_questions(survey_id)
    total_q = len(questions)

    # Знаходимо поточне питання
    current_q = next((q for q in questions if q["question_idx"] == q_idx), None)
    if not current_q:
        await callback.answer("Помилка: запитання не знайдено.", show_alert=True)
        return

    options = current_q.get("options", [])
    if opt_idx < 0 or opt_idx >= len(options):
        await callback.answer("Некоректний варіант відповіді.", show_alert=True)
        return

    chosen_answer = options[opt_idx]
    await save_survey_answer(survey_id, user_id, q_idx, chosen_answer)

    # Переходимо до наступного питання
    next_q = next((q for q in questions if q["question_idx"] == q_idx + 1), None)

    if next_q:
        await update_survey_recipient_progress(survey_id, user_id, q_idx + 1)
        next_text, next_kb = _build_question_render(survey, next_q, q_idx + 1, total_q)

        if next_q["question_type"] == "text":
            await state.set_state(SurveyTakingState.waiting_for_free_text)
            await state.update_data(
                survey_id=survey_id,
                q_idx=q_idx + 1,
                total_q=total_q
            )
        else:
            await state.clear()

        await callback.message.edit_text(next_text, reply_markup=next_kb, parse_mode="HTML")
        await callback.answer()
    else:
        # Опитування завершено
        await state.clear()
        await mark_survey_recipient_completed(survey_id, user_id)
        await callback.message.edit_text(
            "🎉 <b>Дякуємо за участь в опитуванні!</b>\n\n"
            "Ми цінуємо вашу думку та щодня стараємось, аби сімʼя BULKA ставала ще кращою. 🥐✨",
            parse_mode="HTML"
        )
        await callback.answer("Відповідь збережено!", show_alert=False)


async def survey_free_text_answer_message(message: Message, state: FSMContext):
    """Обробка текстової відповіді на відкрите питання (вільна відповідь)."""
    user_id = message.from_user.id
    user_text = message.text.strip() if message.text else ""

    if not user_text:
        await message.answer("Будь ласка, надішліть вашу відповідь у вигляді текстового повідомлення.")
        return

    data = await state.get_data()
    survey_id = data.get("survey_id")
    q_idx = data.get("q_idx")
    total_q = data.get("total_q")

    if not survey_id or not q_idx:
        await state.clear()
        return

    await save_survey_answer(survey_id, user_id, q_idx, user_text)

    survey = await get_survey_by_id(survey_id)
    questions = await get_survey_questions(survey_id)

    next_q = next((q for q in questions if q["question_idx"] == q_idx + 1), None)

    if next_q:
        await update_survey_recipient_progress(survey_id, user_id, q_idx + 1)
        next_text, next_kb = _build_question_render(survey, next_q, q_idx + 1, total_q)

        if next_q["question_type"] == "text":
            await state.update_data(q_idx=q_idx + 1)
        else:
            await state.clear()

        await message.answer(next_text, reply_markup=next_kb, parse_mode="HTML")
    else:
        await state.clear()
        await mark_survey_recipient_completed(survey_id, user_id)
        await message.answer(
            "🎉 <b>Дякуємо за участь в опитуванні!</b>\n\n"
            "Ми цінуємо вашу думку та щодня стараємось, аби сімʼя BULKA ставала ще кращою. 🥐✨",
            parse_mode="HTML"
        )


def register_survey_taking_handlers(dp: Dispatcher) -> None:
    """Реєструє обробники проходження опитування в диспетчері."""
    dp.callback_query.register(survey_start_callback, lambda c: c.data and c.data.startswith("survey_start:"))
    dp.callback_query.register(survey_choice_answer_callback, lambda c: c.data and c.data.startswith("survey_ans:"))
    dp.message.register(survey_free_text_answer_message, SurveyTakingState.waiting_for_free_text)
