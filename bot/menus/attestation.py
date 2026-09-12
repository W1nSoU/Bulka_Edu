from __future__ import annotations
import asyncio
import io
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Set, Optional, Union

import pytz
from aiogram import Dispatcher, Bot
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BufferedInputFile
)
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.config import TIMEZONE
from bot.constants import AVAILABLE_SHOPS
from database.attestation import (
    get_active_wave,
    get_wave_by_id,
    get_wave_shop_by_id,
    get_all_waves,
    create_wave,
    activate_wave,
    close_wave,
    get_questions_for_role,
    get_questions_count_by_role,
    save_questions_for_role,
    get_wave_statistics,
    get_wave_shop_stats,
    get_shop_members_details,
    allow_user_retake,
    add_participants_batch,
    get_wave_participants,
    get_user_latest_attempt,
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
from database.positions import get_all_positions
from database.managers import get_all_managers
from database.hr import is_developer_user
from database.users import get_users_by_shop
from database import DB_PATH
import aiosqlite
from bot.services.attestation_excel import (
    generate_attestation_template,
    parse_attestation_excel,
    generate_attestation_results_xlsx
)
from bot.services.attestation_worker import (
    launch_attestation_broadcast,
    get_attestation_action_button
)

logger = logging.getLogger(__name__)


class AttestationStates(StatesGroup):
    waiting_excel_file = State()
    create_wave_target_type = State()
    create_wave_title = State()
    create_wave_q_count = State()
    create_wave_shops = State()
    create_wave_managers = State()
    create_wave_duration = State()
    create_wave_passing = State()
    create_wave_deadline = State()


async def get_all_system_roles() -> List[str]:
    """Повертає перелік усіх діючих посад у системі, включаючи 'Керівник'."""
    positions = await get_all_positions()
    roles = [p["name"] for p in positions]
    if "Керівник" not in roles:
        roles.insert(0, "Керівник")
    return sorted(list(set(roles)))


async def get_all_system_shops() -> List[str]:
    """Повертає повний перелік магазинів з constants та бази даних."""
    shops_set: Set[str] = set()
    for city, sh_list in AVAILABLE_SHOPS.items():
        for s in sh_list:
            shops_set.add(s.strip())

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT DISTINCT shop FROM users WHERE shop IS NOT NULL AND shop != ''") as cur:
            rows = await cur.fetchall()
            for r in rows:
                shops_set.add(r[0].strip())

    return sorted(list(shops_set))


async def _check_admin(callback_or_message) -> bool:
    uid = callback_or_message.from_user.id
    is_dev = await is_developer_user(uid)
    if not is_dev:
        if isinstance(callback_or_message, CallbackQuery):
            await callback_or_message.answer("⛔️ Доступ дозволено лише адміністраторам.", show_alert=True)
        else:
            await callback_or_message.answer("⛔️ Доступ дозволено лише адміністраторам.")
        return False
    return True


async def _safe_edit_or_answer(
    message_or_cb: Union[Message, CallbackQuery],
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: str = "HTML"
) -> Message:
    """
    Універсальний безпечний хелпер редагування повідомлення в адмін-панелі атестації:
    - Якщо повідомлення має фото (наприклад, з головного меню розсилок):
      - Якщо текст поміщається у підпис (<= 1000 символів), оновлює підпис (edit_caption).
      - Якщо не поміщається або помилка -> видаляє старе фото-повідомлення і надсилає текст (answer).
    - Якщо повідомлення звичайне текстове -> редагує текст (edit_text).
    - У разі збоїв (message not found, there is no text, caption too long) -> видаляє і надсилає нове.
    """
    message = message_or_cb.message if isinstance(message_or_cb, CallbackQuery) else message_or_cb
    has_photo = bool(getattr(message, "photo", None))
    if has_photo:
        if len(text) <= 1000:
            try:
                await message.edit_caption(caption=text, parse_mode=parse_mode, reply_markup=reply_markup)
                return message
            except TelegramBadRequest as e:
                if "message is not modified" in str(e).lower():
                    return message
            except Exception:
                pass
        try:
            await message.delete()
        except Exception:
            pass
        return await message.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)

    try:
        await message.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
        return message
    except TelegramBadRequest as e:
        err = str(e).lower()
        if "message is not modified" in err:
            return message
        try:
            await message.delete()
        except Exception:
            pass
        return await message.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)
    except Exception:
        try:
            await message.delete()
        except Exception:
            pass
        return await message.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)


# =============================================================
# 1. ГОЛОВНЕ МЕНЮ АТЕСТАЦІЇ
# =============================================================

async def dev_attestation_menu_handler(callback: CallbackQuery, state: Optional[FSMContext] = None):
    if not await _check_admin(callback):
        return
    if state:
        await state.clear()

    active_wave = await get_active_wave()

    text = "🎓 <b>Корпоративна піврічна атестація BULKA</b>\n\n"
    if active_wave:
        tgt_badge = "🥐 Працівники пекарень" if active_wave.get("target_type") == "staff" else "👔 Керівники"
        text += (
            f"🟢 <b>Активна хвиля:</b> <b>{active_wave['title']}</b>\n"
            f"🎯 <b>Цільова група:</b> {tgt_badge}\n"
            f"🏪 <b>Магазинів у хвилі:</b> {len(active_wave.get('shops', []))}\n"
            f"⏱ <b>Таймер:</b> {active_wave['duration_minutes']} хв | <b>Поріг:</b> {active_wave['passing_score_pct']}%\n"
            f"📅 <b>Дедлайн:</b> {active_wave['deadline_date']}\n\n"
            f"<i>Тестування триває у Telegram через нативні кнопки.</i>"
        )
    else:
        text += (
            "⚪️ <b>Статус:</b> Наразі немає активної хвилі атестації.\n\n"
            "Ви можете оновити банк питань через Excel або створити нову хвилю для працівників або керівників."
        )

    buttons = []
    if active_wave:
        buttons.append([InlineKeyboardButton(text="📊 Деталі активної хвилі", callback_data=f"dev_att_active_wave:{active_wave['id']}")])
    buttons.append([InlineKeyboardButton(text="➕ Створити хвилю атестації", callback_data="dev_att_create_wave")])
    buttons.append([InlineKeyboardButton(text="📚 Питання за посадами (Excel)", callback_data="dev_att_questions_menu")])
    buttons.append([InlineKeyboardButton(text="📁 Історія хвиль", callback_data="dev_att_history")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад у розсилки", callback_data="dev_broadcasts_menu")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    from bot.menus.developer import _show_admin_photo_menu
    await _show_admin_photo_menu(
        callback,
        "img/admin/admin_broadcasts.jpg",
        text,
        kb
    )


# =============================================================
# 2. КЕРУВАННЯ ПИТАННЯМИ (EXCEL)
# =============================================================

async def dev_att_questions_menu_handler(callback: CallbackQuery, state: FSMContext):
    if not await _check_admin(callback):
        return
    await state.clear()

    roles = await get_all_system_roles()
    q_counts = await get_questions_count_by_role()

    text = "📚 <b>Банк запитань корпоративної атестації</b>\n\n"
    text += "Кількість питань за посадами:\n"
    total_q = 0
    for role in roles:
        cnt = q_counts.get(role, 0)
        total_q += cnt
        icon = "✅" if cnt >= 5 else ("⚠️" if cnt > 0 else "❌")
        text += f"• {icon} <b>{role}:</b> {cnt} питань\n"

    text += f"\n<b>Всього в базі:</b> {total_q} питань.\n\n"
    text += "<i>Завантажте шаблон Excel, заповніть аркуші за посадами та завантажте назад у бот.</i>"

    buttons = [
        [InlineKeyboardButton(text="📥 Завантажити шаблон Excel", callback_data="dev_att_download_template")],
        [InlineKeyboardButton(text="📤 Оновити питання (Excel)", callback_data="dev_att_upload_excel")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="dev_attestation_menu")]
    ]
    await _safe_edit_or_answer(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


async def dev_att_download_template_handler(callback: CallbackQuery):
    if not await _check_admin(callback):
        return
    await callback.answer("⏳ Генерація шаблону...")

    roles = await get_all_system_roles()
    excel_io = generate_attestation_template(roles)

    file = BufferedInputFile(
        file=excel_io.read(),
        filename="template_attestation_bulka.xlsx"
    )

    caption = (
        "📥 <b>Еталонний шаблон атестації BULKA</b>\n\n"
        "• Кожен аркуш файлу відповідає конкретній посаді.\n"
        "• Заповніть питання, варіанти відповідей, номер правильної відповіді (1–4) та бали.\n"
        "• Після заповнення надішліть файл назад через кнопку <b>«📤 Оновити питання»</b>."
    )
    await callback.message.answer_document(document=file, caption=caption, parse_mode="HTML")


async def dev_att_upload_excel_handler(callback: CallbackQuery, state: FSMContext):
    if not await _check_admin(callback):
        return

    await state.set_state(AttestationStates.waiting_excel_file)
    text = (
        "📤 <b>Оновлення банку запитань через Excel</b>\n\n"
        "Будь ласка, надішліть заповнений файл у форматі <code>.xlsx</code> як документ у цей чат.\n\n"
        "<i>Для скасування натисніть кнопку нижче.</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="dev_att_questions_menu")]
    ])
    await _safe_edit_or_answer(callback, text, reply_markup=kb)
    await callback.answer()


async def att_process_excel_document(message: Message, state: FSMContext, bot: Bot):
    if not await _check_admin(message):
        return

    doc = message.document
    if not doc or not doc.file_name.endswith(('.xlsx', '.xlsm')):
        await message.answer("⚠️ Будь ласка, надішліть саме Excel-файл з розширенням <code>.xlsx</code>.")
        return

    wait_msg = await message.answer("⏳ Обробка та валідація файлу атестації...")

    try:
        file_io = io.BytesIO()
        await bot.download(doc, destination=file_io)
        file_bytes = file_io.getvalue()

        roles = await get_all_system_roles()
        parsed_data, warnings = parse_attestation_excel(file_bytes, roles)

        if not parsed_data:
            warn_text = "\n".join(f"• {w}" for w in warnings[:10])
            await wait_msg.edit_text(
                f"❌ <b>Помилка імпорту!</b> Не знайдено коректних запитань у файлі.\n\n{warn_text}",
                parse_mode="HTML"
            )
            return

        total_saved = 0
        saved_roles = []
        for role, q_list in parsed_data.items():
            inserted = await save_questions_for_role(role, q_list)
            total_saved += inserted
            saved_roles.append(f"• <b>{role}:</b> {inserted} питань")

        await state.clear()

        res_text = (
            f"✅ <b>Успішно оновлено банк питань атестації!</b>\n\n"
            f"Всього завантажено: <b>{total_saved}</b> запитань.\n\n"
            + "\n".join(saved_roles)
        )
        if warnings:
            res_text += f"\n\n⚠️ <i>Попередження ({len(warnings)}):</i>\n" + "\n".join(f"• {w}" for w in warnings[:5])

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📚 До банку питань", callback_data="dev_att_questions_menu")],
            [InlineKeyboardButton(text="🎓 В меню атестації", callback_data="dev_attestation_menu")]
        ])
        await wait_msg.edit_text(res_text, parse_mode="HTML", reply_markup=kb)

    except Exception as e:
        logger.error(f"Помилка імпорту атестації з Excel: {e}")
        await wait_msg.edit_text(f"❌ Сталася помилка під час обробки файлу: {str(e)}")


