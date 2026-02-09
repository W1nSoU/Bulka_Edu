import asyncio
import sys
import json
import aiosqlite
import html
from typing import Optional
from pathlib import Path
from datetime import datetime # NEW IMPORT
from aiogram import Dispatcher
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message, InputMediaPhoto
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.exceptions import TelegramBadRequest
from bot.config import MAIN_DEVELOPER_ID, DAYS_TOTAL
from bot.services.logger import get_logger
from bot.services.semantic_search import build_and_reset_embeddings
from database.users import (
    get_all_users,
    get_user_details,
    get_user_by_username,
    get_users_by_full_name, # NEW
    get_all_active_users,
    get_all_inactive_users,
    get_users_by_city,
    delete_user,
    register_user,
    get_reminder_history,
)
from database.hr import (
    is_developer_user,
    is_hr_user,
)
from database.managers import (
    get_all_managers,
    add_manager,
    delete_manager_by_uid,
    get_manager_by_uid,
    get_all_developers as get_all_devs_from_managers_db, # Alias to avoid name conflict if needed
    get_all_kerivnyky,
)

from bot.services.developer_actions import (
    parse_day_input,
    get_user_days_report,
    open_days_for_user,
    close_days_for_user,
    reset_days_for_user,
)
from database.materials import (
    get_unique_roles_from_materials,
    get_material_by_role_day_type,
    update_material_content,
    update_material_resource_url,
    add_or_update_material,
    get_test_by_role_and_day,
    get_material_by_id, # NEW IMPORT
    toggle_test_status,
)
from database.tokens import get_token_stats, cleanup_expired_tokens
from database.analytics import get_daily_stats, get_dropout_funnel
from bot.services.health import get_health_status
from bot.services.test_parser import parse_test_input, format_test_display
from bot.services.learning_progress import get_days_overview, DayStatus
from bot.services.access import get_display_role # Import get_display_role
from bot.constants import AVAILABLE_ROLES, AVAILABLE_SHOPS, AVAILABLE_CITIES
from bot.keyboards import get_pagination_keyboard # Import get_pagination_keyboard
from bot.utils.paginator import split_text # NEW IMPORT
import json


class DeveloperStates(StatesGroup):
    waiting_user_search = State()
    waiting_delete_user = State()
    waiting_add_manager_id = State()
    waiting_add_manager_name = State()
    waiting_add_manager_city = State()
    waiting_add_manager_shops = State()
    waiting_delete_manager = State()
    waiting_days_status = State()
    waiting_days_open = State()
    waiting_days_close = State()
    waiting_days_reset = State()
    waiting_add_developer = State()
    waiting_add_developer_name = State()
    waiting_add_hr = State()
    # Стани для редагування матеріалів
    waiting_material_text = State()
    waiting_material_video = State()
    waiting_material_parts = State() # New state for multi-message input
    waiting_test_input = State() # State for editing tests
    waiting_fix_page = State() # New state for fixing a specific page content
    # Стани для оповіщення про зміни
    waiting_notify_decision = State()
    waiting_notify_message = State()
    # Стани для зміни даних користувача
    waiting_change_manager_id = State()
    waiting_change_role = State()
    waiting_change_city = State()
    # Стани для редагування відео матеріалів
    waiting_video_role = State()
    waiting_video_day = State()
    waiting_video_uploads = State()
    waiting_photo_uploads = State() # New state for photo uploads
    waiting_syllabus_text = State() # State for editing syllabus


async def _ensure_developer(callback: CallbackQuery, require_main: bool = False) -> bool:
    user_id = callback.from_user.id
    is_dev = await is_developer_user(user_id)
    
    if require_main:
        # is_dev is only true if user is in 'developers' table AND is MAIN_DEVELOPER_ID
        is_dev = is_dev and user_id == MAIN_DEVELOPER_ID
    
    if not is_dev:
        await callback.answer("⛔️ Доступ заборонено. Ця дія доступна лише головному розробнику.", show_alert=True)
        return False
    return True


async def _send_in_chunks(message: Message, text: str, reply_markup=None, chunk_size: int = 3500):
    """
    Відправка довгих текстів частинами.
    - Якщо текст поміщається в один блок — оновлюємо поточне повідомлення (через _edit_or_answer).
    - Якщо ні — перший блок оновлює поточне повідомлення, решта надсилаються новими повідомленнями.
    """
    if len(text) <= chunk_size:
        await _edit_or_answer(message, text, reply_markup=reply_markup)
        return

    parts = []
    for line in text.split("\n"):
        if parts and len(parts[-1]) + len(line) + 1 <= chunk_size:
            parts[-1] += "\n" + line
        else:
            parts.append(line)

    # Першу частину показуємо реактивно в поточному повідомленні
    await _edit_or_answer(message, parts[0])

    # Проміжні частини без клавіатури
    for part in parts[1:-1]:
        await message.answer(part)

    # Остання частина з клавіатурою (якщо вона є)
    await message.answer(parts[-1], reply_markup=reply_markup)


def _developer_main_keyboard(is_main_dev: bool) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="👥 Користувачі", callback_data="dev_users_menu")],
        [
            InlineKeyboardButton(text="📝 Матеріали", callback_data="dev_materials_menu"),
            InlineKeyboardButton(text="📝 Тести", callback_data="dev_tests_menu"),
        ],
        [
            InlineKeyboardButton(text="🎥 Відео", callback_data="dev_videos_menu"),
            InlineKeyboardButton(text="🖼 Фото", callback_data="dev_photos_menu"),
        ],
        [
            InlineKeyboardButton(text="📚 Змінити змісти", callback_data="dev_syllabus_menu"),
        ],
        [
            InlineKeyboardButton(text="🎟 Токени", callback_data="dev_tokens_menu"),
            InlineKeyboardButton(text="💚 Health Status", callback_data="dev_health_status"),
        ],
        [InlineKeyboardButton(text="🧠 Нагадати тему", callback_data="remind_topic_global")],
        [
            InlineKeyboardButton(text="📜 Історія нагадувань", callback_data="dev_reminder_history"),
            InlineKeyboardButton(text="📊 Аналітика", callback_data="dev_analytics_menu"),
        ],
        [InlineKeyboardButton(text="📊 Помилки тестів", callback_data="show_test_errors")],
    ]
    # Розділяємо меню для головного розробника та інших
    row_team = []
    
    # "Команда Dev" тепер доступна всім розробникам
    row_team.append(InlineKeyboardButton(text="👨‍💻 Команда Dev", callback_data="dev_team_menu"))
    
    # "Команда Керівників" тепер доступна всім розробникам
    row_team.append(InlineKeyboardButton(text="👔 Команда Керівників", callback_data="dev_manage_managers"))
    buttons.append(row_team)

    buttons.append([InlineKeyboardButton(text="🏠 В головне меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def developer_menu_callback(callback: CallbackQuery):
    if not await _ensure_developer(callback):
        return
    is_main = callback.from_user.id == MAIN_DEVELOPER_ID
    await _edit_or_answer(
        callback.message,
        "🛠 <b>Dev-панель</b>\nОберіть розділ для керування:",
        reply_markup=_developer_main_keyboard(is_main),
    )
    try:
        await callback.answer()
    except TelegramBadRequest as e:
        if "query is too old" not in str(e):
            raise e


async def _edit_or_answer(message: Message, text: str, reply_markup=None):
    """
    Helper: намагається оновити поточне повідомлення, а якщо не виходить — надсилає нове.
    Якщо текст занадто довгий для медіа-підпису (>1024), автоматично переходить на текст.
    """
    # Якщо текст довший за ліміт підпису (з невеликим запасом), 
    # або якщо ми хочемо гарантувати доставку великого списку
    if len(text) > 1000:
        try:
            await message.delete()
        except:
            pass
        return await message.answer(text, reply_markup=reply_markup)

    try:
        if message.photo:
            await message.edit_caption(caption=text, reply_markup=reply_markup)
            return message
        await message.edit_text(text, reply_markup=reply_markup)
        return message
    except TelegramBadRequest as e:
        error_message = str(e).lower()
        if "message to edit not found" in error_message or "there is no text in the message to edit" in error_message:
            try:
                await message.delete()
            except:
                pass
            return await message.answer(text, reply_markup=reply_markup)
        elif "message is not modified" in error_message:
            return message
        else:
            # Для будь-яких інших помилок (наприклад, MEDIA_CAPTION_TOO_LONG), 
            # намагаємося надіслати новим текстовим повідомленням
            try:
                await message.delete()
            except:
                pass
            return await message.answer(text, reply_markup=reply_markup)
    except Exception:
        try:
            await message.delete()
        except:
            pass
        return await message.answer(text, reply_markup=reply_markup)


async def _remember_panel(state: FSMContext, key: str, message: Message):
    await state.update_data(
        **{
            key: {
                "chat_id": message.chat.id,
                "message_id": message.message_id,
            }
        }
    )


async def _refresh_panel_view(bot, panel_info: Optional[dict], builder):
    if not panel_info:
        return
    chat_id = panel_info.get("chat_id")
    message_id = panel_info.get("message_id")
    if not chat_id or not message_id:
        return
    text, kb = await builder()
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=kb)
    except Exception:
        await bot.send_message(chat_id, text, reply_markup=kb)


async def _format_identity(user_id: int, fallback_name=None, fallback_username=None):
    # Пріоритет віддаємо даним, переданим напряму (з таблиці managers)
    full_name = fallback_name
    username = fallback_username

    # Якщо дані відсутні, пробуємо отримати їх з таблиці users як запасний варіант
    if not full_name:
        profile = await get_user_details(user_id)
        if profile:
            full_name = profile.get("full_name")
            if username is None: # Оновлюємо username, тільки якщо він не був переданий
                username = profile.get("username")

    # Фінальні перевірки, щоб уникнути None
    full_name = full_name or "Без імені"
    username = username or ""
    
    username_display = f"@{username}" if username else "без username"
    return full_name, username_display


async def _build_managers_team_view(page: int = 0):
    """Список керівників з пагінацією та новим форматуванням."""
    all_hrs = await get_all_kerivnyky()
    
    city_abbr = {
        "Хмельницький": "ХМ",
        "Камʼянець-Подільський": "КП"
    }
    
    if not all_hrs:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Додати керівника", callback_data="dev_add_manager")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="developer_menu")],
        ])
        return "👔 <b>Команда керівників</b>\n\nПоки що немає", kb

    items_per_page = 10
    total_count = len(all_hrs)
    pages_total = (total_count + items_per_page - 1) // items_per_page
    
    if page < 0: page = 0
    if page >= pages_total and pages_total > 0: page = pages_total - 1
    
    start = page * items_per_page
    end = start + items_per_page
    paginated_hrs = all_hrs[start:end]
    
    lines = [f"👔 <b>Команда керівників</b> (Всього: {total_count}, Стор. {page + 1}/{pages_total})", ""]
    
    for idx, hr in enumerate(paginated_hrs, start=start + 1):
        name, username = await _format_identity(
            hr["uid"],
            hr.get("full_name"),
            hr.get("username"),
        )
        
        # Витягуємо тільки коди магазинів (наприклад, B-17)
        shop_list = hr.get("shops") or []
        shop_codes = [s.split(" ")[0] for s in shop_list]
        shops_str = ", ".join(shop_codes) if shop_codes else "Не вказано"
        
        # Абревіатура міста
        city = hr.get("city")
        
        # Спроба вивести місто з магазинів, якщо воно не вказано в БД
        if not city and shop_list:
            from bot.constants import AVAILABLE_SHOPS
            for city_name, city_shops in AVAILABLE_SHOPS.items():
                if any(s in city_shops for s in shop_list):
                    city = city_name
                    break
        
        abbr = city_abbr.get(city, "??")
        
        # Екрануємо дані з БД
        e_name = html.escape(name)
        e_username = html.escape(username)
        e_shops = html.escape(shops_str)
        
        lines.append(f"{idx}. {e_name} | {e_username} | {e_shops} | {abbr}")
        lines.append("───────────────")
    
    # Кнопки навігації
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Попередня", callback_data=f"dev_mgr_page:{page - 1}"))
    if page < pages_total - 1:
        nav_row.append(InlineKeyboardButton(text="Наступна ➡️", callback_data=f"dev_mgr_page:{page + 1}"))
    
    buttons = []
    if nav_row:
        buttons.append(nav_row)
        
    buttons.append([InlineKeyboardButton(text="➕ Додати керівника", callback_data="dev_add_manager")])
    buttons.append([InlineKeyboardButton(text="❌ Видалити керівника", callback_data="dev_remove_manager_menu")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="developer_menu")])
    
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


async def _build_dev_team_view() -> tuple[str, InlineKeyboardMarkup]:
    """Builds the view for the Dev Team management panel with nice formatting."""
    developers = await get_all_devs_from_managers_db()
    
    # Сортуємо: головний розробник завжди перший
    developers.sort(key=lambda x: x["uid"] != MAIN_DEVELOPER_ID)
    
    lines = [f"👨‍💻 <b>Команда Dev (всього: {len(developers)})</b>", ""]
    if not developers:
        lines.append("  Немає розробників у команді.")
    else:
        for idx, dev in enumerate(developers, start=1):
            name, username = await _format_identity(
                dev["uid"], dev.get("full_name"), dev.get("username")
            )
            # Екрануємо дані з БД
            e_name = html.escape(name)
            e_username = html.escape(username)
            lines.append(f"{idx}. {e_name} | {e_username} | ID: <code>{dev['uid']}</code>")
            lines.append("───────────────")
    
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Додати", callback_data="dev_add_dev"),
                InlineKeyboardButton(text="❌ Видалити", callback_data="dev_remove_dev_menu"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="developer_menu")],
        ]
    )
    return "\n".join(lines), kb

async def developer_dev_team_menu(callback: CallbackQuery, state: FSMContext):
    """Handler to show the Dev Team management menu."""
    if not await _ensure_developer(callback):
        return
    text, kb = await _build_dev_team_view()
    msg = await _edit_or_answer(callback.message, text, reply_markup=kb)
    await _remember_panel(state, "dev_panel", msg or callback.message)
    try:
        await callback.answer()
    except TelegramBadRequest as e:
        if "query is too old" not in str(e):
            raise e

async def developer_remove_dev_menu(callback: CallbackQuery, state: FSMContext):
    """Shows a menu to select a developer to remove."""
    if not await _ensure_developer(callback):
        return
    
    developers = await get_all_devs_from_managers_db()
    if not developers:
        await callback.answer("Немає розробників для видалення.", show_alert=True)
        return
    
    buttons = []
    for dev in developers:
        name, _ = await _format_identity(dev["uid"], dev.get("full_name"))
        buttons.append([
            InlineKeyboardButton(
                text=f"❌ {name}", 
                callback_data=f"dev_remove_confirm:{dev['uid']}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="dev_team_menu")])
    
    await _edit_or_answer(
        callback.message,
        "🗑 Оберіть розробника для видалення:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    try:
        await callback.answer()
    except TelegramBadRequest as e:
        if "query is too old" not in str(e):
            raise e

async def developer_remove_dev(callback: CallbackQuery, state: FSMContext):
    """Performs the removal of a developer after confirmation."""
    if not await _ensure_developer(callback):
        return
    
    try:
        user_id_to_remove = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Некоректний ID.", show_alert=True)
        return

    # Захист від видалення головного розробника
    if user_id_to_remove == MAIN_DEVELOPER_ID:
        await callback.answer(
            "⛔️ Ви не можете видалити головного розробника.",
            show_alert=True
        )
        return
        
    await delete_manager_by_uid(user_id_to_remove)
    await callback.answer(f"Розробника {user_id_to_remove} видалено з команди.", show_alert=True)
    
    # Оновлюємо вигляд меню
    await developer_dev_team_menu(callback, state)

# ---------- Users section ----------

def _users_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🚀 Активні стажери", callback_data="dev_users_active"),
            InlineKeyboardButton(text="😴 Неактивні", callback_data="dev_users_inactive"),
        ],
        [InlineKeyboardButton(text="🏙️ За містом", callback_data="dev_users_by_city")],
        [InlineKeyboardButton(text="📋 Список користувачів", callback_data="dev_users_list")],
        [InlineKeyboardButton(text="🔍 Пошук", callback_data="dev_users_search")],
        [InlineKeyboardButton(text="❌ Видалити", callback_data="dev_users_delete")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="developer_menu")]
    ])


def _cancel_keyboard(callback_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Скасувати", callback_data=callback_data)]]
    )


async def _remember_panel(state: FSMContext, key: str, message: Message):
    await state.update_data(
        **{
            key: {
                "chat_id": message.chat.id,
                "message_id": message.message_id,
            }
        }
    )


async def _refresh_panel_view(bot, panel_info: Optional[dict], builder):
    if not panel_info:
        return
    chat_id = panel_info.get("chat_id")
    message_id = panel_info.get("message_id")
    if not chat_id or not message_id:
        return
    text, kb = await builder()
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=kb)
    except Exception:
        await bot.send_message(chat_id, text, reply_markup=kb)


