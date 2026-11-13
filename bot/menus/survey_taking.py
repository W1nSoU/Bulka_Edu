from __future__ import annotations
import html
import json
import logging
from typing import Optional, List, Dict, Any, Set, Tuple

from aiogram import Dispatcher, Bot, types
from aiogram.exceptions import TelegramBadRequest
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

SURVEY_COMPLETED_TEXT = (
    "🎉 <b>Дякуємо за участь в опитуванні!</b>\n\n"
    "Ми цінуємо вашу думку та щодня стараємось, аби команда BULKA ставала ще кращою. 🥐✨"
)


class SurveyTakingState(StatesGroup):
    waiting_for_free_text = State()


def _build_question_render(
    survey: Dict[str, Any],
    question: Dict[str, Any],
    current_q_idx: int,
    total_q: int,
    selected_mask: int = 0
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
    elif q_type == "multi_choice":
        text += "\n<i>☑️ Можна обрати кілька варіантів і натиснути «Підтвердити»:</i>"
        selected_count = 0
        for opt_idx, opt_text in enumerate(options):
            is_selected = bool((selected_mask >> opt_idx) & 1)
            if is_selected:
                selected_count += 1
            new_mask = selected_mask ^ (1 << opt_idx)
            mark = "✅" if is_selected else "⬜️"
            buttons.append([InlineKeyboardButton(
                text=f"{mark} {opt_text}",
                callback_data=f"survey_mt:{survey_id}:{current_q_idx}:{new_mask}"
            )])
        confirm_text = f"✅ Підтвердити ({selected_count})" if selected_count > 0 else "✅ Підтвердити вибір"
        buttons.append([InlineKeyboardButton(
            text=confirm_text,
            callback_data=f"survey_mc:{survey_id}:{current_q_idx}:{selected_mask}"
        )])
    else:
        text += "\n✍️ <i>Будь ласка, напишіть вашу відповідь звичайним повідомленням у цей чат:</i>"

    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


async def _deliver_next_or_complete(
    target_message: Message,
    state: FSMContext,
    survey: Dict[str, Any],
    questions: List[Dict[str, Any]],
    user_id: int,
    answered_indices: Set[int],
    use_edit: bool,
    callback: Optional[CallbackQuery] = None,
    completion_toast: Optional[str] = None
) -> None:
    """Показує перше запитання без відповіді або завершує опитування."""
    next_q = next((q for q in questions if q["question_idx"] not in answered_indices), None)
    survey_id = survey["id"]
    total_q = len(questions)

    if next_q:
        next_q_idx = next_q["question_idx"]
        await update_survey_recipient_progress(survey_id, user_id, next_q_idx)
        next_text, next_kb = _build_question_render(survey, next_q, next_q_idx, total_q)

        if next_q["question_type"] == "text":
            await state.set_state(SurveyTakingState.waiting_for_free_text)
            await state.update_data(
                survey_id=survey_id,
                q_idx=next_q_idx,
                total_q=total_q
            )
        else:
            await state.clear()

        if use_edit:
            await target_message.edit_text(next_text, reply_markup=next_kb, parse_mode="HTML")
        else:
            await target_message.answer(next_text, reply_markup=next_kb, parse_mode="HTML")

        if callback:
            await callback.answer()
        return

    await state.clear()
    await mark_survey_recipient_completed(survey_id, user_id)
    if use_edit:
        await target_message.edit_text(SURVEY_COMPLETED_TEXT, parse_mode="HTML")
    else:
        await target_message.answer(SURVEY_COMPLETED_TEXT, parse_mode="HTML")

    if callback:
        if completion_toast:
            await callback.answer(completion_toast, show_alert=False)
        else:
            await callback.answer()


async def _validate_question_callback(
    callback: CallbackQuery,
    expected_type: str
) -> Optional[Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any], int, Set[int]]]:
    """Валідує стан опитування, тип питання та відсутність повторної відповіді."""
    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        await callback.answer("Некоректні дані кнопки.", show_alert=True)
        return None
    try:
        survey_id = int(parts[1])
        q_idx = int(parts[2])
        payload_val = int(parts[3])
    except ValueError:
        await callback.answer("Некоректні дані кнопки.", show_alert=True)
        return None

    user_id = callback.from_user.id
    survey = await get_survey_by_id(survey_id)
    if not survey or survey.get("status") == "closed":
        await callback.answer("Опитування не знайдено або воно вже завершене.", show_alert=True)
        return None

    recipient = await get_survey_recipient(survey_id, user_id)
    if recipient and recipient.get("status") == "completed":
        await callback.answer("Ви вже пройшли це опитування! Дякуємо за вашу активність. 🎉", show_alert=True)
        return None

    questions = await get_survey_questions(survey_id)
    current_q = next((q for q in questions if q["question_idx"] == q_idx), None)
    if not current_q or current_q.get("question_type") != expected_type:
        await callback.answer("Помилка: запитання не знайдено або формат змінився.", show_alert=True)
        return None

    existing_answers = await get_survey_answers_for_user(survey_id, user_id)
    answered_indices = {a["question_idx"] for a in existing_answers}
    if q_idx in answered_indices:
        await callback.answer("Ви вже відповіли на це питання.", show_alert=True)
        return None

    return survey, questions, current_q, payload_val, answered_indices