# =============================================================
# 3. МАЙСТЕР СТВОРЕННЯ ХВИЛІ АТЕСТАЦІЇ (FSM WIZARD)
# =============================================================

async def dev_att_create_wave_handler(callback: CallbackQuery, state: FSMContext):
    if not await _check_admin(callback):
        return

    active_wave = await get_active_wave()
    if active_wave:
        text = (
            f"⚠️ <b>Увага:</b> В системі вже діє активна хвиля <b>«{active_wave['title']}»</b>!\n\n"
            "Запуск нової хвилі автоматично завершить поточну активну хвилю.\nБажаєте продовжити?"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Продовжити", callback_data="dev_att_create_wave_confirmed")],
            [InlineKeyboardButton(text="❌ Скасувати", callback_data="dev_attestation_menu")]
        ])
        await _safe_edit_or_answer(callback, text, reply_markup=kb)
        await callback.answer()
        return

    await _start_create_wave_flow(callback, state)


async def dev_att_create_wave_confirmed_handler(callback: CallbackQuery, state: FSMContext):
    await _start_create_wave_flow(callback, state)


async def _start_create_wave_flow(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(AttestationStates.create_wave_target_type)
    text = (
        "➕ <b>Створення нової хвилі атестації</b> [Крок 1/4]\n\n"
        "Оберіть <b>цільову категорію учасників</b> для цієї атестації:\n\n"
        "• <b>Працівники пекарень</b> — атестація персоналу за обраними пекарнями.\n"
        "• <b>Керівники</b> — окрема управлінська атестація керуючих пекарень."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🥐 Працівники пекарень", callback_data="dev_att_tgt:staff")],
        [InlineKeyboardButton(text="👔 Керівники", callback_data="dev_att_tgt:managers")],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="dev_attestation_menu")]
    ])
    await _safe_edit_or_answer(callback, text, reply_markup=kb)
    await callback.answer()


async def dev_att_target_type_handler(callback: CallbackQuery, state: FSMContext):
    if not await _check_admin(callback):
        return

    target_type = callback.data.split(":")[1]
    await state.update_data(target_type=target_type)
    await state.set_state(AttestationStates.create_wave_title)

    tgt_label = "Працівники пекарень" if target_type == "staff" else "Керівники"
    text = (
        f"➕ <b>Створення нової хвилі атестації ({tgt_label})</b> [Крок 2/5]\n\n"
        "Введіть назву хвилі атестації:\n"
        f"<i>(наприклад: <b>Осіння атестація 2026 ({tgt_label})</b>)</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="dev_attestation_menu")]
    ])
    await _safe_edit_or_answer(callback, text, reply_markup=kb)
    await callback.answer()


async def att_process_wave_title(message: Message, state: FSMContext):
    if not await _check_admin(message):
        return

    title = message.text.strip()
    if len(title) < 3:
        await message.answer("⚠️ Назва занадто коротка. Введіть назву хвилі:")
        return

    await state.update_data(wave_title=title)
    await state.set_state(AttestationStates.create_wave_q_count)
    await _render_q_count_picker(message, state)


async def _render_q_count_picker(message_or_cb: Any, state: FSMContext):
    data = await state.get_data()
    title = data.get("wave_title", "")
    target_type = data.get("target_type", "staff")
    tgt_label = "Працівники пекарень" if target_type == "staff" else "Керівники"

    text = (
        f"➕ <b>Створення нової хвилі атестації ({tgt_label})</b> [Крок 3/5]\n\n"
        f"🏷 <b>Назва:</b> {title}\n\n"
        "🔢 <b>Оберіть кількість питань у тесті:</b>\n"
        "<i>Для кожного учасника бот сформує унікальний набір випадкових запитань без повторень із банку.</i>\n\n"
        "<i>Оберіть одне зі стандартних значень або введіть довільне:</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="5 питань", callback_data="dev_att_qcnt:5"),
            InlineKeyboardButton(text="10 питань", callback_data="dev_att_qcnt:10"),
        ],
        [
            InlineKeyboardButton(text="15 питань", callback_data="dev_att_qcnt:15"),
            InlineKeyboardButton(text="20 питань", callback_data="dev_att_qcnt:20"),
        ],
        [
            InlineKeyboardButton(text="✏️ Ввести іншу кількість", callback_data="dev_att_qcnt:custom")
        ],
        [
            InlineKeyboardButton(text="❌ Скасувати", callback_data="dev_attestation_menu")
        ]
    ])
    await _safe_edit_or_answer(message_or_cb, text, reply_markup=kb)


async def dev_att_change_qcnt_handler(callback: CallbackQuery, state: FSMContext):
    if not await _check_admin(callback):
        return
    await state.set_state(AttestationStates.create_wave_q_count)
    await _render_q_count_picker(callback, state)
    await callback.answer()