async def _build_developer_team_view():
    developers = await get_all_devs_from_managers_db()
    text = (
        f"👨‍💻 <b>Команда Dev</b>\n"
        f"Усього учасників: <b>{len(developers)}</b>\n"
        "Оберіть девелопера, щоб керувати його доступом, або додайте нового."
    )
    rows = []
    if developers:
        for dev in developers:
            name, _ = await _format_identity(
                dev["uid"], dev.get("full_name"), dev.get("username")
            )
            rows.append([
                InlineKeyboardButton(
                    text=f"{name} ({dev['uid']})",
                    callback_data=f"dev_team_member_{dev['uid']}",
                )
            ])
    rows.append([InlineKeyboardButton(text="➕ Додати девелопера", callback_data="dev_add_developer")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="developer_menu")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def _build_hr_team_view():
    hrs = await get_all_kerivnyky()
    text = (
        f"👨‍💼 <b>Команда HR</b>\n"
        f"Усього учасників: <b>{len(hrs)}</b>\n"
        "Оберіть HR, щоб керувати доступом, або додайте нового."
    )
    rows = []
    if hrs:
        for hr in hrs:
            name, _ = await _format_identity(
                hr["uid"], hr.get("full_name"), hr.get("username")
            )
            rows.append([
                InlineKeyboardButton(
                    text=f"{name} ({hr['uid']})",
                    callback_data=f"hr_team_member_{hr['uid']}",
                )
            ])
    rows.append([InlineKeyboardButton(text="➕ Додати HR", callback_data="dev_add_hr")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="developer_menu")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_prompt(callback: CallbackQuery, text: str, cancel_callback: str):
    kb = _cancel_keyboard(cancel_callback)
    msg = await _edit_or_answer(callback.message, text, reply_markup=kb)
    return {"chat_id": msg.chat.id, "message_id": msg.message_id}


async def _update_prompt_message(bot, prompt_info: Optional[dict], text: str, cancel_callback: str):
    if not prompt_info:
        return
    kb = _cancel_keyboard(cancel_callback)
    try:
        await bot.edit_message_text(
            chat_id=prompt_info["chat_id"],
            message_id=prompt_info["message_id"],
            text=text,
            reply_markup=kb,
        )
    except Exception:
        pass


async def developer_users_menu(callback: CallbackQuery):
    if not await _ensure_developer(callback):
        return
    await _edit_or_answer(
        callback.message,
        "👥 <b>Користувачі</b>\nОберіть дію:",
        reply_markup=_users_menu_keyboard(),
    )
    await callback.answer()


async def _developer_show_users_list(callback: CallbackQuery, users: list, title: str, mode: str, page: int = 0):
    if not users:
        await _edit_or_answer(callback.message, f"{title}\n\nСписок порожній.", reply_markup=_users_menu_keyboard())
        try:
             await callback.answer()
        except:
             pass
        return

    # Розрахунок пагінації
    items_per_page = 8
    total_count = len(users)
    pages_total = (total_count + items_per_page - 1) // items_per_page
    
    # Корекція поточної сторінки
    curr_page = page
    if curr_page < 0: curr_page = 0
    if curr_page >= pages_total and pages_total > 0: curr_page = pages_total - 1

    start_offset = curr_page * items_per_page
    end_offset = start_offset + items_per_page
    paginated_users = users[start_offset:end_offset]

    lines = [f"{title} (Всього: {total_count}, Стор. {curr_page + 1}/{pages_total})", ""]
    
    for idx, user in enumerate(paginated_users, start=start_offset + 1):
        # Визначаємо роль та посаду
        display_role = await get_display_role(user['user_id'])
        
        if display_role in ["Dev", "Керівник"]:
            job_title = display_role
        else:
            job_title = user.get('role') or "Не вказано"
            
        user_full_name = user.get('full_name', 'Без імені')
        user_username = user.get('username', 'немає')
        current_block = user.get('current_block', 1)
        
        # Витягуємо короткий номер магазину (наприклад, B-19)
        shop_full = user.get('shop', '') or ''
        shop_short = shop_full.split(' ')[0] if shop_full else 'Не вказано'
        
        # Екранування
        e_full_name = html.escape(user_full_name)
        e_username = html.escape(user_username)
        e_job = html.escape(job_title)
        e_shop = html.escape(shop_short)
        
        # Формуємо рядок: день показуємо тільки якщо це не Dev/Керівник
        if display_role in ["Dev", "Керівник"]:
            info_line = f"   @{e_username} | Посада: <b>{e_job}</b> | {e_shop}"
        else:
            info_line = f"   @{e_username} | Посада: <b>{e_job}</b> | {e_shop} | {current_block} день"
            
        lines.append(f"<b>{idx}. {e_full_name}</b> (ID: <code>{user['user_id']}</code>)")
        lines.append(info_line)
        lines.append("───────────────")

    # Формування кнопок
    pagination_buttons = []
    row = []
    if curr_page > 0:
        row.append(InlineKeyboardButton(text="⬅️ Попередня", callback_data=f"dev_users_pag:{mode}:{curr_page - 1}"))
    if curr_page < pages_total - 1:
        row.append(InlineKeyboardButton(text="Наступна ➡️", callback_data=f"dev_users_pag:{mode}:{curr_page + 1}"))
    if row:
        pagination_buttons.append(row)

    pagination_buttons.append([InlineKeyboardButton(text="⬅️ До меню користувачів", callback_data="dev_users_menu")])
    
    await _edit_or_answer(
        callback.message,
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=pagination_buttons),
    )
    try:
        await callback.answer()
    except:
        pass

async def developer_list_users(callback: CallbackQuery, page: int = 0):
    if not await _ensure_developer(callback): return
    users = await get_all_users()
    await _developer_show_users_list(callback, users, "👥 <b>Всі користувачі</b>", "all", page)

async def developer_active_users(callback: CallbackQuery, page: int = 0):
    if not await _ensure_developer(callback): return
    users = await get_all_active_users(days=3)
    await _developer_show_users_list(callback, users, "🚀 <b>Активні стажери</b>", "active", page)

async def developer_inactive_users(callback: CallbackQuery, page: int = 0):
    if not await _ensure_developer(callback): return
    users = await get_all_inactive_users(days=3)
    await _developer_show_users_list(callback, users, "😴 <b>Неактивні стажери</b>", "inactive", page)

async def developer_users_by_city_menu(callback: CallbackQuery):
    if not await _ensure_developer(callback): return
    
    buttons = []
    for city in AVAILABLE_CITIES:
        buttons.append([InlineKeyboardButton(text=city, callback_data=f"dev_users_filter_city:{city}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="dev_users_menu")])
    
    await _edit_or_answer(
        callback.message,
        "🏙️ <b>Оберіть місто для фільтрації:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    try: await callback.answer()
    except: pass

async def developer_users_filter_city(callback: CallbackQuery):
    if not await _ensure_developer(callback): return
    try:
        city = callback.data.split(":")[1]
    except IndexError:
        return
    users = await get_users_by_city(city)
    await _developer_show_users_list(callback, users, f"🏙️ <b>Стажери: {city}</b>", f"city:{city}", 0)

async def developer_users_pagination_handler(callback: CallbackQuery):
    try:
        parts = callback.data.split(":")
        # Formats:
        # dev_users_pag:mode:page
        # dev_users_pag:city:CityName:page
        # dev_users_page:page (legacy)
        
        if len(parts) == 4 and parts[1] == "city":
            city = parts[2]
            page = int(parts[3])
            users = await get_users_by_city(city)
            await _developer_show_users_list(callback, users, f"🏙️ <b>Стажери: {city}</b>", f"city:{city}", page)
            return
        elif len(parts) == 3:
            mode = parts[1]
            page = int(parts[2])
        else:
            mode = "all"
            page = int(parts[1])
            
    except (ValueError, IndexError):
        return

    if mode == "active":
        await developer_active_users(callback, page)
    elif mode == "inactive":
        await developer_inactive_users(callback, page)
    else:
        await developer_list_users(callback, page)


async def developer_request_user_search(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_developer(callback):
        return
    await state.set_state(DeveloperStates.waiting_user_search)
    await _edit_or_answer(
        callback.message,
        "🔍 <b>Пошук користувача</b>\n\n"
        "Введіть один з варіантів:\n"
        "• ID користувача (наприклад, <code>123456</code>)\n"
        "• Username (наприклад, <code>@username</code>)\n"
        "• ПІБ (наприклад, <code>Іванов Іван</code>)\n\n"
        "<i>💡 Пошук не чутливий до регістру</i>",
        reply_markup=_users_menu_keyboard(),
    )
    await callback.answer()


async def developer_process_user_search(message: Message, state: FSMContext):
    query = (message.text or "").strip()
    users = []
    
    if query.startswith("@"):
        user = await get_user_by_username(query)
        if user:
            users.append(user)
    elif query.isdigit():
        user = await get_user_details(int(query))
        if user:
            users.append(user)
    else:
        # Search by full name if it's not a username or ID
        users = await get_users_by_full_name(query)

    if not users:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Новий пошук", callback_data="dev_user_search")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="dev_users_menu")]
        ])
        
        await message.answer(
            "❌ <b>Користувача не знайдено</b>\n\n"
            f"Ваш запит: <code>{query}</code>\n\n"
            "💡 <b>Поради:</b>\n"
            "• Перевірте правильність написання\n"
            "• Спробуйте ввести частину імені\n"
            "• Використайте ID якщо він відомий\n"
            "• Або натисніть /cancel для скасування",
            reply_markup=kb
        )
        return

    if len(users) == 1:
        # If only one user is found, show their profile directly
        user = users[0]
        intern_id = int(user["user_id"])
        report = await get_user_days_report(intern_id)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 Навчальні дні", callback_data=f"dev_days_manage:{intern_id}"),
                InlineKeyboardButton(text="✍️ Змінити", callback_data=f"dev_user_modify:{intern_id}")
            ],
            [
                InlineKeyboardButton(text="❌ Видалити", callback_data=f"dev_user_delete_confirm:{intern_id}"),
                InlineKeyboardButton(text="⬅️ Назад", callback_data="dev_users_menu")
            ]
        ])
        
        await message.answer(report, reply_markup=kb)
    else:
        # If multiple users are found, show a list
        lines = [f"👥 <b>Знайдено {len(users)} користувачів:</b>\n"]
        
        # Показуємо максимум 20 користувачів
        display_users = users[:20]
        for user in display_users:
            full_name = user.get('full_name', 'Без імені')
            user_id = user['user_id']
            username = user.get('username', '')
            
            user_info = f"• <b>{full_name}</b> (ID: <code>{user_id}</code>)"
            if username:
                user_info += f" | @{username}"
            lines.append(user_info)
        
        if len(users) > 20:
            lines.append(f"\n<i>... та ще {len(users) - 20} користувачів</i>")
        
        lines.append("\n💡 <b>Уточніть пошук:</b>")
        lines.append("• Введіть повне ім'я")
        lines.append("• Або використайте ID конкретного користувача")
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Новий пошук", callback_data="dev_user_search")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="dev_users_menu")]
        ])
        
        await message.answer("\n".join(lines), reply_markup=kb)

    await state.clear()


async def developer_request_delete_user(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_developer(callback):
        return
    await state.set_state(DeveloperStates.waiting_delete_user)
    await _edit_or_answer(
        callback.message,
        "❌ Введіть ID користувача, якого потрібно видалити:",
        reply_markup=_users_menu_keyboard(),
    )
    await callback.answer()


async def developer_process_delete_user(message: Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
    except (ValueError, AttributeError):
        await message.answer("❌ ID повинен бути числом. Спробуйте ще раз.")
        return

    user = await get_user_details(user_id)
    if not user:
        await message.answer(f"❌ Користувача з ID {user_id} не знайдено.")
        await state.clear()
        return

    await delete_user(user_id)
    await message.answer(f"✅ Користувача <b>{user.get('full_name', 'Без імені')}</b> (ID: {user_id}) видалено.", reply_markup=_users_menu_keyboard())
    await state.clear()


# ---------- Mentors section ----------

def _managers_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Список керівників", callback_data="dev_managers_list")],
        [InlineKeyboardButton(text="➕ Додати керівника", callback_data="dev_manager_add")],
        [InlineKeyboardButton(text="🗑 Видалити керівника", callback_data="dev_manager_delete")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="developer_menu")]
    ])


async def developer_managers_menu(callback: CallbackQuery):
    if not await _ensure_developer(callback):
        return
    await _edit_or_answer(
        callback.message,
        "🧑‍🏫 <b>Керівники</b>\nОберіть дію:",
        reply_markup=_managers_menu_keyboard(),
    )
    await callback.answer()


async def developer_list_managers(callback: CallbackQuery):
    if not await _ensure_developer(callback):
        return
    managers = await get_all_managers()
    if not managers:
        await _edit_or_answer(
            callback.message,
            "ℹ️ У системі поки немає керівників.",
            reply_markup=_managers_menu_keyboard(),
        )
        await callback.answer()
        return

    lines = ["🧑‍🏫 <b>Список керівників</b>", ""]
    for idx, manager in enumerate(managers, 1):
        lines.append(
            f"{idx}. <b>{manager.get('full_name', 'Без імені')}</b> (uid: {manager.get('uid')})\n"
            f"   @{manager.get('username', 'немає')} · Посада: {manager.get('process', 'Не вказано')}"
        )
        if idx >= 50:
            lines.append("… Показано перших 50 керівників.")
            break
    await _edit_or_answer(
        callback.message,
        "\n".join(lines),
        reply_markup=_managers_menu_keyboard(),
    )
    await callback.answer()


async def developer_request_add_manager(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_developer(callback):
        return
    await state.set_state(DeveloperStates.waiting_add_manager)
    await _edit_or_answer(
        callback.message,
        "➕ Введіть дані керівника у форматі <code>ID;посада</code> (наприклад: <code>123456;Керівник магазину</code>).",
        reply_markup=_managers_menu_keyboard(),
    )
    await callback.answer()


async def developer_process_add_manager(message: Message, state: FSMContext):
    payload = (message.text or "")
    if ";" not in payload:
        await message.answer("❌ Невірний формат. Використайте <code>ID;посада</code>.")
        return
    user_id_part, process_part = payload.split(";", 1)
    try:
        uid = int(user_id_part.strip())
    except ValueError:
        await message.answer("❌ ID повинен бути числом.")
        return
    process = process_part.strip()
    if not process:
        await message.answer("❌ Посада не може бути порожньою.")
        return

    user = await get_user_details(uid)
    if not user:
        await message.answer("❌ Користувача з таким ID не знайдено.")
        await state.clear()
        return
    existing = await get_manager_by_uid(uid)
    if existing:
        await message.answer("⚠️ Користувач вже є керівником.")
        await state.clear()
        return
    await add_manager(uid, process)
    await message.answer(f"✅ Користувача {user.get('full_name', 'Без імені')} призначено керівником ({process}).", reply_markup=_managers_menu_keyboard())
    await state.clear()


async def developer_request_delete_manager(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_developer(callback):
        return
    await state.set_state(DeveloperStates.waiting_delete_manager)
    await _edit_or_answer(
        callback.message,
        "🗑 Введіть ID керівника для видалення:",
        reply_markup=_managers_menu_keyboard(),
    )
    await callback.answer()


async def developer_process_delete_manager(message: Message, state: FSMContext):
    try:
        uid = int(message.text.strip())
    except (ValueError, AttributeError):
        await message.answer("❌ ID повинен бути числом.")
        return

    manager = await get_manager_by_uid(uid)
    if not manager:
        await message.answer("❌ Керівника з таким ID не знайдено.")
        await state.clear()
        return

    await delete_manager_by_uid(uid)
    await message.answer(
        f"✅ Керівник {manager.get('full_name', 'Без імені')} (ID: {uid}) видалений.",
        reply_markup=_managers_menu_keyboard()
    )
    await state.clear()


# ---------- Days section ----------

def _days_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👀 Статус", callback_data="dev_days_status")],
        [InlineKeyboardButton(text="🔓 Відкрити дні", callback_data="dev_days_open")],
        [InlineKeyboardButton(text="🔒 Закрити дні", callback_data="dev_days_close")],
        [InlineKeyboardButton(text="🔄 Скинути прогрес", callback_data="dev_days_reset")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="developer_menu")]
    ])


async def developer_days_menu(callback: CallbackQuery):
    if not await _ensure_developer(callback):
        return
    await _edit_or_answer(
        callback.message,
        "📅 <b>Навчальні дні</b>\nОберіть дію:",
        reply_markup=_days_menu_keyboard(),
    )
    await callback.answer()


async def developer_request_days_status(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_developer(callback):
        return
    await state.set_state(DeveloperStates.waiting_days_status)
    await _edit_or_answer(
        callback.message,
        "👀 Введіть ID стажера для перегляду статусу:",
        reply_markup=_days_menu_keyboard(),
    )
    await callback.answer()


async def developer_process_days_status(message: Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
    except (ValueError, AttributeError):
        await message.answer("❌ ID повинен бути числом.")
        return
    try:
        report = await get_user_days_report(user_id)
    except ValueError as exc:
        await message.answer(f"❌ {exc}")
        await state.clear()
        return
    await _send_in_chunks(message, report, reply_markup=_days_menu_keyboard())
    await state.clear()


async def developer_request_days_action(callback: CallbackQuery, state: FSMContext, action: str):
    if not await _ensure_developer(callback):
        return
    action_map = {
        "open": "🔓 Введіть дані у форматі <code>ID;дні</code> (приклад: <code>123456;3-5</code>) для відкриття.",
        "close": "🔒 Введіть <code>ID;дні</code>, які потрібно закрити (день 1 закрито бути не може).",
        "reset": "🔄 Введіть <code>ID;дні</code>, які потрібно скинути."
    }
    await state.set_state(getattr(DeveloperStates, f"waiting_days_{action}"))
    await _edit_or_answer(callback.message, action_map[action], reply_markup=_days_menu_keyboard())
    await callback.answer()


async def developer_request_days_open(callback: CallbackQuery, state: FSMContext):
    await developer_request_days_action(callback, state, "open")


async def developer_request_days_close(callback: CallbackQuery, state: FSMContext):
    await developer_request_days_action(callback, state, "close")


async def developer_request_days_reset(callback: CallbackQuery, state: FSMContext):
    await developer_request_days_action(callback, state, "reset")


async def _parse_user_days_payload(text: str):
    if ";" not in text:
        raise ValueError("Невірний формат. Використайте <code>ID;дні</code>.")
    user_part, days_part = text.split(";", 1)
    user_id = int(user_part.strip())
    days = parse_day_input(days_part.strip())
    if not days:
        raise ValueError("Невірний формат днів. Приклад: 3 або 3-5.")
    return user_id, days


async def developer_process_days_open(message: Message, state: FSMContext):
    try:
        user_id, days = await _parse_user_days_payload(message.text.strip())
        response = await open_days_for_user(user_id, days)
    except ValueError as exc:
        await message.answer(f"❌ {exc}")
        return
    await message.answer(response, reply_markup=_days_menu_keyboard())
    await state.clear()


async def developer_process_days_close(message: Message, state: FSMContext):
    try:
        user_id, days = await _parse_user_days_payload(message.text.strip())
        response = await close_days_for_user(user_id, days)
    except ValueError as exc:
        await message.answer(f"❌ {exc}")
        return
    await message.answer(response, reply_markup=_days_menu_keyboard())
    await state.clear()


async def developer_process_days_reset(message: Message, state: FSMContext):
    try:
        user_id, days = await _parse_user_days_payload(message.text.strip())
        response = await reset_days_for_user(user_id, days)
    except ValueError as exc:
        await message.answer(f"❌ {exc}")
        return
    await message.answer(response, reply_markup=_days_menu_keyboard())
    await state.clear()


# ---------- Developer management ----------

# ---------- Managers team (unified Dev + HR) ----------

async def developer_manage_managers_menu(callback: CallbackQuery, state: FSMContext, page: int = 0):
    """Об'єднане меню керівників з пагінацією."""
    if not await _ensure_developer(callback):
        return
    text, kb = await _build_managers_team_view(page=page)
    msg = await _edit_or_answer(callback.message, text, reply_markup=kb)
    await _remember_panel(state, "managers_panel", msg or callback.message)
    try:
        await callback.answer()
    except:
        pass

async def developer_managers_pagination_handler(callback: CallbackQuery, state: FSMContext):
    """Обробник пагінації для списку керівників."""
    try:
        page = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        page = 0
    await developer_manage_managers_menu(callback, state, page=page)


async def developer_request_add_manager(callback: CallbackQuery, state: FSMContext):
    """Starts the process of adding a manager by requesting their ID."""
    if not await _ensure_developer(callback):
        return
    await state.set_state(DeveloperStates.waiting_add_manager_id)
    await _edit_or_answer(
        callback.message,
        "👔 Введіть ID користувача, якого потрібно призначити керівником:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Скасувати", callback_data="dev_manage_managers")]
        ])
    )
    await callback.answer()

