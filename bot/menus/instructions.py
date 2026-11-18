from __future__ import annotations

import asyncio
import html
import io
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Union

from aiogram import Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.services.instructions_docx import (
    extract_text_from_docx_bytes,
    generate_instruction_template_docx,
    sanitize_instruction_filename,
)
from bot.services.semantic_search import build_and_reset_embeddings
from database.hr import is_developer_user
from database.instructions import (
    INSTRUCTIONS_FILES_DIR,
    create_instruction,
    delete_instruction,
    get_instruction_by_id,
    get_instructions_paginated,
    update_instruction_file,
    update_instruction_original_file,
    update_instruction_title,
)
from database.managers import is_observer_user, is_territorial_user

logger = logging.getLogger(__name__)

INSTRUCTIONS_PAGE_SIZE = 8
MAX_TELEGRAM_BOT_DOWNLOAD_BYTES = 20 * 1024 * 1024
TEMPLATE_FILENAME = "Шаблон_інструкції_BULKA.docx"


class InstructionStates(StatesGroup):
    waiting_new_title = State()
    waiting_new_file = State()
    waiting_new_original_file = State()
    waiting_edit_file = State()
    waiting_edit_original_file = State()
    waiting_edit_title = State()


async def _check_instructions_admin(event: Union[CallbackQuery, Message]) -> bool:
    """Доступ до розділу «Інструкції» дозволений виключно адміністраторам."""
    uid = event.from_user.id
    if not await is_developer_user(uid):
        return False
    if await is_observer_user(uid) or await is_territorial_user(uid):
        return False
    return True


async def _handle_start_escape(message: Message, state: FSMContext) -> bool:
    """Дозволяє вийти зі стану FSM командою /start."""
    if message.text and message.text.strip().startswith("/start"):
        await _cleanup_temp_ai_file(state)
        await state.clear()
        from bot.handlers import command_start_handler

        await command_start_handler(message, state)
        return True
    return False


async def _cleanup_temp_ai_file(state: FSMContext) -> None:
    """Видаляє тимчасово збережений локальний .docx зі стану створення, якщо процес не завершено."""
    try:
        data = await state.get_data()
    except Exception:
        return
    temp_path = data.get("new_inst_file_path")
    if temp_path and os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass


async def _safe_edit_or_send(
    target: Union[CallbackQuery, Message],
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> Message:
    """Безпечно редагує текстове повідомлення або замінює медіа/документ на текстовий екран."""
    is_cb = isinstance(target, CallbackQuery) or (hasattr(target, "data") and hasattr(target, "message"))
    msg = target.message if is_cb else target
    if is_cb and msg:
        has_media = bool(getattr(msg, "photo", None) or getattr(msg, "video", None) or getattr(msg, "document", None))
        if has_media:
            try:
                await msg.delete()
            except Exception:
                pass
            return await msg.answer(text, reply_markup=reply_markup, parse_mode="HTML")
        try:
            return await msg.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception as exc:
            if "message is not modified" in str(exc).lower():
                return msg
            try:
                await msg.delete()
            except Exception:
                pass
            return await msg.answer(text, reply_markup=reply_markup, parse_mode="HTML")
    return await msg.answer(text, reply_markup=reply_markup, parse_mode="HTML")


def _schedule_ai_reindex() -> None:
    """Асинхронно запускає переіндексацію чанків та ембедингів для ШІ без блокування UI."""
    try:
        asyncio.create_task(build_and_reset_embeddings())
    except RuntimeError:
        logger.debug("No running event loop to schedule build_and_reset_embeddings.")


def _instruction_card_keyboard(inst_id: int, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Замінити файл", callback_data=f"dev_inst_replace_menu:{inst_id}:{page}")],
            [InlineKeyboardButton(text="✏️ Змінити назву", callback_data=f"dev_inst_edit_title:{inst_id}:{page}")],
            [InlineKeyboardButton(text="🗑 Видалити", callback_data=f"dev_inst_del_ask:{inst_id}:{page}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"dev_inst_page:{page}")],
        ]
    )


def _step2_ai_file_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📥 Викачати шаблон", callback_data="dev_inst_dl_template")],
            [InlineKeyboardButton(text="⏭ Залишити пусту", callback_data="dev_inst_save_empty")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="dev_inst_add")],
        ]
    )


def _step3_original_file_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭ Залишити без оригіналу", callback_data="dev_inst_skip_orig")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="dev_inst_back_step2")],
        ]
    )