async def dev_att_qcnt_callback_handler(callback: CallbackQuery, state: FSMContext):
    if not await _check_admin(callback):
        return
    val = callback.data.split(":")[1]
    if val == "custom":
        await state.set_state(AttestationStates.create_wave_q_count)
        text = (
            "✏️ <b>Введіть бажану кількість питань у тесті:</b>\n\n"
            "<i>Надішліть повідомленням ціле число від 1 до 100 (наприклад: 10):</i>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад до варіантів", callback_data="dev_att_change_qcnt")],
            [InlineKeyboardButton(text="❌ Скасувати", callback_data="dev_attestation_menu")]
        ])
        await _safe_edit_or_answer(callback, text, reply_markup=kb)
        await callback.answer()
        return

    q_count = int(val)
    await callback.answer()
    await _proceed_after_q_count(callback, state, q_count)


async def att_process_wave_q_count_msg(message: Message, state: FSMContext):
    if not await _check_admin(message):
        return
    txt = (message.text or "").strip()
    if not txt.isdigit() or not (1 <= int(txt) <= 100):
        await message.answer("⚠️ Будь ласка, введіть коректне число питань від 1 до 100:")
        return
    q_count = int(txt)
    await _proceed_after_q_count(message, state, q_count)


async def _proceed_after_q_count(message_or_cb: Any, state: FSMContext, q_count: int):
    await state.update_data(questions_count=q_count)
    data = await state.get_data()
    target_type = data.get("target_type", "staff")

    if target_type == "managers":
        await state.update_data(selected_managers=[])
        await state.set_state(AttestationStates.create_wave_managers)
        await _render_managers_picker(message_or_cb, state, page=1)
    else:
        await state.update_data(selected_shops=[])
        await state.set_state(AttestationStates.create_wave_shops)
        await _render_shops_picker(message_or_cb, state, page=1)


# -------------------------------------------------------------
# Вибір магазинів (для Staff)
# -------------------------------------------------------------

async def _render_shops_picker(message_or_cb, state: FSMContext, page: int = 1):
    data = await state.get_data()
    selected_shops: List[str] = data.get("selected_shops", [])
    all_shops = await get_all_system_shops()

    per_page = 6
    total_pages = max(1, (len(all_shops) + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * per_page
    page_shops = all_shops[start_idx:start_idx + per_page]

    text = (
        f"🏪 <b>Вибір магазинів для атестації</b> [Крок 2/4]\n"
        f"Хвиля: <b>{data.get('wave_title')}</b>\n\n"
        f"Обрано магазинів: <b>{len(selected_shops)}</b> з {len(all_shops)}\n\n"
        f"<i>Натискайте на кнопки пекарень, щоб додати або зняти позначку:</i>"
    )

    buttons = []
    for idx_in_page, s in enumerate(page_shops):
        global_idx = start_idx + idx_in_page
        is_sel = s in selected_shops
        mark = "✅ " if is_sel else "⬜️ "
        btn_text = f"{mark}{s[:24]}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"dev_att_tgl_sh:{global_idx}")])

    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"dev_att_sh_p:{page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"dev_att_sh_p:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([
        InlineKeyboardButton(text="☑️ Обрати всі", callback_data="dev_att_sh_all"),
        InlineKeyboardButton(text="◻️ Очистити", callback_data="dev_att_sh_clear")
    ])
    buttons.append([
        InlineKeyboardButton(text=f"Далі ➡️ ({len(selected_shops)} обр.)", callback_data="dev_att_sh_done")
    ])
    buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="dev_attestation_menu")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _safe_edit_or_answer(message_or_cb, text, reply_markup=kb)
    if isinstance(message_or_cb, CallbackQuery):
        await message_or_cb.answer()


async def dev_att_toggle_shop_handler(callback: CallbackQuery, state: FSMContext):
    all_shops = await get_all_system_shops()
    try:
        shop_idx = int(callback.data.split(":", 1)[1])
        shop_name = all_shops[shop_idx]
    except (IndexError, ValueError):
        await callback.answer("Помилка вибору магазину", show_alert=True)
        return

    data = await state.get_data()
    selected_shops = set(data.get("selected_shops", []))

    if shop_name in selected_shops:
        selected_shops.remove(shop_name)
    else:
        selected_shops.add(shop_name)

    await state.update_data(selected_shops=list(selected_shops))
    page = (shop_idx // 6) + 1
    await _render_shops_picker(callback, state, page=page)


async def dev_att_select_all_shops_handler(callback: CallbackQuery, state: FSMContext):
    all_shops = await get_all_system_shops()
    await state.update_data(selected_shops=all_shops)
    await _render_shops_picker(callback, state, page=1)


async def dev_att_clear_shops_handler(callback: CallbackQuery, state: FSMContext):
    await state.update_data(selected_shops=[])
    await _render_shops_picker(callback, state, page=1)


async def dev_att_shops_page_handler(callback: CallbackQuery, state: FSMContext):
    page = int(callback.data.split(":")[1])
    await _render_shops_picker(callback, state, page=page)


async def dev_att_shops_done_handler(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected_shops = data.get("selected_shops", [])
    if not selected_shops:
        await callback.answer("⚠️ Оберіть щонайменше 1 магазин для атестації!", show_alert=True)
        return

    await _prompt_duration_step(callback, state)


# -------------------------------------------------------------
# Вибір керівників (для Managers)
# -------------------------------------------------------------

async def _get_active_managers_list() -> List[Dict[str, Any]]:
    managers = await get_all_managers()
    active_mgrs = [m for m in managers if m.get("status") != "fired"]
    return sorted(active_mgrs, key=lambda m: m.get("name") or m.get("full_name") or "")


async def _render_managers_picker(message_or_cb, state: FSMContext, page: int = 1):
    data = await state.get_data()
    selected_mgr_ids: Set[int] = set(data.get("selected_managers", []))
    all_mgrs = await _get_active_managers_list()

    per_page = 6
    total_pages = max(1, (len(all_mgrs) + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * per_page
    page_mgrs = all_mgrs[start_idx:start_idx + per_page]

    text = (
        f"👔 <b>Вибір керівників для атестації</b>\n"
        f"Хвиля: <b>{data.get('wave_title')}</b>\n\n"
        f"Обрано керівників: <b>{len(selected_mgr_ids)}</b> з {len(all_mgrs)}\n\n"
        f"<i>Натискайте на керівників для вибору:</i>"
    )

    buttons = []
    for idx_in_page, m in enumerate(page_mgrs):
        global_idx = start_idx + idx_in_page
        uid = int(m.get("uid") or m.get("user_id"))
        is_sel = uid in selected_mgr_ids
        mark = "✅ " if is_sel else "⬜️ "
        name = m.get("full_name") or m.get("name") or "Керівник"
        btn_text = f"{mark}{name[:24]}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"dev_att_tgl_mgr:{global_idx}")])

    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"dev_att_mgr_p:{page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"dev_att_mgr_p:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([
        InlineKeyboardButton(text="☑️ Обрати всіх", callback_data="dev_att_mgr_all"),
        InlineKeyboardButton(text="◻️ Очистити", callback_data="dev_att_mgr_clear")
    ])
    buttons.append([
        InlineKeyboardButton(text=f"Далі ➡️ ({len(selected_mgr_ids)} обр.)", callback_data="dev_att_mgr_done")
    ])
    buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="dev_attestation_menu")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _safe_edit_or_answer(message_or_cb, text, reply_markup=kb)
    if isinstance(message_or_cb, CallbackQuery):
        await message_or_cb.answer()


async def dev_att_toggle_manager_handler(callback: CallbackQuery, state: FSMContext):
    all_mgrs = await _get_active_managers_list()
    try:
        mgr_idx = int(callback.data.split(":", 1)[1])
        mgr = all_mgrs[mgr_idx]
        uid = int(mgr.get("uid") or mgr.get("user_id"))
    except (IndexError, ValueError):
        await callback.answer("Помилка вибору керівника", show_alert=True)
        return

    data = await state.get_data()
    selected = set(data.get("selected_managers", []))

    if uid in selected:
        selected.remove(uid)
    else:
        selected.add(uid)

    await state.update_data(selected_managers=list(selected))
    page = (mgr_idx // 6) + 1
    await _render_managers_picker(callback, state, page=page)


async def dev_att_select_all_managers_handler(callback: CallbackQuery, state: FSMContext):
    all_mgrs = await _get_active_managers_list()
    all_uids = [int(m.get("uid") or m.get("user_id")) for m in all_mgrs]
    await state.update_data(selected_managers=all_uids)
    await _render_managers_picker(callback, state, page=1)


async def dev_att_clear_managers_handler(callback: CallbackQuery, state: FSMContext):
    await state.update_data(selected_managers=[])
    await _render_managers_picker(callback, state, page=1)


async def dev_att_managers_page_handler(callback: CallbackQuery, state: FSMContext):
    page = int(callback.data.split(":")[1])
    await _render_managers_picker(callback, state, page=page)


async def dev_att_managers_done_handler(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected_mgrs = data.get("selected_managers", [])
    if not selected_mgrs:
        await callback.answer("⚠️ Оберіть щонайменше 1 керівника для атестації!", show_alert=True)
        return

    await _prompt_duration_step(callback, state)


# -------------------------------------------------------------
# Кроки: Тривалість, Поріг, Підтвердження
# -------------------------------------------------------------

async def _prompt_duration_step(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AttestationStates.create_wave_duration)
    text = (
        "⏱ <b>Тривалість тестування</b> [Крок 3/4]\n\n"
        "Скільки хвилин надається на проходження атестації з моменту натискання кнопки старту?\n"
        "<i>(Таймер рахується на сервері)</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="15 хв", callback_data="dev_att_dur:15"),
            InlineKeyboardButton(text="20 хв (реком.)", callback_data="dev_att_dur:20")
        ],
        [
            InlineKeyboardButton(text="25 хв", callback_data="dev_att_dur:25"),
            InlineKeyboardButton(text="30 хв", callback_data="dev_att_dur:30")
        ],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="dev_attestation_menu")]
    ])
    await _safe_edit_or_answer(callback, text, reply_markup=kb)
    await callback.answer()


async def dev_att_duration_handler(callback: CallbackQuery, state: FSMContext):
    dur = int(callback.data.split(":")[1])
    await state.update_data(wave_duration=dur)

    await state.set_state(AttestationStates.create_wave_passing)
    text = (
        "🎯 <b>Прохідний бал атестації</b> [Крок 4/4]\n\n"
        "Який відсоток правильних відповідей необхідний для успішного зарахування?"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="70%", callback_data="dev_att_pass:70"),
            InlineKeyboardButton(text="75%", callback_data="dev_att_pass:75")
        ],
        [
            InlineKeyboardButton(text="80% (стандарт)", callback_data="dev_att_pass:80"),
            InlineKeyboardButton(text="85%", callback_data="dev_att_pass:85")
        ],
        [InlineKeyboardButton(text="90%", callback_data="dev_att_pass:90")],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="dev_attestation_menu")]
    ])
    await _safe_edit_or_answer(callback, text, reply_markup=kb)
    await callback.answer()


