import asyncio
from datetime import datetime, timedelta
import pytz

from aiogram import Dispatcher
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.exceptions import TelegramBadRequest

from bot.config import TIMEZONE, DAYS_TOTAL
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
    get_user_progress
)
from bot.services.developer_actions import get_user_days_report
from bot.constants import AVAILABLE_ROLES, AVAILABLE_CITIES
from database.tokens import generate_token

class ManagerStates(StatesGroup):
    waiting_search_intern = State()
    waiting_add_intern_city = State()
    waiting_add_intern_role = State()
    waiting_confirm_remove = State()
    waiting_remind_topic_select = State()

async def _ensure_manager(callback: CallbackQuery) -> bool:
    user_id = callback.from_user.id
    if not await is_privileged_user(user_id):
        await callback.answer("⛔️ Доступ заборонено.", show_alert=True)
        return False
    return True

def _manager_main_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="🚀 Активні стажери", callback_data="mgr_active"),
            InlineKeyboardButton(text="🎉 Завершили навчання", callback_data="mgr_completed")
        ],
        [
            InlineKeyboardButton(text="😴 Неактивні ≥3 дн.", callback_data="mgr_inactive"),
            InlineKeyboardButton(text="📋 Усі стажери", callback_data="mgr_all")
        ],
        [
            InlineKeyboardButton(text="🏙️ За містом", callback_data="mgr_by_city"),
            InlineKeyboardButton(text="💼 За посадою", callback_data="mgr_by_role")
        ],
        [
            InlineKeyboardButton(text="📊 Звіт стажерів", callback_data="mgr_report"),
            InlineKeyboardButton(text="🧠 Нагадати тему", callback_data="mgr_remind_menu")
        ],
        [
            InlineKeyboardButton(text="➕ Додати стажера", callback_data="mgr_add"),
            InlineKeyboardButton(text="❌ Видалити стажера", callback_data="mgr_remove_menu")
        ],
        [InlineKeyboardButton(text="🏠 Головне меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def manager_menu(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_manager(callback):
        return
    
    await state.clear()
    text = "👔 <b>Панель Керівника</b>\n\nОберіть дію:"
    kb = _manager_main_keyboard()
    
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "there is no text in the message to edit" in str(e) or "message to edit not found" in str(e):
            await callback.message.delete()
            await callback.message.answer(text, reply_markup=kb)
        else:
            raise e
            
    await callback.answer()

# --- Helper to list interns ---
async def _list_interns_generic(callback: CallbackQuery, interns: list, title: str, empty_msg: str):
    if not interns:
        await callback.message.edit_text(
            f"{empty_msg}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="manager_menu")]])
        )
        await callback.answer()
        return

    text = f"{title}\n\n"
    buttons = []
    
    # Pagination or simple list? Assume simple list for now, up to 50
    for intern in interns[:50]:
        name = intern.get("full_name", "Без імені")
        uid = intern.get("user_id")
        current_block = intern.get("current_block", 1)
        buttons.append([InlineKeyboardButton(
            text=f"{name} (День {current_block})", 
            callback_data=f"mgr_view_intern_{uid}"
        )])
    
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="manager_menu")])
    
    await callback.message.edit_text(
        text + "Оберіть стажера для перегляду деталей:", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()

# --- Handlers for main menu buttons ---

async def manager_active_interns(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    interns = await get_interns_in_progress_for_manager(callback.from_user.id)
    await _list_interns_generic(callback, interns, "🚀 <b>Активні стажери:</b>", "📭 Немає активних стажерів.")

async def manager_completed_interns(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    
    all_interns = await get_manager_interns(callback.from_user.id)
    completed = []
    
    for intern in all_interns:
        # Check if they completed all days. This logic might need optimization in DB, but doing in code for now.
        progress = await get_user_progress(intern['user_id'])
        # A simplified check: if count of completed days >= DAYS_TOTAL
        completed_count = sum(1 for p in progress if p.get('completed'))
        if completed_count >= DAYS_TOTAL:
            completed.append(intern)
            
    await _list_interns_generic(callback, completed, "🎉 <b>Завершили навчання:</b>", "📭 Немає стажерів, що завершили навчання.")

async def manager_inactive_interns(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    interns = await get_inactive_interns_for_manager(callback.from_user.id, days=3)
    await _list_interns_generic(callback, interns, "😴 <b>Неактивні ≥3 дн.:</b>", "🎉 Всі стажери активні!")

async def manager_all_interns(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    # Shows only interns assigned to this manager (filtered by manager_id)
    interns = await get_manager_interns(callback.from_user.id)
    await _list_interns_generic(callback, interns, "📋 <b>Усі стажери:</b>", "📭 Список стажерів порожній.")

# --- Filtering by City/Role ---

async def manager_by_city_menu(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    interns = await get_manager_interns(callback.from_user.id)
    cities = sorted(list(set(i.get('city') for i in interns if i.get('city'))))
    
    if not cities:
        await callback.answer("Міста не вказані у стажерів.", show_alert=True)
        return

    buttons = []
    for city in cities:
        buttons.append([InlineKeyboardButton(text=city, callback_data=f"mgr_filter_city:{city}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="manager_menu")])
    
    await callback.message.edit_text("🏙️ Оберіть місто:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

async def manager_filter_city(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    city = callback.data.split(":", 1)[1]
    interns = await get_manager_interns(callback.from_user.id)
    filtered = [i for i in interns if i.get('city') == city]
    await _list_interns_generic(callback, filtered, f"🏙️ <b>Стажери: {city}</b>", "📭 Немає стажерів у цьому місті.")

async def manager_by_role_menu(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    interns = await get_manager_interns(callback.from_user.id)
    roles = sorted(list(set(i.get('role') for i in interns if i.get('role'))))
    
    if not roles:
        await callback.answer("Посади не вказані у стажерів.", show_alert=True)
        return

    buttons = []
    for role in roles:
        buttons.append([InlineKeyboardButton(text=role, callback_data=f"mgr_filter_role:{role}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="manager_menu")])
    
    await callback.message.edit_text("💼 Оберіть посаду:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

async def manager_filter_role(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    role = callback.data.split(":", 1)[1]
    interns = await get_manager_interns(callback.from_user.id)
    filtered = [i for i in interns if i.get('role') == role]
    await _list_interns_generic(callback, filtered, f"💼 <b>Стажери: {role}</b>", "📭 Немає стажерів на цій посаді.")

# --- Report ---
async def manager_report(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    
    interns = await get_manager_interns(callback.from_user.id)
    if not interns:
        await callback.answer("Немає стажерів для звіту.", show_alert=True)
        return

    # Simple stats
    total = len(interns)
    active_list = await get_interns_in_progress_for_manager(callback.from_user.id)
    active = len(active_list)
    completed = total - active # Approximate
    
    # Inactive > 3 days
    inactive_list = await get_inactive_interns_for_manager(callback.from_user.id, days=3)
    inactive = len(inactive_list)
    
    report_text = (
        "📊 <b>Загальний звіт по стажерах</b>\n\n"
        f"👥 Всього: <b>{total}</b>\n"
        f"🚀 Активні: <b>{active}</b>\n"
        f"🎉 Завершили: <b>{completed}</b>\n"
        f"😴 Неактивні (>3 днів): <b>{inactive}</b>\n\n"
    )
    
    await callback.message.edit_text(
        report_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="manager_menu")]])
    )
    await callback.answer()

# --- Remind Topic ---
async def manager_remind_menu(callback: CallbackQuery):
    # Just reusing the active list to select someone to remind
    if not await _ensure_manager(callback):
        return
    interns = await get_interns_in_progress_for_manager(callback.from_user.id)
    
    if not interns:
        await callback.message.edit_text(
            "📭 Немає активних стажерів, яким можна нагадати тему.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="manager_menu")]])
        )
        return

    text = "🧠 <b>Оберіть стажера для нагадування:</b>\n\n"
    buttons = []
    for intern in interns:
        name = intern.get("full_name", "Без імені")
        uid = intern.get("user_id")
        # Reuse the developer functionality for reminding
        buttons.append([InlineKeyboardButton(
            text=f"{name}", 
            callback_data=f"remind_topic_for_intern:{uid}"
        )])
    
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="manager_menu")])
    
    await callback.message.edit_text(
        text, 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
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
    buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="manager_menu")])
    
    await callback.message.edit_text(
        "🏙️ <b>Звідки стажер?</b>\n\nОберіть місто:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
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
    
    buttons = []
    for i, role in enumerate(AVAILABLE_ROLES):
        # Shorten if too long
        label = role[:30] + "..." if len(role) > 30 else role
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"add_role:{i}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="mgr_add")])
    
    await callback.message.edit_text(
        f"🏙️ Місто: <b>{city}</b>\n\n💼 <b>Яка посада у стажера?</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
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
    manager_id = callback.from_user.id
    
    token = await generate_token(manager_id, role, city)
    
    try:
        bot_user = await callback.bot.get_me()
        bot_username = bot_user.username
    except Exception:
        bot_username = "BulkaBot" # Fallback if get_me fails

    link = f"https://t.me/{bot_username}?start={manager_id}-{token}"
    
    await callback.message.edit_text(
        f"✅ <b>Посилання створено!</b>\n\n"
        f"🏙️ Місто: <b>{city}</b>\n"
        f"💼 Посада: <b>{role}</b>\n\n"
        f"🔗 <b>Посилання для стажера:</b>\n"
        f"<code>{link}</code>\n\n"
        f"⚠️ Посилання діє 24 години і лише для одного користувача.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👔 До панелі", callback_data="manager_menu")]])
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
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

async def manager_confirm_remove(callback: CallbackQuery, state: FSMContext):
    try:
        user_id = int(callback.data.split("_")[-1])
    except ValueError:
        return
    
    # Store ID in state to confirm
    await state.update_data(remove_user_id=user_id)
    
    await callback.message.edit_text(
        f"⚠️ <b>Ви впевнені, що хочете видалити стажера {user_id}?</b>\nЦе видалить всі дані про його прогрес.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
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

async def _show_intern_details(message_or_msg: Message, intern_id: int, is_callback=False):
    report = await get_user_days_report(intern_id)
    
    buttons = [
        [InlineKeyboardButton(text="⬅️ Назад до списку", callback_data="mgr_active")],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="manager_menu")]
    ]
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    if is_callback:
        await message_or_msg.edit_text(report, reply_markup=kb)
    else:
        await message_or_msg.answer(report, reply_markup=kb)

async def manager_remind_all_lagging(callback: CallbackQuery):
    if not await _ensure_manager(callback):
        return
    
    from bot.services.reminders import send_intern_reminder
    
    manager_id = callback.from_user.id
    interns = await get_interns_in_progress_for_manager(manager_id)
    sent_count = 0
    
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
            if await send_intern_reminder(callback.bot, uid, source="manager", sender_id=manager_id):
                sent_count += 1
    
    await callback.message.edit_text(
        f"✅ <b>Нагадування надіслано!</b>\n\nОтримали: {sent_count} стажерів.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👌 Добре", callback_data="mgr_dismiss_report")]])
    )
    await callback.answer()

async def manager_dismiss_report(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()

# --- Register ---
def register_manager_handlers(dp: Dispatcher):
    dp.callback_query.register(manager_menu, lambda c: c.data == "manager_menu")
    
    # Daily Report Actions
    dp.callback_query.register(manager_remind_all_lagging, lambda c: c.data == "mgr_remind_all_lagging")
    dp.callback_query.register(manager_dismiss_report, lambda c: c.data == "mgr_dismiss_report")
    
    # Lists
    dp.callback_query.register(manager_active_interns, lambda c: c.data == "mgr_active")
    dp.callback_query.register(manager_completed_interns, lambda c: c.data == "mgr_completed")
    dp.callback_query.register(manager_inactive_interns, lambda c: c.data == "mgr_inactive")
    dp.callback_query.register(manager_all_interns, lambda c: c.data == "mgr_all")
    # dp.callback_query.register(manager_my_interns, lambda c: c.data == "mgr_my_interns") # Removed as function was deleted
    
    # Filters
    dp.callback_query.register(manager_by_city_menu, lambda c: c.data == "mgr_by_city")
    dp.callback_query.register(manager_filter_city, lambda c: c.data and c.data.startswith("mgr_filter_city:"))
    dp.callback_query.register(manager_by_role_menu, lambda c: c.data == "mgr_by_role")
    dp.callback_query.register(manager_filter_role, lambda c: c.data and c.data.startswith("mgr_filter_role:"))
    
    # Report & Remind
    dp.callback_query.register(manager_report, lambda c: c.data == "mgr_report")
    dp.callback_query.register(manager_remind_menu, lambda c: c.data == "mgr_remind_menu")
    
    # Add Intern (New logic)
    dp.callback_query.register(manager_add_intern, lambda c: c.data == "mgr_add")
    dp.callback_query.register(manager_process_add_city_callback, lambda c: c.data and c.data.startswith("add_city:"))
    dp.callback_query.register(manager_process_add_role_callback, lambda c: c.data and c.data.startswith("add_role:"))
    
    # Remove Intern
    dp.callback_query.register(manager_remove_menu, lambda c: c.data == "mgr_remove_menu")
    dp.callback_query.register(manager_confirm_remove, lambda c: c.data and c.data.startswith("mgr_confirm_remove_"))
    dp.callback_query.register(manager_perform_remove, lambda c: c.data == "mgr_perform_remove")
    
    # View Detail
    dp.callback_query.register(manager_view_intern, lambda c: c.data and c.data.startswith("mgr_view_intern_"))
