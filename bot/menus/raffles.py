from __future__ import annotations

import asyncio
import html
import logging
import math
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

import pytz
from aiogram import Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.config import TIMEZONE
from bot.services.raffle_exporter import (
    describe_raffle_participation,
    dispatch_raffle_announcement_waves,
    generate_raffle_media_zips,
    generate_raffle_report_xlsx,
    sanitize_participant_filename,
    validate_raffle_text_submission,
)
from bot.utils.message_utils import sanitize_telegram_html
from database.hr import is_developer_user, is_hr_user
from database.managers import (
    get_manager_by_uid,
    is_manager_user,
    is_observer_user,
    is_territorial_user,
)
from database.news import get_matching_news_recipients
from database.raffles import (
    RAFFLES_MEDIA_DIR,
    add_raffle_submission,
    complete_raffle,
    create_raffle,
    delete_raffle,
    get_active_raffle,
    get_current_kyiv_dt,
    get_latest_raffle,
    get_raffle_by_id,
    get_raffle_history_last_60_days,
    get_user_raffle_submission,
    is_user_eligible_for_active_raffle,
)
from database.users import get_user_details

logger = logging.getLogger(__name__)

MAX_TELEGRAM_BOT_DOWNLOAD_BYTES = 20 * 1024 * 1024  # 20 MB Telegram Bot API limit

RAFFLE_ROLES = [
    "Працівник",
    "Стажер",
    "Керівник",
    "Наглядач",
    "Територіал",
    "Адміністратор",
]


class RaffleCreateStates(StatesGroup):
    waiting_content = State()
    selecting_type = State()
    selecting_text_format = State()
    selecting_deadline = State()
    selecting_roles = State()
    selecting_city = State()
    confirm_launch = State()


class RaffleParticipationStates(StatesGroup):
    waiting_submission = State()
    confirming_submission = State()


async def _check_raffle_read_access(event: Union[CallbackQuery, Message]) -> bool:
    uid = event.from_user.id
    return await is_developer_user(uid) or await is_observer_user(uid)


async def _check_raffle_write_access(event: Union[CallbackQuery, Message]) -> bool:
    uid = event.from_user.id
    return await is_developer_user(uid)


def _extract_title_from_text(raw_text: str) -> str:
    clean = re.sub(r"<[^>]+>", "", raw_text or "").strip()
    clean = html.unescape(clean)
    for line in clean.splitlines():
        line_clean = line.strip()
        if line_clean:
            if len(line_clean) > 60:
                return line_clean[:57] + "..."
            return line_clean
    return "Розіграш BULKA"


async def _handle_start_escape(message: Message, state: FSMContext) -> bool:
    """Якщо користувач ввів /start під час FSM, скидає стан і відкриває головне меню."""
    if message.text and message.text.strip().startswith("/start"):
        await state.clear()
        from bot.handlers import start_menu

        await start_menu(message, state)
        return True
    return False


async def _safe_edit_or_send(
    event: Union[CallbackQuery, Message],
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = "HTML",
) -> None:
    msg = event.message if isinstance(event, CallbackQuery) else event
    if not msg:
        return

    has_media = bool(getattr(msg, "photo", None) or getattr(msg, "video", None))
    if isinstance(event, CallbackQuery):
        if has_media:
            if len(text) <= 1000:
                try:
                    await msg.edit_caption(caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
                    return
                except Exception:
                    pass
            try:
                await msg.delete()
            except Exception:
                pass
            await msg.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
            return

        try:
            await msg.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
            return
        except Exception:
            pass
        try:
            await msg.delete()
        except Exception:
            pass

    await msg.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)


async def _send_raffle_media_card(
    target_msg: Message,
    raffle: Dict[str, Any],
    full_text: str,
    reply_markup: InlineKeyboardMarkup,
    *,
    delete_old: bool = True,
) -> None:
    """Надсилає або оновлює картку розіграшу з урахуванням фото/відео умов та ліміту 1024 символів."""
    if delete_old and target_msg:
        try:
            await target_msg.delete()
        except Exception:
            pass

    media_type = raffle.get("media_type")
    photo_id = raffle.get("photo_file_id")
    video_id = raffle.get("video_file_id")

    if media_type == "video" and video_id:
        if len(full_text) <= 1000:
            await target_msg.answer_video(
                video=video_id,
                caption=full_text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        else:
            await target_msg.answer_video(video=video_id)
            await target_msg.answer(full_text, reply_markup=reply_markup, parse_mode="HTML")
        return

    if media_type == "photo" and photo_id:
        if len(full_text) <= 1000:
            await target_msg.answer_photo(
                photo=photo_id,
                caption=full_text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        else:
            await target_msg.answer_photo(photo=photo_id)
            await target_msg.answer(full_text, reply_markup=reply_markup, parse_mode="HTML")
        return

    await target_msg.answer(full_text, reply_markup=reply_markup, parse_mode="HTML")


# =========================================================================
# 1. АДМІН-МЕНЮ РОЗІГРАШІВ
# =========================================================================


async def dev_raffles_menu_handler(callback: CallbackQuery, state: FSMContext):
    """Головне меню управління розіграшами в розділі Розсилки."""
    if not await _check_raffle_read_access(callback):
        await callback.answer("⛔️ Доступ дозволено лише адміністраторам та наглядачам.", show_alert=True)
        return

    await state.clear()
    is_admin = await _check_raffle_write_access(callback)
    active = await get_active_raffle()
    latest = await get_latest_raffle()

    lines = [
        "🎁 <b>Управління розіграшами</b>",
        "───────────────────",
        "",
    ]
    buttons: List[List[InlineKeyboardButton]] = []

    if active:
        fmt_label = describe_raffle_participation(
            active["participation_type"], active.get("text_format")
        )
        deadline_disp = str(active["deadline"])[:16]
        lines.append("🔥 <b>Активний розіграш зараз триває:</b>")
        lines.append(f"• Назва: <b>{html.escape(active['title'])}</b>")
        lines.append(f"• Формат: {fmt_label}")
        lines.append(f"• Дедлайн: <code>{deadline_disp}</code>")
        lines.append(f"• Учасників: <b>{active.get('submissions_count', 0)}</b>")
        lines.append("")
        lines.append("<i>Одночасно може працювати лише 1 активний розіграш.</i>")

        buttons.append([
            InlineKeyboardButton(
                text=f"🔥 Керувати розіграшем #{active['id']}",
                callback_data=f"dev_raffle_view:{active['id']}:menu",
            )
        ])
        buttons.append([
            InlineKeyboardButton(
                text="📥 Вивантажити учасників",
                callback_data=f"dev_raffle_export:{active['id']}",
            )
        ])
    else:
        lines.append("Наразі немає активного розіграшу.")
        if latest:
            lines.append("")
            lines.append(
                f"📌 <b>Останній розіграш:</b> {html.escape(latest['title'])} "
                f"(учасників: <b>{latest.get('submissions_count', 0)}</b>)"
            )
        if is_admin:
            buttons.append([
                InlineKeyboardButton(text="➕ Створити розіграш", callback_data="dev_raffle_create_start")
            ])
        if latest:
            buttons.append([
                InlineKeyboardButton(
                    text="📥 Вивантажити учасників (останній)",
                    callback_data=f"dev_raffle_export:{latest['id']}",
                )
            ])

    buttons.append([InlineKeyboardButton(text="📜 Історія розіграшів", callback_data="dev_raffle_history:1")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="dev_broadcasts_menu")])

    from bot.menus.developer import _show_admin_photo_menu

    await _show_admin_photo_menu(
        callback,
        "img/admin/admin_broadcasts.jpg",
        "\n".join(lines),
        InlineKeyboardMarkup(inline_keyboard=buttons),
    )


# =========================================================================
# 2. МАЙСТЕР СТВОРЕННЯ РОЗІГРАШУ (АДМІН)
# =========================================================================


async def dev_raffle_create_start(callback: CallbackQuery, state: FSMContext):
    """Крок 1: Введення умов розіграшу (текст або фото/відео + текст)."""
    if not await _check_raffle_write_access(callback):
        await callback.answer("⛔️ Створювати розіграші може лише адміністратор.", show_alert=True)
        return

    active = await get_active_raffle()
    if active:
        await callback.answer(
            "⚠️ Вже є активний розіграш! Спочатку завершіть або видаліть його.",
            show_alert=True,
        )
        return

    await state.clear()
    await state.set_state(RaffleCreateStates.waiting_content)
    await state.update_data(
        photo_file_id=None,
        video_file_id=None,
        media_type=None,
        text_content="",
        title="",
        participation_type="button",
        text_format=None,
        deadline=None,
        deadline_label="",
        selected_roles=["Працівник", "Стажер"],
        selected_city="all",
        send_announcement=False,
    )

    text = (
        "🎁 <b>Створення розіграшу - Крок 1/6: Умови</b>\n"
        "───────────────────\n\n"
        "Надішліть опис та умови розіграшу (у форматі новин):\n"
        "1. Лише текст.\n"
        "2. Фото або відео з текстом в описі (caption).\n"
        "3. Спочатку фото/відео, а потім текст наступним повідомленням.\n\n"
        "💡 <i>Підтримується HTML-форматування. Перший рядок стане назвою розіграшу в історії.</i>"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="dev_raffles_menu")]]
    )
    await _safe_edit_or_send(callback, text, reply_markup=kb)
    await callback.answer()


