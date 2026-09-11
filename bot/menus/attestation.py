from __future__ import annotations
import asyncio
import io
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Set, Optional

import pytz
from aiogram import Dispatcher, Bot
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BufferedInputFile,
    WebAppInfo
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.config import TIMEZONE, WEB_APP_URL
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
    add_participants_batch
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
from bot.services.attestation_worker import launch_attestation_broadcast

logger = logging.getLogger(__name__)


class AttestationStates(StatesGroup):
    waiting_excel_file = State()
    create_wave_title = State()
    create_wave_shops = State()
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

    # Також зчитуємо магазини з користувачів
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


# =============================================================
# 1. ГОЛОВНЕ МЕНЮ АТЕСТАЦІЇ
# =============================================================

async def dev_attestation_menu_handler(callback: CallbackQuery, state: FSMContext):
    if not await _check_admin(callback):
        return
    await state.clear()

    active_wave = await get_active_wave()

    text = "🎓 <b>Корпоративна піврічна атестація BULKA</b>\n\n"
    if active_wave:
        text += (
            f"🟢 <b>Активна хвиля:</b> <b>{active_wave['title']}</b>\n"
            f"🏪 <b>Магазинів у хвилі:</b> {len(active_wave.get('shops', []))}\n"
            f"⏱ <b>Таймер:</b> {active_wave['duration_minutes']} хв | <b>Поріг:</b> {active_wave['passing_score_pct']}%\n"
            f"📅 <b>Дедлайн:</b> {active_wave['deadline_date']}\n\n"
            f"<i>Тестування триває. Ви можете переглядати результати в реальному часі.</i>"
        )
    else:
        text += (
            "⚪️ <b>Статус:</b> Наразі немає активної хвилі атестації.\n\n"
            "Ви можете оновити банк питань через Excel або створити нову хвилю для обраних магазинів."
        )

    buttons = []
    if active_wave:
        buttons.append([InlineKeyboardButton(text="📊 Деталі активної хвилі", callback_data=f"dev_att_active_wave:{active_wave['id']}")])
    buttons.append([InlineKeyboardButton(text="➕ Створити хвилю атестації", callback_data="dev_att_create_wave")])
    buttons.append([InlineKeyboardButton(text="📚 Питання за посадами (Excel)", callback_data="dev_att_questions_menu")])
    buttons.append([InlineKeyboardButton(text="📁 Історія хвиль", callback_data="dev_att_history")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад у розсилки", callback_data="dev_broadcasts_menu")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


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
        icon = "✅" if cnt >= 15 else ("⚠️" if cnt > 0 else "❌")
        text += f"• {icon} <b>{role}:</b> {cnt} питань\n"

    text += f"\n<b>Всього в базі:</b> {total_q} питань.\n\n"
    text += "<i>Завантажте шаблон Excel, заповніть аркуші за посадами та завантажте назад у бот.</i>"

    buttons = [
        [InlineKeyboardButton(text="📥 Завантажити шаблон Excel", callback_data="dev_att_download_template")],
        [InlineKeyboardButton(text="📤 Оновити питання (Excel)", callback_data="dev_att_upload_excel")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="dev_attestation_menu")]
    ]
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
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
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
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
            "Запуск нової хвилі автоматично закриє поточну активну хвилю.\nБажаєте продовжити?"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Продовжити", callback_data="dev_att_create_wave_confirmed")],
            [InlineKeyboardButton(text="❌ Скасувати", callback_data="dev_attestation_menu")]
        ])
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await callback.answer()
        return

    await _start_create_wave_flow(callback, state)


async def dev_att_create_wave_confirmed_handler(callback: CallbackQuery, state: FSMContext):
    await _start_create_wave_flow(callback, state)