async def _send_document_from_record(
    target_msg: Message,
    inst: Dict[str, Any],
    *,
    prefix: str = "",
    caption: Optional[str] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> bool:
    """Надсилає файл інструкції (prefix='') або оригіналу (prefix='original_'). Повертає True у разі успіху."""
    f_path = inst.get(f"{prefix}file_path")
    tg_file_id = inst.get(f"{prefix}telegram_file_id")
    raw_name = inst.get(f"{prefix}file_name")
    default_name = sanitize_instruction_filename(inst.get("title"), inst.get("id"))
    f_name = raw_name or (f"original_{default_name}" if prefix else default_name)

    if f_path and os.path.exists(f_path):
        await target_msg.answer_document(
            document=FSInputFile(f_path, filename=f_name),
            caption=caption,
            reply_markup=reply_markup,
            parse_mode="HTML" if caption else None,
        )
        return True

    if tg_file_id:
        await target_msg.answer_document(
            document=tg_file_id,
            caption=caption,
            reply_markup=reply_markup,
            parse_mode="HTML" if caption else None,
        )
        return True

    return False


async def _send_instruction_document(
    target_msg: Message,
    inst: Dict[str, Any],
    caption: Optional[str] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> bool:
    """Надсилає файл інструкції для ШІ (з диска або за file_id у Telegram)."""
    return await _send_document_from_record(
        target_msg,
        inst,
        prefix="",
        caption=caption,
        reply_markup=reply_markup,
    )


async def _send_original_document(
    target_msg: Message,
    inst: Dict[str, Any],
    caption: Optional[str] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> bool:
    """Надсилає файл оригіналу інструкції (з диска або за file_id у Telegram)."""
    return await _send_document_from_record(
        target_msg,
        inst,
        prefix="original_",
        caption=caption,
        reply_markup=reply_markup,
    )


def _sanitize_original_filename(raw_name: Optional[str], topic_title: str) -> str:
    name = (raw_name or "").strip()
    base, ext = os.path.splitext(name)
    ext_clean = re.sub(r"[^a-zA-Z0-9.]", "", ext)[:12]
    if not base:
        base = topic_title or "original"
    cleaned_base = re.sub(r'[\\/*?:"<>|\r\n\t]+', "", base)
    cleaned_base = re.sub(r"[^\w\s\-'.а-яА-ЯіїєґІЇЄҐ]", "", cleaned_base, flags=re.UNICODE)
    cleaned_base = re.sub(r"\s+", "_", cleaned_base).strip("._ ") or "original"
    return f"{cleaned_base[:70]}{ext_clean}"


async def _render_instructions_menu(
    target: Union[CallbackQuery, Message],
    page: int = 1,
) -> None:
    items, total_count, total_pages = await get_instructions_paginated(
        page=page,
        page_size=INSTRUCTIONS_PAGE_SIZE,
    )
    safe_page = max(1, min(page, total_pages))

    lines = [
        "📋 <b>Інструкції для ШІ-пошуку</b>",
        "───────────────────",
        "",
        f"Всього інструкцій: <b>{total_count}</b>",
    ]
    if total_count == 0:
        lines.append("\n<i>Список порожній. Натисніть «Додати інструкцію», щоб створити першу.</i>")
    else:
        lines.append("\nОберіть інструкцію зі списку для перегляду або редагування:")

    buttons: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="➕ Додати інструкцію", callback_data="dev_inst_add")]
    ]

    for item in items:
        has_ai_file = bool(item.get("file_path") or item.get("telegram_file_id"))
        has_orig_file = bool(item.get("original_file_path") or item.get("original_telegram_file_id"))
        raw_title = (item.get("title") or f"Інструкція #{item['id']}").strip()
        short_title = raw_title if len(raw_title) <= 36 else raw_title[:33] + "..."
        if has_ai_file:
            suffix = ""
        elif has_orig_file:
            suffix = " (без ШІ)"
        else:
            suffix = " (порожня)"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"📄 {short_title}{suffix}",
                    callback_data=f"dev_inst_view:{item['id']}:{safe_page}",
                )
            ]
        )

    if total_pages > 1:
        nav_row: List[InlineKeyboardButton] = []
        if safe_page > 1:
            nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"dev_inst_page:{safe_page - 1}"))
        else:
            nav_row.append(InlineKeyboardButton(text="·", callback_data="dev_inst_noop"))
        nav_row.append(InlineKeyboardButton(text=f"{safe_page}/{total_pages}", callback_data="dev_inst_noop"))
        if safe_page < total_pages:
            nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"dev_inst_page:{safe_page + 1}"))
        else:
            nav_row.append(InlineKeyboardButton(text="·", callback_data="dev_inst_noop"))
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="dev_main_study")])
    await _safe_edit_or_send(target, "\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


async def _render_instruction_card(
    target_msg: Message,
    inst_id: int,
    page: int = 1,
    *,
    delete_source_msg: bool = False,
) -> None:
    inst = await get_instruction_by_id(inst_id)
    if not inst:
        await target_msg.answer(
            "❌ Інструкцію не знайдено.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="🔙 До списку", callback_data=f"dev_inst_page:{page}")]]
            ),
        )
        return

    if delete_source_msg:
        try:
            await target_msg.delete()
        except Exception:
            pass

    title_escaped = html.escape(inst.get("title") or "")
    has_ai = bool(inst.get("file_path") or inst.get("telegram_file_id"))
    has_orig = bool(inst.get("original_file_path") or inst.get("original_telegram_file_id"))

    ai_status = html.escape(inst.get("file_name") or "завантажено") if has_ai else "<i>не завантажено</i>"
    orig_status = html.escape(inst.get("original_file_name") or "завантажено") if has_orig else "<i>не завантажено</i>"

    kb = _instruction_card_keyboard(inst_id, page)
    card_text = (
        f"📋 <b>Інструкція: {title_escaped}</b>\n"
        f"───────────────────\n"
        f"📄 <b>Інструкція (для ШІ):</b> {ai_status}\n"
        f"📎 <b>Оригінал документа:</b> {orig_status}\n\n"
        f"🔍 <i>Пошук ШІ працює за текстом інструкції; оригінал надсилається користувачу разом із відповіддю.</i>"
    )

    if has_ai and has_orig:
        await _send_instruction_document(
            target_msg,
            inst,
            caption=f"📄 <b>Інструкція для ШІ:</b> {title_escaped}",
        )
        sent_orig = await _send_original_document(
            target_msg,
            inst,
            caption=card_text,
            reply_markup=kb,
        )
        if not sent_orig:
            await target_msg.answer(card_text, reply_markup=kb, parse_mode="HTML")
        return

    if has_ai:
        if await _send_instruction_document(target_msg, inst, caption=card_text, reply_markup=kb):
            return

    if has_orig:
        if await _send_original_document(target_msg, inst, caption=card_text, reply_markup=kb):
            return

    await target_msg.answer(card_text, reply_markup=kb, parse_mode="HTML")