async def developer_process_add_manager_city(callback: CallbackQuery, state: FSMContext):
    """Processes the city selection and shows the shop selection menu."""
    try:
        city = callback.data.split(":", 1)[1]
    except IndexError:
        return await callback.answer("Помилка даних міста.", show_alert=True)
        
    await state.update_data(manager_city=city, selected_shops=[])
    await state.set_state(DeveloperStates.waiting_add_manager_shops)
    
    kb = await _build_manager_shops_keyboard(city, [])
    await _edit_or_answer(
        callback.message,
        f"Місто: {city}.\nТепер оберіть магазини. Можна обрати до 5.",
        reply_markup=kb
    )
    await callback.answer()

async def developer_process_add_manager_city(callback: CallbackQuery, state: FSMContext):
    """Processes the city selection and shows the shop selection menu."""
    try:
        city = callback.data.split(":", 1)[1]
    except IndexError:
        return await callback.answer("Помилка даних міста.", show_alert=True)
        
    await state.update_data(manager_city=city, selected_shops=[])
    await state.set_state(DeveloperStates.waiting_add_manager_shops)
    
    kb = await _build_manager_shops_keyboard(city, [])
    await _edit_or_answer(
        callback.message,
        f"Місто: {city}.\nТепер оберіть магазини. Можна обрати до 5.",
        reply_markup=kb
    )
    await callback.answer()

async def developer_process_add_manager_city(callback: CallbackQuery, state: FSMContext):
    """Processes the city selection and shows the shop selection menu."""
    try:
        city = callback.data.split(":", 1)[1]
    except IndexError:
        return await callback.answer("Помилка даних міста.", show_alert=True)
        
    await state.update_data(manager_city=city, selected_shops=[])
    await state.set_state(DeveloperStates.waiting_add_manager_shops)
    
    kb = await _build_manager_shops_keyboard(city, [])
    await _edit_or_answer(
        callback.message,
        f"Місто: {city}.\nТепер оберіть магазини. Можна обрати до 5.",
        reply_markup=kb
    )
    await callback.answer()

async def developer_process_add_manager_city(callback: CallbackQuery, state: FSMContext):
    """Processes the city selection and shows the shop selection menu."""
    try:
        city = callback.data.split(":", 1)[1]
    except IndexError:
        return await callback.answer("Помилка даних міста.", show_alert=True)
        
    await state.update_data(manager_city=city, selected_shops=[])
    await state.set_state(DeveloperStates.waiting_add_manager_shops)
    
    kb = await _build_manager_shops_keyboard(city, [])
    await _edit_or_answer(
        callback.message,
        f"Місто: {city}.\nТепер оберіть магазини. Можна обрати до 5.",
        reply_markup=kb
    )
    await callback.answer()

async def developer_process_add_manager_city(callback: CallbackQuery, state: FSMContext):
    """Processes the city selection and shows the shop selection menu."""
    try:
        city = callback.data.split(":", 1)[1]
    except IndexError:
        return await callback.answer("Помилка даних міста.", show_alert=True)
        
    await state.update_data(manager_city=city, selected_shops=[])
    await state.set_state(DeveloperStates.waiting_add_manager_shops)
    
    kb = await _build_manager_shops_keyboard(city, [])
    await _edit_or_answer(
        callback.message,
        f"Місто: {city}.\nТепер оберіть магазини. Можна обрати до 5.",
        reply_markup=kb
    )
    await callback.answer()

async def developer_process_add_manager_city(callback: CallbackQuery, state: FSMContext):
    """Processes the city selection and shows the shop selection menu."""
    try:
        city = callback.data.split(":", 1)[1]
    except IndexError:
        return await callback.answer("Помилка даних міста.", show_alert=True)
        
    await state.update_data(manager_city=city, selected_shops=[])
    await state.set_state(DeveloperStates.waiting_add_manager_shops)
    
    kb = await _build_manager_shops_keyboard(city, [])
    await _edit_or_answer(
        callback.message,
        f"Місто: {city}.\nТепер оберіть магазини. Можна обрати до 5.",
        reply_markup=kb
    )
    await callback.answer()

async def developer_process_add_manager_city(callback: CallbackQuery, state: FSMContext):
    """Processes the city selection and shows the shop selection menu."""
    try:
        city = callback.data.split(":", 1)[1]
    except IndexError:
        return await callback.answer("Помилка даних міста.", show_alert=True)
        
    await state.update_data(manager_city=city, selected_shops=[])
    await state.set_state(DeveloperStates.waiting_add_manager_shops)
    
    kb = await _build_manager_shops_keyboard(city, [])
    await _edit_or_answer(
        callback.message,
        f"Місто: {city}.\nТепер оберіть магазини. Можна обрати до 5.",
        reply_markup=kb
    )
    await callback.answer()

async def developer_process_add_manager_city(callback: CallbackQuery, state: FSMContext):
    """Processes the city selection and shows the shop selection menu."""
    try:
        city = callback.data.split(":", 1)[1]
    except IndexError:
        return await callback.answer("Помилка даних міста.", show_alert=True)
        
    await state.update_data(manager_city=city, selected_shops=[])
    await state.set_state(DeveloperStates.waiting_add_manager_shops)
    
    kb = await _build_manager_shops_keyboard(city, [])
    await _edit_or_answer(
        callback.message,
        f"Місто: {city}.\nТепер оберіть магазини. Можна обрати до 5.",
        reply_markup=kb
    )
    await callback.answer()

async def developer_process_add_manager_city(callback: CallbackQuery, state: FSMContext):
    """Processes the city selection and shows the shop selection menu."""
    try:
        city = callback.data.split(":", 1)[1]
    except IndexError:
        return await callback.answer("Помилка даних міста.", show_alert=True)
        
    await state.update_data(manager_city=city, selected_shops=[])
    await state.set_state(DeveloperStates.waiting_add_manager_shops)
    
    kb = await _build_manager_shops_keyboard(city, [])
    await _edit_or_answer(
        callback.message,
        f"Місто: {city}.\nТепер оберіть магазини. Можна обрати до 5.",
        reply_markup=kb
    )
    await callback.answer()

async def developer_process_add_manager_city(callback: CallbackQuery, state: FSMContext):
    """Processes the city selection and shows the shop selection menu."""
    try:
        city = callback.data.split(":", 1)[1]
    except IndexError:
        return await callback.answer("Помилка даних міста.", show_alert=True)
        
    await state.update_data(manager_city=city, selected_shops=[])
    await state.set_state(DeveloperStates.waiting_add_manager_shops)
    
    kb = await _build_manager_shops_keyboard(city, [])
    await _edit_or_answer(
        callback.message,
        f"Місто: {city}.\nТепер оберіть магазини. Можна обрати до 5.",
        reply_markup=kb
    )
    await callback.answer()

async def developer_process_add_manager_city(callback: CallbackQuery, state: FSMContext):
    """Processes the city selection and shows the shop selection menu."""
    try:
        city = callback.data.split(":", 1)[1]
    except IndexError:
        return await callback.answer("Помилка даних міста.", show_alert=True)
        
    await state.update_data(manager_city=city, selected_shops=[])
    await state.set_state(DeveloperStates.waiting_add_manager_shops)
    
    kb = await _build_manager_shops_keyboard(city, [])
    await _edit_or_answer(
        callback.message,
        f"Місто: {city}.\nТепер оберіть магазини. Можна обрати до 5.",
        reply_markup=kb
    )
    await callback.answer()

async def developer_process_add_manager_city(callback: CallbackQuery, state: FSMContext):
    """Processes the city selection and shows the shop selection menu."""
    try:
        city = callback.data.split(":", 1)[1]
    except IndexError:
        return await callback.answer("Помилка даних міста.", show_alert=True)
        
    await state.update_data(manager_city=city, selected_shops=[])
    await state.set_state(DeveloperStates.waiting_add_manager_shops)
    
    kb = await _build_manager_shops_keyboard(city, [])
    await _edit_or_answer(
        callback.message,
        f"Місто: {city}.\nТепер оберіть магазини. Можна обрати до 5.",
        reply_markup=kb
    )
    await callback.answer()

async def developer_process_add_manager_city(callback: CallbackQuery, state: FSMContext):
    """Processes the city selection and shows the shop selection menu."""
    try:
        city = callback.data.split(":", 1)[1]
    except IndexError:
        return await callback.answer("Помилка даних міста.", show_alert=True)
        
    await state.update_data(manager_city=city, selected_shops=[])
    await state.set_state(DeveloperStates.waiting_add_manager_shops)
    
    kb = await _build_manager_shops_keyboard(city, [])
    await _edit_or_answer(
        callback.message,
        f"Місто: {city}.\nТепер оберіть магазини. Можна обрати до 5.",
        reply_markup=kb
    )
    await callback.answer()

async def developer_process_add_manager_city(callback: CallbackQuery, state: FSMContext):
    """Processes the city selection and shows the shop selection menu."""
    try:
        city = callback.data.split(":", 1)[1]
    except IndexError:
        return await callback.answer("Помилка даних міста.", show_alert=True)
        
    await state.update_data(manager_city=city, selected_shops=[])
    await state.set_state(DeveloperStates.waiting_add_manager_shops)
    
    kb = await _build_manager_shops_keyboard(city, [])
    await _edit_or_answer(
        callback.message,
        f"Місто: {city}.\nТепер оберіть магазини. Можна обрати до 5.",
        reply_markup=kb
    )
    await callback.answer()

async def developer_process_add_manager_city(callback: CallbackQuery, state: FSMContext):
    """Processes the city selection and shows the shop selection menu."""
    try:
        city = callback.data.split(":", 1)[1]
    except IndexError:
        return await callback.answer("Помилка даних міста.", show_alert=True)
        
    await state.update_data(manager_city=city, selected_shops=[])
    await state.set_state(DeveloperStates.waiting_add_manager_shops)
    
    kb = await _build_manager_shops_keyboard(city, [])
    await _edit_or_answer(
        callback.message,
        f"Місто: {city}.\nТепер оберіть магазини. Можна обрати до 5.",
        reply_markup=kb
    )
    await callback.answer()

async def developer_process_add_manager_city(callback: CallbackQuery, state: FSMContext):
    """Processes the city selection and shows the shop selection menu."""
    try:
        city = callback.data.split(":", 1)[1]
    except IndexError:
        return await callback.answer("Помилка даних міста.", show_alert=True)
        
    await state.update_data(manager_city=city, selected_shops=[])
    await state.set_state(DeveloperStates.waiting_add_manager_shops)
    
    kb = await _build_manager_shops_keyboard(city, [])
    await _edit_or_answer(
        callback.message,
        f"Місто: {city}.\nТепер оберіть магазини. Можна обрати до 5.",
        reply_markup=kb
    )
    await callback.answer()

async def developer_process_add_manager_city(callback: CallbackQuery, state: FSMContext):
    """Processes the city selection and shows the shop selection menu."""
    try:
        city = callback.data.split(":", 1)[1]
    except IndexError:
        return await callback.answer("Помилка даних міста.", show_alert=True)
        
    await state.update_data(manager_city=city, selected_shops=[])
    await state.set_state(DeveloperStates.waiting_add_manager_shops)
    
    kb = await _build_manager_shops_keyboard(city, [])
    await _edit_or_answer(
        callback.message,
        f"Місто: {city}.\nТепер оберіть магазини. Можна обрати до 5.",
        reply_markup=kb
    )
    await callback.answer()

async def _build_manager_shops_keyboard(city: str, selected_shops: list) -> InlineKeyboardMarkup:
    """Builds the keyboard for shop multi-selection for a specific city."""
    shops_in_city = AVAILABLE_SHOPS.get(city, [])
    
    buttons = []
    for i in range(0, len(shops_in_city), 2):
        row = []
        shop1 = shops_in_city[i]
        text1 = f"✅ {shop1}" if shop1 in selected_shops else shop1
        row.append(InlineKeyboardButton(text=text1, callback_data=f"dev_mgr_shop_toggle:{i}"))
        
        if i + 1 < len(shops_in_city):
            shop2 = shops_in_city[i+1]
            text2 = f"✅ {shop2}" if shop2 in selected_shops else shop2
            row.append(InlineKeyboardButton(text=text2, callback_data=f"dev_mgr_shop_toggle:{i+1}"))
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton(text="✅ Готово", callback_data="dev_mgr_shop_done")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад до міст", callback_data="dev_add_manager")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def developer_process_add_manager_id(message: Message, state: FSMContext):
    """Processes the manager ID and asks for their Full Name."""
    if not message.text or not message.text.isdigit():
        await message.answer("❌ ID повинен бути числом. Спробуйте ще раз.")
        return
    
    user_id = int(message.text)
    await state.update_data(new_manager_id=user_id, selected_shops=[])
    await state.set_state(DeveloperStates.waiting_add_manager_name)
    
    await message.answer(
        f"ID: {user_id}. Тепер введіть ПІБ керівника:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Скасувати", callback_data="dev_manage_managers")]
        ])
    )

async def developer_process_add_manager_name(message: Message, state: FSMContext):
    """Processes the manager Name and shows the city selection menu."""
    full_name = message.text.strip()
    if len(full_name.split()) < 2:
        await message.answer("Будь ласка, введіть повне ім'я та прізвище (мінімум 2 слова).")
        return

    await state.update_data(new_manager_name=full_name)
    await state.set_state(DeveloperStates.waiting_add_manager_city)
    
    buttons = []
    for city in AVAILABLE_CITIES:
        buttons.append([InlineKeyboardButton(text=city, callback_data=f"dev_mgr_city_select:{city}")])
    buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="dev_manage_managers")])
    
    await message.answer(
        f"Керівник: <b>{full_name}</b>.\nТепер оберіть місто, до якого належать його магазини:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

async def developer_process_shop_selection(callback: CallbackQuery, state: FSMContext):
    """Handles toggling a shop in the selection menu."""
    data = await state.get_data()
    city = data.get("manager_city")
    if not city:
        # Якщо місто не знайдено у стані, це помилка флоу. Повертаємося в головне меню керівників.
        await callback.answer("Помилка: місто не обрано. Поверніться до меню додавання керівника.", show_alert=True)
        await state.clear()
        await developer_manage_managers_menu(callback, state) # Go back to managers menu
        return
        
    try:
        shop_index = int(callback.data.split(":", 1)[1])
        shops_in_city = AVAILABLE_SHOPS.get(city, [])
        shop_name = shops_in_city[shop_index]
    except (IndexError, ValueError):
        return await callback.answer("Помилка даних магазину.", show_alert=True)

    selected_shops = data.get("selected_shops", [])
    
    if shop_name in selected_shops:
        selected_shops.remove(shop_name)
    else:
        if len(selected_shops) >= 5:
            await callback.answer("⚠️ Можна обрати максимум 5 магазинів.", show_alert=True)
            return
        selected_shops.append(shop_name)
        
    await state.update_data(selected_shops=selected_shops)
    
    kb = await _build_manager_shops_keyboard(city, selected_shops)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

async def developer_finish_shop_selection(callback: CallbackQuery, state: FSMContext):
    """Finalizes adding the manager with the selected shops."""
    data = await state.get_data()
    user_id = data.get("new_manager_id")
    selected_shops = data.get("selected_shops", [])
    full_name = data.get("new_manager_name", "Керівник")
    city = data.get("manager_city")
    
    if not user_id:
        await callback.answer("Помилка: ID керівника не знайдено.", show_alert=True)
        return await developer_manage_managers_menu(callback, state)

    # Get username if possible, but rely on provided full_name
    try:
        chat_info = await callback.bot.get_chat(user_id)
        username = chat_info.username
    except Exception:
        username = ""

    await register_user(user_id, username=username, full_name=full_name)
    await add_manager(
        uid=user_id,
        process="Керівник",
        full_name=full_name,
        username=username,
        shops=selected_shops,
        city=city
    )
    
    await state.clear()
    await callback.answer("✅ Керівника успішно додано/оновлено!", show_alert=True)
    await developer_manage_managers_menu(callback, state)


async def developer_remove_manager_menu(callback: CallbackQuery, state: FSMContext):
    """Меню видалення керівника."""
    if not await _ensure_developer(callback):
        return
    
    hrs = await get_all_kerivnyky()
    if not hrs:
        await callback.answer("Немає керівників для видалення.", show_alert=True)
        return
    
    buttons = []
    for hr in hrs:
        name, _ = await _format_identity(hr["uid"], hr.get("full_name"), hr.get("username"))
        buttons.append([InlineKeyboardButton(
            text=f"❌ {name}",
            callback_data=f"mgr_remove:{hr['uid']}"
        )])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="dev_manage_managers")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _edit_or_answer(callback.message, "🗑 Оберіть керівника для видалення:", reply_markup=kb)
    await callback.answer()


async def developer_remove_manager(callback: CallbackQuery, state: FSMContext):
    """Видалення керівника."""
    if not await _ensure_developer(callback):
        return
    
    try:
        user_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Некоректний ID.", show_alert=True)
        return
    
    await delete_manager_by_uid(user_id)
    await callback.answer(f"Керівника {user_id} видалено.", show_alert=True)
    await developer_manage_managers_menu(callback, state)


async def manager_cancel_add(callback: CallbackQuery, state: FSMContext):
    """Скасування додавання керівника."""
    if not await _ensure_developer(callback):
        return
    await state.set_state(None)
    await state.update_data(mgr_prompt=None)
    await developer_manage_managers_menu(callback, state)
    await callback.answer("Додавання скасовано.", show_alert=True)