async def _start_create_wave_flow(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AttestationStates.create_wave_title)
    text = (
        "➕ <b>Створення нової хвилі атестації</b> [Крок 1/5]\n\n"
        "Введіть назву хвилі атестації:\n"
        "<i>(наприклад: <b>Осіння атестація 2026</b> або <b>Атестація: Вересень</b>)</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="dev_attestation_menu")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


async def att_process_wave_title(message: Message, state: FSMContext):
    if not await _check_admin(message):
        return

    title = message.text.strip()
    if len(title) < 3:
        await message.answer("⚠️ Назва занадто коротка. Введіть назву хвилі:")
        return

    await state.update_data(wave_title=title, selected_shops=[])
    await state.set_state(AttestationStates.create_wave_shops)
    await _render_shops_picker(message, state, page=1)


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
        f"🏪 <b>Вибір магазинів для атестації</b> [Крок 2/5]\n"
        f"Хвиля: <b>{data.get('wave_title')}</b>\n\n"
        f"Обрано магазинів: <b>{len(selected_shops)}</b> з {len(all_shops)}\n\n"
        f"<i>Натискайте на кнопки магазинів, щоб додати або зняти позначку:</i>"
    )

    buttons = []
    for idx_in_page, s in enumerate(page_shops):
        global_idx = start_idx + idx_in_page
        is_sel = s in selected_shops
        mark = "✅ " if is_sel else "⬜️ "
        # Обрізаємо для компактності назви на кнопці
        btn_text = f"{mark}{s[:24]}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"dev_att_tgl_sh:{global_idx}")])

    # Пагінація
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"dev_att_sh_p:{page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"dev_att_sh_p:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    # Кнопки масового вибору
    buttons.append([
        InlineKeyboardButton(text="☑️ Обрати всі", callback_data="dev_att_sh_all"),
        InlineKeyboardButton(text="◻️ Очистити", callback_data="dev_att_sh_clear")
    ])
    buttons.append([
        InlineKeyboardButton(text=f"Далі ➡️ ({len(selected_shops)} обр.)", callback_data="dev_att_sh_done")
    ])
    buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="dev_attestation_menu")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    if isinstance(message_or_cb, CallbackQuery):
        await message_or_cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await message_or_cb.answer()
    else:
        await message_or_cb.answer(text, parse_mode="HTML", reply_markup=kb)


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

    await state.set_state(AttestationStates.create_wave_duration)
    text = (
        "⏱ <b>Тривалість тестування</b> [Крок 3/5]\n\n"
        "Скільки хвилин надається працівнику на проходження атестації з моменту натискання кнопки старту?\n"
        "<i>(Таймер рахується на сервері)</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="15 хв", callback_data="dev_att_dur:15"),
            InlineKeyboardButton(text="20 хв (реком.)", callback_data="dev_att_dur:20")
        ],
        [
            InlineKeyboardButton(text="30 хв", callback_data="dev_att_dur:30"),
            InlineKeyboardButton(text="45 хв", callback_data="dev_att_dur:45")
        ],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="dev_attestation_menu")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


async def dev_att_duration_handler(callback: CallbackQuery, state: FSMContext):
    dur = int(callback.data.split(":")[1])
    await state.update_data(wave_duration=dur)

    await state.set_state(AttestationStates.create_wave_passing)
    text = (
        "🎯 <b>Прохідний бал атестації</b> [Крок 4/5]\n\n"
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
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


async def dev_att_passing_handler(callback: CallbackQuery, state: FSMContext):
    passing = int(callback.data.split(":")[1])
    await state.update_data(wave_passing=passing)

    await state.set_state(AttestationStates.create_wave_deadline)
    text = (
        "📅 <b>Дедлайн проходження атестації</b> [Крок 5/5]\n\n"
        "Скільки днів триватиме хвиля атестації для обраних магазинів?"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="3 дні", callback_data="dev_att_dead:3"),
            InlineKeyboardButton(text="5 днів", callback_data="dev_att_dead:5")
        ],
        [
            InlineKeyboardButton(text="7 днів (тиждень)", callback_data="dev_att_dead:7"),
            InlineKeyboardButton(text="10 днів (реком.)", callback_data="dev_att_dead:10")
        ],
        [InlineKeyboardButton(text="14 днів (2 тижні)", callback_data="dev_att_dead:14")],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="dev_attestation_menu")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