async def _download_and_save_docx(
    message: Message,
    topic_title: str,
) -> tuple[str, str, str, str, str]:
    """
    Перевіряє, завантажує та парсить .docx файл із Telegram.
    Повертає (extracted_text, local_file_path, tg_file_id, orig_file_name, display_err).
    """
    doc = message.document
    if not doc:
        return "", "", "", "", "⚠️ Будь ласка, надішліть саме <b>файл інструкції</b> у форматі <code>.docx</code>."

    orig_name = doc.file_name or "instruction.docx"
    if not orig_name.lower().endswith(".docx"):
        return "", "", "", "", "⚠️ Підтримуються лише Word-документи з розширенням <code>.docx</code>."

    if (doc.file_size or 0) > MAX_TELEGRAM_BOT_DOWNLOAD_BYTES:
        return "", "", "", "", "⚠️ Розмір файлу перевищує ліміт 20 МБ."

    tg_file = await message.bot.get_file(doc.file_id)
    buf = io.BytesIO()
    await message.bot.download_file(tg_file.file_path, destination=buf)
    raw_bytes = buf.getvalue()

    try:
        extracted_text = extract_text_from_docx_bytes(raw_bytes)
    except ValueError as ve:
        return "", "", "", "", f"⚠️ {html.escape(str(ve))}"

    os.makedirs(INSTRUCTIONS_FILES_DIR, exist_ok=True)
    safe_name = sanitize_instruction_filename(topic_title)
    ts = int(time.time() * 1000)
    local_path = os.path.join(INSTRUCTIONS_FILES_DIR, f"{ts}_{safe_name}")
    with open(local_path, "wb") as fh:
        fh.write(raw_bytes)

    return extracted_text, local_path, doc.file_id, orig_name, ""


async def _download_and_save_original_document(
    message: Message,
    topic_title: str,
) -> tuple[str, str, str, str]:
    """
    Завантажує файл оригіналу інструкції будь-якого формату із Telegram.
    Повертає (local_file_path, tg_file_id, orig_file_name, display_err).
    """
    doc = message.document
    if not doc:
        return "", "", "", (
            "⚠️ Будь ласка, надішліть саме <b>файл оригіналу інструкції</b> "
            "(документ <code>.pdf</code>, <code>.docx</code> тощо)."
        )

    if (doc.file_size or 0) > MAX_TELEGRAM_BOT_DOWNLOAD_BYTES:
        return "", "", "", "⚠️ Розмір файлу перевищує ліміт 20 МБ."

    orig_name = doc.file_name or sanitize_instruction_filename(topic_title)
    tg_file = await message.bot.get_file(doc.file_id)
    buf = io.BytesIO()
    await message.bot.download_file(tg_file.file_path, destination=buf)
    raw_bytes = buf.getvalue()

    os.makedirs(INSTRUCTIONS_FILES_DIR, exist_ok=True)
    safe_name = _sanitize_original_filename(orig_name, topic_title)
    ts = int(time.time() * 1000)
    local_path = os.path.join(INSTRUCTIONS_FILES_DIR, f"orig_{ts}_{safe_name}")
    with open(local_path, "wb") as fh:
        fh.write(raw_bytes)

    return local_path, doc.file_id, orig_name, ""


