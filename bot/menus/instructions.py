from __future__ import annotations

import asyncio
import html
import io
import logging
import os
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
    waiting_edit_file = State()
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
        await state.clear()
        from bot.handlers import command_start_handler

        await command_start_handler(message, state)
        return True
    return False


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
            [InlineKeyboardButton(text="🔄 Змінити файл", callback_data=f"dev_inst_edit_file:{inst_id}:{page}")],
            [InlineKeyboardButton(text="✏️ Змінити назву", callback_data=f"dev_inst_edit_title:{inst_id}:{page}")],
            [InlineKeyboardButton(text="🗑 Видалити", callback_data=f"dev_inst_del_ask:{inst_id}:{page}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"dev_inst_page:{page}")],
        ]
    )


async def _send_instruction_document(
    target_msg: Message,
    inst: Dict[str, Any],
    caption: Optional[str] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> bool:
    """Надсилає файл інструкції (з диска або за file_id у Telegram). Повертає True, якщо файл надіслано."""
    f_path = inst.get("file_path")
    tg_file_id = inst.get("telegram_file_id")
    f_name = inst.get("file_name") or sanitize_instruction_filename(inst.get("title"), inst.get("id"))

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
        has_file = bool(item.get("file_path") or item.get("telegram_file_id"))
        raw_title = (item.get("title") or f"Інструкція #{item['id']}").strip()
        short_title = raw_title if len(raw_title) <= 38 else raw_title[:35] + "..."
        suffix = "" if has_file else " (порожня)"
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
    kb = _instruction_card_keyboard(inst_id, page)
    caption = (
        f"📋 <b>Інструкція: {title_escaped}</b>\n"
        f"───────────────────\n"
        f"🔍 <i>Індексується в пошуку ШІ разом із навчальними матеріалами.</i>"
    )

    sent_doc = await _send_instruction_document(target_msg, inst, caption=caption, reply_markup=kb)
    if not sent_doc:
        empty_text = (
            f"📋 <b>Інструкція: {title_escaped}</b>\n"
            f"───────────────────\n"
            f"⚠️ <i>Файл інструкції ще не завантажено (порожня інструкція).</i>"
        )
        await target_msg.answer(empty_text, reply_markup=kb, parse_mode="HTML")


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


# =========================================================================
# ХЕНДЛЕРИ МЕНЮ ТА ПАГІНАЦІЇ
# =========================================================================


async def dev_instructions_menu_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_instructions_admin(callback):
        await callback.answer("⛔️ Доступ дозволено лише адміністраторам.", show_alert=True)
        return

    await state.clear()
    await callback.answer()
    await _render_instructions_menu(callback, page=1)


async def dev_instructions_page_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_instructions_admin(callback):
        await callback.answer("⛔️ Доступ дозволено лише адміністраторам.", show_alert=True)
        return

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
# СТВОРЕННЯ ІНСТРУКЦІЇ
# =========================================================================


async def dev_inst_add_start_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _check_instructions_admin(callback):
        await callback.answer("⛔️ Доступ дозволено лише адміністраторам.", show_alert=True)
        return

    await state.clear()
    await state.set_state(InstructionStates.waiting_new_title)
    text = (
        "📝 <b>Створення інструкції — Крок 1/2</b>\n"
        "───────────────────\n\n"
        "Вкажіть назву теми:"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="dev_instructions_menu")]]
    )
    await callback.answer()
    await _safe_edit_or_send(callback, text, reply_markup=kb)


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

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📥 Викачати шаблон", callback_data="dev_inst_dl_template")],
            [InlineKeyboardButton(text="⏭ Залишити пусту", callback_data="dev_inst_save_empty")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="dev_inst_add")],
        ]
    )
    await message.answer(
        f"📂 <b>Створення інструкції — Крок 2/2</b>\n"
        f"📌 Тема: <b>{html.escape(title)}</b>\n"
        f"───────────────────\n\n"
        f"Надішліть заповнений файл інструкції у форматі <code>.docx</code>, "
        f"завантажте шаблон або залиште інструкцію порожньою:",
        reply_markup=kb,
        parse_mode="HTML",
    )


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
                "Заповніть цей документ та надішліть його сюди у відповідь — "
                "бот автоматично збереже інструкцію та додасть її в пошук ШІ."
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
    if not await _check_instructions_admin(callback):
        await callback.answer("⛔️ Доступ дозволено лише адміністраторам.", show_alert=True)
        return

    data = await state.get_data()
    title = (data.get("new_inst_title") or "").strip()
    if not title:
        await callback.answer("⚠️ Спочатку вкажіть назву теми.", show_alert=True)
        return

    inst_id = await create_instruction(
        title=title,
        content="",
        file_path=None,
        telegram_file_id=None,
        file_name=None,
        created_by=callback.from_user.id,
    )
    await state.clear()
    await callback.answer("✅ Порожню інструкцію створено!")
    if callback.message:
        await _render_instruction_card(callback.message, inst_id, page=1, delete_source_msg=True)


async def dev_inst_process_new_file(message: Message, state: FSMContext) -> None:
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
        await message.answer(
            err,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📥 Викачати шаблон", callback_data="dev_inst_dl_template")],
                    [InlineKeyboardButton(text="⏭ Залишити пусту", callback_data="dev_inst_save_empty")],
                    [InlineKeyboardButton(text="🔙 Назад", callback_data="dev_inst_add")],
                ]
            ),
            parse_mode="HTML",
        )
        return

    inst_id = await create_instruction(
        title=title,
        content=extracted,
        file_path=local_path,
        telegram_file_id=tg_file_id,
        file_name=orig_name,
        created_by=message.from_user.id,
    )
    await state.clear()
    _schedule_ai_reindex()

    await message.answer("✅ Інструкцію збережено та додано до пошуку ШІ!")
    await _render_instruction_card(message, inst_id, page=1, delete_source_msg=False)


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
        f"🔄 <b>Оновлення файлу інструкції: {html.escape(inst['title'])}</b>\n\n"
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
        f"<i>Файл і текст інструкції буде вилучено також із пошуку ШІ.</i>",
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

    # Створення
    dp.callback_query.register(dev_inst_add_start_handler, lambda c: c.data == "dev_inst_add")
    dp.message.register(dev_inst_process_new_title, InstructionStates.waiting_new_title)
    dp.callback_query.register(dev_inst_download_template_handler, lambda c: c.data == "dev_inst_dl_template")
    dp.callback_query.register(dev_inst_save_empty_handler, lambda c: c.data == "dev_inst_save_empty")
    dp.message.register(dev_inst_process_new_file, InstructionStates.waiting_new_file)

    # Перегляд та редагування
    dp.callback_query.register(dev_inst_view_handler, lambda c: c.data and c.data.startswith("dev_inst_view:"))
    dp.callback_query.register(dev_inst_edit_file_start_handler, lambda c: c.data and c.data.startswith("dev_inst_edit_file:"))
    dp.message.register(dev_inst_process_edit_file, InstructionStates.waiting_edit_file)
    dp.callback_query.register(dev_inst_edit_title_start_handler, lambda c: c.data and c.data.startswith("dev_inst_edit_title:"))
    dp.message.register(dev_inst_process_edit_title, InstructionStates.waiting_edit_title)

    # Видалення
    dp.callback_query.register(dev_inst_delete_ask_handler, lambda c: c.data and c.data.startswith("dev_inst_del_ask:"))
    dp.callback_query.register(dev_inst_delete_do_handler, lambda c: c.data and c.data.startswith("dev_inst_del_do:"))