async def dev_att_deadline_handler(callback: CallbackQuery, state: FSMContext):
    days = int(callback.data.split(":")[1])
    tz = pytz.timezone(TIMEZONE)
    deadline_dt = datetime.now(tz) + timedelta(days=days)
    deadline_str = deadline_dt.strftime("%Y-%m-%d 23:59:59")
    await state.update_data(wave_deadline=deadline_str, wave_deadline_days=days)

    data = await state.get_data()
    title = data["wave_title"]
    shops = data["selected_shops"]
    dur = data["wave_duration"]
    pass_pct = data["wave_passing"]

    # Розраховуємо кількість людей
    participants_to_register = await _collect_eligible_participants(shops)

    text = (
        "📋 <b>Підтвердження запуску атестації</b>\n\n"
        f"🏷 <b>Назва:</b> {title}\n"
        f"🏪 <b>Обрано магазинів:</b> {len(shops)}\n"
        f"👥 <b>Потенційних учасників:</b> {len(participants_to_register)} ос. (Працівники та Керівники)\n"
        f"⏱ <b>Час на тест:</b> {dur} хв\n"
        f"🎯 <b>Прохідний поріг:</b> {pass_pct}%\n"
        f"📅 <b>Дедлайн здачі:</b> до {deadline_dt.strftime('%d.%m.%Y о 23:59')} ({days} днів)\n\n"
        "<i>Після натискання «Запустити» хвиля активується, а всім учасникам буде надіслано персональне запрошення у Mini App.</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Запустити атестацію", callback_data="dev_att_confirm_launch")],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="dev_attestation_menu")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


async def _collect_eligible_participants(shops: List[str]) -> List[Dict[str, Any]]:
    """Знаходить усіх діючих працівників та керівників обраних магазинів."""
    participants = []
    seen_uids = set()

    # 1. Працівники (тільки статус 'Працівник', стажери виключаються)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        for shop in shops:
            async with db.execute(
                "SELECT user_id, full_name, role, shop FROM users WHERE shop = ? AND status = 'Працівник'",
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
                            "role_name": r["role"],
                            "shop_name": r["shop"],
                            "is_manager": 0
                        })

    # 2. Керівники
    managers = await get_all_managers()
    for m in managers:
        m_uid = m.get("user_id")
        if not m_uid or m_uid in seen_uids:
            continue
        # Перевіряємо прив'язку магазинів
        m_shops = m.get("shops", [])
        if isinstance(m_shops, str):
            try:
                m_shops = json.loads(m_shops)
            except Exception:
                m_shops = [m_shops]

        for s in m_shops:
            if s in shops:
                seen_uids.add(m_uid)
                participants.append({
                    "user_id": m_uid,
                    "full_name": m.get("name") or "Керівник",
                    "role_name": "Керівник",
                    "shop_name": s,
                    "is_manager": 1
                })
                break

    return participants