async def manager_team_back(callback: CallbackQuery, state: FSMContext):
    """Повернення до списку керівників."""
    await developer_manage_managers_menu(callback, state)


async def developer_cancel_add_role(callback: CallbackQuery, state: FSMContext):
    """Cancels the process of adding a new developer."""
    if not await _ensure_developer(callback):
        return
    await state.clear()
    # Повертаємо користувача до меню команди розробників
    await developer_dev_team_menu(callback, state)
    await callback.answer("Додавання скасовано.")


async def developer_manage_hrs_menu(callback: CallbackQuery, state: FSMContext):
    await developer_manage_managers_menu(callback, state)


async def developer_request_add_dev(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_developer(callback):
        return
    await state.set_state(DeveloperStates.waiting_add_developer)
    prompt_info = await _show_prompt(
        callback,
        "👨‍💻 Введіть ID користувача, якому потрібно надати роль Developer:",
        "dev_cancel_add_role",
    )
    await state.update_data(dev_prompt=prompt_info)
    try:
        await callback.answer()
    except TelegramBadRequest as e:
        if "query is too old" not in str(e):
            raise e


async def developer_process_add_dev(message: Message, state: FSMContext):
    data = await state.get_data()
    prompt_info = data.get("dev_prompt")
    text_value = (message.text or "").strip()
    if not text_value.isdigit():
        await _update_prompt_message(
            message.bot,
            prompt_info,
            "⚠️ ID повинен бути числом.\n\n👨‍💻 Введіть ID користувача, якому потрібно надати роль Developer:",
            "dev_cancel_add_role",
        )
        return

    user_id = int(text_value)
    await state.update_data(new_dev_id=user_id)
    await state.set_state(DeveloperStates.waiting_add_developer_name)
    
    await _update_prompt_message(
        message.bot,
        prompt_info,
        f"ID: {user_id}. Тепер введіть ПІБ розробника:",
        "dev_cancel_add_role"
    )

async def developer_process_add_dev_name(message: Message, state: FSMContext):
    full_name = message.text.strip()
    if len(full_name.split()) < 2:
        await message.answer("Будь ласка, введіть повне ім'я та прізвище (мінімум 2 слова).")
        return

    data = await state.get_data()
    user_id = data.get("new_dev_id")
    prompt_info = data.get("dev_prompt")
    panel_info = data.get("dev_panel")

    # Отримуємо username якщо можливо
    try:
        chat_info = await message.bot.get_chat(user_id)
        username = chat_info.username
    except Exception:
        username = ""

    # Реєструємо або оновлюємо користувача в таблиці users
    await register_user(user_id, username=username, full_name=full_name)

    await add_manager(
        uid=user_id,
        process="Developer",
        full_name=full_name,
        username=username,
    )
    await state.set_state(None)
    await state.update_data(dev_prompt=None)
    await _update_prompt_message(
        message.bot,
        prompt_info,
        f"✅ Користувача {full_name} додано до Dev-команди.\n\nВикористайте кнопку нижче, щоб повернутися.",
        "dev_team_back",
    )
    await _refresh_panel_view(message.bot, panel_info, _build_developer_team_view)


async def developer_manage_hrs_menu(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_developer(callback):
        return
    text, kb = await _build_hr_team_view()
    msg = await _edit_or_answer(callback.message, text, reply_markup=kb)
    await _remember_panel(state, "hr_panel", msg or callback.message)
    await callback.answer()


async def developer_request_add_hr(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_developer(callback):
        return
    await state.set_state(DeveloperStates.waiting_add_hr)
    prompt_info = await _show_prompt(
        callback,
        "👨‍💼 Введіть ID користувача, якому потрібно надати роль HR:",
        "hr_cancel_add_role",
    )
    await state.update_data(hr_prompt=prompt_info)
    await callback.answer()


async def developer_process_add_hr(message: Message, state: FSMContext):
    data = await state.get_data()
    prompt_info = data.get("hr_prompt")
    panel_info = data.get("hr_panel")
    text_value = (message.text or "").strip()
    if not text_value.isdigit():
        await _update_prompt_message(
            message.bot,
            prompt_info,
            "⚠️ Введіть, будь ласка, числовий Telegram ID.\n\n"
            "👨‍💼 Введіть ID користувача, якому потрібно надати роль HR:",
            "hr_cancel_add_role",
        )
        return

    user_id = int(text_value)
    user = await get_user_details(user_id)
    if not user:
        await register_user(user_id)
        user = await get_user_details(user_id) or {"username": None, "full_name": None}

    # Use the name from Telegram API or the one already in the DB
    try:
        chat_info = await message.bot.get_chat(user_id)
        full_name = chat_info.full_name
        username = chat_info.username
    except Exception:
        full_name = user.get("full_name", "")
        username = user.get("username", "")

    await add_manager(
        user_id,
        process="Керівник",
        full_name=full_name,
        username=username
    )
    await state.set_state(None)
    await state.update_data(hr_prompt=None)
    await _update_prompt_message(
        message.bot,
        prompt_info,
        f"✅ Користувача {full_name or user_id} додано до HR-команди.\n\nВикористайте кнопку нижче, щоб повернутися.",
        "hr_team_back",
    )
    await _refresh_panel_view(message.bot, panel_info, _build_hr_team_view)


async def developer_cancel_add_role(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_developer(callback, require_main=True):
        return
    await state.set_state(None)
    await state.update_data(dev_prompt=None)
    await developer_dev_team_menu(callback, state)
    await callback.answer("Додавання скасовано.", show_alert=True)


async def hr_cancel_add_role(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_developer(callback):
        return
    await state.set_state(None)
    await state.update_data(hr_prompt=None)
    await developer_manage_hrs_menu(callback, state)
    await callback.answer("Додавання скасовано.", show_alert=True)


async def developer_team_member_handler(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_developer(callback):
        return
    try:
        user_id = int(callback.data.split("_")[-1])
    except (ValueError, IndexError):
        await callback.answer("Некоректний ID.", show_alert=True)
        return
    name, username = await _format_identity(user_id)
    text = (
        f"👨‍💻 <b>{name}</b> (ID: <code>{user_id}</code>)\n"
        f"Username: {username}\n\n"
        "Цей користувач має роль Developer. Що зробити?"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚫 Прибрати з Dev-команди", callback_data=f"dev_remove_{user_id}")],
            [InlineKeyboardButton(text="⬅️ Назад до списку", callback_data="dev_team_back")],
        ]
    )
    await _edit_or_answer(callback.message, text, reply_markup=kb)
    await callback.answer()


async def developer_remove_member(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_developer(callback):
        return
    try:
        user_id = int(callback.data.split("_")[-1])
    except (ValueError, IndexError):
        await callback.answer("Некоректний ID.", show_alert=True)
        return
    await delete_manager_by_uid(user_id)
    text, kb = await _build_developer_team_view()
    msg = await _edit_or_answer(callback.message, f"✅ Користувача {user_id} вилучено з Dev-команди.\n\n{text}", reply_markup=kb)
    await _remember_panel(state, "dev_panel", msg or callback.message)
    await callback.answer("Користувача вилучено.", show_alert=True)


async def developer_team_back(callback: CallbackQuery, state: FSMContext):
    await developer_manage_devs_menu(callback, state)


async def hr_team_member_handler(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_developer(callback):
        return
    try:
        user_id = int(callback.data.split("_")[-1])
    except (ValueError, IndexError):
        await callback.answer("Некоректний ID.", show_alert=True)
        return
    name, username = await _format_identity(user_id)
    text = (
        f"👨‍💼 <b>{name}</b> (ID: <code>{user_id}</code>)\n"
        f"Username: {username}\n\n"
        "Цей користувач має доступ HR. Що зробити?"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚫 Прибрати з HR-команди", callback_data=f"hr_remove_{user_id}")],
            [InlineKeyboardButton(text="⬅️ Назад до списку", callback_data="hr_team_back")],
        ]
    )
    await _edit_or_answer(callback.message, text, reply_markup=kb)
    await callback.answer()


async def hr_remove_member(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_developer(callback):
        return
    try:
        user_id = int(callback.data.split("_")[-1])
    except (ValueError, IndexError):
        await callback.answer("Некоректний ID.", show_alert=True)
        return
    await delete_manager_by_uid(user_id)
    text, kb = await _build_hr_team_view()
    msg = await _edit_or_answer(callback.message, f"✅ Користувача {user_id} вилучено з HR-команди.\n\n{text}", reply_markup=kb)
    await _remember_panel(state, "hr_panel", msg or callback.message)
    await callback.answer("Користувача вилучено.", show_alert=True)


async def hr_team_back(callback: CallbackQuery, state: FSMContext):
    await developer_manage_hrs_menu(callback, state)


# ==================== Materials Editor ====================

def _materials_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="developer_menu")]
    ])


async def developer_materials_menu(callback: CallbackQuery):
    """Головне меню редагування матеріалів — вибір посади."""
    if not await _ensure_developer(callback):
        return
    
    # Використовуємо AVAILABLE_ROLES з constants
    buttons = []
    for i, role in enumerate(AVAILABLE_ROLES):
        # Скорочуємо назву для кнопки
        short_name = role[:25] + "..." if len(role) > 28 else role
        buttons.append([InlineKeyboardButton(
            text=short_name,
            callback_data=f"dev_mat_role|{i}"
        )])
    
    buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="developer_menu")])
    
    await _edit_or_answer(
        callback.message,
        "📝 <b>Редагування навчального матеріалу</b>\n\n"
        "Оберіть посаду для редагування матеріалів:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


async def developer_materials_select_day(callback: CallbackQuery, state: FSMContext):
    """Вибір дня для редагування."""
    if not await _ensure_developer(callback):
        return
    
    try:
        _, role_part = callback.data.split("|", 1)
        role_index = int(role_part)
        if not (0 <= role_index < len(AVAILABLE_ROLES)):
            await callback.answer("Неправильний індекс ролі.", show_alert=True)
            return
        role = AVAILABLE_ROLES[role_index]
    except (ValueError, IndexError):
        await callback.answer("Помилка формату ролі.", show_alert=True)
        return
    
    await state.update_data(edit_role=role, edit_role_index=role_index)
    
    buttons = []
    for day in range(1, DAYS_TOTAL + 1):
        buttons.append([InlineKeyboardButton(
            text=f"📅 День {day}",
            callback_data=f"dev_mat_day|{day}"
        )])
    
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="dev_materials_menu")])
    
    await _edit_or_answer(
        callback.message,
        f"📝 <b>Редагування матеріалів</b>\n\n"
        f"Посада: <b>{role}</b>\n\n"
        f"Оберіть день:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


async def developer_materials_select_type(callback: CallbackQuery, state: FSMContext):
    """Вибір типу контенту (текст/відео)."""
    if not await _ensure_developer(callback):
        return
    
    try:
        _, day_str = callback.data.split("|", 1)
        day = int(day_str)
    except (ValueError, IndexError):
        await callback.answer("Помилка формату.", show_alert=True)
        return
    
    data = await state.get_data()
    role = data.get("edit_role", "")
    role_index = data.get("edit_role_index", 0)
    await state.update_data(edit_day=day)
    
    buttons = [
        [InlineKeyboardButton(text="📄 Текст", callback_data="dev_mat_type|text")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev_mat_role|{role_index}")],
    ]
    
    await _edit_or_answer(
        callback.message,
        f"📝 <b>Редагування матеріалів</b>\n\n"
        f"Посада: <b>{role}</b>\n"
        f"День: <b>{day}</b>\n\n"
        f"Оберіть тип контенту:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


def parse_material_content(content: str) -> list[dict]:
    """
    Parses material content which can be:
    1. A JSON string representing a list of pages (each page is a dict with 'text' and optional 'photo').
    2. A plain text string (old format).
    
    Returns a list of dicts: [{'text': '...', 'photo': '...'}, ...]
    """
    if not content:
        return []
    
    content = content.strip()
    
    # Try parsing as JSON list of dicts (new format)
    if content.startswith('[') and content.endswith(']'):
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                # Validate items are dicts or can be converted
                normalized = []
                for item in parsed:
                    if isinstance(item, dict):
                        normalized.append(item)
                    elif isinstance(item, str):
                        normalized.append({"text": item})
                return normalized
        except json.JSONDecodeError:
            pass # Fallback to plain text handling
            
    # Fallback: Treat as plain text (old format)
    # Use split_text to paginate plain text
    from bot.utils.paginator import split_text
    text_pages = split_text(content)
    return [{"text": p} for p in text_pages]


async def developer_materials_view(callback: CallbackQuery, state: FSMContext):
    """Показ поточного матеріалу з можливістю редагування."""
    if not await _ensure_developer(callback):
        return
    
    try:
        _, content_type = callback.data.split("|", 1)
    except (ValueError, IndexError):
        await callback.answer("Помилка формату.", show_alert=True)
        return
    
    data = await state.get_data()
    role = data.get("edit_role", "")
    day = data.get("edit_day", 1)
    await state.update_data(edit_type=content_type)
    
    # Отримуємо матеріал з БД
    material = await get_material_by_role_day_type(role, day, content_type)
    
    if material:
        current_content = material.get("content", "")
        current_url = material.get("resource_url", "")
        material_id = material.get("id")
        await state.update_data(edit_material_id=material_id)
        
        if content_type == "text":
            parsed = parse_material_content(current_content)
            if parsed:
                preview_text = parsed[0].get("text", "")[:500]
                if len(parsed) > 1:
                    preview_text += f"\n\n... (ще сторінок: {len(parsed)-1})"
                elif parsed[0].get("photo"):
                    preview_text += "\n\n[Містить фото]"
            else:
                preview_text = "(порожньо)"

            text = (
                f"📝 <b>Текстовий матеріал</b>\n\n"
                f"Посада: <b>{role}</b>\n"
                f"День: <b>{day}</b>\n\n"
                f"<b>Поточний контент:</b>\n"
                f"<code>{preview_text}</code>\n\n"
                f"Натисніть «Редагувати», щоб змінити текст."
            )
        else:
            preview = current_url if current_url else "(не встановлено)"
            text = (
                f"🎥 <b>Відео матеріал</b>\n\n"
                f"Посада: <b>{role}</b>\n"
                f"День: <b>{day}</b>\n\n"
                f"<b>Поточне посилання:</b>\n"
                f"<code>{preview}</code>\n\n"
                f"Натисніть «Редагувати», щоб змінити посилання."
            )
    else:
        await state.update_data(edit_material_id=None)
        text = (
            f"📝 <b>Матеріал не знайдено</b>\n\n"
            f"Посада: <b>{role}</b>\n"
            f"День: <b>{day}</b>\n"
            f"Тип: <b>{content_type}</b>\n\n"
            f"Натисніть «Редагувати», щоб створити новий матеріал."
        )
    
    buttons = []
        
    buttons.append([InlineKeyboardButton(text="➕ Додати навчання", callback_data=f"dev_mat_edit|{content_type}")])
    buttons.append([InlineKeyboardButton(text="🔍 Повний перегляд", callback_data=f"dev_mat_full_view|{content_type}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev_mat_day|{day}")])
    
    await _edit_or_answer(
        callback.message,
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()

async def developer_material_fix_start(callback: CallbackQuery, state: FSMContext):
    """Starts the process of fixing a specific page of material."""
    if not await _ensure_developer(callback): return
    
    try:
        _, mid_str, day_str, page_str = callback.data.split(":")
        material_id = int(mid_str)
        day = int(day_str)
        page = int(page_str)
    except (ValueError, IndexError):
        await callback.answer("Помилка даних.")
        return

    material = await get_material_by_id(material_id)
    if not material:
        await callback.answer("Матеріал не знайдено.")
        return
        
    content_type = material.get("content_type", "text")
    if content_type != "text" and content_type != "photo_files":
        await callback.answer("Виправлення поки доступне тільки для тексту та фото.", show_alert=True)
        return

    if content_type == "photo_files":
        try:
            file_ids = json.loads(material.get("content", "[]"))
            pages = [{"photo": fid} for fid in file_ids]
        except:
            pages = []
        current_text = ""
        prompt_text = "Надішліть нове фото для заміни поточного."
    else:
        pages = parse_material_content(material.get("content", ""))
        current_page_data = pages[page]
        current_text = current_page_data.get("text", "")
        prompt_text = "Надішліть виправлений текст для цієї сторінки.\nЯкщо сторінка містить фото, ви можете надіслати нове фото з підписом для заміни, або просто текст, щоб залишити старе фото."
    
    if not (0 <= page < len(pages)):
        await callback.answer("Сторінка не знайдена.")
        return
        
    await state.update_data(
        fix_material_id=material_id,
        fix_day=day,
        fix_page=page,
        fix_full_content=pages,
        fix_content_type=content_type
    )
    await state.set_state(DeveloperStates.waiting_fix_page)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ Скасувати", callback_data=f"dev_pag:{material_id}:{day}:{page}:{content_type}")
    ]])
    
    # 1. Прибираємо кнопки з поточного повідомлення (перегляду), щоб не клікали під час редагування
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except:
        pass

    # 2. Надсилаємо інструкцію окремим повідомленням
    instruction_text = (
        f"🛠 <b>Виправлення сторінки {page + 1}</b>\n\n"
        f"Поточний текст:\n<pre>{current_text}</pre>\n\n"
        f"{prompt_text}"
    )
    
    await callback.message.answer(instruction_text, reply_markup=kb)
    await callback.answer()

async def developer_process_fix_page(message: Message, state: FSMContext):
    """Processes the fixed content for a page."""
    data = await state.get_data()
    material_id = data.get("fix_material_id")
    page = data.get("fix_page")
    pages = data.get("fix_full_content")
    day = data.get("fix_day")
    ctype = data.get("fix_content_type")
    
    if not pages or page is None:
        await message.answer("Помилка стану.")
        await state.clear()
        return
    
    if ctype == "photo_files":
        if not message.photo:
            await message.answer("Будь ласка, надішліть фото для заміни.")
            return
        
        if 0 <= page < len(pages):
            pages[page]["photo"] = message.photo[-1].file_id
            
        # For photo_files, content is just list of IDs
        import json
        file_ids = [p["photo"] for p in pages if p.get("photo")]
        new_content_json = json.dumps(file_ids)
        
        await update_material_content(material_id, new_content_json)
        await message.answer(f"✅ Фото {page + 1} оновлено!")
        
    else:
        # Text content logic
        input_text = message.caption if message.caption is not None else message.text
        
        if 0 <= page < len(pages):
            if input_text is not None:
                 pages[page]["text"] = input_text
            if message.photo:
                 pages[page]["photo"] = message.photo[-1].file_id
        
        import json
        new_content_json = json.dumps(pages, ensure_ascii=False)
        await update_material_content(material_id, new_content_json)
        await message.answer(f"✅ Сторінку {page + 1} оновлено!")
    
    # Render view
    kb = _get_dev_pagination_keyboard(page, len(pages), material_id, day, ctype)
    
    page_data = pages[page]
    text_display = page_data.get("text", "")
    photo_display = page_data.get("photo")
    
    if photo_display:
        if len(text_display or "") <= 1024:
            await message.answer_photo(photo_display, caption=text_display, reply_markup=kb)
        else:
            # Long text: send photo then text
            await message.answer_photo(photo_display)
            await message.answer(text_display, reply_markup=kb)
    else:
        await message.answer(text_display, reply_markup=kb)
        
    await state.clear()


def _get_dev_pagination_keyboard(current_page, total_pages, material_id, day, content_type):
    buttons = []
    
    # Navigation row (arrows)
    nav_row = []
    if current_page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"dev_pag:{material_id}:{day}:{current_page-1}:{content_type}"))
    
    if total_pages > 1:
        nav_row.append(InlineKeyboardButton(text=f"{current_page+1}/{total_pages}", callback_data="noop"))
    
    if current_page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"dev_pag:{material_id}:{day}:{current_page+1}:{content_type}"))
    
    if nav_row:
        buttons.append(nav_row)
    
    # "Fix" button on every page
    buttons.append([InlineKeyboardButton(text="🛠 Виправити", callback_data=f"dev_mat_fix:{material_id}:{day}:{current_page}")])

    # Action buttons: on the last page OR if there is only 1 page
    if current_page == total_pages - 1:
        buttons.append([InlineKeyboardButton(text="➕ Додати навчання", callback_data=f"dev_mat_edit|{content_type}")])
        buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev_mat_type|{content_type}")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def developer_pagination_handler(callback: CallbackQuery):
    try:
        _, mid_str, day_str, page_str, ctype = callback.data.split(":")
        material_id = int(mid_str)
        day = int(day_str)
        page = int(page_str)
    except (ValueError, IndexError):
        await callback.answer("Помилка навігації.")
        return

    material = await get_material_by_id(material_id)
    if not material:
        await callback.answer("Матеріал не знайдено.")
        return

    if ctype == "text":
        pages = parse_material_content(material.get("content", ""))
    elif ctype == "video":
        pages = [{"text": material.get("resource_url", "")}]
    elif ctype == "photo_files":
        try:
            file_ids = json.loads(material.get("content", "[]"))
            pages = [{"photo": fid, "text": f"Фото {i+1}"} for i, fid in enumerate(file_ids)]
        except json.JSONDecodeError:
            pages = []
    else:
        # Fallback for other types
        from bot.utils.paginator import split_text
        pages = [{"text": p} for p in split_text(material.get("content", ""))]

    if 0 <= page < len(pages):
        kb = _get_dev_pagination_keyboard(page, len(pages), material_id, day, ctype)
        
        page_data = pages[page]
        text = page_data.get("text", "")
        photo = page_data.get("photo")
        
        is_photo_message = bool(callback.message.photo)
        is_text_message = bool(callback.message.text)
        
        if photo:
            if is_photo_message:
                 media = InputMediaPhoto(media=photo, caption=text)
                 await callback.message.edit_media(media=media, reply_markup=kb)
            else:
                 await callback.message.delete()
                 await callback.message.answer_photo(photo, caption=text, reply_markup=kb)
        else:
            if is_text_message:
                 if callback.message.text != text:
                     await callback.message.edit_text(text, reply_markup=kb)
                 else:
                     await callback.message.edit_reply_markup(reply_markup=kb)
            else:
                 await callback.message.delete()
                 await callback.message.answer(text, reply_markup=kb)
    
    await callback.answer()