async def _show_raffle_type_selection(event: Union[CallbackQuery, Message], state: FSMContext):
    """Крок 2: Вибір формату участі для працівників."""
    data = await state.get_data()
    title = html.escape(data.get("title") or "Розіграш BULKA")

    text = (
        "🎯 <b>Створення розіграшу - Крок 2/6: Формат участі</b>\n"
        "───────────────────\n"
        f"📌 Назва: <b>{title}</b>\n\n"
        "Оберіть, яку дію має виконати учасник для участі:"
    )
    buttons = [
        [InlineKeyboardButton(text="💬 Відправка повідомлення", callback_data="dev_raffle_type:text")],
        [InlineKeyboardButton(text="📐 Повідомлення з форматом", callback_data="dev_raffle_type:formatted_text")],
        [InlineKeyboardButton(text="📸 Надсилання фото або відео", callback_data="dev_raffle_type:media")],
        [InlineKeyboardButton(text="📎 Надсилання файлів", callback_data="dev_raffle_type:document")],
        [InlineKeyboardButton(text="🔘 Натискання «Взяти участь»", callback_data="dev_raffle_type:button")],
        [InlineKeyboardButton(text="🔙 Змінити умови", callback_data="dev_raffle_create_start")],
    ]
    await _safe_edit_or_send(event, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    if isinstance(event, CallbackQuery):
        await event.answer()


async def dev_raffle_process_content(message: Message, state: FSMContext):
    """Обробка тексту / фото / відео умов розіграшу."""
    if await _handle_start_escape(message, state):
        return
    if not await _check_raffle_write_access(message):
        await message.answer("⛔️ Доступ заборонено.")
        return

    data = await state.get_data()
    stored_media = data.get("media_type")

    if message.video:
        caption = (message.caption or "").strip()
        if caption:
            await state.update_data(
                photo_file_id=None,
                video_file_id=message.video.file_id,
                media_type="video",
                text_content=caption,
                title=_extract_title_from_text(caption),
            )
            await state.set_state(RaffleCreateStates.selecting_type)
            await _show_raffle_type_selection(message, state)
        else:
            await state.update_data(
                photo_file_id=None,
                video_file_id=message.video.file_id,
                media_type="video",
            )
            await message.answer("✅ Відео збережено! Тепер надішліть текст умов розіграшу:")
        return

    if message.photo:
        caption = (message.caption or "").strip()
        photo_id = message.photo[-1].file_id
        if caption:
            await state.update_data(
                photo_file_id=photo_id,
                video_file_id=None,
                media_type="photo",
                text_content=caption,
                title=_extract_title_from_text(caption),
            )
            await state.set_state(RaffleCreateStates.selecting_type)
            await _show_raffle_type_selection(message, state)
        else:
            await state.update_data(
                photo_file_id=photo_id,
                video_file_id=None,
                media_type="photo",
            )
            await message.answer("✅ Фото збережено! Тепер надішліть текст умов розіграшу:")
        return

    if message.text:
        text_content = message.text.strip()
        if not text_content:
            await message.answer("⚠️ Текст не може бути порожнім. Надішліть умови розіграшу ще раз:")
            return

        updates: Dict[str, Any] = {
            "text_content": text_content,
            "title": _extract_title_from_text(text_content),
        }
        if stored_media not in ("photo", "video"):
            updates.update(photo_file_id=None, video_file_id=None, media_type=None)

        await state.update_data(**updates)
        await state.set_state(RaffleCreateStates.selecting_type)
        await _show_raffle_type_selection(message, state)
        return

    await message.answer("⚠️ Будь ласка, надішліть текст, фото або відео для умов розіграшу.")


async def dev_raffle_back_to_types_handler(callback: CallbackQuery, state: FSMContext):
    if not await _check_raffle_write_access(callback):
        await callback.answer("⛔️ Доступ заборонено.", show_alert=True)
        return
    await state.set_state(RaffleCreateStates.selecting_type)
    await _show_raffle_type_selection(callback, state)


async def _show_raffle_text_format_selection(callback: CallbackQuery):
    text = (
        "📐 <b>Уточнення формату повідомлення</b>\n"
        "───────────────────\n\n"
        "Оберіть, який саме формат відповіді очікувати від учасників:"
    )
    buttons = [
        [InlineKeyboardButton(text="📝 Текстовий (будь-який текст)", callback_data="dev_raffle_fmt:any")],
        [InlineKeyboardButton(text="🔢 Числовий (будь-яке число)", callback_data="dev_raffle_fmt:numeric")],
        [InlineKeyboardButton(text="⚽ Рахунок (формат 0:0)", callback_data="dev_raffle_fmt:score")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="dev_raffle_back_types")],
    ]
    await _safe_edit_or_send(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


async def _show_raffle_deadline_selection(event: Union[CallbackQuery, Message], state: FSMContext):
    data = await state.get_data()
    fmt_label = describe_raffle_participation(
        data.get("participation_type", "button"),
        data.get("text_format"),
    )
    text = (
        "⏳ <b>Створення розіграшу - Крок 3/6: Дата закінчення</b>\n"
        "───────────────────\n"
        f"🎯 Формат: <b>{fmt_label}</b>\n\n"
        "Оберіть тривалість швидкою кнопкою або надішліть точну дату й час у чат "
        "у форматі <code>ДД.ММ.РРРР ГГ:ХХ</code> (наприклад: <code>25.11.2026 18:00</code>):"
    )
    buttons = [
        [
            InlineKeyboardButton(text="⏳ 1 день", callback_data="dev_raffle_dur:1"),
            InlineKeyboardButton(text="⏳ 3 дні", callback_data="dev_raffle_dur:3"),
        ],
        [
            InlineKeyboardButton(text="⏳ 1 тиждень", callback_data="dev_raffle_dur:7"),
            InlineKeyboardButton(text="⏳ 2 тижні", callback_data="dev_raffle_dur:14"),
        ],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="dev_raffle_back_types")],
    ]
    await _safe_edit_or_send(event, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    if isinstance(event, CallbackQuery):
        await event.answer()


async def dev_raffle_select_type_handler(callback: CallbackQuery, state: FSMContext):
    if not await _check_raffle_write_access(callback):
        await callback.answer("⛔️ Доступ заборонено.", show_alert=True)
        return

    ptype = callback.data.split(":", 1)[1]
    if ptype == "formatted_text":
        await state.update_data(participation_type="formatted_text")
        await state.set_state(RaffleCreateStates.selecting_text_format)
        await _show_raffle_text_format_selection(callback)
        return

    await state.update_data(participation_type=ptype, text_format=None)
    await state.set_state(RaffleCreateStates.selecting_deadline)
    await _show_raffle_deadline_selection(callback, state)


async def dev_raffle_select_fmt_handler(callback: CallbackQuery, state: FSMContext):
    if not await _check_raffle_write_access(callback):
        await callback.answer("⛔️ Доступ заборонено.", show_alert=True)
        return

    fmt = callback.data.split(":", 1)[1]
    await state.update_data(participation_type="formatted_text", text_format=fmt)
    await state.set_state(RaffleCreateStates.selecting_deadline)
    await _show_raffle_deadline_selection(callback, state)


async def dev_raffle_duration_handler(callback: CallbackQuery, state: FSMContext):
    if not await _check_raffle_write_access(callback):
        await callback.answer("⛔️ Доступ заборонено.", show_alert=True)
        return

    days = int(callback.data.split(":", 1)[1])
    deadline_dt = get_current_kyiv_dt() + timedelta(days=days)
    deadline_str = deadline_dt.strftime("%Y-%m-%d %H:%M:%S")
    deadline_label = deadline_dt.strftime("%d.%m.%Y %H:%M")

    await state.update_data(deadline=deadline_str, deadline_label=deadline_label)
    await state.set_state(RaffleCreateStates.selecting_roles)
    await _show_raffle_roles_selection(callback, state)


async def dev_raffle_process_deadline_text(message: Message, state: FSMContext):
    if await _handle_start_escape(message, state):
        return
    if not await _check_raffle_write_access(message):
        await message.answer("⛔️ Доступ заборонено.")
        return

    raw = (message.text or "").strip()
    tz = pytz.timezone(TIMEZONE)
    parsed_dt = None

    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S"):
        try:
            naive = datetime.strptime(raw, fmt)
            parsed_dt = tz.localize(naive)
            break
        except ValueError:
            continue

    if not parsed_dt:
        try:
            naive = datetime.strptime(raw, "%d.%m.%Y")
            parsed_dt = tz.localize(naive.replace(hour=23, minute=59, second=0))
        except ValueError:
            parsed_dt = None

    if not parsed_dt:
        await message.answer(
            "⚠️ Не вдалося розпізнати дату!\n"
            "Введіть дату у форматі <code>ДД.ММ.РРРР ГГ:ХХ</code> (наприклад: <code>25.11.2026 18:00</code>) "
            "або оберіть швидкий варіант вище."
        )
        return

    now_dt = get_current_kyiv_dt()
    if parsed_dt <= now_dt:
        await message.answer(
            "⚠️ Дата закінчення має бути у майбутньому! Вкажіть актуальний час:"
        )
        return

    deadline_str = parsed_dt.strftime("%Y-%m-%d %H:%M:%S")
    deadline_label = parsed_dt.strftime("%d.%m.%Y %H:%M")
    await state.update_data(deadline=deadline_str, deadline_label=deadline_label)
    await state.set_state(RaffleCreateStates.selecting_roles)
    await _show_raffle_roles_selection(message, state)


async def _show_raffle_roles_selection(event: Union[CallbackQuery, Message], state: FSMContext):
    data = await state.get_data()
    selected_roles = set(data.get("selected_roles", ["Працівник", "Стажер"]))

    buttons: List[List[InlineKeyboardButton]] = []
    for role in RAFFLE_ROLES:
        mark = "✅ " if role in selected_roles else "⬜️ "
        buttons.append([
            InlineKeyboardButton(text=f"{mark}{role}", callback_data=f"dev_raffle_toggle_role:{role}")
        ])

    all_selected = len(selected_roles) == len(RAFFLE_ROLES)
    toggle_all_text = "⬜️ Зняти всі ролі" if all_selected else "✅ Обрати всі ролі"
    buttons.append([InlineKeyboardButton(text=toggle_all_text, callback_data="dev_raffle_roles_all")])
    buttons.append([InlineKeyboardButton(text="➡️ Далі (вибір міста)", callback_data="dev_raffle_to_city")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="dev_raffle_back_deadline")])

    text = (
        "👥 <b>Створення розіграшу - Крок 4/6: Аудиторія (Ролі)</b>\n"
        "───────────────────\n"
        f"⏳ Дедлайн: <code>{data.get('deadline_label', '')}</code>\n\n"
        "Оберіть ролі співробітників, у яких з'явиться кнопка «🎁 Розіграш»:"
    )
    await _safe_edit_or_send(event, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    if isinstance(event, CallbackQuery):
        await event.answer()


async def dev_raffle_back_deadline_handler(callback: CallbackQuery, state: FSMContext):
    if not await _check_raffle_write_access(callback):
        await callback.answer("⛔️ Доступ заборонено.", show_alert=True)
        return
    await state.set_state(RaffleCreateStates.selecting_deadline)
    await _show_raffle_deadline_selection(callback, state)


async def dev_raffle_toggle_role_handler(callback: CallbackQuery, state: FSMContext):
    if not await _check_raffle_write_access(callback):
        await callback.answer("⛔️ Доступ заборонено.", show_alert=True)
        return

    role = callback.data.split(":", 1)[1]
    data = await state.get_data()
    selected_roles = list(data.get("selected_roles", []))

    if role in selected_roles:
        if len(selected_roles) <= 1:
            await callback.answer("⚠️ Потрібно обрати хоча б одну роль.", show_alert=True)
            return
        selected_roles.remove(role)
    else:
        selected_roles.append(role)

    await state.update_data(selected_roles=selected_roles)
    await _show_raffle_roles_selection(callback, state)


async def dev_raffle_roles_all_handler(callback: CallbackQuery, state: FSMContext):
    if not await _check_raffle_write_access(callback):
        await callback.answer("⛔️ Доступ заборонено.", show_alert=True)
        return

    data = await state.get_data()
    current = set(data.get("selected_roles", []))
    if len(current) == len(RAFFLE_ROLES):
        new_roles = ["Працівник"]
    else:
        new_roles = list(RAFFLE_ROLES)

    await state.update_data(selected_roles=new_roles)
    await _show_raffle_roles_selection(callback, state)


async def _show_raffle_city_selection(callback: CallbackQuery, state: FSMContext):
    from bot.menus.developer import _get_active_city_names

    data = await state.get_data()
    selected_city = data.get("selected_city", "all")

    buttons: List[List[InlineKeyboardButton]] = []
    mark_all = "✅ " if selected_city == "all" else ""
    buttons.append([InlineKeyboardButton(text=f"{mark_all}🌐 Усі міста", callback_data="dev_raffle_select_city:all")])

    active_cities = await _get_active_city_names()
    row: List[InlineKeyboardButton] = []
    for idx, c_name in enumerate(active_cities):
        mark = "✅ " if selected_city == c_name else ""
        row.append(InlineKeyboardButton(text=f"{mark}{c_name}", callback_data=f"dev_raffle_select_city:{idx}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="dev_raffle_back_roles")])

    text = (
        "🏙 <b>Створення розіграшу - Крок 5/6: Місто</b>\n"
        "───────────────────\n\n"
        "Оберіть місто проведення розіграшу або «Усі міста»:"
    )
    await _safe_edit_or_send(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


async def dev_raffle_to_city_handler(callback: CallbackQuery, state: FSMContext):
    if not await _check_raffle_write_access(callback):
        await callback.answer("⛔️ Доступ заборонено.", show_alert=True)
        return
    data = await state.get_data()
    if not data.get("selected_roles"):
        await callback.answer("⚠️ Оберіть хоча б одну роль.", show_alert=True)
        return
    await state.set_state(RaffleCreateStates.selecting_city)
    await _show_raffle_city_selection(callback, state)


async def dev_raffle_back_roles_handler(callback: CallbackQuery, state: FSMContext):
    if not await _check_raffle_write_access(callback):
        await callback.answer("⛔️ Доступ заборонено.", show_alert=True)
        return
    await state.set_state(RaffleCreateStates.selecting_roles)
    await _show_raffle_roles_selection(callback, state)


async def _show_raffle_launch_preview(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected_roles = data.get("selected_roles", [])
    selected_city = data.get("selected_city", "all")
    recipients = await get_matching_news_recipients(selected_roles, selected_city)
    rec_count = len(recipients)

    send_ann = bool(data.get("send_announcement", False))
    ann_label = "🔔 Анонс в особисті: Увімкнено ✅" if send_ann else "🔕 Анонс в особисті: Вимкнено"

    fmt_label = describe_raffle_participation(
        data.get("participation_type", "button"),
        data.get("text_format"),
    )
    city_str = "Усі міста" if selected_city == "all" else selected_city
    roles_str = ", ".join(selected_roles)
    terms = sanitize_telegram_html(data.get("text_content") or "")

    preview_text = (
        f"👁 <b>Попередній перегляд розіграшу (Крок 6/6)</b>\n"
        f"───────────────────\n"
        f"🎯 <b>Формат:</b> {fmt_label}\n"
        f"⏳ <b>Дедлайн:</b> <code>{data.get('deadline_label', '')}</code>\n"
        f"👥 <b>Аудиторія:</b> {roles_str} ({city_str})\n"
        f"📬 <b>Охоплення:</b> {rec_count} осіб\n"
        f"───────────────────\n\n"
        f"{terms}"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=ann_label, callback_data="dev_raffle_toggle_ann")],
            [InlineKeyboardButton(text=f"🚀 Запустити розіграш ({rec_count} ос.)", callback_data="dev_raffle_launch")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="dev_raffle_to_city")],
        ]
    )

    dummy_raffle = {
        "media_type": data.get("media_type"),
        "photo_file_id": data.get("photo_file_id"),
        "video_file_id": data.get("video_file_id"),
    }
    if dummy_raffle["media_type"] and callback.message:
        await _send_raffle_media_card(
            callback.message,
            dummy_raffle,
            preview_text,
            kb,
            delete_old=True,
        )
    else:
        await _safe_edit_or_send(callback, preview_text, reply_markup=kb)

    await callback.answer()


async def dev_raffle_select_city_handler(callback: CallbackQuery, state: FSMContext):
    if not await _check_raffle_write_access(callback):
        await callback.answer("⛔️ Доступ заборонено.", show_alert=True)
        return

    from bot.menus.developer import _resolve_city_from_callback_val

    raw_city = callback.data.split(":", 1)[1]
    city = "all" if raw_city == "all" else (await _resolve_city_from_callback_val(raw_city) or raw_city)
    await state.update_data(selected_city=city)
    await state.set_state(RaffleCreateStates.confirm_launch)
    await _show_raffle_launch_preview(callback, state)


async def dev_raffle_toggle_ann_handler(callback: CallbackQuery, state: FSMContext):
    if not await _check_raffle_write_access(callback):
        await callback.answer("⛔️ Доступ заборонено.", show_alert=True)
        return

    data = await state.get_data()
    new_val = not bool(data.get("send_announcement", False))
    await state.update_data(send_announcement=new_val)
    await _show_raffle_launch_preview(callback, state)


async def dev_raffle_launch_handler(callback: CallbackQuery, state: FSMContext):
    if not await _check_raffle_write_access(callback):
        await callback.answer("⛔️ Доступ заборонено.", show_alert=True)
        return

    data = await state.get_data()
    selected_roles = data.get("selected_roles", [])
    selected_city = data.get("selected_city", "all")
    send_ann = bool(data.get("send_announcement", False))
    text_content = sanitize_telegram_html(data.get("text_content") or "")

    try:
        raffle_id = await create_raffle(
            title=data.get("title") or _extract_title_from_text(text_content),
            text=text_content,
            participation_type=data.get("participation_type", "button"),
            text_format=data.get("text_format"),
            selected_roles=selected_roles,
            selected_city=selected_city,
            deadline=data.get("deadline"),
            media_type=data.get("media_type"),
            photo_file_id=data.get("photo_file_id"),
            video_file_id=data.get("video_file_id"),
            send_announcement=send_ann,
            created_by=callback.from_user.id,
        )
    except ValueError as ve:
        await state.clear()
        await callback.answer(f"⚠️ {ve}", show_alert=True)
        await dev_raffles_menu_handler(callback, state)
        return

    await state.clear()
    await callback.answer("🚀 Розіграш запущено!", show_alert=True)

    raffle = await get_raffle_by_id(raffle_id)
    if send_ann and raffle:
        recipients = await get_matching_news_recipients(selected_roles, selected_city)
        if recipients:
            asyncio.create_task(
                dispatch_raffle_announcement_waves(
                    bot=callback.bot,
                    recipient_uids=recipients,
                    raffle=raffle,
                    admin_chat_id=callback.message.chat.id if callback.message else None,
                )
            )

    await _render_admin_raffle_card(callback, raffle_id, back_target="menu")


# =========================================================================
# 3. КАРТКА, ІСТОРІЯ ТА ЕКСПОРТ (АДМІН)
# =========================================================================


async def _render_admin_raffle_card(
    callback: CallbackQuery,
    raffle_id: int,
    back_target: str = "history:1",
):
    raffle = await get_raffle_by_id(raffle_id)
    if not raffle:
        await callback.answer("❌ Розіграш не знайдено.", show_alert=True)
        return

    is_admin = await _check_raffle_write_access(callback)
    is_active = raffle["status"] == "active"
    status_badge = "🔥 Активний" if is_active else "✅ Завершений"
    fmt_label = describe_raffle_participation(
        raffle["participation_type"], raffle.get("text_format")
    )
    city_str = "Усі міста" if raffle.get("selected_city") == "all" else raffle.get("selected_city")
    roles_str = ", ".join(raffle.get("selected_roles") or [])
    clean_terms = re.sub(r"<[^>]+>", "", raffle.get("text") or "").strip()
    if len(clean_terms) > 400:
        clean_terms = clean_terms[:397] + "..."

    lines = [
        f"🎁 <b>Розіграш #{raffle_id}: {html.escape(raffle['title'])}</b>",
        "───────────────────",
        f"📌 <b>Статус:</b> {status_badge}",
        f"🎯 <b>Формат:</b> {fmt_label}",
        f"👥 <b>Учасників:</b> <b>{raffle.get('submissions_count', 0)}</b>",
        f"📅 <b>Створено:</b> <code>{str(raffle.get('created_at', ''))[:16]}</code>",
        f"⏳ <b>Дедлайн:</b> <code>{str(raffle.get('deadline', ''))[:16]}</code>",
        f"🏙 <b>Аудиторія:</b> {roles_str} ({city_str})",
    ]
    if raffle.get("media_cleaned"):
        lines.append("🧹 <i>Медіафайли очищено після 60 днів.</i>")
    lines.extend([
        "",
        "<b>Умови:</b>",
        html.escape(clean_terms),
    ])

    buttons: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="📥 Вивантажити учасників", callback_data=f"dev_raffle_export:{raffle_id}")]
    ]
    if is_active and is_admin:
        buttons.append([
            InlineKeyboardButton(text="🛑 Завершити достроково", callback_data=f"dev_raffle_stop:{raffle_id}:{back_target}")
        ])
    if is_admin:
        buttons.append([
            InlineKeyboardButton(text="🗑 Видалити розіграш", callback_data=f"dev_raffle_del_confirm:{raffle_id}")
        ])

    back_cb = "dev_raffles_menu" if back_target == "menu" else f"dev_raffle_{back_target}"
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data=back_cb)])

    await _safe_edit_or_send(callback, "\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


async def dev_raffle_view_handler(callback: CallbackQuery):
    if not await _check_raffle_read_access(callback):
        await callback.answer("⛔️ Доступ заборонено.", show_alert=True)
        return

    parts = callback.data.split(":")
    raffle_id = int(parts[1])
    back_target = ":".join(parts[2:]) if len(parts) > 2 else "history:1"
    await _render_admin_raffle_card(callback, raffle_id, back_target=back_target)
    await callback.answer()


async def dev_raffle_stop_handler(callback: CallbackQuery):
    if not await _check_raffle_write_access(callback):
        await callback.answer("⛔️ Доступ заборонено.", show_alert=True)
        return

    parts = callback.data.split(":")
    raffle_id = int(parts[1])
    back_target = ":".join(parts[2:]) if len(parts) > 2 else "menu"
    stopped = await complete_raffle(raffle_id)
    if stopped:
        await callback.answer("🛑 Розіграш завершено! Кнопка зникла з меню працівників.", show_alert=True)
    else:
        await callback.answer("Розіграш уже завершено.", show_alert=True)

    await _render_admin_raffle_card(callback, raffle_id, back_target=back_target)


async def dev_raffle_del_confirm_handler(callback: CallbackQuery):
    if not await _check_raffle_write_access(callback):
        await callback.answer("⛔️ Доступ заборонено.", show_alert=True)
        return

    raffle_id = int(callback.data.split(":")[1])
    raffle = await get_raffle_by_id(raffle_id)
    if not raffle:
        await callback.answer("Розіграш не знайдено.", show_alert=True)
        return

    text = (
        f"⚠️ <b>Видалення розіграшу #{raffle_id}</b>\n\n"
        f"Ви дійсно бажаєте безповоротно видалити розіграш «<b>{html.escape(raffle['title'])}</b>»?\n\n"
        f"❗ <i>Усі записи учасників та завантажені фото/відео/файли будуть стерті.</i>"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Так, видалити назавжди", callback_data=f"dev_raffle_del_do:{raffle_id}")],
            [InlineKeyboardButton(text="🔙 Скасувати", callback_data=f"dev_raffle_view:{raffle_id}:menu")],
        ]
    )
    await _safe_edit_or_send(callback, text, reply_markup=kb)
    await callback.answer()