async def dev_att_confirm_launch_handler(callback: CallbackQuery, state: FSMContext, bot: Bot):
    if not await _check_admin(callback):
        return

    data = await state.get_data()
    title = data.get("wave_title")
    shops = data.get("selected_shops", [])
    dur = data.get("wave_duration", 20)
    pass_pct = data.get("wave_passing", 80)
    deadline = data.get("wave_deadline")

    if not title or not shops:
        await callback.answer("⚠️ Дані сесії втрачено. Почніть знову.", show_alert=True)
        await state.clear()
        return

    await callback.message.edit_text("⏳ Створення та активація хвилі атестації...", parse_mode="HTML")

    # Створюємо хвилю
    wave_id = await create_wave(
        title=title,
        created_by=callback.from_user.id,
        duration_minutes=dur,
        passing_score_pct=pass_pct,
        deadline_date=deadline,
        shops=shops
    )
    await activate_wave(wave_id)

    # Реєструємо учасників
    participants = await _collect_eligible_participants(shops)
    await add_participants_batch(wave_id, participants)

    # Запускаємо похвильову розсилку у фоні
    bot_instance = bot or callback.bot
    asyncio.create_task(launch_attestation_broadcast(bot_instance, wave_id))

    await state.clear()
    await callback.message.answer(
        f"🎉 <b>Хвилю атестації «{title}» успішно запущено!</b>\n\n"
        f"🏪 Магазинів: <b>{len(shops)}</b>\n"
        f"👥 Зареєстровано учасників: <b>{len(participants)}</b>\n\n"
        f"Похвильова розсилка сповіщень у Telegram розпочалася.",
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
    wave_id = int(parts[1]) if len(parts) > 1 else None

    if wave_id:
        wave = await get_wave_by_id(wave_id)
    else:
        wave = await get_active_wave()

    if not wave:
        await callback.answer("Хвилю не знайдено або вона завершена.", show_alert=True)
        return

    wave_id = wave["id"]
    stats = await get_wave_statistics(wave_id)
    shop_stats = await get_wave_shop_stats(wave_id)

    pct_done = round((stats["completed_count"] / stats["total_participants"] * 100), 1) if stats["total_participants"] > 0 else 0.0

    text = (
        f"📊 <b>Результати атестації: {wave['title']}</b>\n\n"
        f"📅 <b>Дедлайн:</b> {wave['deadline_date']}\n"
        f"🎯 <b>Прохідний бал:</b> {wave['passing_score_pct']}%\n\n"
        f"📈 <b>Прогрес мережі:</b>\n"
        f"• Всього учасників: <b>{stats['total_participants']}</b> ос.\n"
        f"• Завершили тест: <b>{stats['completed_count']}</b> ({pct_done}%)\n"
        f"• ✅ Склали успішно: <b>{stats['passed_count']}</b>\n"
        f"• ❌ Не склали: <b>{stats['failed_count']}</b>\n"
        f"• ⭐️ Середній бал: <b>{stats['avg_score']}%</b>\n\n"
        f"🏪 <b>Магазини хвилі (натисніть для деталей):</b>"
    )

    buttons = []
    # Сортуємо магазини
    for s in shop_stats:
        sh_id = s.get("shop_id", 0)
        sh_name = s["shop_name"]
        icon = "✅" if s["completed"] == s["total_participants"] and s["total_participants"] > 0 else "⏳"
        label = f"{icon} {sh_name[:20]} ({s['completed']}/{s['total_participants']} — {s['avg_score_pct']}%)"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"dev_att_sh_dt:{sh_id}")])

    buttons.append([InlineKeyboardButton(text="📊 Вивантажити звіт XLSX", callback_data=f"dev_att_export_xlsx:{wave_id}")])
    if wave.get("status") == "active":
        buttons.append([InlineKeyboardButton(text="🛑 Завершити хвилю", callback_data=f"dev_att_close:{wave_id}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="dev_attestation_menu")])

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


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

    members = await get_shop_members_details(wave_id, shop_name)
    wave = await get_wave_by_id(wave_id)

    text = f"🏪 <b>Магазин: {shop_name}</b>\n"
    text += f"Хвиля: <i>{wave['title'] if wave else ''}</i>\n\n"

    buttons = []
    for m in members:
        is_m = m.get("is_manager")
        role_pfx = "👔 Керівник" if is_m else "👷"
        status = m.get("attempt_status")

        if status == "passed":
            st_text = f"✅ {m.get('score_pct')}% ({m.get('score')}/{m.get('max_score')} б.)"
        elif status == "failed":
            st_text = f"❌ {m.get('score_pct')}% ({m.get('score')}/{m.get('max_score')} б.)"
        elif status == "in_progress":
            st_text = "⏳ Проходить тест"
        else:
            st_text = "💤 Ще не розпочав"

        text += f"• {role_pfx} <b>{m.get('full_name')}</b> ({m.get('role_name')})\n  Статус: {st_text}\n"

        # Кнопка перездачі, якщо тест завалено
        if status == "failed":
            can_retake = m.get("can_retake", 0)
            if can_retake == 1:
                text += "  <i>(Дозвіл на перездачу вже надано)</i>\n"
            else:
                buttons.append([InlineKeyboardButton(
                    text=f"🔄 Дозволити перездачу: {m.get('full_name')[:18]}",
                    callback_data=f"dev_att_rtk:{wave_shop_id}:{m['user_id']}"
                )])

    buttons.append([InlineKeyboardButton(text="🔙 До списку магазинів", callback_data=f"dev_att_active_wave:{wave_id}")])

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


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
        # Надсилаємо повідомлення співробітнику в бот
        try:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚀 Пройти атестацію повторно", web_app=WebAppInfo(url=WEB_APP_URL))]
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

        # Оновлюємо екран магазину
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
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await callback.answer()
        return

    buttons = []
    for w in waves:
        status_icon = "🟢" if w.get("status") == "active" else "🏁"
        btn_text = f"{status_icon} {w['title']} ({len(w.get('shops', []))} маг.)"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"dev_att_active_wave:{w['id']}")])

    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="dev_attestation_menu")])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