async def developer_materials_full_view(callback: CallbackQuery, state: FSMContext):
    """Надсилає повний текст матеріалу розробнику з пагінацією."""
    if not await _ensure_developer(callback):
        return

    try:
        _, content_type = callback.data.split("|", 1)
    except (ValueError, IndexError):
        await callback.answer("Помилка формату.", show_alert=True)
        return

    data = await state.get_data()
    role = data.get("edit_role", "")
    day = data.get("edit_day", 1)

    material = await get_material_by_role_day_type(role, day, content_type)

    if material:
        if content_type == "text":
            pages = parse_material_content(material.get("content", ""))
        elif content_type == "video": 
            pages = [{"text": material.get("resource_url", "(Не встановлено)")}]
        elif content_type == "photo_files":
            try:
                file_ids = json.loads(material.get("content", "[]"))
                pages = [{"photo": fid, "text": f"Фото {i+1}"} for i, fid in enumerate(file_ids)]
            except json.JSONDecodeError:
                pages = []
        else:
            from bot.utils.paginator import split_text
            pages = [{"text": p} for p in split_text(material.get("content", ""))]
        material_id = material.get("id")
    else:
        pages = [{"text": "(Матеріал ще не створено)"}]
        material_id = 0
    
    if not pages:
        pages = [{"text": "(Матеріал порожній)"}]
    
    # Show page 0
    kb = _get_dev_pagination_keyboard(0, len(pages), material_id, day, content_type)
    
    # Always delete the old message (which might be a menu) and send a new message
    try:
        await callback.message.delete()
    except Exception:
        pass 

    page_0 = pages[0]
    text = page_0.get("text", "")
    photo = page_0.get("photo")
    
    if photo:
        await callback.message.answer_photo(photo, caption=text, reply_markup=kb)
    else:
        await callback.message.answer(text, reply_markup=kb)

    await callback.answer()




async def developer_materials_edit_start(callback: CallbackQuery, state: FSMContext):
    """Початок редагування — запит нового контенту."""
    if not await _ensure_developer(callback):
        return
    
    try:
        _, content_type = callback.data.split("|", 1)
    except (ValueError, IndexError):
        await callback.answer("Помилка формату.", show_alert=True)
        return
    
    data = await state.get_data()
    role = data.get("edit_role", "")
    day = data.get("edit_day", 1)
    
    if content_type == "text":
        prompt = (
            f"✏️ <b>Редагування тексту</b>\n\n"
            f"Посада: <b>{role}</b>\n"
            f"День: <b>{day}</b>\n\n"
            f"Надішліть новий текстовий контент для цього матеріалу. Можна відправити кількома повідомленнями. Коли закінчите, напишіть <b>Готово</b>."
        )
        await state.set_state(DeveloperStates.waiting_material_parts)
        await state.update_data(material_parts=[])
    else:
        prompt = (
            f"🎥 <b>Редагування відео</b>\n\n"
            f"Посада: <b>{role}</b>\n"
            f"День: <b>{day}</b>\n\n"
            f"Надішліть нове посилання на відео (YouTube, Vimeo тощо):"
        )
        await state.set_state(DeveloperStates.waiting_material_video)
    
    buttons = [
        [InlineKeyboardButton(text="❌ Скасувати", callback_data=f"dev_mat_type|{content_type}")],
    ]
    
    await _edit_or_answer(
        callback.message,
        prompt,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


async def developer_process_material_parts(message: Message, state: FSMContext):
    """Collects multiple messages for material content until 'Готово' is received."""
    text = (message.text or message.caption or "").strip()
    data = await state.get_data()
    material_parts = data.get("material_parts", [])
    confirmation_msg_id = data.get("text_confirmation_msg_id")

    if text.lower() == 'готово':
        if not material_parts:
            await message.answer("❌ Ви нічого не надіслали. Ввеведіть контент або скасуйте редагування.")
            return

        if confirmation_msg_id:
            try:
                await message.bot.delete_message(chat_id=message.chat.id, message_id=confirmation_msg_id)
            except Exception:
                pass
            
        # Serialize to JSON for new format
        import json
        full_content = json.dumps(material_parts, ensure_ascii=False)
        await _finalize_material_update(message, state, full_content)
    else:
        # Store as object with text and optional photo
        page = {"text": text}
        if message.photo:
            page["photo"] = message.photo[-1].file_id
            
        material_parts.append(page)
        await state.update_data(material_parts=material_parts)

        new_text = f"✅ Отримано частин: {len(material_parts)}. Надішліть наступну частину (текст/фото) або напишіть 'Готово', щоб завершити."

        if confirmation_msg_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=confirmation_msg_id,
                    text=new_text,
                )
            except TelegramBadRequest as e:
                if "message is not modified" not in str(e):
                    sent_msg = await message.answer(new_text)
                    await state.update_data(text_confirmation_msg_id=sent_msg.message_id)
        else:
            sent_msg = await message.answer(new_text)
            await state.update_data(text_confirmation_msg_id=sent_msg.message_id)


async def _finalize_material_update(message: Message, state: FSMContext, new_content: str):
    """Обробка нового текстового контенту і збереження."""
    if not new_content:
        await message.answer("❌ Текст не може бути порожнім.")
        return
    
    data = await state.get_data()
    material_id = data.get("edit_material_id") # Get the original material ID

    # Зберігаємо новий контент у стейті для подальшого збереження
    await state.update_data(
        pending_content=new_content,
        pending_content_type="text",
        pending_material_id=material_id # Pass it to the save function
    )
    
    # Одразу зберігаємо матеріал
    success, role, content_type, day = await _save_pending_material(state)
    
    if success:
        await message.answer(
            f"✅ <b>Матеріал оновлено!</b>\n\n"
            f"Посада: {role}\n"
            f"День: {day}\n"
            f"Тип: {content_type}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ До Dev-панелі", callback_data="developer_menu")]
            ])
        )
    else:
        await message.answer(
            "❌ Помилка збереження матеріалу.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ До Dev-панелі", callback_data="developer_menu")]
            ])
        )
    
    await state.clear()


async def developer_process_material_video(message: Message, state: FSMContext):
    """Обробка нового посилання на відео і збереження."""
    new_url = message.text.strip()
    if not new_url:
        await message.answer("❌ Посилання не може бути порожнім.")
        return

    data = await state.get_data()
    material_id = data.get("edit_material_id")
    await state.update_data(
        pending_content=new_url,
        pending_content_type="video",
        pending_material_id=material_id
    )
    
    success, role, content_type, day = await _save_pending_material(state)
    
    if success:
        await message.answer(
            f"✅ <b>Матеріал оновлено!</b>\n\nПосада: {role}\nДень: {day}\nТип: {content_type}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ До Dev-панелі", callback_data="developer_menu")]])
        )
    else:
        await message.answer("❌ Помилка збереження матеріалу.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ До Dev-панелі", callback_data="developer_menu")]]))
    
    await state.clear()


async def _finalize_video_update(message: Message, state: FSMContext, video_file_ids: list[str]):
    """Обробка завантажених відеофайлів і збереження."""
    if not video_file_ids:
        await message.answer("❌ Немає відеофайлів для збереження.")
        return

    data = await state.get_data()
    material_id = data.get("edit_video_material_id")
    await state.update_data(
        pending_content=json.dumps(video_file_ids),
        pending_content_type="video_files",
        pending_material_id=material_id
    )

    success, role, content_type, day = await _save_pending_material(state)
    
    if success:
        await message.answer(
            f"✅ <b>Матеріал оновлено!</b>\n\nПосада: {role}\nДень: {day}\nТип: {content_type}\nЗавантажено файлів: {len(video_file_ids)}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ До Dev-панелі", callback_data="developer_menu")]])
        )
    else:
        await message.answer("❌ Помилка збереження матеріалу.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ До Dev-панелі", callback_data="developer_menu")]]))
    
    await state.clear()


# ==================== Tests Editor ====================

async def developer_tests_menu(callback: CallbackQuery):
    """Головне меню редагування тестів — вибір посади."""
    if not await _ensure_developer(callback):
        return
    
    buttons = []
    for i, role in enumerate(AVAILABLE_ROLES):
        short_name = role[:25] + "..." if len(role) > 28 else role
        buttons.append([InlineKeyboardButton(
            text=short_name,
            callback_data=f"dev_test_role|{i}"
        )])
    
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="developer_menu")])
    
    await _edit_or_answer(
        callback.message,
        "📝 <b>Редагування тестів</b>\n\n"
        "Оберіть посаду для редагування тестів:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


async def developer_tests_select_day(callback: CallbackQuery, state: FSMContext):
    """Вибір дня для тесту."""
    if not await _ensure_developer(callback):
        return
    
    try:
        _, role_part = callback.data.split("|", 1)
        role_index = int(role_part)
        role = AVAILABLE_ROLES[role_index]
    except (ValueError, IndexError):
        await callback.answer("Помилка ролі.", show_alert=True)
        return
    
    await state.update_data(test_role=role, test_role_index=role_index)
    
    buttons = []
    for day in range(1, DAYS_TOTAL + 1):
        buttons.append([InlineKeyboardButton(
            text=f"📅 День {day}",
            callback_data=f"dev_test_day|{day}"
        )])
    
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="dev_tests_menu")])
    
    await _edit_or_answer(
        callback.message,
        f"📝 <b>Редагування тестів</b>\n\n"
        f"Посада: <b>{role}</b>\n\n"
        f"Оберіть день:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


async def developer_videos_select_day(callback: CallbackQuery, state: FSMContext):
    """Вибір дня для редагування відео."""
    if not await _ensure_developer(callback):
        return
    
    try:
        _, role_part = callback.data.split("|", 1)
        role_index = int(role_part)
        if not (0 <= role_index < len(AVAILABLE_ROLES)):
            await callback.answer("Неправильний індекс ролі.", show_alert=True)
            return
        role = AVAILABLE_ROLES[role_index]
    except (ValueError, IndexError):
        await callback.answer("Помилка формату ролі.", show_alert=True)
        return
    
    await state.update_data(edit_video_role=role, edit_video_role_index=role_index)
    
    buttons = []
    for day in range(1, DAYS_TOTAL + 1):
        buttons.append([InlineKeyboardButton(
            text=f"📅 День {day}",
            callback_data=f"dev_video_day|{day}"
        )])
    
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="dev_videos_menu")])
    
    await _edit_or_answer(
        callback.message,
        f"🎥 <b>Редагування відео матеріалів</b>\n\n"
        f"Посада: <b>{role}</b>\n\n"
        f"Оберіть день:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


async def developer_tests_view(callback: CallbackQuery, state: FSMContext, day: Optional[int] = None, role_index: Optional[int] = None):
    """Перегляд поточного тесту."""
    if not await _ensure_developer(callback):
        return
    
    data = await state.get_data()
    
    try:
        if day is None or role_index is None:
            parts = callback.data.split("|")
            if len(parts) == 3: # dev_test_day|{day}|{role_index}
                day = int(parts[1])
                role_index = int(parts[2])
            else: # old format: dev_test_day|{day}
                day = int(parts[1])
                role_index = data.get("test_role_index", 0) # Fallback to stored role index
        
        role = AVAILABLE_ROLES[role_index]
    except (ValueError, IndexError, TypeError):
        await callback.answer("Помилка дня або ролі.", show_alert=True)
        return
    
    # role is already determined above from AVAILABLE_ROLES[role_index]
    # update state with current day/role if needed, though role is derived
    await state.update_data(test_day=day, test_role=role, test_role_index=role_index)
    
    test_material = await get_test_by_role_and_day(role, day)
    
    display_text = "Тест ще не створено."
    is_enabled = True # Default enabled
    
    if test_material:
        is_enabled = bool(test_material.get("is_enabled", 1))
        if test_material.get("content"):
            try:
                current_questions = json.loads(test_material["content"])
                formatted = format_test_display(current_questions)
                display_text = formatted if formatted else "Тест порожній."
            except json.JSONDecodeError:
                display_text = "⚠️ Помилка формату даних тесту."
    
    status_icon = "✅" if is_enabled else "zzz"
    status_text_display = "АКТИВНИЙ" if is_enabled else "ВИМКНЕНИЙ (не враховується)"
    
    text = (
        f"📝 <b>Тест: {role} — День {day}</b>\n"
        f"Статус: {status_icon} <b>{status_text_display}</b>\n\n"
        f"{display_text}\n\n"
        f"Натисніть «Редагувати», щоб змінити або створити тест."
    )
    
    toggle_btn_text = "🔴 Вимкнути тест" if is_enabled else "🟢 Увімкнути тест"
    toggle_action = "disable" if is_enabled else "enable"
    
    buttons = [
        [InlineKeyboardButton(text="✏️ Редагувати", callback_data="dev_test_edit")],
        [InlineKeyboardButton(text=toggle_btn_text, callback_data=f"dev_test_toggle:{toggle_action}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev_test_role|{role_index}")]
    ]
    
    await _edit_or_answer(
        callback.message,
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()

async def developer_test_toggle(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_developer(callback): return
    
    try:
        action = callback.data.split(":")[1]
        is_enabled = (action == "enable")
    except IndexError:
        return
    
    data = await state.get_data()
    role = data.get("test_role")
    day = data.get("test_day")
    role_index = data.get("test_role_index")
    
    if not role or day is None:
        await callback.answer("Помилка стану. Будь ласка, почніть спочатку.", show_alert=True)
        return

    # Якщо тесту ще немає, створимо порожній, щоб можна було змінити статус
    test_material = await get_test_by_role_and_day(role, day)
    if not test_material:
        await add_or_update_material(
            role=role, day=day, content_type="test", 
            title="Тест", content="[]", resource_url=None
        )

    await toggle_test_status(role, day, is_enabled)
    
    status_msg = "Тест увімкнено! Тепер він обов'язковий." if is_enabled else "Тест вимкнено! Студенти зможуть завершити день без нього."
    await callback.answer(status_msg, show_alert=True)
    
    # Refresh view without modifying callback.data
    await developer_tests_view(callback, state, day=day, role_index=role_index)

async def developer_videos_view(callback: CallbackQuery, state: FSMContext):
    """Показ поточного відео матеріалу з можливістю редагування."""
    if not await _ensure_developer(callback):
        return
    
    try:
        _, day_str = callback.data.split("|", 1)
        day = int(day_str)
    except (ValueError, IndexError):
        await callback.answer("Помилка формату.", show_alert=True)
        return
    
    data = await state.get_data()
    role = data.get("edit_video_role", "")
    await state.update_data(edit_video_day=day)
    
    # Отримуємо матеріал з БД, використовуючи новий тип для завантажених відео
    video_material = await get_material_by_role_day_type(role, day, "video_files")
    
    current_file_ids = []
    video_material_id = None
    if video_material and video_material.get("content"):
        try:
            current_file_ids = json.loads(video_material["content"])
            video_material_id = video_material.get("id")
        except json.JSONDecodeError:
            pass # Will be treated as no content
    
    await state.update_data(edit_video_material_id=video_material_id)
    
    if current_file_ids:
        preview = f"Завантажено відеофайлів: {len(current_file_ids)}"
        text = (
            f"🎥 <b>Відео матеріал</b>\n\n"
            f"Посада: <b>{role}</b>\n"
            f"День: <b>{day}</b>\n\n"
            f"<b>Поточний контент:</b>\n"
            f"{preview}\n\n"
            f"Натисніть «Редагувати», щоб змінити відеофайли."
        )
    else:
        text = (
            f"🎥 <b>Відео матеріал не знайдено</b>\n\n"
            f"Посада: <b>{role}</b>\n"
            f"День: <b>{day}</b>\n\n"
            f"Натисніть «Редагувати», щоб завантажити новий відео матеріал."
        )
    
    buttons = [
        [InlineKeyboardButton(text="✏️ Редагувати", callback_data="dev_video_edit")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev_video_role|{data.get('edit_video_role_index')}")],
    ]
    
    await _edit_or_answer(
        callback.message,
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


async def developer_tests_edit_start(callback: CallbackQuery, state: FSMContext):
    """Початок редагування тесту."""
    if not await _ensure_developer(callback):
        return
        
    data = await state.get_data()
    role = data.get("test_role", "")
    day = data.get("test_day", 1)
    
    template = (
        "1. Питання\n"
        "а. Варіант 1\n"
        "б. Варіант 2 (х)\n"
        "в. Варіант 3\n\n"
        "2. Наступне питання\n"
        "а. Варіант А (х)\n"
        "б. Варіант Б"
    )
    
    text = (
        f"✏️ <b>Редагування тесту: {role} — День {day}</b>\n\n"
        f"Надішліть новий тест у наступному форматі (можна копіювати):\n\n"
        f"<code>{template}</code>\n\n"
        f"⚠️ <b>Важливо:</b>\n"
        f"— Правильну відповідь позначайте як <b>(х)</b> або <b>(x)</b>\n"
        f"— Кожне питання має мати мінімум 2 варіанти."
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Скасувати", callback_data=f"dev_test_day|{day}")]
    ])
    
    await _edit_or_answer(callback.message, text, reply_markup=kb)
    await state.set_state(DeveloperStates.waiting_test_input)
    await callback.answer()


async def developer_video_edit_start(callback: CallbackQuery, state: FSMContext):
    """Початок редагування відео — запит нових відеофайлів."""
    if not await _ensure_developer(callback):
        return
    
    data = await state.get_data()
    role = data.get("edit_video_role", "")
    day = data.get("edit_video_day", 1)
    
    prompt = (
        f"🎥 <b>Завантаження відео матеріалів</b>\n\n"
        f"Посада: <b>{role}</b>\n"
        f"День: <b>{day}</b>\n\n"
        f"Надішліть один або кілька відеофайлів. Коли закінчите, будь ласка, напишіть <b>Готово</b>.\n"
        f"(Максимальний розмір відео файлу - 50МБ, тривалість до 1 хвилини)"
    )
    
    buttons = [
        [InlineKeyboardButton(text="❌ Скасувати", callback_data=f"dev_video_day|{day}")],
    ]
    
    await _edit_or_answer(
        callback.message,
        prompt,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await state.set_state(DeveloperStates.waiting_video_uploads)
    await state.update_data(video_file_ids=[])
    await callback.answer()


async def developer_tests_process_input(message: Message, state: FSMContext):
    """Обробка введеного тексту тесту."""
    text_input = message.text
    
    questions, errors = parse_test_input(text_input)
    
    if errors:
        error_msg = "\n".join([f"• {e}" for e in errors])
        await message.answer(
            f"❌ <b>Знайдено помилки у форматі:</b>\n\n{error_msg}\n\n"
            "Виправте помилки та надішліть текст знову, або натисніть /cancel для скасування."
        )
        return
        
    if not questions:
        await message.answer("❌ Не вдалося розпізнати жодного питання. Перевірте формат.")
        return
    
    data = await state.get_data()
    role = data.get("test_role", "")
    day = data.get("test_day", 1)
    
    # Save to DB
    json_content = json.dumps(questions, ensure_ascii=False)
    
    await add_or_update_material(
        role=role,
        day=day,
        content_type="test",
        title=f"Тест: {role} — День {day}",
        content=json_content,
        resource_url=None,
        order_index=999 # Tests usually go last
    )
    
    await message.answer(
        f"✅ <b>Тест успішно збережено!</b>\n"
        f"Розпізнано питань: {len(questions)}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ До перегляду тесту", callback_data=f"dev_test_day|{day}")]
        ])
    )
    await state.clear()


async def developer_process_video_uploads(message: Message, state: FSMContext):
    """Collects multiple video messages for video content until 'Готово' is received."""
    data = await state.get_data()
    video_file_ids = data.get("video_file_ids", [])
    confirmation_msg_id = data.get("video_confirmation_msg_id")

    if message.video:
        file_id = message.video.file_id
        video_file_ids.append(file_id)
        await state.update_data(video_file_ids=video_file_ids)

        new_text = f"✅ Отримано {len(video_file_ids)} відео. Надішліть наступне відео або напишіть 'Готово', щоб завершити."

        if confirmation_msg_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=confirmation_msg_id,
                    text=new_text,
                )
            except TelegramBadRequest as e:
                if "message is not modified" not in str(e):
                    sent_msg = await message.answer(new_text)
                    await state.update_data(video_confirmation_msg_id=sent_msg.message_id)
        else:
            sent_msg = await message.answer(new_text)
            await state.update_data(video_confirmation_msg_id=sent_msg.message_id)

    elif message.text and message.text.lower() == 'готово':
        if not video_file_ids:
            await message.answer("❌ Ви не надіслали жодного відео. Надішліть відео або скасуйте редагування.")
            return
            
        if confirmation_msg_id:
            try:
                await message.bot.delete_message(chat_id=message.chat.id, message_id=confirmation_msg_id)
            except Exception:
                pass

        await _finalize_video_update(message, state, video_file_ids)
    else:
        await message.answer("Будь ласка, надішліть відеофайл або напишіть 'Готово' для завершення.")