async def dev_raffle_del_do_handler(callback: CallbackQuery, state: FSMContext):
    if not await _check_raffle_write_access(callback):
        await callback.answer("⛔️ Доступ заборонено.", show_alert=True)
        return

    raffle_id = int(callback.data.split(":")[1])
    await delete_raffle(raffle_id)
    await callback.answer("🗑 Розіграш та його файли видалено.", show_alert=True)
    await dev_raffles_menu_handler(callback, state)


async def dev_raffle_history_handler(callback: CallbackQuery):
    if not await _check_raffle_read_access(callback):
        await callback.answer("⛔️ Доступ заборонено.", show_alert=True)
        return

    parts = callback.data.split(":")
    page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1

    raffles = await get_raffle_history_last_60_days()
    if not raffles:
        text = (
            "📜 <b>Історія розіграшів (останні 2 місяці)</b>\n"
            "───────────────────\n\n"
            "За останні 60 днів розіграшів не знайдено."
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="dev_raffles_menu")]]
        )
        from bot.menus.developer import _show_admin_photo_menu

        await _show_admin_photo_menu(callback, "img/admin/admin_broadcasts.jpg", text, kb)
        return

    per_page = 6
    total_pages = max(1, math.ceil(len(raffles) / per_page))
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * per_page
    page_items = raffles[start_idx : start_idx + per_page]

    buttons: List[List[InlineKeyboardButton]] = []
    for r in page_items:
        badge = "🔥" if r["status"] == "active" else "✅"
        date_raw = str(r.get("created_at", ""))[:10]
        if "-" in date_raw:
            p = date_raw.split("-")
            date_disp = f"{p[2]}.{p[1]}" if len(p) == 3 else date_raw
        else:
            date_disp = date_raw
        short_title = r["title"][:24] + "..." if len(r["title"]) > 24 else r["title"]
        cnt = r.get("submissions_count", 0)
        buttons.append([
            InlineKeyboardButton(
                text=f"{badge} {date_disp} · {short_title} ({cnt})",
                callback_data=f"dev_raffle_view:{r['id']}:history:{page}",
            )
        ])

    if total_pages > 1:
        pag_row: List[InlineKeyboardButton] = []
        if page > 1:
            pag_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"dev_raffle_history:{page - 1}"))
        pag_row.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="ignore"))
        if page < total_pages:
            pag_row.append(InlineKeyboardButton(text="➡️", callback_data=f"dev_raffle_history:{page + 1}"))
        buttons.append(pag_row)

    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="dev_raffles_menu")])

    text = (
        "📜 <b>Історія розіграшів (останні 2 місяці)</b>\n"
        "───────────────────\n\n"
        f"Знайдено розіграшів: <b>{len(raffles)}</b>\n"
        "Оберіть розіграш для перегляду деталей або вивантаження учасників:"
    )
    from bot.menus.developer import _show_admin_photo_menu

    await _show_admin_photo_menu(
        callback,
        "img/admin/admin_broadcasts.jpg",
        text,
        InlineKeyboardMarkup(inline_keyboard=buttons),
    )