async def dev_att_passing_handler(callback: CallbackQuery, state: FSMContext):
    passing = int(callback.data.split(":")[1])
    
    # Атестація діє 1 день за замовчуванням
    days = 1
    tz = pytz.timezone(TIMEZONE)
    deadline_dt = datetime.now(tz) + timedelta(days=days)
    deadline_str = deadline_dt.strftime("%Y-%m-%d 23:59:59")
    await state.update_data(wave_passing=passing, wave_deadline=deadline_str, wave_deadline_days=days)

    data = await state.get_data()
    title = data["wave_title"]
    dur = data["wave_duration"]
    pass_pct = passing
    target_type = data.get("target_type", "staff")
    q_count = data.get("questions_count", 10)

    if target_type == "managers":
        mgr_ids = data.get("selected_managers", [])
        participants_to_register = await _collect_eligible_participants(mgr_ids, target_type="managers")
        tgt_text = f"👔 <b>Цільова група:</b> Керівники ({len(mgr_ids)} обрано)\n"
    else:
        shops = data.get("selected_shops", [])
        participants_to_register = await _collect_eligible_participants(shops, target_type="staff")
        tgt_text = f"🏪 <b>Обрано пекарень:</b> {len(shops)}\n"

    # Перевірка наявності питань у банку для всіх посад учасників
    needed_roles = set(p["role_name"] for p in participants_to_register)
    q_counts = await get_questions_count_by_role()
    deficient_roles = []
    for r in sorted(needed_roles):
        avail = q_counts.get(r, 0)
        if avail < q_count:
            deficient_roles.append((r, avail, q_count))

    text = (
        "📋 <b>Підтвердження запуску атестації</b>\n\n"
        f"🏷 <b>Назва:</b> {title}\n"
        f"{tgt_text}"
        f"👥 <b>Потенційних учасників:</b> {len(participants_to_register)} ос.\n"
        f"🔢 <b>Питань у тесті:</b> {q_count} (випадкова унікальна вибірка)\n"
        f"⏱ <b>Час на тест:</b> {dur} хв (серверний таймер)\n"
        f"🎯 <b>Прохідний поріг:</b> {pass_pct}%\n"
        f"📅 <b>Дедлайн здачі:</b> 1 день (до {deadline_dt.strftime('%d.%m.%Y о 23:59')})\n\n"
    )

    if deficient_roles:
        text += "⚠️ <b>Неможливо запустити атестацію! У банку недостатньо питань:</b>\n"
        for r, avail, req in deficient_roles:
            text += f"• ⚠️ <b>{r}:</b> {avail} з {req} необхідних\n"
        text += (
            "\n💡 <i>Запуск заблоковано. Будь ласка, додайте питання в банк або оберіть меншу кількість питань для тесту.</i>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Змінити к-ть питань", callback_data="dev_att_change_qcnt")],
            [InlineKeyboardButton(text="📚 Банк запитань", callback_data="dev_att_questions_menu")],
            [InlineKeyboardButton(text="❌ Скасувати", callback_data="dev_attestation_menu")]
        ])
    else:
        text += "<i>Після натискання «Запустити» хвиля активується, а всім учасникам буде надіслано персональне запрошення з інлайн-кнопкою старту тесту.</i>"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Запустити атестацію", callback_data="dev_att_confirm_launch")],
            [InlineKeyboardButton(text="🔄 Змінити к-ть питань", callback_data="dev_att_change_qcnt")],
            [InlineKeyboardButton(text="❌ Скасувати", callback_data="dev_attestation_menu")]
        ])

    await _safe_edit_or_answer(callback, text, reply_markup=kb)
    await callback.answer()


async def _collect_eligible_participants(
    targets: List[Any],
    target_type: str = "staff"
) -> List[Dict[str, Any]]:
    """
    Знаходить діючих працівників або керівників для атестації.
    - target_type == 'staff': шукає тільки працівників обраних магазинів (без керівників).
    - target_type == 'managers': шукає керівників за переданими user_id або магазинами.
    """
    participants = []
    seen_uids = set()

    if target_type == "managers":
        managers = await get_all_managers()
        target_uids = set(int(t) for t in targets) if targets else set()

        for m in managers:
            if m.get("status") == "fired":
                continue
            m_uid = int(m.get("uid") or m.get("user_id") or 0)
            if not m_uid or (target_uids and m_uid not in target_uids):
                continue
            if m_uid in seen_uids:
                continue

            seen_uids.add(m_uid)
            m_shops = m.get("shops", [])
            if isinstance(m_shops, str):
                try:
                    m_shops = json.loads(m_shops)
                except Exception:
                    m_shops = [m_shops]
            elif not isinstance(m_shops, list):
                m_shops = []
            primary_shop = m_shops[0] if m_shops else "Керівництво"

            participants.append({
                "user_id": m_uid,
                "full_name": m.get("full_name") or m.get("name") or "Керівник",
                "role_name": "Керівник",
                "shop_name": primary_shop,
                "is_manager": 1
            })

    else:
        # staff mode: шукаємо працівників пекарень
        shops = [str(s) for s in targets]
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            for shop in shops:
                async with db.execute(
                    "SELECT user_id, full_name, role, shop, status FROM users WHERE shop = ? AND status = 'Працівник' AND (role != 'Керівник' OR role IS NULL)",
                    (shop,)
                ) as cur:
                    rows = await cur.fetchall()
                    for r in rows:
                        uid = r["user_id"]
                        if uid not in seen_uids:
                            seen_uids.add(uid)
                            participants.append({
                                "user_id": uid,
                                "full_name": r["full_name"],
                                "role_name": r["role"] or "ВВ Пекар",
                                "shop_name": r["shop"],
                                "is_manager": 0
                            })

    return participants