# =========================================================================
# ХЕНДЛЕРИ МЕНЮ ТА ПАГІНАЦІЇ
# =========================================================================


async def dev_instructions_menu_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_instructions_admin(callback):
        await callback.answer("⛔️ Доступ дозволено лише адміністраторам.", show_alert=True)
        return

    await _cleanup_temp_ai_file(state)
    await state.clear()
    await callback.answer()
    await _render_instructions_menu(callback, page=1)


async def dev_instructions_page_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_instructions_admin(callback):
        await callback.answer("⛔️ Доступ дозволено лише адміністраторам.", show_alert=True)
        return

    await _cleanup_temp_ai_file(state)
    await state.clear()
    page = 1
    try:
        page = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        page = 1
    await callback.answer()
    await _render_instructions_menu(callback, page=page)


async def dev_instructions_noop_handler(callback: CallbackQuery) -> None:
    await callback.answer()


# =========================================================================
# СТВОРЕННЯ ІНСТРУКЦІЇ (3 КРОКИ: НАЗВА -> ІНСТРУКЦІЯ .DOCX -> ОРИГІНАЛ)
# =========================================================================


async def dev_inst_add_start_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_instructions_admin(callback):
        await callback.answer("⛔️ Доступ дозволено лише адміністраторам.", show_alert=True)
        return

    await _cleanup_temp_ai_file(state)
    await state.clear()
    await state.set_state(InstructionStates.waiting_new_title)
    text = (
        "📝 <b>Створення інструкції - Крок 1/3</b>\n"
        "───────────────────\n\n"
        "Вкажіть назву теми:"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="dev_instructions_menu")]]
    )
    await callback.answer()
    await _safe_edit_or_send(callback, text, reply_markup=kb)


async def _prompt_step2_ai_file(target_msg: Message, title: str) -> None:
    await target_msg.answer(
        f"📂 <b>Створення інструкції - Крок 2/3</b>\n"
        f"📌 Тема: <b>{html.escape(title)}</b>\n"
        f"───────────────────\n\n"
        f"Надішліть заповнений файл інструкції для ШІ у форматі <code>.docx</code>, "
        f"завантажте шаблон або залиште інструкцію порожньою:",
        reply_markup=_step2_ai_file_keyboard(),
        parse_mode="HTML",
    )


async def _prompt_step3_original_file(target: Union[CallbackQuery, Message], title: str) -> None:
    text = (
        f"📎 <b>Створення інструкції - Крок 3/3</b>\n"
        f"📌 Тема: <b>{html.escape(title)}</b>\n"
        f"───────────────────\n\n"
        f"Тепер надішліть повний <b>оригінал інструкції</b> "
        f"(документ будь-якого формату: <code>.pdf</code>, <code>.docx</code>, <code>.xlsx</code> тощо) "
        f"або натисніть «Залишити без оригіналу»:"
    )
    await _safe_edit_or_send(target, text, reply_markup=_step3_original_file_keyboard())


async def dev_inst_process_new_title(message: Message, state: FSMContext) -> None:
    if await _handle_start_escape(message, state):
        return
    if not await _check_instructions_admin(message):
        await state.clear()
        await message.answer("⛔️ Доступ дозволено лише адміністраторам.")
        return

    title = (message.text or "").strip()
    if not title:
        await message.answer(
            "⚠️ Назва теми не може бути порожньою. Вкажіть назву теми:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="dev_instructions_menu")]]
            ),
        )
        return

    await state.update_data(new_inst_title=title)
    await state.set_state(InstructionStates.waiting_new_file)
    await _prompt_step2_ai_file(message, title)


async def dev_inst_download_template_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_instructions_admin(callback):
        await callback.answer("⛔️ Доступ дозволено лише адміністраторам.", show_alert=True)
        return

    data = await state.get_data()
    title = data.get("new_inst_title")
    template_io = generate_instruction_template_docx(title)

    await callback.answer()
    if callback.message:
        await callback.message.answer_document(
            document=BufferedInputFile(template_io.getvalue(), filename=TEMPLATE_FILENAME),
            caption=(
                "📥 <b>Шаблон інструкції BULKA</b>\n\n"
                "Заповніть цей документ та надішліть його сюди у відповідь - "
                "далі бот попросить прикріпити оригінал документа."
            ),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⏭ Залишити пусту", callback_data="dev_inst_save_empty")],
                    [InlineKeyboardButton(text="🔙 Назад", callback_data="dev_inst_add")],
                ]
            ),
            parse_mode="HTML",
        )