async def dev_raffle_export_handler(callback: CallbackQuery):
    if not await _check_raffle_read_access(callback):
        await callback.answer("⛔️ Доступ заборонено.", show_alert=True)
        return

    raffle_id = int(callback.data.split(":")[1])
    raffle = await get_raffle_by_id(raffle_id)
    if not raffle:
        await callback.answer("Розіграш не знайдено.", show_alert=True)
        return

    await callback.answer("⏳ Формуємо файли для вивантаження...")

    chat_id = callback.message.chat.id if callback.message else callback.from_user.id
    try:
        excel_stream = await generate_raffle_report_xlsx(raffle_id)
        doc_xlsx = BufferedInputFile(
            excel_stream.getvalue(),
            filename=f"Учасники_розіграшу_{raffle_id}.xlsx",
        )
        await callback.bot.send_document(
            chat_id=chat_id,
            document=doc_xlsx,
            caption=(
                f"📊 <b>Таблиця учасників розіграшу #{raffle_id}</b>\n"
                f"«{html.escape(raffle['title'])}»\n"
                f"Усього учасників: <b>{raffle.get('submissions_count', 0)}</b>"
            ),
            parse_mode="HTML",
        )

        if raffle["participation_type"] in ("media", "document"):
            zips = await generate_raffle_media_zips(raffle_id)
            if zips:
                total_parts = len(zips)
                for idx, (fname, zbytes) in enumerate(zips, start=1):
                    cap = (
                        f"📦 <b>Архів файлів учасників</b> (частина {idx}/{total_parts})"
                        if total_parts > 1
                        else f"📦 <b>Архів файлів учасників розіграшу #{raffle_id}</b>"
                    )
                    await callback.bot.send_document(
                        chat_id=chat_id,
                        document=BufferedInputFile(zbytes, filename=fname),
                        caption=cap,
                        parse_mode="HTML",
                    )
            else:
                if raffle.get("media_cleaned"):
                    await callback.bot.send_message(
                        chat_id=chat_id,
                        text="🧹 Медіафайли цього розіграшу були автоматично видалені після спливу 60 днів.",
                    )
                elif raffle.get("submissions_count", 0) > 0:
                    await callback.bot.send_message(
                        chat_id=chat_id,
                        text="ℹ️ Локальні медіафайли на диску відсутні.",
                    )
    except Exception as exc:
        logger.exception(f"Raffle export error for raffle_id={raffle_id}: {exc}")
        await callback.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Помилка під час вивантаження результатів: {html.escape(str(exc))}",
            parse_mode="HTML",
        )