async def dev_att_confirm_launch_handler(callback: CallbackQuery, state: FSMContext, bot: Bot):
    if not await _check_admin(callback):
        return

    data = await state.get_data()
    title = data.get("wave_title")
    dur = data.get("wave_duration", 20)
    pass_pct = data.get("wave_passing", 80)
    deadline = data.get("wave_deadline")
    target_type = data.get("target_type", "staff")
    q_count = data.get("questions_count", 10)

    if target_type == "managers":
        mgr_ids = data.get("selected_managers", [])
        if not title or not mgr_ids:
            await callback.answer("⚠️ Дані сесії втрачено. Почніть знову.", show_alert=True)
            await state.clear()
            return
        participants = await _collect_eligible_participants(mgr_ids, target_type="managers")
        shops = list(set(p["shop_name"] for p in participants))
    else:
        shops = data.get("selected_shops", [])
        if not title or not shops:
            await callback.answer("⚠️ Дані сесії втрачено. Почніть знову.", show_alert=True)
            await state.clear()
            return
        participants = await _collect_eligible_participants(shops, target_type="staff")

    # Сувора валідація банку питань перед запуском
    needed_roles = set(p["role_name"] for p in participants)
    q_counts = await get_questions_count_by_role()
    deficient_roles = [r for r in needed_roles if q_counts.get(r, 0) < q_count]
    if deficient_roles:
        def_str = ", ".join(f"{r} ({q_counts.get(r, 0)}/{q_count})" for r in deficient_roles)
        await callback.answer(f"⚠️ Недостатньо питань у банку для: {def_str}. Змініть кількість або додайте питання!", show_alert=True)
        return

    await _safe_edit_or_answer(callback, "⏳ Створення та активація хвилі атестації...")

    # Створюємо хвилю
    wave_id = await create_wave(
        title=title,
        created_by=callback.from_user.id,
        duration_minutes=dur,
        passing_score_pct=pass_pct,
        deadline_date=deadline,
        shops=shops,
        target_type=target_type,
        questions_count=q_count
    )
    await activate_wave(wave_id)

    # Реєструємо учасників
    await add_participants_batch(wave_id, participants)

    # Запускаємо похвильову розсилку у фоні
    bot_instance = bot or callback.bot
    asyncio.create_task(launch_attestation_broadcast(bot_instance, wave_id))

    await state.clear()
    tgt_desc = "Працівники пекарень" if target_type == "staff" else "Керівники"
    await callback.message.answer(
        f"🎉 <b>Хвилю атестації «{title}» успішно запущено!</b>\n\n"
        f"🎯 Цільова група: <b>{tgt_desc}</b>\n"
        f"🏪 Пекарень: <b>{len(shops)}</b>\n"
        f"👥 Зареєстровано учасників: <b>{len(participants)}</b>\n"
        f"🔢 Питань у тесті: <b>{q_count}</b>\n"
        f"⏱ Час на спробу: <b>{dur} хв</b>\n"
        f"🎯 Прохідний поріг: <b>{pass_pct}%</b>\n\n"
        f"Похвильова розсилка запрошень розпочалася.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Деталі активної хвилі", callback_data=f"dev_att_active_wave:{wave_id}")],
            [InlineKeyboardButton(text="🎓 В меню атестації", callback_data="dev_attestation_menu")]
        ])
    )


# =============================================================
# 4. МОНІТОРИНГ АКТИВНОЇ ХВИЛІ ТА МАГАЗИНІВ
# =============================================================

