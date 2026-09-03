import asyncio
import html
from datetime import datetime, timedelta
import pytz

from aiogram import Dispatcher
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.exceptions import TelegramBadRequest

from bot.config import TIMEZONE, DAYS_TOTAL
from bot.state import SearchStates
from database.hr import is_privileged_user
from database.users import (
    get_manager_interns, 
    get_user_details, 
    get_user_by_username,
    get_interns_in_progress_for_manager,
    get_inactive_interns_for_manager,
    register_user,
    set_intern_extra,
    delete_user,
    update_user_role,
    log_training_event,
    get_user_progress,
    get_manager_team_users,
    get_manager_workers,
    get_manager_interns_full,
)
from bot.services.developer_actions import get_user_days_report, _format_last_activity
from bot.constants import AVAILABLE_ROLES, AVAILABLE_CITIES, AVAILABLE_SHOPS
from database.tokens import generate_token

class ManagerStates(StatesGroup):
    waiting_search_intern = State()
    waiting_search_worker = State()
    waiting_add_intern_city = State()
    waiting_add_intern_shop = State()
    waiting_add_intern_role = State()
    waiting_confirm_remove = State()
    waiting_remind_topic_select = State()

async def _ensure_manager(callback: CallbackQuery) -> bool:
    user_id = callback.from_user.id
    from database.managers import is_manager_user
    from database.hr import is_developer_user, is_hr_user
    if not (await is_manager_user(user_id) or await is_hr_user(user_id) or await is_developer_user(user_id)):
        await callback.answer("⛔️ Доступ заборонено.", show_alert=True)
        return False
    return True

PAGE_SIZE = 10