# =============================================================
# РЕЄСТРАЦІЯ ХЕНДЛЕРІВ
# =============================================================

def register_attestation_handlers(dp: Dispatcher):
    """Реєструє всі обробники меню атестації."""
    # Головне меню та банк питань
    dp.callback_query.register(dev_attestation_menu_handler, lambda c: c.data == "dev_attestation_menu")
    dp.callback_query.register(dev_att_questions_menu_handler, lambda c: c.data == "dev_att_questions_menu")
    dp.callback_query.register(dev_att_download_template_handler, lambda c: c.data == "dev_att_download_template")
    dp.callback_query.register(dev_att_upload_excel_handler, lambda c: c.data == "dev_att_upload_excel")
    dp.message.register(att_process_excel_document, AttestationStates.waiting_excel_file)

    # Майстер створення хвилі
    dp.callback_query.register(dev_att_create_wave_handler, lambda c: c.data == "dev_att_create_wave")
    dp.callback_query.register(dev_att_create_wave_confirmed_handler, lambda c: c.data == "dev_att_create_wave_confirmed")
    dp.message.register(att_process_wave_title, AttestationStates.create_wave_title)

    # Вибір магазинів
    dp.callback_query.register(dev_att_toggle_shop_handler, lambda c: c.data and c.data.startswith("dev_att_tgl_sh:"))
    dp.callback_query.register(dev_att_select_all_shops_handler, lambda c: c.data == "dev_att_sh_all")
    dp.callback_query.register(dev_att_clear_shops_handler, lambda c: c.data == "dev_att_sh_clear")
    dp.callback_query.register(dev_att_shops_page_handler, lambda c: c.data and c.data.startswith("dev_att_sh_p:"))
    dp.callback_query.register(dev_att_shops_done_handler, lambda c: c.data == "dev_att_sh_done")

    # Параметри тесту
    dp.callback_query.register(dev_att_duration_handler, lambda c: c.data and c.data.startswith("dev_att_dur:"))
    dp.callback_query.register(dev_att_passing_handler, lambda c: c.data and c.data.startswith("dev_att_pass:"))
    dp.callback_query.register(dev_att_deadline_handler, lambda c: c.data and c.data.startswith("dev_att_dead:"))
    dp.callback_query.register(dev_att_confirm_launch_handler, lambda c: c.data == "dev_att_confirm_launch")

    # Моніторинг та звіти
    dp.callback_query.register(dev_att_active_wave_handler, lambda c: c.data and c.data.startswith("dev_att_active_wave"))
    dp.callback_query.register(dev_att_shop_details_handler, lambda c: c.data and c.data.startswith("dev_att_sh_dt:"))
    dp.callback_query.register(dev_att_grant_retake_handler, lambda c: c.data and c.data.startswith("dev_att_rtk:"))
    dp.callback_query.register(dev_att_export_xlsx_handler, lambda c: c.data and c.data.startswith("dev_att_export_xlsx:"))
    dp.callback_query.register(dev_att_close_wave_handler, lambda c: c.data and c.data.startswith("dev_att_close:"))
    dp.callback_query.register(dev_att_history_handler, lambda c: c.data == "dev_att_history")