# =========================================================================
# 4. УЧАСТЬ ПРАЦІВНИКА / КОРИСТУВАЧА В РОЗІГРАШІ
# =========================================================================


def _get_participation_prompt(raffle: Dict[str, Any]) -> str:
    ptype = raffle.get("participation_type", "button")
    tfmt = raffle.get("text_format")
    if ptype == "text":
        return "💬 <b>Надішліть текстове повідомлення</b> для участі в розіграші:"
    if ptype == "formatted_text":
        if tfmt == "numeric":
            return "🔢 <b>Надішліть число</b> (наприклад: <code>42</code> або <code>12.5</code>) для участі:"
        if tfmt == "score":
            return "⚽ <b>Надішліть рахунок у форматі 0:0</b> (наприклад: <code>2:1</code>) для участі:"
        return "📝 <b>Надішліть текстове повідомлення</b> для участі в розіграші:"
    if ptype == "media":
        return "📸 <b>Надішліть фото або відео</b> для участі в розіграші:"
    if ptype == "document":
        return "📎 <b>Надішліть файл (документ)</b> для участі в розіграші:"
    return "Натисніть кнопку «Взяти участь» нижче:"


async def _show_user_raffle_screen(
    target_msg: Message,
    raffle: Dict[str, Any],
    user_id: int,
    state: FSMContext,
    *,
    delete_old: bool = True,
) -> None:
    sub = await get_user_raffle_submission(raffle["id"], user_id)
    terms = sanitize_telegram_html(raffle.get("text") or "")
    deadline_disp = str(raffle.get("deadline", ""))[:16]

    if sub:
        await state.clear()
        full_text = (
            f"🎁 <b>{html.escape(raffle['title'])}</b>\n"
            f"⏳ <i>Діє до: {deadline_disp}</i>\n"
            f"───────────────────\n"
            f"{terms}\n\n"
            f"✅ <b>Ви берете участь в акції!</b>"
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="user_raffle_back_main")]]
        )
        await _send_raffle_media_card(target_msg, raffle, full_text, kb, delete_old=delete_old)
        return

    ptype = raffle["participation_type"]
    if ptype == "button":
        await state.clear()
        full_text = (
            f"🎁 <b>{html.escape(raffle['title'])}</b>\n"
            f"⏳ <i>Діє до: {deadline_disp}</i>\n"
            f"───────────────────\n"
            f"{terms}\n\n"
            f"👇 Натисніть кнопку нижче, щоб взяти участь:"
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🎁 Взяти участь", callback_data=f"user_raffle_join_btn:{raffle['id']}")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="user_raffle_back_main")],
            ]
        )
        await _send_raffle_media_card(target_msg, raffle, full_text, kb, delete_old=delete_old)
        return

    await state.set_state(RaffleParticipationStates.waiting_submission)
    await state.update_data(active_raffle_id=raffle["id"])
    prompt_line = _get_participation_prompt(raffle)
    full_text = (
        f"🎁 <b>{html.escape(raffle['title'])}</b>\n"
        f"⏳ <i>Діє до: {deadline_disp}</i>\n"
        f"───────────────────\n"
        f"{terms}\n\n"
        f"{prompt_line}"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="user_raffle_back_main")]]
    )
    await _send_raffle_media_card(target_msg, raffle, full_text, kb, delete_old=delete_old)