async def dev_inst_save_empty_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Крок 2/3 -> пропуск файлу інструкції для ШІ та перехід до Кроку 3/3 (оригінал)."""
    if not await _check_instructions_admin(callback):
        await callback.answer("⛔️ Доступ дозволено лише адміністраторам.", show_alert=True)
        return

    data = await state.get_data()
    title = (data.get("new_inst_title") or "").strip()
    if not title:
        await callback.answer("⚠️ Спочатку вкажіть назву теми.", show_alert=True)
        return

    await _cleanup_temp_ai_file(state)
    await state.update_data(
        new_inst_content="",
        new_inst_file_path=None,
        new_inst_tg_file_id=None,
        new_inst_file_name=None,
    )
    await state.set_state(InstructionStates.waiting_new_original_file)
    await callback.answer()
    await _prompt_step3_original_file(callback, title)


async def dev_inst_process_new_file(message: Message, state: FSMContext) -> None:
    """Крок 2/3 -> збереження файлу інструкції для ШІ в FSM та перехід до Кроку 3/3 (оригінал)."""
    if await _handle_start_escape(message, state):
        return
    if not await _check_instructions_admin(message):
        await state.clear()
        await message.answer("⛔️ Доступ дозволено лише адміністраторам.")
        return

    data = await state.get_data()
    title = (data.get("new_inst_title") or "").strip()
    if not title:
        await state.set_state(InstructionStates.waiting_new_title)
        await message.answer("⚠️ Сесію скинуто. Вкажіть назву теми:")
        return

    extracted, local_path, tg_file_id, orig_name, err = await _download_and_save_docx(message, title)
    if err:
        await message.answer(err, reply_markup=_step2_ai_file_keyboard(), parse_mode="HTML")
        return

    await _cleanup_temp_ai_file(state)
    await state.update_data(
        new_inst_content=extracted,
        new_inst_file_path=local_path,
        new_inst_tg_file_id=tg_file_id,
        new_inst_file_name=orig_name,
    )
    await state.set_state(InstructionStates.waiting_new_original_file)
    await _prompt_step3_original_file(message, title)


async def dev_inst_back_to_step2_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Повертає з Кроку 3/3 на Крок 2/3, очищаючи тимчасово завантажений .docx."""
    if not await _check_instructions_admin(callback):
        await callback.answer("⛔️ Доступ дозволено лише адміністраторам.", show_alert=True)
        return

    data = await state.get_data()
    title = (data.get("new_inst_title") or "").strip()
    if not title:
        await dev_inst_add_start_handler(callback, state)
        return

    await _cleanup_temp_ai_file(state)
    await state.update_data(
        new_inst_content="",
        new_inst_file_path=None,
        new_inst_tg_file_id=None,
        new_inst_file_name=None,
    )
    await state.set_state(InstructionStates.waiting_new_file)
    await callback.answer()
    if callback.message:
        await _safe_edit_or_send(
            callback,
            f"📂 <b>Створення інструкції - Крок 2/3</b>\n"
            f"📌 Тема: <b>{html.escape(title)}</b>\n"
            f"───────────────────\n\n"
            f"Надішліть заповнений файл інструкції для ШІ у форматі <code>.docx</code>, "
            f"завантажте шаблон або залиште інструкцію порожньою:",
            reply_markup=_step2_ai_file_keyboard(),
        )


async def _finalize_new_instruction(
    target_msg: Message,
    state: FSMContext,
    user_id: int,
    *,
    original_file_path: Optional[str] = None,
    original_telegram_file_id: Optional[str] = None,
    original_file_name: Optional[str] = None,
    delete_source_msg: bool = False,
) -> Optional[int]:
    data = await state.get_data()
    title = (data.get("new_inst_title") or "").strip()
    if not title:
        return None

    content = data.get("new_inst_content") or ""
    inst_id = await create_instruction(
        title=title,
        content=content,
        file_path=data.get("new_inst_file_path"),
        telegram_file_id=data.get("new_inst_tg_file_id"),
        file_name=data.get("new_inst_file_name"),
        original_file_path=original_file_path,
        original_telegram_file_id=original_telegram_file_id,
        original_file_name=original_file_name,
        created_by=user_id,
    )
    await state.clear()
    if content.strip():
        _schedule_ai_reindex()

    if delete_source_msg:
        try:
            await target_msg.delete()
        except Exception:
            pass

    if content.strip():
        await target_msg.answer("✅ Інструкцію збережено та додано до пошуку ШІ!")
    else:
        await target_msg.answer("✅ Інструкцію збережено!")
    await _render_instruction_card(target_msg, inst_id, page=1, delete_source_msg=False)
    return inst_id


async def dev_inst_skip_original_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_instructions_admin(callback):
        await callback.answer("⛔️ Доступ дозволено лише адміністраторам.", show_alert=True)
        return

    data = await state.get_data()
    if not (data.get("new_inst_title") or "").strip():
        await callback.answer("⚠️ Спочатку вкажіть назву теми.", show_alert=True)
        return

    await callback.answer("✅ Інструкцію створено!")
    if callback.message:
        await _finalize_new_instruction(
            callback.message,
            state,
            callback.from_user.id,
            delete_source_msg=True,
        )