async def developer_videos_menu(callback: CallbackQuery):
    """Головне меню редагування відео матеріалів — вибір посади."""
    if not await _ensure_developer(callback):
        return
    
    buttons = []
    for i, role in enumerate(AVAILABLE_ROLES):
        short_name = role[:25] + "..." if len(role) > 28 else role
        buttons.append([InlineKeyboardButton(
            text=short_name,
            callback_data=f"dev_video_role|{i}"
        )])
    
    buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="developer_menu")])
    
    await _edit_or_answer(
        callback.message,
        "🎥 <b>Редагування відео матеріалів</b>\n\n"
        "Оберіть посаду для редагування відео:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


async def developer_photos_menu(callback: CallbackQuery):
    """Головне меню редагування фото матеріалів — вибір посади."""
    if not await _ensure_developer(callback):
        return
    
    buttons = []
    for i, role in enumerate(AVAILABLE_ROLES):
        short_name = role[:25] + "..." if len(role) > 28 else role
        buttons.append([InlineKeyboardButton(
            text=short_name,
            callback_data=f"dev_photo_role|{i}"
        )])
    
    buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="developer_menu")])
    
    await _edit_or_answer(
        callback.message,
        "🖼 <b>Редагування фото матеріалів</b>\n\n"
        "Оберіть посаду для редагування фото:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()

async def developer_photos_select_day(callback: CallbackQuery, state: FSMContext):
    """Вибір дня для редагування фото."""
    if not await _ensure_developer(callback):
        return
    
    try:
        _, role_part = callback.data.split("|", 1)
        role_index = int(role_part)
        if not (0 <= role_index < len(AVAILABLE_ROLES)):
            await callback.answer("Неправильний індекс ролі.", show_alert=True)
            return
        role = AVAILABLE_ROLES[role_index]
    except (ValueError, IndexError):
        await callback.answer("Помилка формату ролі.", show_alert=True)
        return
    
    await state.update_data(edit_photo_role=role, edit_photo_role_index=role_index)
    
    buttons = []
    for day in range(1, DAYS_TOTAL + 1):
        buttons.append([InlineKeyboardButton(
            text=f"📅 День {day}",
            callback_data=f"dev_photo_day|{day}"
        )])
    
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="dev_photos_menu")])
    
    await _edit_or_answer(
        callback.message,
        f"🖼 <b>Редагування фото матеріалів</b>\n\n"
        f"Посада: <b>{role}</b>\n\n"
        f"Оберіть день:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()

async def developer_photos_view(callback: CallbackQuery, state: FSMContext):
    """Показ поточного фото матеріалу з можливістю редагування."""
    if not await _ensure_developer(callback):
        return
    
    try:
        _, day_str = callback.data.split("|", 1)
        day = int(day_str)
    except (ValueError, IndexError):
        await callback.answer("Помилка формату.", show_alert=True)
        return
    
    data = await state.get_data()
    role = data.get("edit_photo_role", "")
    await state.update_data(edit_photo_day=day)
    
    # Отримуємо матеріал з БД, використовуючи новий тип для завантажених фото
    photo_material = await get_material_by_role_day_type(role, day, "photo_files")
    
    current_file_ids = []
    photo_material_id = None
    if photo_material and photo_material.get("content"):
        try:
            current_file_ids = json.loads(photo_material["content"])
            photo_material_id = photo_material.get("id")
        except json.JSONDecodeError:
            pass # Will be treated as no content
    
    await state.update_data(edit_photo_material_id=photo_material_id)
    # Also set generic edit state for full view handler
    await state.update_data(edit_role=role, edit_day=day)
    
    if current_file_ids:
        preview = f"Завантажено фотофайлів: {len(current_file_ids)}"
        text = (
            f"🖼 <b>Фото матеріал</b>\n\n"
            f"Посада: <b>{role}</b>\n"
            f"День: <b>{day}</b>\n\n"
            f"<b>Поточний контент:</b>\n"
            f"{preview}\n\n"
            f"Натисніть «Повний перегляд», щоб побачити або виправити фото."
        )
        buttons = [
            [InlineKeyboardButton(text="➕ Додати навчання", callback_data="dev_photo_edit")],
            [InlineKeyboardButton(text="🔍 Повний перегляд", callback_data="dev_mat_full_view|photo_files")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev_photo_role|{data.get('edit_photo_role_index')}")],
        ]
    else:
        text = (
            f"🖼 <b>Фото матеріал не знайдено</b>\n\n"
            f"Посада: <b>{role}</b>\n"
            f"День: <b>{day}</b>\n\n"
            f"Натисніть «Додати навчання», щоб завантажити новий фото матеріал."
        )
        buttons = [
            [InlineKeyboardButton(text="➕ Додати навчання", callback_data="dev_photo_edit")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev_photo_role|{data.get('edit_photo_role_index')}")],
        ]
    
    await _edit_or_answer(
        callback.message,
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()

async def developer_photo_edit_start(callback: CallbackQuery, state: FSMContext):
    """Початок редагування фото — запит нових фотофайлів."""
    if not await _ensure_developer(callback):
        return
    
    data = await state.get_data()
    role = data.get("edit_photo_role", "")
    day = data.get("edit_photo_day", 1)
    
    prompt = (
        f"🖼 <b>Завантаження фото матеріалів</b>\n\n"
        f"Посада: <b>{role}</b>\n"
        f"День: <b>{day}</b>\n\n"
        f"Надішліть один або кілька фотофайлів (jpg, jpeg, png). Коли закінчите, будь ласка, напишіть <b>Готово</b>."
    )
    
    buttons = [
        [InlineKeyboardButton(text="❌ Скасувати", callback_data=f"dev_photo_day|{day}")],
    ]
    
    await _edit_or_answer(
        callback.message,
        prompt,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await state.set_state(DeveloperStates.waiting_photo_uploads)
    await state.update_data(photo_file_ids=[])
    await callback.answer()

async def _finalize_photo_update(message: Message, state: FSMContext, photo_file_ids: list[str]):
    """Обробка завантажених фотофайлів і збереження."""
    if not photo_file_ids:
        await message.answer("❌ Немає фотофайлів для збереження.")
        return

    # edit_role and edit_day are needed by _save_pending_material
    data = await state.get_data()
    role = data.get("edit_photo_role", "")
    day = data.get("edit_photo_day", 1)
    material_id = data.get("edit_photo_material_id")

    await state.update_data(
        pending_content=json.dumps(photo_file_ids),
        pending_content_type="photo_files",
        edit_role=role,
        edit_day=day,
        pending_material_id=material_id
    )

    success, role, content_type, day = await _save_pending_material(state)
    
    if success:
        await message.answer(
            f"✅ <b>Матеріал оновлено!</b>\n\nПосада: {role}\nДень: {day}\nТип: {content_type}\nЗавантажено файлів: {len(photo_file_ids)}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ До Dev-панелі", callback_data="developer_menu")]])
        )
    else:
        await message.answer("❌ Помилка збереження матеріалу.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ До Dev-панелі", callback_data="developer_menu")]]))
    
    await state.clear()


async def developer_process_photo_uploads(message: Message, state: FSMContext):
    """Collects multiple photo messages for photo content until 'Готово' is received."""
    data = await state.get_data()
    photo_file_ids = data.get("photo_file_ids", [])
    confirmation_msg_id = data.get("photo_confirmation_msg_id")

    if message.photo:
        file_id = message.photo[-1].file_id
        photo_file_ids.append(file_id)
        await state.update_data(photo_file_ids=photo_file_ids)

        new_text = f"✅ Отримано {len(photo_file_ids)} фото. Надішліть наступне фото або напишіть 'Готово', щоб завершити."

        if confirmation_msg_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=confirmation_msg_id,
                    text=new_text,
                )
            except TelegramBadRequest as e:
                if "message is not modified" not in str(e):
                    sent_msg = await message.answer(new_text)
                    await state.update_data(photo_confirmation_msg_id=sent_msg.message_id)
        else:
            sent_msg = await message.answer(new_text)
            await state.update_data(photo_confirmation_msg_id=sent_msg.message_id)

    elif message.text and message.text.lower() == 'готово':
        if not photo_file_ids:
            await message.answer("❌ Ви не надіслали жодного фото. Надішліть фото або скасуйте редагування.")
            return
            
        if confirmation_msg_id:
            try:
                await message.bot.delete_message(chat_id=message.chat.id, message_id=confirmation_msg_id)
            except Exception:
                pass

        await _finalize_photo_update(message, state, photo_file_ids)
    else:
        if message.text:
             await message.answer("Будь ласка, надішліть фотофайл або напишіть 'Готово' для завершення.")

# ==================== Syllabus Editor ====================

async def developer_syllabus_menu(callback: CallbackQuery):
    """Головне меню редагування змістів — вибір посади."""
    if not await _ensure_developer(callback):
        return
    
    buttons = []
    for i, role in enumerate(AVAILABLE_ROLES):
        short_name = role[:25] + "..." if len(role) > 28 else role
        buttons.append([InlineKeyboardButton(
            text=short_name,
            callback_data=f"dev_syl_role|{i}"
        )])
    
    buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="developer_menu")])
    
    await _edit_or_answer(
        callback.message,
        "📚 <b>Редагування змістів (Syllabus)</b>\n\n"
        "Оберіть посаду для редагування змісту:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()

async def developer_syllabus_view(callback: CallbackQuery, state: FSMContext, role_index: Optional[int] = None):
    """Перегляд поточного змісту для обраної посади з можливістю ввімкнення."""
    if not await _ensure_developer(callback):
        return
    
    try:
        if role_index is None:
            _, role_part = callback.data.split("|", 1)
            role_index = int(role_part)
        
        role = AVAILABLE_ROLES[role_index]
    except (ValueError, IndexError, TypeError):
        await callback.answer("Помилка ролі.", show_alert=True)
        return
    
    await state.update_data(syllabus_role=role, syllabus_role_index=role_index)
    
    # Syllabus is stored with day=0 and content_type='syllabus'
    syllabus_material = await get_material_by_role_day_type(role, 0, "syllabus")
    
    is_enabled = True
    if syllabus_material:
        is_enabled = bool(syllabus_material.get("is_enabled", 1))
        content = syllabus_material.get("content", "")
    else:
        content = ""

    display_content = content[:500] + "..." if len(content) > 500 else (content or "(порожньо)")
    
    status_icon = "✅" if is_enabled else "zzz"
    status_text = "АКТИВНИЙ" if is_enabled else "ВИМКНЕНИЙ (прихований від стажерів)"

    text = (
        f"📚 <b>Зміст: {role}</b>\n"
        f"Статус: {status_icon} <b>{status_text}</b>\n\n"
        f"{display_content}\n\n"
        f"Натисніть «Редагувати», щоб змінити текст змісту."
    )
    
    toggle_btn_text = "🔴 Вимкнути зміст" if is_enabled else "🟢 Увімкнути зміст"
    toggle_action = "disable" if is_enabled else "enable"

    buttons = [
        [InlineKeyboardButton(text="✏️ Редагувати", callback_data="dev_syl_edit")],
        [InlineKeyboardButton(text=toggle_btn_text, callback_data=f"dev_syl_toggle:{toggle_action}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="dev_syllabus_menu")]
    ]
    
    await _edit_or_answer(
        callback.message,
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()

async def developer_syllabus_toggle(callback: CallbackQuery, state: FSMContext):
    """Вмикає або вимикає зміст."""
    if not await _ensure_developer(callback): return
    
    try:
        action = callback.data.split(":")[1]
        is_enabled = (action == "enable")
    except IndexError:
        return
    
    data = await state.get_data()
    role = data.get("syllabus_role")
    role_index = data.get("syllabus_role_index")
    
    if not role or role_index is None:
        await callback.answer("Помилка стану.", show_alert=True)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE materials SET is_enabled = ? WHERE role = ? AND day = 0 AND content_type = 'syllabus'",
            (is_enabled, role)
        )
        await db.commit()
    
    status_msg = "Зміст увімкнено!" if is_enabled else "Зміст вимкнено!"
    await callback.answer(status_msg, show_alert=True)
    
    # Refresh view
    await developer_syllabus_view(callback, state, role_index=role_index)

async def developer_syllabus_edit(callback: CallbackQuery, state: FSMContext):
    """Початок редагування змісту."""
    if not await _ensure_developer(callback):
        return
        
    data = await state.get_data()
    role = data.get("syllabus_role", "")
    
    text = (
        f"✏️ <b>Редагування змісту: {role}</b>\n\n"
        f"Надішліть новий текст змісту. Ви можете використовувати HTML-розмітку.\n\n"
        f"<b>Приклад оформлення:</b>\n"
        f"<code>&lt;b&gt;День 1&lt;/b&gt;: Знайомство з пекарнею\n"
        f"— Стандарти обслуговування\n"
        f"— &lt;i&gt;Техніка безпеки&lt;/i&gt;\n\n"
        f"&lt;b&gt;День 2&lt;/b&gt;: Робота з касою\n"
        f"— Розрахунок клієнтів</code>"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Скасувати", callback_data=f"dev_syl_role|{data.get('syllabus_role_index')}")]
    ])
    
    await _edit_or_answer(callback.message, text, reply_markup=kb)
    await state.set_state(DeveloperStates.waiting_syllabus_text)
    await callback.answer()

async def developer_process_syllabus(message: Message, state: FSMContext):
    """Збереження змісту."""
    text_input = message.text
    if not text_input:
        await message.answer("❌ Текст не може бути порожнім.")
        return
        
    data = await state.get_data()
    role = data.get("syllabus_role", "")
    
    # Save to DB with day=0 and type='syllabus'
    await add_or_update_material(
        role=role,
        day=0,
        content_type="syllabus",
        title=f"Зміст: {role}",
        content=text_input,
        resource_url=None,
        order_index=0
    )
    
    await message.answer(
        f"✅ <b>Зміст успішно збережено!</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ До перегляду", callback_data=f"dev_syl_role|{data.get('syllabus_role_index')}")]
        ])
    )
    await state.clear()