async def user_raffle_menu_handler(callback: CallbackQuery, state: FSMContext):
    """Відкриття картки розіграшу з головного меню співробітника або з анонсу."""
    user_id = callback.from_user.id
    raffle = await is_user_eligible_for_active_raffle(user_id)
    if not raffle:
        await state.clear()
        await callback.answer("⏳ Активний розіграш вже завершено або недоступний.", show_alert=True)
        await _return_to_role_main_menu(callback, force_photo=True)
        return

    await callback.answer()
    if callback.message:
        await _show_user_raffle_screen(callback.message, raffle, user_id, state, delete_old=True)


async def user_raffle_join_btn_handler(callback: CallbackQuery, state: FSMContext):
    """Миттєва участь для розіграшу формату «Натискання Взяти участь»."""
    user_id = callback.from_user.id
    raffle_id = int(callback.data.split(":")[1])

    raffle = await is_user_eligible_for_active_raffle(user_id)
    if not raffle or raffle["id"] != raffle_id:
        await state.clear()
        await callback.answer("⏳ Розіграш уже завершено або недоступний.", show_alert=True)
        await _return_to_role_main_menu(callback, force_photo=True)
        return

    if raffle["participation_type"] != "button":
        await callback.answer("Цей розіграш вимагає інший формат участі.", show_alert=True)
        return

    ok, msg, _ = await add_raffle_submission(
        raffle_id=raffle_id,
        user_id=user_id,
        submission_text="Взяв участь (кнопка)",
        fallback_username=callback.from_user.username,
        fallback_full_name=callback.from_user.full_name,
    )
    await callback.answer(msg, show_alert=not ok)
    if callback.message:
        await _show_user_raffle_screen(callback.message, raffle, user_id, state, delete_old=True)