async def survey_start_callback(callback: CallbackQuery, state: FSMContext):
    """Початок проходження опитування респондентом."""
    user_id = callback.from_user.id
    parts = callback.data.split(":")
    survey_id = int(parts[1])

    survey = await get_survey_by_id(survey_id)
    if not survey or survey.get("status") == "closed":
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

    await _deliver_next_or_complete(
        callback.message, state, survey, questions, user_id, answered_indices,
        use_edit=True, callback=callback
    )


async def survey_choice_answer_callback(callback: CallbackQuery, state: FSMContext):
    """Обробка відповіді на запитання з вибором одного варіанту."""
    validated = await _validate_question_callback(callback, expected_type="choice")
    if not validated:
        return
    survey, questions, current_q, opt_idx, answered_indices = validated
    survey_id = survey["id"]
    q_idx = current_q["question_idx"]
    user_id = callback.from_user.id

    options = current_q.get("options", [])
    if opt_idx < 0 or opt_idx >= len(options):
        await callback.answer("Некоректний варіант відповіді.", show_alert=True)
        return

    chosen_answer = options[opt_idx]
    await save_survey_answer(survey_id, user_id, q_idx, chosen_answer)
    answered_indices.add(q_idx)

    await _deliver_next_or_complete(
        callback.message, state, survey, questions, user_id, answered_indices,
        use_edit=True, callback=callback, completion_toast="Відповідь збережено!"
    )


async def survey_multi_toggle_callback(callback: CallbackQuery, state: FSMContext):
    """Перемикання прапорця варіанта у питанні з вибором кількох варіантів."""
    validated = await _validate_question_callback(callback, expected_type="multi_choice")
    if not validated:
        return
    survey, questions, current_q, new_mask, _ = validated
    q_idx = current_q["question_idx"]
    options = current_q.get("options", [])

    if new_mask < 0 or new_mask >= (1 << len(options)):
        await callback.answer("Некоректний вибір варіантів.", show_alert=True)
        return

    _, updated_kb = _build_question_render(survey, current_q, q_idx, len(questions), selected_mask=new_mask)
    try:
        await callback.message.edit_reply_markup(reply_markup=updated_kb)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise
    await callback.answer()


async def survey_multi_confirm_callback(callback: CallbackQuery, state: FSMContext):
    """Підтвердження обраних варіантів у питанні з мультивибором."""
    validated = await _validate_question_callback(callback, expected_type="multi_choice")
    if not validated:
        return
    survey, questions, current_q, selected_mask, answered_indices = validated
    survey_id = survey["id"]
    q_idx = current_q["question_idx"]
    user_id = callback.from_user.id
    options = current_q.get("options", [])

    if selected_mask <= 0:
        await callback.answer("⚠️ Оберіть хоча б один варіант!", show_alert=True)
        return

    selected_options = [opt for i, opt in enumerate(options) if (selected_mask >> i) & 1]
    if not selected_options:
        await callback.answer("⚠️ Оберіть хоча б один варіант!", show_alert=True)
        return

    answer_payload = json.dumps(selected_options, ensure_ascii=False)
    await save_survey_answer(survey_id, user_id, q_idx, answer_payload)
    answered_indices.add(q_idx)

    await _deliver_next_or_complete(
        callback.message, state, survey, questions, user_id, answered_indices,
        use_edit=True, callback=callback, completion_toast="Відповідь збережено!"
    )


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

    if not survey_id or not q_idx:
        await state.clear()
        return

    survey = await get_survey_by_id(survey_id)
    if not survey or survey.get("status") == "closed":
        await state.clear()
        await message.answer("Опитування не знайдено або воно вже завершене.")
        return

    await save_survey_answer(survey_id, user_id, q_idx, user_text)

    questions = await get_survey_questions(survey_id)
    existing_answers = await get_survey_answers_for_user(survey_id, user_id)
    answered_indices = {a["question_idx"] for a in existing_answers}
    answered_indices.add(q_idx)

    await _deliver_next_or_complete(
        message, state, survey, questions, user_id, answered_indices,
        use_edit=False
    )


def register_survey_taking_handlers(dp: Dispatcher) -> None:
    """Реєструє обробники проходження опитування в диспетчері."""
    dp.callback_query.register(survey_start_callback, lambda c: c.data and c.data.startswith("survey_start:"))
    dp.callback_query.register(survey_choice_answer_callback, lambda c: c.data and c.data.startswith("survey_ans:"))
    dp.callback_query.register(survey_multi_toggle_callback, lambda c: c.data and c.data.startswith("survey_mt:"))
    dp.callback_query.register(survey_multi_confirm_callback, lambda c: c.data and c.data.startswith("survey_mc:"))
    dp.message.register(survey_free_text_answer_message, SurveyTakingState.waiting_for_free_text)