async def dev_att_active_wave_handler(callback: CallbackQuery):
    if not await _check_admin(callback):
        return

    parts = callback.data.split(":")
    wave_id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None

    if wave_id:
        wave = await get_wave_by_id(wave_id)
    else:
        wave = await get_active_wave()

    if not wave:
        await callback.answer("Хвилю не знайдено або вона завершена.", show_alert=True)
        return

    wave_id = wave["id"]
    stats = await get_wave_statistics(wave_id)
    shop_statuses = await get_wave_shops_status(wave_id)
    status_map = {s["shop_name"]: s["status"] for s in shop_statuses}

    pct_done = round((stats["completed_count"] / stats["total_participants"] * 100), 1) if stats["total_participants"] > 0 else 0.0
    tgt_desc = "🥐 Працівники пекарень" if wave.get("target_type") == "staff" else "👔 Керівники"

    text = (
        f"📊 <b>Результати атестації: {wave['title']}</b>\n"
        f"🎯 Цільова група: <b>{tgt_desc}</b>\n"
        f"📅 <b>Дедлайн:</b> {wave['deadline_date']}\n"
        f"🎯 <b>Прохідний бал:</b> {wave['passing_score_pct']}%\n\n"
        f"📈 <b>Прогрес мережі:</b>\n"
        f"• Всього учасників: <b>{stats['total_participants']}</b> ос.\n"
        f"• Завершили тест: <b>{stats['completed_count']}</b> ({pct_done}%)\n"
        f"• ✅ Склали успішно: <b>{stats['passed_count']}</b>\n"
        f"• ❌ Не склали: <b>{stats['failed_count']}</b>\n"
        f"• ⭐️ Середній бал: <b>{stats['avg_score']}%</b>\n\n"
        f"🏪 <b>Пекарні хвилі (натисніть для деталей):</b>"
    )

    buttons = []
    shop_stats = await get_wave_shop_stats(wave_id)
    for s in shop_stats:
        sh_id = s.get("shop_id", 0)
        sh_name = s["shop_name"]
        is_active = status_map.get(sh_name, "active") == "active"
        icon = "🟢" if is_active else "🔴"
        status_suffix = "" if is_active else " (Зупинено)"
        label = f"{icon} {sh_name[:20]}{status_suffix} ({s['completed']}/{s['total_participants']} — {s['avg_score_pct']}%)"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"dev_att_sh_dt:{sh_id}")])

    # Кнопка підключення ще одного магазину для активних staff хвиль
    if wave.get("status") == "active" and wave.get("target_type") == "staff":
        buttons.append([InlineKeyboardButton(text="➕ Запустити ще магазин", callback_data=f"dev_att_add_sh_menu:{wave_id}")])

    buttons.append([InlineKeyboardButton(text="📊 Вивантажити звіт XLSX", callback_data=f"dev_att_export_xlsx:{wave_id}")])
    if wave.get("status") == "active":
        buttons.append([InlineKeyboardButton(text="🛑 Завершити всю атестацію", callback_data=f"dev_att_close:{wave_id}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="dev_attestation_menu")])

    await _safe_edit_or_answer(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


# -------------------------------------------------------------
# Динамічне підключення магазину до активної хвилі
# -------------------------------------------------------------

async def dev_att_add_shop_menu_handler(callback: CallbackQuery):
    if not await _check_admin(callback):
        return

    parts = callback.data.split(":")
    wave_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 and parts[0] == "dev_att_add_sh_p" else 1

    wave = await get_wave_by_id(wave_id)
    if not wave:
        await callback.answer("Хвилю не знайдено", show_alert=True)
        return

    current_shops = set(wave.get("shops", []))
    all_shops = await get_all_system_shops()
    available_to_add = [s for s in all_shops if s not in current_shops]

    if not available_to_add:
        await callback.answer("Усі діючі магазини мережі вже підключені до цієї хвилі!", show_alert=True)
        return

    PER_PAGE = 8
    total_pages = max(1, (len(available_to_add) + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * PER_PAGE
    page_shops = available_to_add[start_idx:start_idx + PER_PAGE]

    text = (
        f"➕ <b>Підключити магазин до активної атестації</b>\n"
        f"Хвиля: <b>{wave['title']}</b>\n\n"
        f"Оберіть пекарню для відкриття тестування та відправки запрошень працівникам:"
    )

    buttons = []
    for s in page_shops:
        global_idx = all_shops.index(s)
        buttons.append([InlineKeyboardButton(text=f"🏪 {s[:26]}", callback_data=f"dev_att_add_sh_cf:{wave_id}:{global_idx}")])

    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"dev_att_add_sh_p:{wave_id}:{page - 1}"))
    if total_pages > 1:
        nav_row.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"dev_att_add_sh_p:{wave_id}:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton(text="🔙 До активної хвилі", callback_data=f"dev_att_active_wave:{wave_id}")])
    await _safe_edit_or_answer(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


async def dev_att_add_shop_confirm_handler(callback: CallbackQuery, bot: Bot):
    if not await _check_admin(callback):
        return

    parts = callback.data.split(":")
    wave_id = int(parts[1])
    shop_idx = int(parts[2])

    all_shops = await get_all_system_shops()
    if shop_idx < 0 or shop_idx >= len(all_shops):
        await callback.answer("Помилка індексу магазину", show_alert=True)
        return
    shop_name = all_shops[shop_idx]

    await callback.answer("⏳ Підключення пекарні...")

    # Додаємо магазин у БД
    await add_shop_to_active_wave(wave_id, shop_name)

    # Збираємо працівників цього магазину
    new_participants = await _collect_eligible_participants([shop_name], target_type="staff")
    if new_participants:
        await add_participants_batch(wave_id, new_participants)

        # Надсилаємо їм запрошення
        bot_instance = bot or callback.bot
        asyncio.create_task(launch_attestation_broadcast(bot_instance, wave_id))

    await callback.answer(
        f"✅ Магазин «{shop_name}» підключено!\nЗареєстровано {len(new_participants)} працівників.",
        show_alert=True
    )
    # Повертаємось на екран активної хвилі
    callback.data = f"dev_att_active_wave:{wave_id}"
    await dev_att_active_wave_handler(callback)


# -------------------------------------------------------------
# Деталі магазину та зупинка / відновлення
# -------------------------------------------------------------

async def dev_att_shop_details_handler(callback: CallbackQuery):
    if not await _check_admin(callback):
        return

    wave_shop_id = int(callback.data.split(":", 1)[1])
    wave_shop = await get_wave_shop_by_id(wave_shop_id)
    if not wave_shop:
        await callback.answer("Магазин не знайдено", show_alert=True)
        return

    wave_id = wave_shop["wave_id"]
    shop_name = wave_shop["shop_name"]
    is_active = await is_shop_active_in_wave(wave_id, shop_name)

    members = await get_shop_members_details(wave_id, shop_name)
    wave = await get_wave_by_id(wave_id)

    status_badge = "🟢 Активний (тест відкритий)" if is_active else "🔴 Зупинено (тест заблоковано)"
    text = (
        f"🏪 <b>Пекарня: {shop_name}</b>\n"
        f"Хвиля: <i>{wave['title'] if wave else ''}</i>\n"
        f"Статус тестування: <b>{status_badge}</b>\n\n"
        f"👥 <b>Працівники пекарні:</b>\n"
    )

    buttons = []
    for m in members:
        is_m = m.get("is_manager")
        role_pfx = "👔 Керівник" if is_m else "👷"
        status = m.get("attempt_status")

        if status == "passed":
            st_text = f"✅ {m.get('score_pct')}% ({m.get('score')}/{m.get('max_score')} б.)"
        elif status == "failed":
            st_text = f"❌ {m.get('score_pct')}% ({m.get('score')}/{m.get('max_score')} б.)"
        elif status == "timeout":
            st_text = f"⏱ Час вичерпано ({m.get('score_pct')}%)"
        elif status == "in_progress":
            st_text = "⏳ Проходить тест"
        else:
            st_text = "💤 Ще не розпочав"

        text += f"• {role_pfx} <b>{m.get('full_name')}</b> ({m.get('role_name')})\n  Статус: {st_text}\n"

        if status in ("failed", "timeout"):
            can_retake = m.get("can_retake", 0)
            if can_retake == 1:
                text += "  <i>(Дозвіл на перездачу вже надано)</i>\n"
            else:
                buttons.append([InlineKeyboardButton(
                    text=f"🔄 Дозволити перездачу: {m.get('full_name')[:18]}",
                    callback_data=f"dev_att_rtk:{wave_shop_id}:{m['user_id']}"
                )])

    # Кнопка зупинки або відновлення тесту для цього магазину
    if is_active:
        buttons.append([InlineKeyboardButton(text="⏹ Зупинити для цього магазину", callback_data=f"dev_att_stop_sh:{wave_shop_id}")])
    else:
        buttons.append([InlineKeyboardButton(text="▶️ Відновити для цього магазину", callback_data=f"dev_att_resume_sh:{wave_shop_id}")])

    buttons.append([InlineKeyboardButton(text="🔙 До списку магазинів", callback_data=f"dev_att_active_wave:{wave_id}")])

    await _safe_edit_or_answer(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


async def dev_att_stop_shop_handler(callback: CallbackQuery):
    if not await _check_admin(callback):
        return

    wave_shop_id = int(callback.data.split(":")[1])
    wave_shop = await get_wave_shop_by_id(wave_shop_id)
    if not wave_shop:
        await callback.answer("Магазин не знайдено", show_alert=True)
        return

    await close_shop_in_active_wave(wave_shop["wave_id"], wave_shop["shop_name"])
    await callback.answer("⏹ Атестацію для цього магазину зупинено.", show_alert=True)
    await dev_att_shop_details_handler(callback)


async def dev_att_resume_shop_handler(callback: CallbackQuery):
    if not await _check_admin(callback):
        return

    wave_shop_id = int(callback.data.split(":")[1])
    wave_shop = await get_wave_shop_by_id(wave_shop_id)
    if not wave_shop:
        await callback.answer("Магазин не знайдено", show_alert=True)
        return

    await add_shop_to_active_wave(wave_shop["wave_id"], wave_shop["shop_name"])
    await callback.answer("▶️ Атестацію для цього магазину відновлено.", show_alert=True)
    await dev_att_shop_details_handler(callback)


async def dev_att_grant_retake_handler(callback: CallbackQuery, bot: Bot):
    if not await _check_admin(callback):
        return

    _, wave_shop_id_str, user_id_str = callback.data.split(":", 2)
    wave_shop_id = int(wave_shop_id_str)
    user_id = int(user_id_str)

    wave_shop = await get_wave_shop_by_id(wave_shop_id)
    if not wave_shop:
        await callback.answer("Магазин не знайдено", show_alert=True)
        return

    wave_id = wave_shop["wave_id"]

    success = await allow_user_retake(wave_id, user_id, callback.from_user.id)
    if success:
        await callback.answer("✅ Дозвіл на перездачу надано!", show_alert=True)
        try:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [get_attestation_action_button("🚀 Пройти атестацію повторно", user_id=user_id)]
            ])
            await bot.send_message(
                chat_id=user_id,
                text=(
                    "🔄 <b>Вам надано дозвіл на повторне складання атестації!</b>\n\n"
                    "Керівництво погодило додаткову спробу. Ви можете розпочати проходження тесту заново. Успіхів! 🥐"
                ),
                parse_mode="HTML",
                reply_markup=kb
            )
        except Exception as e:
            logger.warning(f"Не вдалося сповістити користувача {user_id} про перездачу: {e}")

        callback.data = f"dev_att_sh_dt:{wave_shop_id}"
        await dev_att_shop_details_handler(callback)
    else:
        await callback.answer("⚠️ Не вдалося надати дозвіл на перездачу.", show_alert=True)


async def dev_att_export_xlsx_handler(callback: CallbackQuery):
    if not await _check_admin(callback):
        return

    wave_id = int(callback.data.split(":")[1])
    await callback.answer("⏳ Генерація підсумкового звіту Excel...")

    try:
        excel_io = await generate_attestation_results_xlsx(wave_id)
        wave = await get_wave_by_id(wave_id)
        w_title = wave.get("title", f"wave_{wave_id}").replace(" ", "_")

        file = BufferedInputFile(
            file=excel_io.read(),
            filename=f"attestation_results_{w_title}.xlsx"
        )
        caption = f"📊 <b>Підсумковий звіт атестації: {wave.get('title')}</b>\nВкладки: Зведений рейтинг + деталізація за кожним магазином."
        await callback.message.answer_document(document=file, caption=caption, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Помилка експорту атестації в Excel: {e}")
        await callback.message.answer(f"❌ Помилка генерації звіту: {str(e)}")


async def dev_att_close_wave_handler(callback: CallbackQuery):
    if not await _check_admin(callback):
        return

    wave_id = int(callback.data.split(":")[1])
    await close_wave(wave_id)
    await callback.answer("✅ Хвилю атестації успішно завершено!", show_alert=True)
    await dev_attestation_menu_handler(callback, None)


async def dev_att_history_handler(callback: CallbackQuery):
    if not await _check_admin(callback):
        return

    waves = await get_all_waves()
    text = "📁 <b>Історія хвиль корпоративної атестації</b>\n\n"

    if not waves:
        text += "<i>Хвиль атестації ще не створювалось.</i>"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="dev_attestation_menu")]
        ])
        await _safe_edit_or_answer(callback, text, reply_markup=kb)
        await callback.answer()
        return

    buttons = []
    for w in waves:
        status_icon = "🟢" if w.get("status") == "active" else "🏁"
        tgt = "Працівники" if w.get("target_type") == "staff" else "Керівники"
        btn_text = f"{status_icon} {w['title']} ({tgt}, {len(w.get('shops', []))} маг.)"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"dev_att_active_wave:{w['id']}")])

    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="dev_attestation_menu")])
    await _safe_edit_or_answer(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


# =============================================================
# 5. ІНТЕРАКТИВНЕ ТЕСТУВАННЯ У ЧАТІ (SINGLE MESSAGE UI)
# =============================================================

async def att_start_test_handler(callback: CallbackQuery):
    """
    Запуск або продовження тестування для співробітника / керівника.
    Працює як через 'att_start_test', так і через 'attestation_start'.
    """
    user_id = callback.from_user.id
    wave = await get_active_wave()

    if not wave:
        await callback.answer("Наразі немає активної хвилі атестації.", show_alert=True)
        return

    wave_id = wave["id"]

    # Знаходимо запис учасника у цій хвилі
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM attestation_participants WHERE wave_id = ? AND user_id = ?",
            (wave_id, user_id)
        ) as cur:
            participant_row = await cur.fetchone()

    if not participant_row:
        await callback.answer("Ви не зареєстровані у цій хвилі атестації. Зверніться до адміністратора.", show_alert=True)
        return

    participant = dict(participant_row)
    shop_name = participant["shop_name"]
    role_name = participant["role_name"]

    # Якщо хвиля для працівників — перевіряємо чи відкритий магазин
    if wave.get("target_type") == "staff":
        is_active_shop = await is_shop_active_in_wave(wave_id, shop_name)
        if not is_active_shop:
            await callback.answer("⚠️ Атестацію для вашого магазину наразі закрито або зупинено.", show_alert=True)
            return

    # Перевіряємо чи є питання для посади
    q_count = (await get_questions_count_by_role()).get(role_name, 0)
    if q_count == 0:
        await callback.answer(f"⚠️ Для посади «{role_name}» ще не завантажено питань в систему.", show_alert=True)
        return

    # Запускаємо або отримуємо спробу
    try:
        attempt = await start_inline_attempt(
            wave_id=wave_id,
            user_id=user_id,
            role_name=role_name,
            shop_name=shop_name,
            duration_minutes=wave["duration_minutes"]
        )
    except Exception as e:
        logger.error(f"Помилка старту спроби для {user_id}: {e}")
        await callback.answer(f"Помилка ініціалізації тесту: {e}", show_alert=True)
        return

    attempt_id = attempt["id"]

    # Якщо спроба вже завершена і перездача не надана
    if attempt.get("status") in ("passed", "failed", "timeout") and attempt.get("can_retake") != 1:
        await callback.answer("Ви вже пройшли атестацію.", show_alert=True)
        await _render_inline_finish_card(callback, attempt)
        return

    # Відображаємо поточне питання
    await _render_inline_question(callback, attempt_id)