async def user_raffle_process_submission(message: Message, state: FSMContext):
    """Прийом та валідація повідомлення / фото / відео / файлу від учасника розіграшу."""
    if await _handle_start_escape(message, state):
        return

    user_id = message.from_user.id
    raffle = await is_user_eligible_for_active_raffle(user_id)
    if not raffle:
        await state.clear()
        await message.answer("⏳ На жаль, розіграш уже завершився.")
        return

    existing = await get_user_raffle_submission(raffle["id"], user_id)
    if existing:
        await state.clear()
        await _show_user_raffle_screen(message, raffle, user_id, state, delete_old=False)
        return

    back_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="user_raffle_back_main")]]
    )
    ptype = raffle["participation_type"]
    tfmt = raffle.get("text_format")

    if ptype in ("text", "formatted_text"):
        if not message.text:
            await message.answer(
                "⚠️ Очікується саме <b>текстове повідомлення</b>. Спробуйте ще раз:",
                reply_markup=back_kb,
                parse_mode="HTML",
            )
            return

        is_valid, cleaned, err_msg = validate_raffle_text_submission(message.text, ptype, tfmt)
        if not is_valid:
            await message.answer(err_msg, reply_markup=back_kb, parse_mode="HTML")
            return

        await state.update_data(
            active_raffle_id=raffle["id"],
            draft_text=cleaned,
            draft_media_type=None,
            draft_file_id=None,
            draft_orig_filename=None,
            draft_file_size=0,
        )
        await state.set_state(RaffleParticipationStates.confirming_submission)
        confirm_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Підтвердити участь", callback_data="user_raffle_confirm_sub")],
                [InlineKeyboardButton(text="✏️ Змінити", callback_data="user_raffle_edit_sub")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="user_raffle_back_main")],
            ]
        )
        await message.answer(
            f"📝 <b>Перевірте вашу відповідь перед відправкою:</b>\n\n"
            f"<blockquote>{html.escape(cleaned)}</blockquote>\n\n"
            f"Після підтвердження змінити відповідь буде неможливо.",
            reply_markup=confirm_kb,
            parse_mode="HTML",
        )
        return

    if ptype == "media":
        if message.photo:
            photo = message.photo[-1]
            fsize = photo.file_size or 0
            if fsize > MAX_TELEGRAM_BOT_DOWNLOAD_BYTES:
                await message.answer(
                    "⚠️ Розмір фото перевищує 20 МБ (обмеження Telegram для завантаження ботом). Надішліть менше фото:",
                    reply_markup=back_kb,
                )
                return
            media_type = "photo"
            file_id = photo.file_id
            orig_filename = None
            caption = (message.caption or "").strip()
        elif message.video:
            vid = message.video
            fsize = vid.file_size or 0
            if fsize > MAX_TELEGRAM_BOT_DOWNLOAD_BYTES:
                await message.answer(
                    "⚠️ Розмір відео перевищує 20 МБ (обмеження Telegram для завантаження ботом). Стисніть відео або надішліть коротший ролик:",
                    reply_markup=back_kb,
                )
                return
            media_type = "video"
            file_id = vid.file_id
            orig_filename = vid.file_name
            caption = (message.caption or "").strip()
        else:
            await message.answer(
                "⚠️ Потрібно надіслати саме <b>фото або відео</b> (не документом і не текстом). Спробуйте ще раз:",
                reply_markup=back_kb,
                parse_mode="HTML",
            )
            return

        await state.update_data(
            active_raffle_id=raffle["id"],
            draft_text=caption,
            draft_media_type=media_type,
            draft_file_id=file_id,
            draft_orig_filename=orig_filename,
            draft_file_size=fsize,
        )
        await state.set_state(RaffleParticipationStates.confirming_submission)
        confirm_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Підтвердити участь", callback_data="user_raffle_confirm_sub")],
                [InlineKeyboardButton(text="✏️ Змінити", callback_data="user_raffle_edit_sub")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="user_raffle_back_main")],
            ]
        )
        type_ua = "Фото" if media_type == "photo" else "Відео"
        cap_line = f"\n💬 Підпис: <i>{html.escape(caption)}</i>" if caption else ""
        await message.answer(
            f"📸 <b>{type_ua} отримано!</b>{cap_line}\n\n"
            f"Натисніть «Підтвердити участь» для фіксації заявки або «Змінити» для повторної відправки.",
            reply_markup=confirm_kb,
            parse_mode="HTML",
        )
        return

    if ptype == "document":
        if not message.document:
            await message.answer(
                "⚠️ Потрібно надіслати саме <b>файл (документ)</b>. Спробуйте ще раз:",
                reply_markup=back_kb,
                parse_mode="HTML",
            )
            return

        doc = message.document
        fsize = doc.file_size or 0
        if fsize > MAX_TELEGRAM_BOT_DOWNLOAD_BYTES:
            await message.answer(
                "⚠️ Розмір файлу перевищує 20 МБ (обмеження Telegram для завантаження ботом). Надішліть менший файл:",
                reply_markup=back_kb,
            )
            return

        caption = (message.caption or "").strip()
        await state.update_data(
            active_raffle_id=raffle["id"],
            draft_text=caption,
            draft_media_type="document",
            draft_file_id=doc.file_id,
            draft_orig_filename=doc.file_name,
            draft_file_size=fsize,
        )
        await state.set_state(RaffleParticipationStates.confirming_submission)
        confirm_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Підтвердити участь", callback_data="user_raffle_confirm_sub")],
                [InlineKeyboardButton(text="✏️ Змінити", callback_data="user_raffle_edit_sub")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="user_raffle_back_main")],
            ]
        )
        fname_disp = html.escape(doc.file_name or "Файл")
        await message.answer(
            f"📎 <b>Файл отримано:</b> <code>{fname_disp}</code>\n\n"
            f"Натисніть «Підтвердити участь» для фіксації заявки або «Змінити» для вибору іншого файлу.",
            reply_markup=confirm_kb,
            parse_mode="HTML",
        )