# ==================== Notification handlers ====================

async def _save_pending_material(state: FSMContext) -> tuple[bool, str, str, int]:
    """Зберігає pending матеріал. Повертає (success, role, content_type, day)."""
    logger = get_logger()
    data = await state.get_data()
    role = data.get("edit_role") or data.get("edit_video_role", "")
    day = data.get("edit_day") or data.get("edit_video_day", 1)
    content_type = data.get("pending_content_type", "text")
    content = data.get("pending_content", "")
    material_id = data.get("pending_material_id")
    
    try:
        if content_type == "text":
            if material_id:
                await update_material_content(material_id, content)
            else:
                await add_or_update_material(
                    role=role,
                    day=day,
                    content_type="text",
                    title=f"День {day} — Текст",
                    content=content,
                    resource_url=None,
                    order_index=0,
                )
        elif content_type == "video": # External video URL
            if material_id:
                await update_material_resource_url(material_id, content)
            else:
                await add_or_update_material(
                    role=role,
                    day=day,
                    content_type="video",
                    title=f"День {day} — Відео (посилання)",
                    content=None,
                    resource_url=content,
                    order_index=0,
                )
        elif content_type == "video_files": # Uploaded video files
            if material_id:
                # For video files, we store JSON list of file_ids in content
                await update_material_content(material_id, content)
                await update_material_resource_url(material_id, None) # Clear URL for uploaded files
            else:
                await add_or_update_material(
                    role=role,
                    day=day,
                    content_type="video_files",
                    title=f"День {day} — Відео",
                    content=content, # JSON string of file_ids
                    resource_url=None,
                    order_index=0,
                )
        elif content_type == "photo_files": # Uploaded photo files
            if material_id:
                await update_material_content(material_id, content)
                await update_material_resource_url(material_id, None)
            else:
                await add_or_update_material(
                    role=role,
                    day=day,
                    content_type="photo_files",
                    title=f"День {day} — Фото",
                    content=content, # JSON string of file_ids
                    resource_url=None,
                    order_index=0,
                )
        
        # Schedule the embeddings build to run in the background.
        # This function now contains lazy imports, so it won't crash the bot.
        logger.info("Material saved, scheduling embeddings build.")
        asyncio.create_task(build_and_reset_embeddings())
        
        return True, role, content_type, day
    except Exception as e:
        logger.error(f"Failed to save material: {e}", exc_info=True)
        return False, role, content_type, day


async def notify_decision_no(callback: CallbackQuery, state: FSMContext):
    """Користувач обрав НІ — зберігаємо без оповіщення."""
    success, role, content_type, day = await _save_pending_material(state)
    
    if success:
        await callback.message.edit_text(
            f"✅ <b>Матеріал оновлено!</b>\n\n"
            f"Посада: {role}\n"
            f"День: {day}\n"
            f"Тип: {content_type}\n\n"
            f"<i>Оповіщення не надсилалось.</i>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ До Dev-панелі", callback_data="developer_menu")]
            ])
        )
    else:
        await callback.message.edit_text(
            "❌ Помилка збереження матеріалу.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ До Dev-панелі", callback_data="developer_menu")]
            ])
        )
    
    await state.clear()
    await callback.answer()


async def notify_decision_yes(callback: CallbackQuery, state: FSMContext):
    """Користувач обрав ТАК — просимо текст оповіщення."""
    data = await state.get_data()
    role = data.get("edit_role", "")
    day = data.get("edit_day", 1)
    
    await state.set_state(DeveloperStates.waiting_notify_message)
    
    await callback.message.edit_text(
        f"📢 <b>Оповіщення про зміни</b>\n\n"
        f"Посада: {role}\n"
        f"День: {day}\n\n"
        f"Напишіть опис змін, який отримають користувачі.\n\n"
        f"<b>Приклад:</b>\n"
        f"<i>🔄 Оновлено навчальний матеріал:\n"
        f"• Додано нову інформацію про стандарти обслуговування\n"
        f"• Виправлено помилки в попередній версії</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Скасувати оповіщення", callback_data="notify_cancel")]
        ])
    )
    await callback.answer()


async def notify_cancel(callback: CallbackQuery, state: FSMContext):
    """Скасування оповіщення — зберігаємо без нього."""
    await notify_decision_no(callback, state)


async def process_notify_message(message: Message, state: FSMContext):
    """Обробка тексту оповіщення та розсилка."""
    from database.users import get_all_users
    
    notify_text = message.text.strip()
    if not notify_text:
        await message.answer("❌ Текст оповіщення не може бути порожнім.")
        return
    
    # Спочатку зберігаємо матеріал
    success, role, content_type, day = await _save_pending_material(state)
    
    if not success:
        await message.answer(
            "❌ Помилка збереження матеріалу.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ До Dev-панелі", callback_data="developer_menu")]
            ])
        )
        await state.clear()
        return
    
    # Отримуємо всіх користувачів
    users = await get_all_users()
    
    # Формуємо повідомлення
    full_message = (
        f"📢 <b>Оновлення навчальних матеріалів</b>\n\n"
        f"📚 Посада: <b>{role}</b>\n"
        f"📅 День: <b>{day}</b>\n\n"
        f"{notify_text}"
    )
    
    # Розсилаємо
    sent_count = 0
    failed_count = 0
    
    for user in users:
        user_id = user.get("user_id")
        if not user_id:
            continue
        try:
            await message.bot.send_message(user_id, full_message)
            sent_count += 1
        except Exception:
            failed_count += 1
    
    await message.answer(
        f"✅ <b>Матеріал оновлено та оповіщення надіслано!</b>\n\n"
        f"Посада: {role}\n"
        f"День: {day}\n"
        f"Тип: {content_type}\n\n"
        f"📊 <b>Статистика розсилки:</b>\n"
        f"• Надіслано: {sent_count}\n"
        f"• Не вдалось: {failed_count}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ До Dev-панелі", callback_data="developer_menu")]
        ])
    )
    
    await state.clear()


# ==================== Tokens Management ====================

async def developer_tokens_menu(callback: CallbackQuery):
    """Меню управління токенами з поясненнями."""
    if not await _ensure_developer(callback):
        return
    
    stats = await get_token_stats()
    
    text = (
        "🎟 <b>УПРАВЛІННЯ ТОКЕНАМИ</b>\n"
        "───────────────────\n"
        f"📊 <b>Статистика:</b>\n"
        f"• Активні (діючі): <b>{stats.get('active', 0)}</b>\n"
        f"• Використані: <b>{stats.get('used', 0)}</b>\n"
        f"• Прострочені: <b>{stats.get('expired', 0)}</b>\n"
        f"• Всього в базі: <b>{stats.get('total', 0)}</b>\n\n"
        
        f"⚙️ <b>Функції:</b>\n"
        f"🧹 <b>Очищення прострочених:</b> видаляє з бази даних усі посилання-запрошення, термін дії яких (24 години) вже закінчився і які так і не були використані.\n"
        "───────────────────\n"
        "<i>💡 Це допомагає підтримувати базу даних чистою та видаляти неактуальне сміття.</i>"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧹 Очистити прострочені", callback_data="dev_tokens_cleanup")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="developer_menu")],
    ])
    
    await _edit_or_answer(callback.message, text, reply_markup=kb)
    await callback.answer()


async def developer_tokens_cleanup(callback: CallbackQuery):
    """Очищення прострочених токенів."""
    if not await _ensure_developer(callback):
        return
    
    count = await cleanup_expired_tokens()
    
    await callback.answer(f"Оброблено {count} токенів", show_alert=True)
    await developer_tokens_menu(callback)


# ==================== Health Status ====================

async def developer_health_status(callback: CallbackQuery):
    """Показує статус здоров'я бота з покращеним інтерфейсом."""
    if not await _ensure_developer(callback):
        return
    
    status = get_health_status()
    
    health_icon = "🟢" if status["status"] == "healthy" else "🔴"
    scheduler_icon = "✅" if status["scheduler_healthy"] else "❌"
    reminder_icon = "✅" if status["reminder_healthy"] else "❌"
    
    from datetime import datetime
    import pytz
    from bot.config import TIMEZONE
    from bot.services.health import health_check
    
    now = datetime.now(pytz.timezone(TIMEZONE))
    
    def format_delta(last_time):
        if not last_time: return "немає даних"
        delta = now - last_time
        minutes = int(delta.total_seconds() / 60)
        if minutes == 0: return "щойно"
        if minutes < 60: return f"{minutes} хв тому"
        return f"{minutes // 60} год {minutes % 60} хв тому"

    scheduler_delta = format_delta(health_check._last_scheduler_heartbeat)
    reminder_delta = format_delta(health_check._last_reminder_heartbeat)
    
    # Форматуємо дату очищення токенів
    token_cleanup = status['last_token_cleanup']
    if token_cleanup:
        try:
            # Спроба зробити дату красивішою
            token_cleanup = datetime.fromisoformat(token_cleanup.replace('Z', '+00:00')).astimezone(pytz.timezone(TIMEZONE)).strftime('%H:%M:%S (%d.%m)')
        except:
            pass

    text = (
        f"🛡 <b>МОНІТОРИНГ СИСТЕМИ</b>\n"
        f"───────────────────\n"
        f"{health_icon} Стан системи: <b>{status['status'].upper()}</b>\n"
        f"⏱ Час роботи: <b>{status['uptime_human']}</b>\n"
        f"❌ Помилок за сесію: <b>{status['errors_count']}</b>\n\n"
        
        f"⚙️ <b>Життєздатність компонентів:</b>\n"
        f"{scheduler_icon} <b>Планувальник (Scheduler):</b>\n"
        f"  └ Активність: {scheduler_delta}\n"
        f"{reminder_icon} <b>Цикл нагадувань:</b>\n"
        f"  └ Активність: {reminder_delta}\n\n"
        
        f"📊 <b>Додаткові дані:</b>\n"
        f"🕒 Сервер: <code>{now.strftime('%H:%M:%S')}</code>\n"
        f"🧹 Очищення токенів: <code>{token_cleanup or 'немає'}</code>\n"
        f"───────────────────\n"
        f"<i>💡 Кнопка «Оновити» перевіряє актуальні дані датчиків активності без перезавантаження сторінки.</i>"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Оновити статус", callback_data="dev_health_status")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="developer_menu")],
    ])
    
    await _edit_or_answer(callback.message, text, reply_markup=kb)
    await callback.answer()


# ---------- New User Management Handlers (from user profile) ----------

async def _rebuild_user_profile_view(callback: CallbackQuery, user_id: int, state: FSMContext):
    """Helper to refresh the user profile view after an action."""
    report = await get_user_days_report(user_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📅 Навчальні дні", callback_data=f"dev_days_manage:{user_id}"),
            InlineKeyboardButton(text="✍️ Змінити", callback_data=f"dev_user_modify:{user_id}")
        ],
        [
            InlineKeyboardButton(text="❌ Видалити", callback_data=f"dev_user_delete_confirm:{user_id}"),
            InlineKeyboardButton(text="⬅️ Назад", callback_data="dev_users_menu")
        ]
    ])
    await _edit_or_answer(callback.message, report, reply_markup=kb)
    await state.clear()

# --- Learning Days Management ---

async def developer_days_manage_menu(callback: CallbackQuery, state: FSMContext, user_id: Optional[int] = None):
    if user_id is None:
        try:
            user_id = int(callback.data.split(":")[1])
        except (ValueError, IndexError):
            await callback.answer("Помилка ID користувача.", show_alert=True)
            return

    user = await get_user_details(user_id)
    overview = await get_days_overview(user_id)
    
    buttons = []
    for day, status in overview:
        action = "close" if status == DayStatus.OPEN else "open"
        icon = "🟢" if status == DayStatus.OPEN else "✅" if status == DayStatus.COMPLETED else "🔒"
        buttons.append([InlineKeyboardButton(
            text=f"{icon} День {day}",
            callback_data=f"dev_toggle_day:{user_id}:{day}:{action}"
        )])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад до профілю", callback_data=f"dev_user_profile_back:{user_id}")])
    
    await _edit_or_answer(
        callback.message,
        f"<b>Керування днями для {user.get('full_name')}</b>\nНатисніть на день, щоб змінити його статус (відкрити/закрити).",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

async def developer_toggle_day_status(callback: CallbackQuery, state: FSMContext):
    _, user_id_str, day_str, action = callback.data.split(":")
    user_id, day = int(user_id_str), int(day_str)

    if action == "open":
        await open_days_for_user(user_id, [day])
    else: # close
        await close_days_for_user(user_id, [day])
    
    # Refresh the menu
    await developer_days_manage_menu(callback, state, user_id=user_id)

async def developer_user_profile_back(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split(":")[1])
    # To redisplay the profile, we essentially re-run the search result display logic
    report = await get_user_days_report(user_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📅 Навчальні дні", callback_data=f"dev_days_manage:{user_id}"),
            InlineKeyboardButton(text="✍️ Змінити", callback_data=f"dev_user_modify:{user_id}")
        ],
        [
            InlineKeyboardButton(text="❌ Видалити", callback_data=f"dev_user_delete_confirm:{user_id}"),
            InlineKeyboardButton(text="⬅️ Назад", callback_data="dev_users_menu")
        ]
    ])
    await _edit_or_answer(callback.message, report, reply_markup=kb)

# --- Modify User ---

async def developer_user_modify_menu(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split(":")[1])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Змінити керівника", callback_data=f"dev_change_manager:{user_id}")],
        [InlineKeyboardButton(text="Змінити посаду", callback_data=f"dev_change_role:{user_id}")],
        [InlineKeyboardButton(text="Змінити місто", callback_data=f"dev_change_city:{user_id}")],
        [InlineKeyboardButton(text="⬅️ Назад до профілю", callback_data=f"dev_user_profile_back:{user_id}")]
    ])
    await _edit_or_answer(callback.message, "✍️ <b>Що саме ви хочете змінити?</b>", reply_markup=kb)

async def developer_change_manager_start(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split(":")[1])
    await state.set_state(DeveloperStates.waiting_change_manager_id)
    await state.update_data(user_id_to_modify=user_id)
    await _edit_or_answer(callback.message, "Введіть новий ID керівника:", reply_markup=_cancel_keyboard(f"dev_user_modify:{user_id}"))

async def developer_process_change_manager(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = data.get("user_id_to_modify")
    try:
        new_manager_id = int(message.text)
        # Check if manager exists
        if not await get_manager_by_uid(new_manager_id):
            await message.answer("⚠️ Керівника з таким ID не знайдено. Спробуйте ще раз.")
            return
        
        user_details = await get_user_details(user_id)
        # set_intern_extra updates all three fields, so we pass existing ones
        await set_intern_extra(user_id, new_manager_id, user_details.get('role'), user_details.get('city'))
        await message.answer("✅ Керівника успішно змінено!")
        
        # Re-create a mock callback to return to the profile
        from aiogram.types import User, CallbackQuery
        mock_callback = CallbackQuery(id="mock", from_user=message.from_user, chat_instance="", message=message, data=f"dev_user_profile_back:{user_id}")
        await _rebuild_user_profile_view(mock_callback, user_id, state)
        
    except ValueError:
        await message.answer("❌ ID має бути числом. Спробуйте ще раз.")
        return
    except Exception as e:
        await message.answer(f"Сталася помилка: {e}")
        await state.clear()

    except Exception as e:
        await message.answer(f"Сталася помилка: {e}")
        await state.clear()

async def developer_change_role_start(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split(":")[1])
    buttons = []
    for role in AVAILABLE_ROLES:
        buttons.append([InlineKeyboardButton(text=role, callback_data=f"dev_process_change_role:{user_id}:{role}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev_user_modify:{user_id}")])
    await _edit_or_answer(callback.message, "Оберіть нову посаду:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

async def developer_process_change_role(callback: CallbackQuery, state: FSMContext):
    _, user_id_str, new_role = callback.data.split(":", 2)
    user_id = int(user_id_str)
    
    user_details = await get_user_details(user_id)
    await set_intern_extra(user_id, user_details.get('manager_id'), new_role, user_details.get('city'))
    await callback.answer("Посаду змінено!")
    await _rebuild_user_profile_view(callback, user_id, state)

async def developer_change_city_start(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split(":")[1])
    buttons = []
    for city in AVAILABLE_CITIES:
        buttons.append([InlineKeyboardButton(text=city, callback_data=f"dev_process_change_city:{user_id}:{city}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev_user_modify:{user_id}")])
    await _edit_or_answer(callback.message, "Оберіть нове місто:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

async def developer_process_change_city(callback: CallbackQuery, state: FSMContext):
    _, user_id_str, new_city = callback.data.split(":", 2)
    user_id = int(user_id_str)
    
    user_details = await get_user_details(user_id)
    await set_intern_extra(user_id, user_details.get('manager_id'), user_details.get('role'), new_city)
    await callback.answer("Місто змінено!")
    await _rebuild_user_profile_view(callback, user_id, state)

# --- Delete User ---

async def developer_user_delete_confirm(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split(":")[1])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Так, видалити", callback_data=f"dev_user_delete_perform:{user_id}"),
            InlineKeyboardButton(text="❌ Ні, назад", callback_data=f"dev_user_profile_back:{user_id}")
        ]
    ])
    await _edit_or_answer(callback.message, f"Ви впевнені, що хочете видалити користувача {user_id}?", reply_markup=kb)