async def dev_inst_process_new_original_file(message: Message, state: FSMContext) -> None:
    if await _handle_start_escape(message, state):
        return
    if not await _check_instructions_admin(message):
        await _cleanup_temp_ai_file(state)
        await state.clear()
        await message.answer("⛔️ Доступ дозволено лише адміністраторам.")
        return

    data = await state.get_data()
    title = (data.get("new_inst_title") or "").strip()
    if not title:
        await state.set_state(InstructionStates.waiting_new_title)
        await message.answer("⚠️ Сесію скинуто. Вкажіть назву теми:")
        return

    orig_path, orig_tg_id, orig_name, err = await _download_and_save_original_document(message, title)
    if err:
        await message.answer(err, reply_markup=_step3_original_file_keyboard(), parse_mode="HTML")
        return

    await _finalize_new_instruction(
        message,
        state,
        message.from_user.id,
        original_file_path=orig_path,
        original_telegram_file_id=orig_tg_id,
        original_file_name=orig_name,
        delete_source_msg=False,
    )


# =========================================================================
# ПЕРЕГЛЯД ІНСТРУКЦІЇ ТА РЕДАГУВАННЯ
# =========================================================================


async def dev_inst_view_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_instructions_admin(callback):
        await callback.answer("⛔️ Доступ дозволено лише адміністраторам.", show_alert=True)
        return

    await state.clear()
    parts = callback.data.split(":")
    inst_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 1

    await callback.answer()
    if callback.message:
        await _render_instruction_card(callback.message, inst_id, page=page, delete_source_msg=True)