async def att_ans_handler(callback: CallbackQuery):
    """
    Обробник вибору варіанта відповіді.
    Формат callback_data: att_ans:{attempt_id}:{question_id}:{orig_num}
    """
    parts = callback.data.split(":")
    try:
        attempt_id = int(parts[1])
        question_id = int(parts[2])
        orig_num = int(parts[3])
    except (IndexError, ValueError):
        await callback.answer("Помилка відповіді.", show_alert=True)
        return

    try:
        attempt_dict, is_finished = await save_inline_answer(attempt_id, question_id, orig_num)
    except Exception as e:
        logger.error(f"Помилка збереження відповіді: {e}")
        await callback.answer("Помилка збереження відповіді.", show_alert=True)
        return

    await _render_inline_question(callback, attempt_id)


async def att_nav_handler(callback: CallbackQuery):
    """
    Обробник переходу [ ⬅️ Назад ] або [ Далі ➡️ ].
    Формат callback_data: att_nav:{attempt_id}:{delta}
    """
    parts = callback.data.split(":")
    try:
        attempt_id = int(parts[1])
        delta = int(parts[2])
    except (IndexError, ValueError):
        await callback.answer("Помилка навігації.", show_alert=True)
        return

    try:
        await navigate_inline_question(attempt_id, delta)
    except Exception as e:
        logger.error(f"Помилка навігації: {e}")
        await callback.answer("Помилка навігації.", show_alert=True)
        return

    await _render_inline_question(callback, attempt_id)


async def _render_inline_question(callback: CallbackQuery, attempt_id: int):
    """
    Відображає поточне питання у єдиному повідомленні з тост-таймером та кнопками відповідей.
    """
    card_data = await get_inline_attempt_card_data(attempt_id)
    if not card_data:
        await callback.answer("Тест не знайдено або завершено.", show_alert=True)
        return

    if card_data.get("is_finished"):
        if card_data.get("timeout"):
            await callback.answer("⏱ Час на тестування вичерпано!", show_alert=True)
        else:
            await callback.answer("🏁 Тест завершено!", show_alert=False)
        await _render_inline_finish_card(callback, card_data["attempt"])
        return

    # Сервісний Toast-таймер зверху екрана
    rem_secs = card_data["remaining_seconds"]
    mins = rem_secs // 60
    secs = rem_secs % 60
    await callback.answer(f"⏱ Залишилось: {mins:02d} хв {secs:02d} с", show_alert=False)

    # Форматуємо час дедлайну
    exp_hm = ""
    if card_data.get("expires_at"):
        try:
            exp_dt = datetime.strptime(card_data["expires_at"], "%Y-%m-%d %H:%M:%S")
            exp_hm = exp_dt.strftime("%H:%M")
        except Exception:
            exp_hm = ""

    header_time = f"⏱ <b>Час спливає о {exp_hm}</b> ({mins} хв {secs} с)\n" if exp_hm else f"⏱ <b>Залишилось:</b> {mins} хв {secs} с\n"

    text = (
        f"{header_time}"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"❓ <b>Питання {card_data['current_q_num']} з {card_data['total_questions']}:</b>\n\n"
        f"{card_data['question_text']}"
    )

    buttons = []
    # Варіанти відповідей: широкий рядок на кожен варіант
    for opt in card_data["options"]:
        radio_icon = "🔘 " if opt["is_selected"] else "⚪️ "
        opt_text = f"{radio_icon}{opt['text']}"
        cb_data = f"att_ans:{attempt_id}:{card_data['question_id']}:{opt['orig_num']}"
        buttons.append([InlineKeyboardButton(text=opt_text[:50], callback_data=cb_data)])

    # Навігаційний рядок (Назад / Далі)
    nav_row = []
    if card_data["has_previous"]:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"att_nav:{attempt_id}:-1"))
    if card_data["has_next"]:
        nav_row.append(InlineKeyboardButton(text="Далі ➡️", callback_data=f"att_nav:{attempt_id}:1"))
    if nav_row:
        buttons.append(nav_row)

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        # Ігноруємо помилку, якщо вміст не змінився
        logger.debug(f"Message edit ignored: {e}")