async def developer_user_delete_perform(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split(":")[1])
    await delete_user(user_id)
    await callback.answer(f"Користувача {user_id} видалено.", show_alert=True)
    await _edit_or_answer(callback.message, "Користувача видалено.", reply_markup=_users_menu_keyboard())


# ==================== Reminder History ====================

async def developer_reminder_history_menu(callback: CallbackQuery):
    """Displays the reminder history."""
    if not await _ensure_developer(callback):
        return
    
    # Показуємо 15 останніх записів, щоб не перевищити ліміт символів
    logs = await get_reminder_history(limit=15)
    
    if not logs:
        await _edit_or_answer(
            callback.message,
            "📭 Історія нагадувань порожня.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="developer_menu")]
            ])
        )
        await callback.answer()
        return

    lines = [f"📜 <b>Історія нагадувань (останні {len(logs)})</b>", ""]
    
    for log in logs:
        sent_at = log['sent_at']
        intern_name = log['intern_name'] or f"ID {log['intern_id']}"
        source = log['source']
        sender_name = log['sender_name'] or (f"ID {log['sender_id']}" if log['sender_id'] else None)
        
        icon = "🤖"
        if source == "manager":
            icon = "👨‍🏫"
        elif source == "hr":
            icon = "👔"
            
        by_whom = ""
        if source == "auto":
            by_whom = "Автоматично"
        elif sender_name:
            by_whom = f"{sender_name}"
        else:
            by_whom = source.capitalize()
            
        # Екрануємо дані з БД
        e_intern_name = html.escape(intern_name)
        e_by_whom = html.escape(by_whom)
        
        lines.append(f"{icon} <b>{sent_at}</b> → {e_intern_name}")
        lines.append(f"   <i>Від: {e_by_whom}</i>")
        lines.append("───────────────")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Оновити", callback_data="dev_reminder_history")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="developer_menu")]
    ])
    
    await _edit_or_answer(callback.message, "\n".join(lines), reply_markup=kb)
    await callback.answer()


# ==================== Analytics ====================

async def developer_analytics_menu(callback: CallbackQuery):
    """Меню вибору аналітичних звітів."""
    if not await _ensure_developer(callback):
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Щоденний дайджест", callback_data="dev_analytics_digest")],
        [InlineKeyboardButton(text="📉 Воронка відсіву", callback_data="dev_analytics_funnel")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="developer_menu")]
    ])
    
    await _edit_or_answer(
        callback.message,
        "📊 <b>Аналітика</b>\nОберіть тип звіту:",
        reply_markup=kb
    )
    await callback.answer()

async def developer_daily_digest(callback: CallbackQuery):
    """Показує статистику за останні 24 години."""
    if not await _ensure_developer(callback):
        return
        
    stats = await get_daily_stats()
    
    text = (
        "📅 <b>Щоденний дайджест (24 год)</b>\n\n"
        f"🆕 Нових стажерів: <b>{stats['new_users']}</b>\n"
        f"✅ Пройдено блоків: <b>{stats['completions']}</b>\n"
        f"🏃‍♂️ Активних користувачів: <b>{stats['active_users']}</b>\n"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="dev_analytics_menu")]
    ])
    
    await _edit_or_answer(callback.message, text, reply_markup=kb)
    await callback.answer()

async def developer_dropout_report(callback: CallbackQuery):
    """Показує воронку відсіву користувачів."""
    if not await _ensure_developer(callback):
        return
        
    data = await get_dropout_funnel(active_days=3)
    
    # 1. Секція для АКТИВНИХ
    active_total = data['active_users']
    active_dist = data['active_distribution']
    
    lines = [
        "📉 <b>Воронка відсіву (АКТИВНІ до 3 дн)</b>",
        f"Активних стажерів: <b>{active_total}</b>",
        ""
    ]
    
    if active_total > 0:
        for day in range(1, DAYS_TOTAL + 1):
            count = active_dist.get(day, 0)
            percent = (count / active_total * 100)
            bar = "█" * int(percent / 5)
            lines.append(f"День {day}: <b>{count}</b> ({percent:.1f}%)")
            lines.append(f"<code>{bar}</code>")
    else:
        lines.append("<i>Немає активних стажерів за останні 3 дні.</i>")

    lines.append("\n" + "─" * 15 + "\n")

    # 2. Секція для ВСІХ
    total_count = data['total_users']
    total_dist = data['total_distribution']
    
    lines.append("📊 <b>Загальна статистика (всі)</b>")
    lines.append(f"Всього в базі: <b>{total_count}</b>\n")
    
    if total_count > 0:
        for day in range(1, DAYS_TOTAL + 1):
            count = total_dist.get(day, 0)
            percent = (count / total_count * 100)
            bar = "░" * int(percent / 5)
            lines.append(f"День {day}: <b>{count}</b> ({percent:.1f}%)")
            lines.append(f"<code>{bar}</code>")
    
    footer = "* Секція 'Активні' не враховує тих, хто не заходив у бот ≥ 3 дні."
    lines.append(f"\n<i>{html.escape(footer)}</i>")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Оновити", callback_data="dev_analytics_funnel")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="dev_analytics_menu")]
    ])
    
    await _edit_or_answer(callback.message, "\n".join(lines), reply_markup=kb)
    await callback.answer()


def register_developer_menu_handlers(dp: Dispatcher):
    dp.callback_query.register(developer_menu_callback, lambda c: c.data == "developer_menu")

    # Analytics
    dp.callback_query.register(developer_analytics_menu, lambda c: c.data == "dev_analytics_menu")
    dp.callback_query.register(developer_daily_digest, lambda c: c.data == "dev_analytics_digest")
    dp.callback_query.register(developer_dropout_report, lambda c: c.data == "dev_analytics_funnel")

    # Reminder History
    dp.callback_query.register(developer_reminder_history_menu, lambda c: c.data == "dev_reminder_history")

    # Users
    dp.callback_query.register(developer_users_menu, lambda c: c.data == "dev_users_menu")
    dp.callback_query.register(developer_list_users, lambda c: c.data == "dev_users_list")
    
    # Active/Inactive users
    dp.callback_query.register(developer_active_users, lambda c: c.data == "dev_users_active")
    dp.callback_query.register(developer_inactive_users, lambda c: c.data == "dev_users_inactive")
    
    # City filter
    dp.callback_query.register(developer_users_by_city_menu, lambda c: c.data == "dev_users_by_city")
    dp.callback_query.register(developer_users_filter_city, lambda c: c.data and c.data.startswith("dev_users_filter_city:"))
    
    # Updated pagination
    dp.callback_query.register(developer_users_pagination_handler, lambda c: c.data and (c.data.startswith("dev_users_pag:") or c.data.startswith("dev_users_page:")))
    
    dp.callback_query.register(developer_request_user_search, lambda c: c.data == "dev_users_search")
    dp.callback_query.register(developer_request_delete_user, lambda c: c.data == "dev_users_delete")
    dp.message.register(developer_process_user_search, DeveloperStates.waiting_user_search)
    dp.message.register(developer_process_delete_user, DeveloperStates.waiting_delete_user)

    # Managers Team Management
    dp.callback_query.register(developer_manage_managers_menu, lambda c: c.data == "dev_manage_managers")
    dp.callback_query.register(developer_managers_pagination_handler, lambda c: c.data and c.data.startswith("dev_mgr_page:"))
    dp.callback_query.register(developer_list_managers, lambda c: c.data == "dev_managers_list")
    dp.callback_query.register(developer_request_add_manager, lambda c: c.data == "dev_add_manager")
    dp.message.register(developer_process_add_manager_id, DeveloperStates.waiting_add_manager_id)
    dp.message.register(developer_process_add_manager_name, DeveloperStates.waiting_add_manager_name) # NEW
    dp.callback_query.register(developer_process_add_manager_city, DeveloperStates.waiting_add_manager_city, lambda c: c.data.startswith("dev_mgr_city_select:"))
    dp.callback_query.register(developer_process_shop_selection, DeveloperStates.waiting_add_manager_shops, lambda c: c.data.startswith("dev_mgr_shop_toggle:"))
    dp.callback_query.register(developer_finish_shop_selection, DeveloperStates.waiting_add_manager_shops, lambda c: c.data == "dev_mgr_shop_done")
    dp.callback_query.register(developer_remove_manager_menu, lambda c: c.data == "dev_remove_manager_menu")
    dp.callback_query.register(developer_remove_manager, lambda c: c.data and c.data.startswith("mgr_remove:"))
    dp.callback_query.register(manager_cancel_add, lambda c: c.data == "mgr_cancel_add")
    dp.callback_query.register(manager_team_back, lambda c: c.data == "mgr_team_back")
    
    # HR Team Management (moved up or handled here)
    dp.callback_query.register(developer_request_add_hr, lambda c: c.data == "dev_add_hr")
    dp.message.register(developer_process_add_hr, DeveloperStates.waiting_add_hr)
    dp.callback_query.register(hr_cancel_add_role, lambda c: c.data == "hr_cancel_add_role")
    dp.callback_query.register(hr_team_member_handler, lambda c: c.data and c.data.startswith("hr_team_member_"))
    dp.callback_query.register(hr_remove_member, lambda c: c.data and c.data.startswith("hr_remove_"))
    dp.callback_query.register(hr_team_back, lambda c: c.data == "hr_team_back")

    # Tokens & Health
    dp.callback_query.register(developer_tokens_menu, lambda c: c.data == "dev_tokens_menu")
    dp.callback_query.register(developer_tokens_cleanup, lambda c: c.data == "dev_tokens_cleanup")
    dp.callback_query.register(developer_health_status, lambda c: c.data == "dev_health_status")

    # Materials Editor
    dp.callback_query.register(developer_materials_menu, lambda c: c.data == "dev_materials_menu")
    dp.callback_query.register(developer_materials_select_day, lambda c: c.data and c.data.startswith("dev_mat_role|"))
    dp.callback_query.register(developer_materials_select_type, lambda c: c.data and c.data.startswith("dev_mat_day|"))
    dp.callback_query.register(developer_materials_view, lambda c: c.data and c.data.startswith("dev_mat_type|"))
    dp.callback_query.register(developer_materials_full_view, lambda c: c.data and c.data.startswith("dev_mat_full_view|"))
    dp.callback_query.register(developer_pagination_handler, lambda c: c.data and c.data.startswith("dev_pag:")) # NEW
    dp.callback_query.register(developer_material_fix_start, lambda c: c.data and c.data.startswith("dev_mat_fix:"))
    dp.message.register(developer_process_fix_page, DeveloperStates.waiting_fix_page)
    dp.callback_query.register(developer_materials_edit_start, lambda c: c.data and c.data.startswith("dev_mat_edit|"))
    dp.message.register(developer_process_material_parts, DeveloperStates.waiting_material_parts)
    dp.message.register(developer_process_material_video, DeveloperStates.waiting_material_video)


    # Video Editor
    dp.callback_query.register(developer_videos_menu, lambda c: c.data == "dev_videos_menu")
    dp.callback_query.register(developer_videos_select_day, lambda c: c.data and c.data.startswith("dev_video_role|"))
    dp.callback_query.register(developer_videos_view, lambda c: c.data and c.data.startswith("dev_video_day|"))
    dp.callback_query.register(developer_video_edit_start, lambda c: c.data == "dev_video_edit")
    dp.message.register(developer_process_video_uploads, DeveloperStates.waiting_video_uploads)

    # Photo Editor
    dp.callback_query.register(developer_photos_menu, lambda c: c.data == "dev_photos_menu")
    dp.callback_query.register(developer_photos_select_day, lambda c: c.data and c.data.startswith("dev_photo_role|"))
    dp.callback_query.register(developer_photos_view, lambda c: c.data and c.data.startswith("dev_photo_day|"))
    dp.callback_query.register(developer_photo_edit_start, lambda c: c.data == "dev_photo_edit")
    dp.message.register(developer_process_photo_uploads, DeveloperStates.waiting_photo_uploads)

    # Syllabus Editor
    dp.callback_query.register(developer_syllabus_menu, lambda c: c.data == "dev_syllabus_menu")
    dp.callback_query.register(developer_syllabus_view, lambda c: c.data and c.data.startswith("dev_syl_role|"))
    dp.callback_query.register(developer_syllabus_toggle, lambda c: c.data and c.data.startswith("dev_syl_toggle:"))
    dp.callback_query.register(developer_syllabus_edit, lambda c: c.data == "dev_syl_edit")
    dp.message.register(developer_process_syllabus, DeveloperStates.waiting_syllabus_text)

    # Tests Editor
    dp.callback_query.register(developer_tests_menu, lambda c: c.data == "dev_tests_menu")
    dp.callback_query.register(developer_tests_select_day, lambda c: c.data and c.data.startswith("dev_test_role|"))
    dp.callback_query.register(developer_tests_view, lambda c: c.data and c.data.startswith("dev_test_day|"))
    dp.callback_query.register(developer_test_toggle, lambda c: c.data and c.data.startswith("dev_test_toggle:"))
    dp.callback_query.register(developer_tests_edit_start, lambda c: c.data == "dev_test_edit")
    dp.message.register(developer_tests_process_input, DeveloperStates.waiting_test_input)

    # Notification handlers
    dp.callback_query.register(notify_decision_yes, lambda c: c.data == "notify_yes")
    dp.callback_query.register(notify_decision_no, lambda c: c.data == "notify_no")
    dp.callback_query.register(notify_cancel, lambda c: c.data == "notify_cancel")
    dp.message.register(process_notify_message, DeveloperStates.waiting_notify_message)

    # Days
    dp.callback_query.register(developer_days_menu, lambda c: c.data == "dev_days_menu")
    dp.callback_query.register(developer_request_days_status, lambda c: c.data == "dev_days_status")
    dp.callback_query.register(developer_request_days_open, lambda c: c.data == "dev_days_open")
    dp.callback_query.register(developer_request_days_close, lambda c: c.data == "dev_days_close")
    dp.callback_query.register(developer_request_days_reset, lambda c: c.data == "dev_days_reset")
    dp.message.register(developer_process_days_status, DeveloperStates.waiting_days_status)
    dp.message.register(developer_process_days_open, DeveloperStates.waiting_days_open)
    dp.message.register(developer_process_days_close, DeveloperStates.waiting_days_close)
    dp.message.register(developer_process_days_reset, DeveloperStates.waiting_days_reset)

    # Dev Team Management
    dp.callback_query.register(developer_dev_team_menu, lambda c: c.data == "dev_team_menu")
    dp.callback_query.register(developer_request_add_dev, lambda c: c.data == "dev_add_dev")
    dp.callback_query.register(developer_remove_dev_menu, lambda c: c.data == "dev_remove_dev_menu")
    dp.callback_query.register(developer_remove_dev, lambda c: c.data and c.data.startswith("dev_remove_confirm:"))
    dp.callback_query.register(developer_cancel_add_role, lambda c: c.data == "dev_cancel_add_role")
    dp.message.register(developer_process_add_dev, DeveloperStates.waiting_add_developer)
    dp.message.register(developer_process_add_dev_name, DeveloperStates.waiting_add_developer_name)

    # New User Profile Actions
    dp.callback_query.register(developer_days_manage_menu, lambda c: c.data and c.data.startswith("dev_days_manage:"))
    dp.callback_query.register(developer_toggle_day_status, lambda c: c.data and c.data.startswith("dev_toggle_day:"))
    dp.callback_query.register(developer_user_profile_back, lambda c: c.data and c.data.startswith("dev_user_profile_back:"))
    dp.callback_query.register(developer_user_modify_menu, lambda c: c.data and c.data.startswith("dev_user_modify:"))
    dp.callback_query.register(developer_change_manager_start, lambda c: c.data and c.data.startswith("dev_change_manager:"))
    dp.message.register(developer_process_change_manager, DeveloperStates.waiting_change_manager_id)
    dp.callback_query.register(developer_change_role_start, lambda c: c.data and c.data.startswith("dev_change_role:"))
    dp.callback_query.register(developer_process_change_role, lambda c: c.data and c.data.startswith("dev_process_change_role:"))
    dp.callback_query.register(developer_change_city_start, lambda c: c.data and c.data.startswith("dev_change_city:"))
    dp.callback_query.register(developer_process_change_city, lambda c: c.data and c.data.startswith("dev_process_change_city:"))
    dp.callback_query.register(developer_user_delete_confirm, lambda c: c.data and c.data.startswith("dev_user_delete_confirm:"))
    dp.callback_query.register(developer_user_delete_perform, lambda c: c.data and c.data.startswith("dev_user_delete_perform:"))
    
    # HR Team Management
    dp.callback_query.register(developer_manage_hrs_menu, lambda c: c.data == "dev_hr_team_menu")
    
    # Legacy/Unified handlers (keep for MAIN_DEVELOPER_ID or specific access)
    # Removed duplicate manager handlers as they are now handled in the 'Managers' section above

    # The following handlers were moved or replaced:
    # dp.callback_query.register(developer_manage_managers_menu, lambda c: c.data == "dev_manage_managers")
    # dp.callback_query.register(developer_request_add_manager, lambda c: c.data == "dev_add_manager")
    # dp.message.register(developer_process_add_manager_id, DeveloperStates.waiting_add_manager_id)
    # dp.callback_query.register(developer_process_shop_selection, DeveloperStates.waiting_add_manager_shops, lambda c: c.data.startswith("dev_mgr_shop_toggle:"))
    # dp.callback_query.register(developer_finish_shop_selection, DeveloperStates.waiting_add_manager_shops, lambda c: c.data == "dev_mgr_shop_done")
    dp.callback_query.register(developer_remove_manager_menu, lambda c: c.data == "dev_remove_manager_menu")
    dp.callback_query.register(developer_remove_manager, lambda c: c.data and c.data.startswith("mgr_remove:"))
    dp.callback_query.register(manager_cancel_add, lambda c: c.data == "mgr_cancel_add")
    dp.callback_query.register(manager_team_back, lambda c: c.data == "mgr_team_back")