async def dev_inst_replace_menu_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Відкриває вибір: замінити інструкцію для ШІ або замінити оригінал інструкції."""
    if not await _check_instructions_admin(callback):
        await callback.answer("⛔️ Доступ дозволено лише адміністраторам.", show_alert=True)
        return

    await state.clear()
    parts = callback.data.split(":")
    inst_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 1

    inst = await get_instruction_by_id(inst_id)
    if not inst:
        await callback.answer("❌ Інструкцію не знайдено.", show_alert=True)
        return

    await callback.answer()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📄 Замінити інструкцію", callback_data=f"dev_inst_edit_file:{inst_id}:{page}")],
            [InlineKeyboardButton(text="📎 Замінити оригінал інструкції", callback_data=f"dev_inst_edit_orig:{inst_id}:{page}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"dev_inst_view:{inst_id}:{page}")],
        ]
    )
    await _safe_edit_or_send(
        callback,
        f"🔄 <b>Заміна файлів: {html.escape(inst['title'])}</b>\n\nОберіть, який файл бажаєте замінити:",
        reply_markup=kb,
    )


async def dev_inst_edit_file_start_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_instructions_admin(callback):
        await callback.answer("⛔️ Доступ дозволено лише адміністраторам.", show_alert=True)
        return

    parts = callback.data.split(":")
    inst_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 1

    inst = await get_instruction_by_id(inst_id)
    if not inst:
        await callback.answer("❌ Інструкцію не знайдено.", show_alert=True)
        return

    await state.set_state(InstructionStates.waiting_edit_file)
    await state.update_data(edit_inst_id=inst_id, edit_inst_page=page)
    await callback.answer()

    msg = callback.message
    if not msg:
        return

    # 1. Надсилаємо поточний файл інструкції (якщо він є)
    await _send_instruction_document(
        msg,
        inst,
        caption=f"📄 <b>Поточний файл інструкції:</b> {html.escape(inst['title'])}",
    )

    # 2. Надсилаємо шаблон
    template_io = generate_instruction_template_docx(inst["title"])
    await msg.answer_document(
        document=BufferedInputFile(template_io.getvalue(), filename=TEMPLATE_FILENAME),
        caption="📥 <b>Шаблон для заповнення</b>",
        parse_mode="HTML",
    )

    # 3. Запитуємо новий файл (лише .docx) + кнопка Назад
    await msg.answer(
        f"🔄 <b>Оновлення файлу інструкції (для ШІ): {html.escape(inst['title'])}</b>\n\n"
        f"Надішліть новий файл інструкції у форматі <code>.docx</code> (лише файл):",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data=f"dev_inst_view:{inst_id}:{page}")]]
        ),
        parse_mode="HTML",
    )


async def dev_inst_process_edit_file(message: Message, state: FSMContext) -> None:
    if await _handle_start_escape(message, state):
        return
    if not await _check_instructions_admin(message):
        await state.clear()
        await message.answer("⛔️ Доступ дозволено лише адміністраторам.")
        return

    data = await state.get_data()
    inst_id = data.get("edit_inst_id")
    page = int(data.get("edit_inst_page") or 1)

    inst = await get_instruction_by_id(inst_id) if inst_id else None
    if not inst:
        await state.clear()
        await message.answer("❌ Інструкцію не знайдено.")
        return

    extracted, local_path, tg_file_id, orig_name, err = await _download_and_save_docx(message, inst["title"])
    if err:
        await message.answer(
            err,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data=f"dev_inst_view:{inst_id}:{page}")]]
            ),
            parse_mode="HTML",
        )
        return

    await update_instruction_file(
        inst_id=inst_id,
        content=extracted,
        file_path=local_path,
        telegram_file_id=tg_file_id,
        file_name=orig_name,
    )
    await state.clear()
    _schedule_ai_reindex()

    await message.answer("✅ Файл інструкції оновлено та переіндексовано для пошуку ШІ!")
    await _render_instruction_card(message, inst_id, page=page, delete_source_msg=False)


async def dev_inst_edit_orig_start_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_instructions_admin(callback):
        await callback.answer("⛔️ Доступ дозволено лише адміністраторам.", show_alert=True)
        return

    parts = callback.data.split(":")
    inst_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 1

    inst = await get_instruction_by_id(inst_id)
    if not inst:
        await callback.answer("❌ Інструкцію не знайдено.", show_alert=True)
        return

    await state.set_state(InstructionStates.waiting_edit_original_file)
    await state.update_data(edit_inst_id=inst_id, edit_inst_page=page)
    await callback.answer()

    msg = callback.message
    if not msg:
        return

    await _send_original_document(
        msg,
        inst,
        caption=f"📎 <b>Поточний оригінал інструкції:</b> {html.escape(inst['title'])}",
    )

    await msg.answer(
        f"📎 <b>Оновлення оригіналу інструкції: {html.escape(inst['title'])}</b>\n\n"
        f"Надішліть новий повний файл оригіналу (<code>.pdf</code>, <code>.docx</code>, <code>.xlsx</code> тощо):",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data=f"dev_inst_view:{inst_id}:{page}")]]
        ),
        parse_mode="HTML",
    )


async def dev_inst_process_edit_orig_file(message: Message, state: FSMContext) -> None:
    if await _handle_start_escape(message, state):
        return
    if not await _check_instructions_admin(message):
        await state.clear()
        await message.answer("⛔️ Доступ дозволено лише адміністраторам.")
        return

    data = await state.get_data()
    inst_id = data.get("edit_inst_id")
    page = int(data.get("edit_inst_page") or 1)

    inst = await get_instruction_by_id(inst_id) if inst_id else None
    if not inst:
        await state.clear()
        await message.answer("❌ Інструкцію не знайдено.")
        return

    local_path, tg_file_id, orig_name, err = await _download_and_save_original_document(message, inst["title"])
    if err:
        await message.answer(
            err,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data=f"dev_inst_view:{inst_id}:{page}")]]
            ),
            parse_mode="HTML",
        )
        return

    await update_instruction_original_file(
        inst_id=inst_id,
        original_file_path=local_path,
        original_telegram_file_id=tg_file_id,
        original_file_name=orig_name,
    )
    await state.clear()

    await message.answer("✅ Оригінал інструкції оновлено!")
    await _render_instruction_card(message, inst_id, page=page, delete_source_msg=False)


async def dev_inst_edit_title_start_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_instructions_admin(callback):
        await callback.answer("⛔️ Доступ дозволено лише адміністраторам.", show_alert=True)
        return

    parts = callback.data.split(":")
    inst_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 1

    inst = await get_instruction_by_id(inst_id)
    if not inst:
        await callback.answer("❌ Інструкцію не знайдено.", show_alert=True)
        return

    await state.set_state(InstructionStates.waiting_edit_title)
    await state.update_data(edit_inst_id=inst_id, edit_inst_page=page)
    await callback.answer()
    await _safe_edit_or_send(
        callback,
        f"✏️ <b>Зміна назви інструкції</b>\n"
        f"Поточна назва: <b>{html.escape(inst['title'])}</b>\n\n"
        f"Надішліть нову назву теми:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data=f"dev_inst_view:{inst_id}:{page}")]]
        ),
    )


async def dev_inst_process_edit_title(message: Message, state: FSMContext) -> None:
    if await _handle_start_escape(message, state):
        return
    if not await _check_instructions_admin(message):
        await state.clear()
        await message.answer("⛔️ Доступ дозволено лише адміністраторам.")
        return

    data = await state.get_data()
    inst_id = data.get("edit_inst_id")
    page = int(data.get("edit_inst_page") or 1)
    new_title = (message.text or "").strip()

    if not new_title:
        await message.answer(
            "⚠️ Назва не може бути порожньою. Введіть нову назву:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data=f"dev_inst_view:{inst_id}:{page}")]]
            ),
        )
        return

    ok = await update_instruction_title(inst_id, new_title)
    await state.clear()
    if ok:
        _schedule_ai_reindex()
        await message.answer("✅ Назву інструкції оновлено!")
        await _render_instruction_card(message, inst_id, page=page, delete_source_msg=False)
    else:
        await message.answer("❌ Інструкцію не знайдено.")


# =========================================================================
# ВИДАЛЕННЯ ІНСТРУКЦІЇ
# =========================================================================


async def dev_inst_delete_ask_handler(callback: CallbackQuery) -> None:
    if not await _check_instructions_admin(callback):
        await callback.answer("⛔️ Доступ дозволено лише адміністраторам.", show_alert=True)
        return

    parts = callback.data.split(":")
    inst_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 1

    inst = await get_instruction_by_id(inst_id)
    if not inst:
        await callback.answer("❌ Інструкцію не знайдено.", show_alert=True)
        return

    await callback.answer()
    await _safe_edit_or_send(
        callback,
        f"⚠️ <b>Видалення інструкції</b>\n\n"
        f"Ви дійсно бажаєте видалити інструкцію «<b>{html.escape(inst['title'])}</b>»?\n"
        f"<i>Обидва файли та текст інструкції буде вилучено також із пошуку ШІ.</i>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Так, видалити", callback_data=f"dev_inst_del_do:{inst_id}:{page}")],
                [InlineKeyboardButton(text="🔙 Скасувати", callback_data=f"dev_inst_view:{inst_id}:{page}")],
            ]
        ),
    )


async def dev_inst_delete_do_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_instructions_admin(callback):
        await callback.answer("⛔️ Доступ дозволено лише адміністраторам.", show_alert=True)
        return

    parts = callback.data.split(":")
    inst_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 1

    deleted = await delete_instruction(inst_id)
    await state.clear()
    if deleted:
        _schedule_ai_reindex()
        await callback.answer("🗑 Інструкцію видалено!", show_alert=True)
    else:
        await callback.answer("❌ Інструкцію не знайдено.", show_alert=True)

    await _render_instructions_menu(callback, page=page)


# =========================================================================
# РЕЄСТРАЦІЯ ХЕНДЛЕРІВ
# =========================================================================


def register_instructions_handlers(dp: Dispatcher) -> None:
    """Реєструє всі обробники підрозділу «Інструкції» для адміністраторів."""
    dp.callback_query.register(dev_instructions_menu_handler, lambda c: c.data == "dev_instructions_menu")
    dp.callback_query.register(dev_instructions_page_handler, lambda c: c.data and c.data.startswith("dev_inst_page:"))
    dp.callback_query.register(dev_instructions_noop_handler, lambda c: c.data == "dev_inst_noop")

    # Створення (Крок 1: назва -> Крок 2: файл .docx для ШІ -> Крок 3: оригінал документа)
    dp.callback_query.register(dev_inst_add_start_handler, lambda c: c.data == "dev_inst_add")
    dp.message.register(dev_inst_process_new_title, InstructionStates.waiting_new_title)
    dp.callback_query.register(dev_inst_download_template_handler, lambda c: c.data == "dev_inst_dl_template")
    dp.callback_query.register(dev_inst_save_empty_handler, lambda c: c.data == "dev_inst_save_empty")
    dp.message.register(dev_inst_process_new_file, InstructionStates.waiting_new_file)
    dp.callback_query.register(dev_inst_back_to_step2_handler, lambda c: c.data == "dev_inst_back_step2")
    dp.callback_query.register(dev_inst_skip_original_handler, lambda c: c.data == "dev_inst_skip_orig")
    dp.message.register(dev_inst_process_new_original_file, InstructionStates.waiting_new_original_file)

    # Перегляд та редагування
    dp.callback_query.register(dev_inst_view_handler, lambda c: c.data and c.data.startswith("dev_inst_view:"))
    dp.callback_query.register(dev_inst_replace_menu_handler, lambda c: c.data and c.data.startswith("dev_inst_replace_menu:"))
    dp.callback_query.register(dev_inst_edit_file_start_handler, lambda c: c.data and c.data.startswith("dev_inst_edit_file:"))
    dp.message.register(dev_inst_process_edit_file, InstructionStates.waiting_edit_file)
    dp.callback_query.register(dev_inst_edit_orig_start_handler, lambda c: c.data and c.data.startswith("dev_inst_edit_orig:"))
    dp.message.register(dev_inst_process_edit_orig_file, InstructionStates.waiting_edit_original_file)
    dp.callback_query.register(dev_inst_edit_title_start_handler, lambda c: c.data and c.data.startswith("dev_inst_edit_title:"))
    dp.message.register(dev_inst_process_edit_title, InstructionStates.waiting_edit_title)

    # Видалення
    dp.callback_query.register(dev_inst_delete_ask_handler, lambda c: c.data and c.data.startswith("dev_inst_del_ask:"))
    dp.callback_query.register(dev_inst_delete_do_handler, lambda c: c.data and c.data.startswith("dev_inst_del_do:"))