def _manager_main_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="👥 Мої працівники", callback_data="mgr_my_team")],
        [InlineKeyboardButton(text="📚 Навчання", callback_data="mgr_study_root")],
        [InlineKeyboardButton(text="🏠 Головне меню", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def _edit_menu_message(message: Message, text: str, reply_markup: InlineKeyboardMarkup):
    """
    Helper to edit message text or caption depending on whether it has a photo.
    """
    try:
        if message.photo:
            await message.edit_caption(caption=text, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "there is no text in the message to edit" in str(e) or "message to edit not found" in str(e):
            # If editing fails drastically, try to delete and resend
            try:
                await message.delete()
            except Exception:
                pass
            await message.answer(text, reply_markup=reply_markup, parse_mode="HTML")
        elif "message is not modified" in str(e):
            pass # Ignore
        else:
            raise e

async def manager_menu(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_manager(callback):
        return
    
    await state.clear()
    text = "👔 <b>Панель Керівника</b>\n\nОберіть потрібний розділ:"
    kb = _manager_main_keyboard()
    
    await _edit_menu_message(callback.message, text, kb)     
    await callback.answer()

# --- Section 1: Мої працівники ---

async def manager_my_team_menu(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_manager(callback):
        return
    await state.clear()
    text = (
        "👥 <b>Мої працівники</b>\n\n"
        "Керування працівниками та стажерами вашого магазину.\n"
        "Оберіть дію:"
    )
    buttons = [
        [InlineKeyboardButton(text="👥 Усі працівники", callback_data="mgr_all_workers_menu")],
        [InlineKeyboardButton(text="🔎 Пошук", callback_data="mgr_search_worker")],
        [InlineKeyboardButton(text="🔍 Фільтри", callback_data="mgr_filters_menu")],
        [InlineKeyboardButton(text="➕ Додати стажера", callback_data="mgr_add")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="manager_menu")]
    ]
    await _edit_menu_message(callback.message, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

async def manager_all_workers_menu(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    text = (
        "👥 <b>Усі працівники та стажери</b>\n\n"
        "Оберіть формат перегляду команди вашого магазину:"
    )
    buttons = [
        [InlineKeyboardButton(text="📋 Список усіх (текстом)", callback_data="mgr_list_all_text")],
        [InlineKeyboardButton(text="🎓 Стажери (картки)", callback_data="mgr_interns_list:0")],
        [InlineKeyboardButton(text="💼 Працівники (картки)", callback_data="mgr_workers_list:0")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="mgr_my_team")]
    ]
    await _edit_menu_message(callback.message, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

async def manager_list_all_text(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    team = await get_manager_team_users(callback.from_user.id)
    if not team:
        await _edit_menu_message(
            callback.message,
            "📭 У вашому магазині поки що немає закріплених працівників або стажерів.",
            InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="mgr_all_workers_menu")]])
        )
        await callback.answer()
        return

    interns = [u for u in team if not u.get("is_worker") and u.get("role") != "Працівник" and u.get("status") != "Працівник"]
    workers = [u for u in team if u.get("is_worker") or u.get("role") == "Працівник" or u.get("status") == "Працівник"]

    lines = ["📋 <b>Список команди вашого магазину:</b>\n"]
    if interns:
        lines.append(f"🎓 <b>Стажери ({len(interns)}):</b>")
        for idx, u in enumerate(interns, 1):
            name = html.escape(u.get("full_name") or u.get("username") or f"ID {u.get('user_id')}")
            role = html.escape(u.get("role") or "Стажер")
            day = u.get("current_block") or 1
            lines.append(f"{idx}. {name} — <i>{role}</i> (День {day})")
        lines.append("")

    if workers:
        lines.append(f"💼 <b>Працівники ({len(workers)}):</b>")
        for idx, u in enumerate(workers, 1):
            name = html.escape(u.get("full_name") or u.get("username") or f"ID {u.get('user_id')}")
            role = html.escape(u.get("role") or "Працівник")
            lines.append(f"{idx}. {name} — <i>{role}</i>")
        lines.append("")

    lines.append(f"<i>Всього людей у команді: {len(team)}</i>")
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3950] + "\n\n<i>...частину списку скорочено...</i>"

    buttons = [[InlineKeyboardButton(text="⬅️ Назад", callback_data="mgr_all_workers_menu")]]
    await _edit_menu_message(callback.message, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

async def manager_interns_list(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    page = int(callback.data.split(":")[1])
    interns = await get_manager_interns_full(callback.from_user.id)
    if not interns:
        await _edit_menu_message(
            callback.message,
            "📭 Немає стажерів у вашому магазині.",
            InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="mgr_all_workers_menu")]])
        )
        await callback.answer()
        return

    total = len(interns)
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    page = max(0, min(page, total_pages - 1))
    slice_interns = interns[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]

    buttons = []
    for intern in slice_interns:
        name = intern.get("full_name") or intern.get("username") or f"ID {intern.get('user_id')}"
        uid = intern.get("user_id")
        day = intern.get("current_block", 1)
        buttons.append([InlineKeyboardButton(
            text=f"🎓 {name} (День {day})",
            callback_data=f"mgr_view_intern_{uid}"
        )])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Попередня", callback_data=f"mgr_interns_list:{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="Наступна ➡️", callback_data=f"mgr_interns_list:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="mgr_all_workers_menu")])
    text = f"🎓 <b>Стажери магазину</b> (Стор. {page + 1}/{total_pages})\nОберіть для перегляду картки:"
    await _edit_menu_message(callback.message, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

async def manager_workers_list(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    page = int(callback.data.split(":")[1])
    workers = await get_manager_workers(callback.from_user.id)
    if not workers:
        await _edit_menu_message(
            callback.message,
            "📭 Немає постійних працівників у вашому магазині.",
            InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="mgr_all_workers_menu")]])
        )
        await callback.answer()
        return

    total = len(workers)
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    page = max(0, min(page, total_pages - 1))
    slice_workers = workers[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]

    buttons = []
    for worker in slice_workers:
        name = worker.get("full_name") or worker.get("username") or f"ID {worker.get('user_id')}"
        uid = worker.get("user_id")
        role = worker.get("role") or "Працівник"
        buttons.append([InlineKeyboardButton(
            text=f"💼 {name} ({role})",
            callback_data=f"mgr_view_intern_{uid}"
        )])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Попередня", callback_data=f"mgr_workers_list:{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="Наступна ➡️", callback_data=f"mgr_workers_list:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="mgr_all_workers_menu")])
    text = f"💼 <b>Працівники магазину</b> (Стор. {page + 1}/{total_pages})\nОберіть для перегляду картки:"
    await _edit_menu_message(callback.message, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

# --- Isolated Search ---

async def manager_search_worker_start(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_manager(callback):
        return
    await state.set_state(ManagerStates.waiting_search_worker)
    text = (
        "🔎 <b>Пошук працівника або стажера</b>\n\n"
        "Введіть Telegram ID або ім'я/прізвище людини для пошуку серед працівників вашого магазину:"
    )
    buttons = [[InlineKeyboardButton(text="❌ Скасувати", callback_data="mgr_my_team")]]
    await _edit_menu_message(callback.message, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

async def manager_search_worker_process(message: Message, state: FSMContext):
    user_id = message.from_user.id
    from database.managers import is_manager_user
    from database.hr import is_developer_user, is_hr_user
    if not (await is_manager_user(user_id) or await is_hr_user(user_id) or await is_developer_user(user_id)):
        return

    query = (message.text or "").strip().lower()
    await state.clear()

    team = await get_manager_team_users(user_id)
    matched = []
    for u in team:
        uid_str = str(u.get("user_id", ""))
        full_name = (u.get("full_name") or "").lower()
        username = (u.get("username") or "").lower()
        if query == uid_str or query in full_name or query in username:
            matched.append(u)

    if not matched:
        await message.answer(
            f"🔍 За запитом «{message.text}» серед команди вашого магазину нікого не знайдено.\n\n"
            "<i>Зверніть увагу: пошук здійснюється виключно серед працівників та стажерів вашого магазину.</i>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔎 Спробувати знову", callback_data="mgr_search_worker")],
                [InlineKeyboardButton(text="👥 До працівників", callback_data="mgr_my_team")]
            ]),
            parse_mode="HTML"
        )
        return

    buttons = []
    for u in matched[:15]:
        name = u.get("full_name") or u.get("username") or f"ID {u.get('user_id')}"
        uid = u.get("user_id")
        role = u.get("role") or ("Працівник" if u.get("is_worker") else "Стажер")
        prefix = "💼" if (u.get("is_worker") or role == "Працівник") else "🎓"
        buttons.append([InlineKeyboardButton(text=f"{prefix} {name} ({role})", callback_data=f"mgr_view_intern_{uid}")])

    buttons.append([InlineKeyboardButton(text="👥 До працівників", callback_data="mgr_my_team")])
    await message.answer(
        f"🔍 <b>Знайдено ({len(matched)}):</b>\nОберіть для перегляду картки:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )

# --- Filters Menu ---

async def manager_filters_menu(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    text = (
        "🔍 <b>Фільтри працівників</b>\n\n"
        "Оберіть критерій для фільтрації:"
    )
    buttons = [
        [InlineKeyboardButton(text="💼 За посадою", callback_data="mgr_by_role")],
        [InlineKeyboardButton(text="🚀 Активні стажери", callback_data="mgr_active")],
        [InlineKeyboardButton(text="🎉 Завершили навчання", callback_data="mgr_completed")],
        [InlineKeyboardButton(text="⏱️ Активні працівники (взаємодія)", callback_data="mgr_filter_recent_activity")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="mgr_my_team")]
    ]
    await _edit_menu_message(callback.message, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

async def manager_filter_recent_activity(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    team = await get_manager_team_users(callback.from_user.id)
    if not team:
        await _edit_menu_message(
            callback.message,
            "📭 Немає працівників чи стажерів у вашому магазині.",
            InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="mgr_filters_menu")]])
        )
        await callback.answer()
        return

    lines = ["⏱️ <b>Активність команди (остання взаємодія з ботом):</b>\n"]
    for idx, u in enumerate(team, 1):
        name = html.escape(u.get("full_name") or u.get("username") or f"ID {u.get('user_id')}")
        role = html.escape(u.get("role") or ("Працівник" if u.get("is_worker") else "Стажер"))
        last_act = _format_last_activity(u.get("last_activity"))
        prefix = "💼" if (u.get("is_worker") or role == "Працівник") else "🎓"
        lines.append(f"{idx}. {prefix} <b>{name}</b> ({role})\n    🕒 {last_act}")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3950] + "\n\n<i>...частину списку скорочено...</i>"

    buttons = [[InlineKeyboardButton(text="⬅️ Назад", callback_data="mgr_filters_menu")]]
    await _edit_menu_message(callback.message, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

# --- Helper to list interns ---
async def _list_interns_generic(
    callback: CallbackQuery,
    interns: list,
    title: str,
    empty_msg: str,
    *,
    mark_completed: bool = False,
    back_callback: str = "mgr_my_team"
):
    if not interns:
        await _edit_menu_message(
            callback.message,
            f"{empty_msg}",
            InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback)]])
        )
        await callback.answer()
        return

    text = f"{title}\n\n"
    buttons = []
    
    for intern in interns[:50]:
        name = intern.get("full_name") or intern.get("username") or f"ID {intern.get('user_id')}"
        uid = intern.get("user_id")
        role = intern.get("role", "Стажер")
        is_worker = intern.get("is_worker") or role == "Працівник" or intern.get("status") == "Працівник"
        if is_worker:
            suffix = f"Працівник ({role})"
            prefix = "💼"
        elif mark_completed:
            suffix = "Завершено"
            prefix = "🎉"
        else:
            current_block = intern.get("current_block", 1)
            suffix = f"День {current_block}"
            prefix = "🎓"
        buttons.append([InlineKeyboardButton(
            text=f"{prefix} {name} ({suffix})",
            callback_data=f"mgr_view_intern_{uid}"
        )])
    
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback)])
    
    await _edit_menu_message(
        callback.message,
        text + "Оберіть людину для перегляду деталей:", 
        InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()

# --- Handlers for filter buttons ---

async def manager_active_interns(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    interns = await get_interns_in_progress_for_manager(callback.from_user.id)
    await _list_interns_generic(
        callback, 
        interns, 
        "🚀 <b>Активні стажери:</b>", 
        "📭 Немає активних стажерів.",
        back_callback="mgr_filters_menu"
    )

async def manager_completed_interns(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    
    all_interns = await get_manager_interns(callback.from_user.id)
    completed = []
    
    for intern in all_interns:
        progress = await get_user_progress(intern['user_id'])
        completed_count = sum(1 for p in progress if p.get('completed'))
        if completed_count >= DAYS_TOTAL:
            completed.append(intern)
            
    await _list_interns_generic(
        callback,
        completed,
        "🎉 <b>Завершили навчання:</b>",
        "📭 Немає стажерів, що завершили навчання.",
        mark_completed=True,
        back_callback="mgr_filters_menu"
    )

async def manager_inactive_interns(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    interns = await get_inactive_interns_for_manager(callback.from_user.id, days=3)
    await _list_interns_generic(
        callback, 
        interns, 
        "😴 <b>Неактивні ≥3 дн.:</b>", 
        "🎉 Всі стажери активні!",
        back_callback="mgr_filters_menu"
    )

async def manager_all_interns(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    interns = await get_manager_interns(callback.from_user.id)
    await _list_interns_generic(
        callback, 
        interns, 
        "📋 <b>Усі стажери:</b>", 
        "📭 Список стажерів порожній.",
        back_callback="mgr_all_workers_menu"
    )

async def manager_by_city_menu(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    interns = await get_manager_interns(callback.from_user.id)
    cities_in_db = set(i.get('city') for i in interns if i.get('city'))
    
    buttons = []
    for i, city in enumerate(AVAILABLE_CITIES):
        if city in cities_in_db:
            buttons.append([InlineKeyboardButton(text=city, callback_data=f"mgr_filter_city:{i}")])
    
    if not buttons:
        await callback.answer("Міста не вказані у стажерів.", show_alert=True)
        return

    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="mgr_filters_menu")])
    await _edit_menu_message(callback.message, "🏙️ Оберіть місто:", InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

async def manager_filter_city(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    try:
        city_idx = int(callback.data.split(":", 1)[1])
        city = AVAILABLE_CITIES[city_idx]
    except (ValueError, IndexError):
        await callback.answer("Помилка вибору міста.", show_alert=True)
        return

    interns = await get_manager_interns(callback.from_user.id)
    filtered = [i for i in interns if i.get('city') == city]
    await _list_interns_generic(
        callback, 
        filtered, 
        f"🏙️ <b>Стажери: {city}</b>", 
        "📭 Немає стажерів у цьому місті.",
        back_callback="mgr_by_city"
    )

async def manager_by_role_menu(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    team = await get_manager_team_users(callback.from_user.id)
    roles_in_db = set(i.get('role') for i in team if i.get('role'))
    
    buttons = []
    for i, role in enumerate(AVAILABLE_ROLES):
        if role in roles_in_db:
            label = role[:30] + "..." if len(role) > 30 else role
            buttons.append([InlineKeyboardButton(text=f"💼 {label}", callback_data=f"mgr_filter_role:{i}")])
    
    if not buttons:
        await _edit_menu_message(
            callback.message,
            "📭 У працівників вашого магазину ще не вказано посад.",
            InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="mgr_filters_menu")]])
        )
        await callback.answer()
        return

    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="mgr_filters_menu")])
    await _edit_menu_message(callback.message, "💼 <b>Фільтр за посадою</b>\n\nОберіть посаду:", InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

async def manager_filter_role(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    try:
        role_idx = int(callback.data.split(":", 1)[1])
        role = AVAILABLE_ROLES[role_idx]
    except (ValueError, IndexError):
        await callback.answer("Помилка вибору посади.", show_alert=True)
        return

    team = await get_manager_team_users(callback.from_user.id)
    filtered = [i for i in team if i.get('role') == role]
    await _list_interns_generic(
        callback, 
        filtered, 
        f"💼 <b>Працівники та стажери: {role}</b>", 
        "📭 Немає людей на цій посаді.",
        back_callback="mgr_by_role"
    )

# --- Section 2: Навчання (Курс керівника & Матеріали) ---

async def manager_study_root_menu(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    text = (
        "📚 <b>Розділ «Навчання»</b>\n\n"
        "Оберіть необхідний розділ:\n\n"
        "• <b>Навчання керівника</b> — програма навчання та матеріали курсу для посади «Керівник»\n"
        "• <b>Матеріали</b> — навчальні матеріали інших посад (режим читання) та нагадування тем"
    )
    buttons = [
        [InlineKeyboardButton(text="🎓 Навчання керівника", callback_data="mgr_training_course")],
        [InlineKeyboardButton(text="📚 Матеріали", callback_data="mgr_materials_catalog")],
        [InlineKeyboardButton(text="🏠 Головне меню", callback_data="manager_menu")]
    ]
    await _edit_menu_message(callback.message, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

async def manager_training_course_menu(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    role = "Керівник"
    from database.materials import get_days_for_role
    days = await get_days_for_role(role)
    if not days:
        days = [1, 2, 3, 4, 5]
    else:
        days = sorted(set(days))

    text = (
        "🎓 <b>Навчання керівника</b>\n\n"
        "Матеріали та завдання навчального курсу для посади «Керівник».\n"
        "Оберіть день для перегляду:"
    )
    buttons = []
    row = []
    for d in days:
        row.append(InlineKeyboardButton(text=f"День {d}", callback_data=f"mgr_tr_day:{d}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="mgr_study_root")])
    await _edit_menu_message(callback.message, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

async def manager_training_day_view(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    day = int(callback.data.split(":")[1])
    role = "Керівник"

    from database.materials import get_materials_for_day, get_test_by_role_and_day
    materials = await get_materials_for_day(role, day)
    test = await get_test_by_role_and_day(role, day)

    lines = [f"🎓 <b>Курс керівника: День {day}</b>\n"]
    if not materials and not test:
        lines.append("<i>Для цього дня курсу керівника поки що немає матеріалів.</i>")
    else:
        if materials:
            for idx, m in enumerate(materials, 1):
                m_type = m.get("content_type", "матеріал")
                title = m.get("title") or f"{m_type.capitalize()} #{idx}"
                content = m.get("content") or ""
                url = m.get("resource_url")
                lines.append(f"<b>{idx}. {html.escape(title)}</b> ({m_type})")
                if content:
                    lines.append(html.escape(content))
                if url:
                    lines.append(f"🔗 Посилання: {html.escape(url)}")
                lines.append("")
        if test:
            lines.append("📝 <b>Тест для керівника наявний.</b>")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3950] + "\n\n<i>...частину тексту скорочено...</i>"

    buttons = [
        [InlineKeyboardButton(text="⬅️ До днів навчання", callback_data="mgr_training_course")],
        [InlineKeyboardButton(text="📚 Навчання", callback_data="mgr_study_root")]
    ]
    await _edit_menu_message(callback.message, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

async def manager_materials_catalog(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    filtered_roles = [r for r in AVAILABLE_ROLES if r not in ("Керівник", "Керівник Стажер")]

    text = (
        "📚 <b>Матеріали навчання за посадами</b>\n\n"
        "Доступний перегляд матеріалів усіх посад у режимі читання (без редагування):\n"
        "<i>(Оберіть посаду або скористайтесь швидким нагадуванням теми)</i>"
    )
    buttons = []
    row = []
    for idx, role in enumerate(filtered_roles):
        row.append(InlineKeyboardButton(text=f"👤 {role}", callback_data=f"mgr_mat_role:{idx}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton(text="🧠 Нагадати тему", callback_data="remind_topic_global")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="mgr_study_root")])
    await _edit_menu_message(callback.message, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

async def manager_materials_role_days(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    try:
        role_idx = int(callback.data.split(":")[1])
        filtered_roles = [r for r in AVAILABLE_ROLES if r not in ("Керівник", "Керівник Стажер")]
        role = filtered_roles[role_idx]
    except (ValueError, IndexError):
        await callback.answer("Некоректна посада.", show_alert=True)
        return

    from database.materials import get_days_for_role
    days = await get_days_for_role(role)
    if not days:
        days = [1, 2, 3, 4, 5]
    else:
        days = sorted(set(days))

    text = (
        f"📖 <b>Матеріали: {role}</b>\n\n"
        "Оберіть день для перегляду матеріалів (режим читання):"
    )
    buttons = []
    row = []
    for d in days:
        row.append(InlineKeyboardButton(text=f"День {d}", callback_data=f"mgr_mat_view:{role_idx}:{d}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton(text="⬅️ Назад до посад", callback_data="mgr_materials_catalog")])
    await _edit_menu_message(callback.message, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

async def manager_material_view_day(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    parts = callback.data.split(":")
    role_idx = int(parts[1])
    day = int(parts[2])

    filtered_roles = [r for r in AVAILABLE_ROLES if r not in ("Керівник", "Керівник Стажер")]
    if role_idx >= len(filtered_roles):
        await callback.answer("Роль не знайдено.", show_alert=True)
        return
    role = filtered_roles[role_idx]

    from database.materials import get_materials_for_day, get_test_by_role_and_day
    materials = await get_materials_for_day(role, day)
    test = await get_test_by_role_and_day(role, day)

    lines = [f"📖 <b>Матеріали: {role} · День {day}</b>\n"]
    if not materials and not test:
        lines.append("<i>Для цього дня поки що немає матеріалів.</i>")
    else:
        if materials:
            for idx, m in enumerate(materials, 1):
                m_type = m.get("content_type", "матеріал")
                title = m.get("title") or f"{m_type.capitalize()} #{idx}"
                content = m.get("content") or ""
                url = m.get("resource_url")
                lines.append(f"<b>{idx}. {html.escape(title)}</b> ({m_type})")
                if content:
                    lines.append(html.escape(content[:500]) + ("..." if len(content) > 500 else ""))
                if url:
                    lines.append(f"🔗 Посилання: {html.escape(url)}")
                lines.append("")
        if test:
            lines.append("📝 <b>Тест доступний:</b> перевірочні запитання наявні.")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3950] + "\n\n<i>...частину тексту скорочено...</i>"

    buttons = [
        [InlineKeyboardButton(text="⬅️ До днів посади", callback_data=f"mgr_mat_role:{role_idx}")],
        [InlineKeyboardButton(text="📚 До каталогу посад", callback_data="mgr_materials_catalog")]
    ]
    await _edit_menu_message(callback.message, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

# --- Legacy Reports (Kept for compatibility) ---
async def manager_report(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    
    interns = await get_manager_interns(callback.from_user.id)
    if not interns:
        await callback.answer("Немає стажерів для звіту.", show_alert=True)
        return

    total = len(interns)
    completed_list = []
    for i in interns:
        progress = await get_user_progress(i['user_id'])
        if sum(1 for p in progress if p.get('completed')) >= DAYS_TOTAL:
            completed_list.append(i)
    completed = len(completed_list)
    
    active_list = await get_interns_in_progress_for_manager(callback.from_user.id, active_only=True)
    active = len(active_list)
    
    inactive_list = await get_inactive_interns_for_manager(callback.from_user.id, days=3)
    inactive = len(inactive_list)
    
    report_text = (
        "📊 <b>Загальний звіт по стажерах</b>\n\n"
        f"👥 Всього: <b>{total}</b>\n"
        f"🚀 Активні (менше 3 дн.): <b>{active}</b>\n"
        f"🎉 Завершили навчання: <b>{completed}</b>\n"
        f"😴 Неактивні (3 дні і більше): <b>{inactive}</b>\n\n"
    )
    
    await _edit_menu_message(
        callback.message,
        report_text,
        InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="mgr_filters_menu")]])
    )
    await callback.answer()

async def manager_remind_menu(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    buttons = []
    for i, role in enumerate(AVAILABLE_ROLES):
        label = role[:30] + "..." if len(role) > 30 else role
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"mgr_remind_role:{i}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="mgr_study_root")])
    await _edit_menu_message(
        callback.message,
        "🧠 <b>База знань</b>\n\nОберіть посаду для пошуку матеріалів:", 
        InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()

async def manager_process_remind_role(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_manager(callback):
        return
    try:
        role_idx = int(callback.data.split(":")[1])
        role = AVAILABLE_ROLES[role_idx]
    except (ValueError, IndexError):
        await callback.answer("Некоректна посада.", show_alert=True)
        return

    await state.update_data(role=role, mode="manager_global")
    await state.set_state(SearchStates.waiting_for_query)
    await _edit_menu_message(
        callback.message,
        f"🧠 <b>Пошук матеріалів ({role})</b>\n\n"
        "Введи ключові слова або питання, щоб знайти інформацію:",
        InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="mgr_remind_menu")]])
    )
    await callback.answer()

# --- Add Intern (New Logic) ---
async def manager_add_intern(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_manager(callback):
        return
    await state.clear()
    
    buttons = []
    for city in AVAILABLE_CITIES:
        buttons.append([InlineKeyboardButton(text=city, callback_data=f"add_city:{city}")])
    buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="mgr_my_team")])
    
    await _edit_menu_message(
        callback.message,
        "🏙️ <b>Звідки стажер?</b>\n\nОберіть місто:",
        InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await state.set_state(ManagerStates.waiting_add_intern_city)
    await callback.answer()

async def manager_process_add_city_callback(callback: CallbackQuery, state: FSMContext):
    try:
        _, city = callback.data.split(":", 1)
    except ValueError:
        await callback.answer("Помилка даних міста.", show_alert=True)
        return

    await state.update_data(add_city=city)
    
    # Отримуємо список магазинів для обраного міста
    shops = AVAILABLE_SHOPS.get(city, [])
    
    buttons = []
    if shops:
        for i in range(0, len(shops), 2):
            row = []
            shop1 = shops[i]
            label1 = shop1[:30] + "..." if len(shop1) > 30 else shop1
            row.append(InlineKeyboardButton(text=label1, callback_data=f"add_shop:{i}"))
            
            if i + 1 < len(shops):
                shop2 = shops[i+1]
                label2 = shop2[:30] + "..." if len(shop2) > 30 else shop2
                row.append(InlineKeyboardButton(text=label2, callback_data=f"add_shop:{i+1}"))
            buttons.append(row)
    
    if not buttons:
         # Fallback to roles if no shops defined
        buttons = []
        for i, role in enumerate(AVAILABLE_ROLES):
            label = role[:30] + "..." if len(role) > 30 else role
            buttons.append([InlineKeyboardButton(text=label, callback_data=f"add_role:{i}")])
        buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="mgr_add")])
        
        await _edit_menu_message(
            callback.message,
            f"🏙️ Місто: <b>{city}</b>\n(Магазини не знайдено)\n\n💼 <b>Яка посада у стажера?</b>",
            InlineKeyboardMarkup(inline_keyboard=buttons)
        )
        await state.set_state(ManagerStates.waiting_add_intern_role)
    else:
        buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="mgr_add")])
        await _edit_menu_message(
            callback.message,
            f"🏙️ Місто: <b>{city}</b>\n\n🏪 <b>Оберіть магазин:</b>",
            InlineKeyboardMarkup(inline_keyboard=buttons)
        )
        await state.set_state(ManagerStates.waiting_add_intern_shop)
    
    await callback.answer()

async def manager_process_add_shop_callback(callback: CallbackQuery, state: FSMContext):
    try:
        _, shop_idx_str = callback.data.split(":", 1)
        shop_idx = int(shop_idx_str)
        
        data = await state.get_data()
        city = data.get("add_city")
        shops = AVAILABLE_SHOPS.get(city, [])
        shop = shops[shop_idx]
    except (ValueError, IndexError):
        await callback.answer("Помилка даних магазину.", show_alert=True)
        return

    await state.update_data(add_shop=shop)
    
    buttons = []
    for i, role in enumerate(AVAILABLE_ROLES):
        label = role[:30] + "..." if len(role) > 30 else role
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"add_role:{i}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад (до міст)", callback_data="mgr_add")])
    
    await _edit_menu_message(
        callback.message,
        f"🏙️ Місто: <b>{city}</b>\n🏪 Магазин: <b>{shop}</b>\n\n💼 <b>Яка посада у стажера?</b>",
        InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await state.set_state(ManagerStates.waiting_add_intern_role)
    await callback.answer()

async def manager_process_add_role_callback(callback: CallbackQuery, state: FSMContext):
    try:
        _, role_idx_str = callback.data.split(":", 1)
        role_idx = int(role_idx_str)
        role = AVAILABLE_ROLES[role_idx]
    except (ValueError, IndexError):
        await callback.answer("Помилка даних посади.", show_alert=True)
        return

    data = await state.get_data()
    city = data.get("add_city")
    shop = data.get("add_shop")
    manager_id = callback.from_user.id
    
    token = await generate_token(manager_id, role, city, shop=shop)
    
    try:
        bot_user = await callback.bot.get_me()
        bot_username = bot_user.username
    except Exception:
        bot_username = "BulkaBot" # Fallback if get_me fails

    link = f"https://t.me/{bot_username}?start={manager_id}-{token}"
    
    shop_text = f"\n🏪 Магазин: <b>{shop}</b>" if shop else ""
    
    await _edit_menu_message(
        callback.message,
        f"✅ <b>Посилання створено!</b>\n\n"
        f"🏙️ Місто: <b>{city}</b>{shop_text}\n"
        f"💼 Посада: <b>{role}</b>\n\n"
        f"🔗 <b>Посилання для стажера:</b>\n"
        f"<code>{link}</code>\n\n"
        f"⚠️ Посилання діє 24 години і лише для одного користувача.",
        InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👔 До панелі", callback_data="manager_menu")]])
    )
    await state.clear()
    await callback.answer()

# --- Remove Intern ---
async def manager_remove_menu(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    interns = await get_manager_interns(callback.from_user.id)
    
    if not interns:
        await callback.answer("Немає стажерів для видалення.", show_alert=True)
        return

    text = "❌ <b>Оберіть стажера для видалення:</b>\n"
    buttons = []
    for intern in interns:
        name = intern.get("full_name", "Без імені")
        uid = intern.get("user_id")
        buttons.append([InlineKeyboardButton(
            text=f"❌ {name}", 
            callback_data=f"mgr_confirm_remove_{uid}"
        )])
    
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="manager_menu")])
    
    await _edit_menu_message(callback.message, text, InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

async def manager_confirm_remove(callback: CallbackQuery, state: FSMContext):
    try:
        user_id = int(callback.data.split("_")[-1])
    except ValueError:
        return
    
    # Store ID in state to confirm
    await state.update_data(remove_user_id=user_id)
    
    await _edit_menu_message(
        callback.message,
        f"⚠️ <b>Ви впевнені, що хочете видалити стажера {user_id}?</b>\nЦе видалить всі дані про його прогрес.",
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Так, видалити", callback_data="mgr_perform_remove")],
            [InlineKeyboardButton(text="❌ Ні, скасувати", callback_data="manager_menu")]
        ])
    )
    await callback.answer()

async def manager_perform_remove(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = data.get("remove_user_id")
    
    if user_id:
        await delete_user(user_id)
        await callback.answer("Стажера видалено.", show_alert=True)
    
    await manager_menu(callback, state)

# --- View Intern Detail (Existing) ---
async def manager_view_intern(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_manager(callback):
        return
    
    try:
        intern_id = int(callback.data.split("_")[-1])
    except (ValueError, IndexError):
        await callback.answer("Некоректний ID.", show_alert=True)
        return
    
    await _show_intern_details(callback.message, intern_id, is_callback=True)
    await callback.answer()

async def manager_manage_days_menu(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    
    manager_id = callback.from_user.id
    interns = await get_manager_interns(manager_id)
    
    if not interns:
        await _edit_menu_message(
            callback.message,
            "📭 У вас немає стажерів для керування днями.",
            InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="manager_menu")]])
        )
        await callback.answer()
        return

    text = "📅 <b>Оберіть стажера для керування навчальними днями:</b>\n\n"
    buttons = []
    for intern in interns:
        name = intern.get("full_name", "Без імені")
        uid = intern.get("user_id")
        buttons.append([InlineKeyboardButton(
            text=f"{name} (ID: {uid})",
            callback_data=f"manager_intern_learning_{uid}"
        )])
    
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="manager_menu")])
    
    await _edit_menu_message(
        callback.message,
        text, 
        InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()

async def _show_intern_details(message_or_msg: Message, intern_id: int, is_callback=False):
    report = await get_user_days_report(intern_id)
    
    buttons = [
        [InlineKeyboardButton(text="⬅️ До працівників", callback_data="mgr_my_team")],
        [InlineKeyboardButton(text="🏠 Головне меню", callback_data="manager_menu")]
    ]
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    if is_callback:
        # message_or_msg is actually the message object when called from callback handler (callback.message)
        # Wait, in manager_view_intern we pass callback.message, so it is a Message object.
        await _edit_menu_message(message_or_msg, report, kb)
    else:
        await message_or_msg.answer(report, reply_markup=kb)

async def manager_remind_all_lagging(callback: CallbackQuery):
    """Нагадує всім відстаючим стажерам з щоденного звіту."""
    if not await _ensure_manager(callback):
        return
    
    from bot.services.reminders import send_intern_reminder
    from bot.services.logger import get_logger
    
    logger = get_logger()
    manager_id = callback.from_user.id
    
    try:
        interns = await get_interns_in_progress_for_manager(manager_id)
        sent_count = 0
        failed_count = 0
        
        logger.debug(f"Manager {manager_id} initiating reminders for {len(interns)} interns")
        
        for intern in interns:
            uid = intern['user_id']
            current_block = intern.get('current_block', 1)
            
            progress_rows = await get_user_progress(uid)
            is_completed = False
            for row in progress_rows:
                if row['day'] == current_block and row['completed']:
                    is_completed = True
                    break
            
            if not is_completed:
                # Send reminder
                try:
                    if await send_intern_reminder(callback.bot, uid, source="manager", sender_id=manager_id):
                        sent_count += 1
                        logger.debug(f"Reminder sent to intern {uid}")
                    else:
                        failed_count += 1
                        logger.debug(f"Reminder failed for intern {uid}")
                except Exception as e:
                    failed_count += 1
                    logger.error(f"Error sending reminder to intern {uid}: {e}")
        
        result_text = f"✅ <b>Нагадування надіслано!</b>\n\n"
        result_text += f"📨 Успішно: {sent_count} стажерів\n"
        if failed_count > 0:
            result_text += f"❌ Не вдалося: {failed_count} стажерів\n"
        result_text += f"\n<i>Стажери отримали повідомлення про продовження навчання</i>"
        
        await _edit_menu_message(
            callback.message,
            result_text,
            InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👌 Добре", callback_data="mgr_dismiss_report")]])
        )
        await callback.answer("✅ Нагадування відправлено")
        
        logger.info(f"Manager {manager_id} sent reminders: {sent_count} success, {failed_count} failed")
        
    except Exception as e:
        logger.error(f"Error in manager_remind_all_lagging: {e}", exc_info=True)
        await callback.answer("❌ Помилка при відправці нагадувань", show_alert=True)

async def manager_dismiss_report(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()

async def intern_promote_handler(callback: CallbackQuery):
    """Переводить стажера в статус Працівника."""
    try:
        intern_id = int(callback.data.split("_")[-1])
    except (ValueError, IndexError):
        await callback.answer("Помилка даних.", show_alert=True)
        return

    intern = await get_user_details(intern_id)
    if not intern:
        await callback.answer("Стажера не знайдено в системі.", show_alert=True)
        try:
            await callback.message.delete()
        except Exception:
            pass
        return

    await update_user_role(intern_id, "Працівник", actor_id=callback.from_user.id)
    full_name = intern.get("full_name") or intern.get("username") or f"ID {intern_id}"

    # Повідомлення керівнику
    try:
        await callback.message.edit_text(
            f"✅ <b>{full_name}</b> тепер має статус <b>Працівника</b>.\n\nВітаємо з новим членом команди! 🎉",
            parse_mode="HTML"
        )
    except Exception:
        pass

    # Вітальне повідомлення стажеру
    try:
        congrats_text = (
            "🎉 <b>Вітаємо! Ви стали Працівником Bulka!</b>\n\n"
            "Ваш керівник підтвердив, що ви готові розпочати свій шлях у нашій команді.\n\n"
            "🍞 Ласкаво просимо до родини Bulka — тут починається ваша справжня кар'єра!\n\n"
            "<i>Бажаємо вам натхнення, зростання та яскравих успіхів!</i> 🌟"
        )
        await callback.bot.send_message(intern_id, congrats_text, parse_mode="HTML")
    except Exception:
        pass

    await callback.answer("Статус оновлено ✅")

async def intern_dismiss_handler(callback: CallbackQuery):
    """Видаляє стажера з системи після завершення навчання."""
    try:
        intern_id = int(callback.data.split("_")[-1])
    except (ValueError, IndexError):
        await callback.answer("Помилка даних.", show_alert=True)
        return

    intern = await get_user_details(intern_id)
    full_name = intern.get("full_name") or intern.get("username") or f"ID {intern_id}" if intern else f"ID {intern_id}"

    if intern:
        await log_training_event(
            user_id=intern_id,
            event_type="rejected",
            actor_id=callback.from_user.id,
            full_name=intern.get("full_name"),
            username=intern.get("username"),
            city=intern.get("city"),
            shop=intern.get("shop"),
            role=intern.get("role"),
            manager_id=intern.get("manager_id"),
        )

    await delete_user(intern_id)

    try:
        await callback.message.edit_text(
            f"❌ <b>{full_name}</b> видалено з системи.",
            parse_mode="HTML"
        )
    except Exception:
        pass
    await callback.answer("Видалено ❌")

# --- Register ---
def register_manager_handlers(dp: Dispatcher):
    dp.callback_query.register(manager_menu, lambda c: c.data == "manager_menu")
    
    # Restructured Manager Navigation
    dp.callback_query.register(manager_my_team_menu, lambda c: c.data == "mgr_my_team")
    dp.callback_query.register(manager_all_workers_menu, lambda c: c.data == "mgr_all_workers_menu")
    dp.callback_query.register(manager_list_all_text, lambda c: c.data == "mgr_list_all_text")
    dp.callback_query.register(manager_interns_list, lambda c: c.data and c.data.startswith("mgr_interns_list:"))
    dp.callback_query.register(manager_workers_list, lambda c: c.data and c.data.startswith("mgr_workers_list:"))
    
    # Isolated Search
    dp.callback_query.register(manager_search_worker_start, lambda c: c.data == "mgr_search_worker")
    dp.message.register(manager_search_worker_process, ManagerStates.waiting_search_worker)

    # Filters
    dp.callback_query.register(manager_filters_menu, lambda c: c.data == "mgr_filters_menu")
    dp.callback_query.register(manager_filter_recent_activity, lambda c: c.data == "mgr_filter_recent_activity")

    # Training & Materials
    dp.callback_query.register(manager_study_root_menu, lambda c: c.data == "mgr_study_root")
    dp.callback_query.register(manager_training_course_menu, lambda c: c.data == "mgr_training_course")
    dp.callback_query.register(manager_training_day_view, lambda c: c.data and c.data.startswith("mgr_tr_day:"))
    dp.callback_query.register(manager_materials_catalog, lambda c: c.data == "mgr_materials_catalog")
    dp.callback_query.register(manager_materials_role_days, lambda c: c.data and c.data.startswith("mgr_mat_role:"))
    dp.callback_query.register(manager_material_view_day, lambda c: c.data and c.data.startswith("mgr_mat_view:"))

    # Daily Report Actions
    dp.callback_query.register(manager_remind_all_lagging, lambda c: c.data == "mgr_remind_all_lagging")
    dp.callback_query.register(manager_dismiss_report, lambda c: c.data == "mgr_dismiss_report")

    # Training completion — promote / dismiss
    dp.callback_query.register(intern_promote_handler, lambda c: c.data and c.data.startswith("intern_promote_"))
    dp.callback_query.register(intern_dismiss_handler, lambda c: c.data and c.data.startswith("intern_dismiss_"))
    
    # Lists
    dp.callback_query.register(manager_active_interns, lambda c: c.data == "mgr_active")
    dp.callback_query.register(manager_completed_interns, lambda c: c.data == "mgr_completed")
    dp.callback_query.register(manager_inactive_interns, lambda c: c.data == "mgr_inactive")
    dp.callback_query.register(manager_all_interns, lambda c: c.data == "mgr_all")
    
    # Filters by city/role
    dp.callback_query.register(manager_by_city_menu, lambda c: c.data == "mgr_by_city")
    dp.callback_query.register(manager_filter_city, lambda c: c.data and c.data.startswith("mgr_filter_city:"))
    dp.callback_query.register(manager_by_role_menu, lambda c: c.data == "mgr_by_role")
    dp.callback_query.register(manager_filter_role, lambda c: c.data and c.data.startswith("mgr_filter_role:"))
    
    # Report & Remind
    dp.callback_query.register(manager_report, lambda c: c.data == "mgr_report")
    dp.callback_query.register(manager_remind_menu, lambda c: c.data == "mgr_remind_menu")
    dp.callback_query.register(manager_process_remind_role, lambda c: c.data and c.data.startswith("mgr_remind_role:"))
    
    # Add Intern (New logic)
    dp.callback_query.register(manager_add_intern, lambda c: c.data == "mgr_add")
    dp.callback_query.register(manager_process_add_city_callback, lambda c: c.data and c.data.startswith("add_city:"))
    dp.callback_query.register(manager_process_add_shop_callback, lambda c: c.data and c.data.startswith("add_shop:"))
    dp.callback_query.register(manager_process_add_role_callback, lambda c: c.data and c.data.startswith("add_role:"))
    
    # Remove Intern
    dp.callback_query.register(manager_remove_menu, lambda c: c.data == "mgr_remove_menu")
    dp.callback_query.register(manager_confirm_remove, lambda c: c.data and c.data.startswith("mgr_confirm_remove_"))
    dp.callback_query.register(manager_perform_remove, lambda c: c.data == "mgr_perform_remove")
    
    dp.callback_query.register(manager_manage_days_menu, lambda c: c.data == "mgr_manage_days")
    
    # View Detail
    dp.callback_query.register(manager_view_intern, lambda c: c.data and c.data.startswith("mgr_view_intern_"))