async def user_raffle_edit_sub_handler(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    raffle = await is_user_eligible_for_active_raffle(user_id)
    if not raffle:
        await state.clear()
        await callback.answer("⏳ Розіграш уже завершено.", show_alert=True)
        await _return_to_role_main_menu(callback, force_photo=True)
        return

    existing = await get_user_raffle_submission(raffle["id"], user_id)
    if existing:
        await state.clear()
        await callback.answer("Ви вже берете участь в акції.", show_alert=True)
        if callback.message:
            await _show_user_raffle_screen(callback.message, raffle, user_id, state, delete_old=True)
        return

    await callback.answer()
    if callback.message:
        await _show_user_raffle_screen(callback.message, raffle, user_id, state, delete_old=True)


async def user_raffle_confirm_sub_handler(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    raffle_id = data.get("active_raffle_id")

    raffle = await is_user_eligible_for_active_raffle(user_id)
    if not raffle or (raffle_id and raffle["id"] != raffle_id):
        await state.clear()
        await callback.answer("⏳ На жаль, розіграш уже завершився.", show_alert=True)
        await _return_to_role_main_menu(callback, force_photo=True)
        return

    existing = await get_user_raffle_submission(raffle["id"], user_id)
    if existing:
        await state.clear()
        await callback.answer("Ви вже берете участь в акції!", show_alert=True)
        if callback.message:
            await _show_user_raffle_screen(callback.message, raffle, user_id, state, delete_old=True)
        return

    media_type = data.get("draft_media_type")
    file_id = data.get("draft_file_id")
    orig_filename = data.get("draft_orig_filename")
    file_size = data.get("draft_file_size") or 0
    draft_text = data.get("draft_text")
    local_file_path: Optional[str] = None

    if media_type and file_id:
        await callback.answer("⏳ Зберігаємо файл...")
        try:
            tg_file = await callback.bot.get_file(file_id)
            ext = ""
            if orig_filename and "." in orig_filename:
                _, ext = os.path.splitext(orig_filename)
            if not ext and tg_file.file_path and "." in tg_file.file_path:
                _, ext = os.path.splitext(tg_file.file_path)
            if not ext:
                if media_type == "photo":
                    ext = ".jpg"
                elif media_type == "video":
                    ext = ".mp4"
                else:
                    ext = ".bin"

            # Формуємо безпечне ім'я файлу на диску: ПІБ_user_id.ext
            user_details = await get_user_details(user_id)
            full_name = (user_details.get("full_name") if user_details else None)
            if not full_name:
                mgr = await get_manager_by_uid(user_id)
                if mgr:
                    full_name = mgr.get("full_name")
            full_name = full_name or callback.from_user.full_name

            safe_base = sanitize_participant_filename(full_name, user_id)
            raffle_dir = os.path.join(RAFFLES_MEDIA_DIR, str(raffle["id"]))
            os.makedirs(raffle_dir, exist_ok=True)
            local_file_path = os.path.join(raffle_dir, f"{safe_base}_{user_id}{ext}")

            await callback.bot.download_file(tg_file.file_path, destination=local_file_path)
            if os.path.exists(local_file_path):
                file_size = os.path.getsize(local_file_path)
        except Exception as exc:
            logger.exception(f"Failed to download raffle file for uid={user_id}, raffle={raffle['id']}: {exc}")
            await callback.message.answer(
                "❌ Не вдалося зберегти файл (можливо, він перевищує ліміт Telegram). Спробуйте надіслати інший файл:",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="user_raffle_back_main")]]
                ),
            )
            await state.set_state(RaffleParticipationStates.waiting_submission)
            return
    else:
        await callback.answer()

    ok, msg, _ = await add_raffle_submission(
        raffle_id=raffle["id"],
        user_id=user_id,
        submission_text=draft_text,
        media_type=media_type,
        file_id=file_id,
        local_file_path=local_file_path,
        file_size=file_size,
        fallback_username=callback.from_user.username,
        fallback_full_name=callback.from_user.full_name,
    )
    if not ok:
        await callback.answer(msg, show_alert=True)

    await state.clear()
    if callback.message:
        await _show_user_raffle_screen(callback.message, raffle, user_id, state, delete_old=True)


async def _return_to_role_main_menu(callback: CallbackQuery, force_photo: bool = False):
    from bot.handlers import main_menu_callback, main_menu_callback_force_photo

    if force_photo:
        await main_menu_callback_force_photo(callback)
    else:
        await main_menu_callback(callback)


async def user_raffle_back_main_handler(callback: CallbackQuery, state: FSMContext):
    """Повертає користувача в головне меню, очищуючи FSM очікування участі."""
    await state.clear()
    msg = callback.message
    is_media_or_text_only = bool(msg and (getattr(msg, "video", None) or not getattr(msg, "photo", None)))
    await _return_to_role_main_menu(callback, force_photo=is_media_or_text_only)


# =========================================================================
# 5. РЕЄСТРАЦІЯ ОБРОБНИКІВ
# =========================================================================


def register_raffle_handlers(dp: Dispatcher) -> None:
    """Реєструє всі адмінські та користувацькі обробники підсистеми розіграшів."""
    # Адмін-меню та історія
    dp.callback_query.register(dev_raffles_menu_handler, lambda c: c.data == "dev_raffles_menu")
    dp.callback_query.register(
        dev_raffle_history_handler,
        lambda c: c.data and (c.data == "dev_raffle_history" or c.data.startswith("dev_raffle_history:")),
    )
    dp.callback_query.register(dev_raffle_view_handler, lambda c: c.data and c.data.startswith("dev_raffle_view:"))
    dp.callback_query.register(dev_raffle_stop_handler, lambda c: c.data and c.data.startswith("dev_raffle_stop:"))
    dp.callback_query.register(
        dev_raffle_del_confirm_handler, lambda c: c.data and c.data.startswith("dev_raffle_del_confirm:")
    )
    dp.callback_query.register(dev_raffle_del_do_handler, lambda c: c.data and c.data.startswith("dev_raffle_del_do:"))
    dp.callback_query.register(dev_raffle_export_handler, lambda c: c.data and c.data.startswith("dev_raffle_export:"))

    # Майстер створення розіграшу
    dp.callback_query.register(dev_raffle_create_start, lambda c: c.data == "dev_raffle_create_start")
    dp.message.register(dev_raffle_process_content, RaffleCreateStates.waiting_content)
    dp.callback_query.register(dev_raffle_back_to_types_handler, lambda c: c.data == "dev_raffle_back_types")
    dp.callback_query.register(dev_raffle_select_type_handler, lambda c: c.data and c.data.startswith("dev_raffle_type:"))
    dp.callback_query.register(dev_raffle_select_fmt_handler, lambda c: c.data and c.data.startswith("dev_raffle_fmt:"))
    dp.callback_query.register(dev_raffle_duration_handler, lambda c: c.data and c.data.startswith("dev_raffle_dur:"))
    dp.message.register(dev_raffle_process_deadline_text, RaffleCreateStates.selecting_deadline)
    dp.callback_query.register(dev_raffle_back_deadline_handler, lambda c: c.data == "dev_raffle_back_deadline")
    dp.callback_query.register(
        dev_raffle_toggle_role_handler, lambda c: c.data and c.data.startswith("dev_raffle_toggle_role:")
    )
    dp.callback_query.register(dev_raffle_roles_all_handler, lambda c: c.data == "dev_raffle_roles_all")
    dp.callback_query.register(dev_raffle_to_city_handler, lambda c: c.data == "dev_raffle_to_city")
    dp.callback_query.register(dev_raffle_back_roles_handler, lambda c: c.data == "dev_raffle_back_roles")
    dp.callback_query.register(
        dev_raffle_select_city_handler, lambda c: c.data and c.data.startswith("dev_raffle_select_city:")
    )
    dp.callback_query.register(dev_raffle_toggle_ann_handler, lambda c: c.data == "dev_raffle_toggle_ann")
    dp.callback_query.register(
        dev_raffle_launch_handler,
        RaffleCreateStates.confirm_launch,
        lambda c: c.data == "dev_raffle_launch",
    )

    # Користувацька участь
    dp.callback_query.register(user_raffle_menu_handler, lambda c: c.data == "user_raffle_menu")
    dp.callback_query.register(
        user_raffle_join_btn_handler, lambda c: c.data and c.data.startswith("user_raffle_join_btn:")
    )
    dp.message.register(user_raffle_process_submission, RaffleParticipationStates.waiting_submission)
    dp.callback_query.register(user_raffle_confirm_sub_handler, lambda c: c.data == "user_raffle_confirm_sub")
    dp.callback_query.register(user_raffle_edit_sub_handler, lambda c: c.data == "user_raffle_edit_sub")
    dp.callback_query.register(user_raffle_back_main_handler, lambda c: c.data == "user_raffle_back_main")