async def _render_inline_finish_card(callback: CallbackQuery, attempt: Dict[str, Any]):
    """
    Відображає фінальну картку результатів тестування у тому самому повідомленні.
    """
    user_id = attempt["user_id"]
    wave_id = attempt["wave_id"]
    score = attempt.get("score", 0)
    max_score = attempt.get("max_score", 0)
    score_pct = attempt.get("score_pct", 0.0)
    status = attempt.get("status", "failed")
    duration_secs = attempt.get("duration_seconds", 0)
    mins = duration_secs // 60
    secs = duration_secs % 60

    # Отримуємо ПІБ та прохідний поріг
    wave = await get_wave_by_id(wave_id)
    pass_pct = wave.get("passing_score_pct", 80) if wave else 80

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT full_name FROM attestation_participants WHERE wave_id = ? AND user_id = ?", (wave_id, user_id)) as cur:
            p_row = await cur.fetchone()
            full_name = p_row["full_name"] if p_row else "Колега"

    if status == "passed":
        text = (
            "🎉 <b>Вітаємо! Атестацію успішно складено!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Співробітник:</b> {full_name}\n"
            f"🏪 <b>Пекарня:</b> {attempt.get('shop_name')}\n"
            f"👔 <b>Посада:</b> {attempt.get('role_name')}\n\n"
            f"📊 <b>Ваш результат:</b> {score} з {max_score} б. (<b>{score_pct}%</b>)\n"
            f"🎯 <b>Прохідний поріг:</b> {pass_pct}%\n"
            f"⏱ <b>Витрачено часу:</b> {mins} хв {secs} с\n\n"
            "<i>Твій результат успішно зараховано до рейтингу пекарні! Дякуємо за професіоналізм! 🥐</i>"
        )
    elif status == "timeout":
        text = (
            "⏱ <b>Час на проходження атестації вичерпано!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Співробітник:</b> {full_name}\n"
            f"🏪 <b>Пекарня:</b> {attempt.get('shop_name')}\n"
            f"👔 <b>Посада:</b> {attempt.get('role_name')}\n\n"
            f"📊 <b>Зарахований результат:</b> {score} з {max_score} б. (<b>{score_pct}%</b>)\n"
            f"🎯 <b>Прохідний поріг:</b> {pass_pct}%\n\n"
            "<i>Тестування зупинено за таймером. Зверніться до свого керівника щодо призначення повторної спроби.</i>"
        )
    else:
        text = (
            "⏳ <b>Атестацію не складено</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Співробітник:</b> {full_name}\n"
            f"🏪 <b>Пекарня:</b> {attempt.get('shop_name')}\n"
            f"👔 <b>Посада:</b> {attempt.get('role_name')}\n\n"
            f"📊 <b>Ваш результат:</b> {score} з {max_score} б. (<b>{score_pct}%</b>)\n"
            f"🎯 <b>Прохідний поріг:</b> {pass_pct}%\n"
            f"⏱ <b>Витрачено часу:</b> {mins} хв {secs} с\n\n"
            "<i>На жаль, набраних балів недостатньо для прохідного порогу. Зверніться до свого керівника щодо призначення повторної спроби.</i>"
        )

    # Якщо користувач адміністратор — даємо кнопку повернення в меню
    is_admin = await is_developer_user(user_id)
    buttons = []
    if is_admin:
        buttons.append([InlineKeyboardButton(text="🎓 В меню атестації", callback_data="dev_attestation_menu")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        logger.debug(f"Finish card edit: {e}")


# =============================================================
# 6. РЕЄСТРАЦІЯ ХЕНДЛЕРІВ
# =============================================================

def register_attestation_handlers(dp: Dispatcher):
    """Реєструє всі обробники меню атестації та інлайн-тестування."""
    # Головне меню та банк питань
    dp.callback_query.register(dev_attestation_menu_handler, lambda c: c.data == "dev_attestation_menu")
    dp.callback_query.register(dev_att_questions_menu_handler, lambda c: c.data == "dev_att_questions_menu")
    dp.callback_query.register(dev_att_download_template_handler, lambda c: c.data == "dev_att_download_template")
    dp.callback_query.register(dev_att_upload_excel_handler, lambda c: c.data == "dev_att_upload_excel")
    dp.message.register(att_process_excel_document, AttestationStates.waiting_excel_file)

    # Майстер створення хвилі: вибір цілі та назва
    dp.callback_query.register(dev_att_create_wave_handler, lambda c: c.data == "dev_att_create_wave")
    dp.callback_query.register(dev_att_create_wave_confirmed_handler, lambda c: c.data == "dev_att_create_wave_confirmed")
    dp.callback_query.register(dev_att_target_type_handler, lambda c: c.data and c.data.startswith("dev_att_tgt:"))
    dp.message.register(att_process_wave_title, AttestationStates.create_wave_title)

    # Майстер створення хвилі: вибір кількості питань
    dp.callback_query.register(dev_att_qcnt_callback_handler, lambda c: c.data and c.data.startswith("dev_att_qcnt:"))
    dp.callback_query.register(dev_att_change_qcnt_handler, lambda c: c.data == "dev_att_change_qcnt")
    dp.message.register(att_process_wave_q_count_msg, AttestationStates.create_wave_q_count)

    # Вибір магазинів (staff)
    dp.callback_query.register(dev_att_toggle_shop_handler, lambda c: c.data and c.data.startswith("dev_att_tgl_sh:"))
    dp.callback_query.register(dev_att_select_all_shops_handler, lambda c: c.data == "dev_att_sh_all")
    dp.callback_query.register(dev_att_clear_shops_handler, lambda c: c.data == "dev_att_sh_clear")
    dp.callback_query.register(dev_att_shops_page_handler, lambda c: c.data and c.data.startswith("dev_att_sh_p:"))
    dp.callback_query.register(dev_att_shops_done_handler, lambda c: c.data == "dev_att_sh_done")

    # Вибір керівників (managers)
    dp.callback_query.register(dev_att_toggle_manager_handler, lambda c: c.data and c.data.startswith("dev_att_tgl_mgr:"))
    dp.callback_query.register(dev_att_select_all_managers_handler, lambda c: c.data == "dev_att_mgr_all")
    dp.callback_query.register(dev_att_clear_managers_handler, lambda c: c.data == "dev_att_mgr_clear")
    dp.callback_query.register(dev_att_managers_page_handler, lambda c: c.data and c.data.startswith("dev_att_mgr_p:"))
    dp.callback_query.register(dev_att_managers_done_handler, lambda c: c.data == "dev_att_mgr_done")

    # Параметри тесту
    dp.callback_query.register(dev_att_duration_handler, lambda c: c.data and c.data.startswith("dev_att_dur:"))
    dp.callback_query.register(dev_att_passing_handler, lambda c: c.data and c.data.startswith("dev_att_pass:"))
    dp.callback_query.register(dev_att_confirm_launch_handler, lambda c: c.data == "dev_att_confirm_launch")

    # Моніторинг та звіти
    dp.callback_query.register(dev_att_active_wave_handler, lambda c: c.data and c.data.startswith("dev_att_active_wave"))
    dp.callback_query.register(dev_att_add_shop_menu_handler, lambda c: c.data and (c.data.startswith("dev_att_add_sh_menu:") or c.data.startswith("dev_att_add_sh_p:")))
    dp.callback_query.register(dev_att_add_shop_confirm_handler, lambda c: c.data and (c.data.startswith("dev_att_add_sh_cf:") or c.data.startswith("dev_att_add_sh_confirm:")))
    dp.callback_query.register(lambda c: c.answer(), lambda c: c.data == "noop")
    dp.callback_query.register(dev_att_shop_details_handler, lambda c: c.data and c.data.startswith("dev_att_sh_dt:"))
    dp.callback_query.register(dev_att_stop_shop_handler, lambda c: c.data and c.data.startswith("dev_att_stop_sh:"))
    dp.callback_query.register(dev_att_resume_shop_handler, lambda c: c.data and c.data.startswith("dev_att_resume_sh:"))
    dp.callback_query.register(dev_att_grant_retake_handler, lambda c: c.data and c.data.startswith("dev_att_rtk:"))
    dp.callback_query.register(dev_att_export_xlsx_handler, lambda c: c.data and c.data.startswith("dev_att_export_xlsx:"))
    dp.callback_query.register(dev_att_close_wave_handler, lambda c: c.data and c.data.startswith("dev_att_close:"))
    dp.callback_query.register(dev_att_history_handler, lambda c: c.data == "dev_att_history")

    # Інтерактивне тестування для співробітників
    dp.callback_query.register(att_start_test_handler, lambda c: c.data in ("att_start_test", "attestation_start"))
    dp.callback_query.register(att_ans_handler, lambda c: c.data and c.data.startswith("att_ans:"))
    dp.callback_query.register(att_nav_handler, lambda c: c.data and c.data.startswith("att_nav:"))
