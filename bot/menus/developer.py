import asyncio
import sys
from pathlib import Path
from aiogram import Dispatcher
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
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
)
from database.tokens import get_token_stats, cleanup_expired_tokens
from database.analytics import get_daily_stats, get_dropout_funnel
from bot.services.health import get_health_status
from bot.services.test_parser import parse_test_input, format_test_display
from bot.services.learning_progress import get_days_overview, DayStatus
from bot.services.access import get_display_role # Import get_display_role
from bot.constants import AVAILABLE_ROLES, AVAILABLE_SHOPS, AVAILABLE_CITIES
from bot.keyboards import get_pagination_keyboard # Import get_pagination_keyboard
import json


class DeveloperStates(StatesGroup):
    waiting_user_search = State()
    waiting_delete_user = State()
    waiting_add_manager_id = State()
    waiting_add_manager_city = State()
    waiting_add_manager_shops = State()
    waiting_delete_manager = State()
    waiting_days_status = State()
    waiting_days_open = State()
    waiting_days_close = State()
    waiting_days_reset = State()
    waiting_add_developer = State()
    # Стани для редагування матеріалів
    waiting_material_text = State()
    waiting_material_video = State()
    waiting_material_parts = State() # New state for multi-message input
    waiting_test_input = State() # State for editing tests
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
    if is_main_dev:
        buttons.append([
            InlineKeyboardButton(text="👨‍💻 Команда Dev", callback_data="dev_team_menu"),
            InlineKeyboardButton(text="👔 Команда Керівників", callback_data="dev_manage_managers"),
        ])
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
    Працює і для текстових повідомлень, і для повідомлень з фото+caption.
    """
    try:
        if message.photo:
            await message.edit_caption(caption=text, reply_markup=reply_markup)
            return message
        await message.edit_text(text, reply_markup=reply_markup)
        return message
    except TelegramBadRequest as e:
        error_message = str(e).lower()
        if "message to edit not found" in error_message or "there is no text in the message to edit" in error_message:
            # Якщо повідомлення не знайдено або воно не містить тексту для редагування,
            # намагаємося видалити старе і відправити нове.
            try:
                await message.delete()
            except Exception:
                pass
            return await message.answer(text, reply_markup=reply_markup)
        elif "message is not modified" in error_message:
            # Ігноруємо помилку, якщо повідомлення не змінилося
            return message
        else:
            # Інші TelegramBadRequest прокидаємо далі
            raise e
    except Exception:
        # Загальні помилки також обробляємо як надсилання нового повідомлення
        try:
            await message.delete()
        except Exception:
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


async def _refresh_panel_view(bot, panel_info: dict | None, builder):
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


async def _build_managers_team_view():
    """Список керівників (HR)."""
    hrs = await get_all_kerivnyky()
    
    lines = ["👔 <b>Команда керівників</b>", ""]
    
    if not hrs:
        lines.append("  Поки що немає")
    else:
        for hr in hrs:
            name, username = await _format_identity(
                hr["uid"],
                hr.get("full_name"),
                hr.get("username"),
            )
            display_role = await get_display_role(hr["uid"])
            lines.append(f"  • {name} · {username} · Роль: <b>{display_role}</b>")
    
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Додати керівника", callback_data="dev_add_manager")],
            [InlineKeyboardButton(text="❌ Видалити керівника", callback_data="dev_remove_manager_menu")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="developer_menu")],
        ]
    )
    return "\n".join(lines), kb


async def _build_dev_team_view() -> tuple[str, InlineKeyboardMarkup]:
    """Builds the view for the Dev Team management panel."""
    developers = await get_all_devs_from_managers_db()
    
    lines = [f"👨‍💻 <b>Команда Dev (всього: {len(developers)})</b>", ""]
    if not developers:
        lines.append("  Немає розробників у команді.")
    else:
        for dev in developers:
            name, username = await _format_identity(
                dev["uid"], dev.get("full_name"), dev.get("username")
            )
            display_role = await get_display_role(dev["uid"])
            lines.append(f"  • {name} · {username} · Роль: <b>{display_role}</b> · <code>{dev['uid']}</code>")
    
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
    if not await _ensure_developer(callback, require_main=True):
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
    if not await _ensure_developer(callback, require_main=True):
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
    if not await _ensure_developer(callback, require_main=True):
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


async def _refresh_panel_view(bot, panel_info: dict | None, builder):
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


async def _update_prompt_message(bot, prompt_info: dict | None, text: str, cancel_callback: str):
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


async def developer_list_users(callback: CallbackQuery, page: int = 0):
    """Displays a paginated list of all users."""
    if not await _ensure_developer(callback):
        return

    users = await get_all_users()
    if not users:
        await _edit_or_answer(callback.message, "База користувачів порожня.", reply_markup=_users_menu_keyboard())
        await callback.answer()
        return

    page_size = 10  # 10 користувачів на сторінці
    total_users = len(users)
    total_pages = (total_users + page_size - 1) // page_size
    
    start_offset = page * page_size
    end_offset = start_offset + page_size
    paginated_users = users[start_offset:end_offset]

    if not paginated_users and page > 0:
        # Якщо сторінка порожня, а це не перша сторінка, повертаємось на першу
        return await developer_list_users(callback, page=0)

    lines = [f"👥 <b>Всього користувачів: {total_users}</b> (Сторінка {page + 1}/{total_pages})", ""]
    
    for idx, user in enumerate(paginated_users, start=start_offset + 1):
        display_role = await get_display_role(user['user_id'])
        user_full_name = user.get('full_name', 'Без імені')
        user_username = user.get('username', 'немає')
        current_block = user.get('current_block', 1)
        
        # Витягуємо короткий номер магазину (наприклад, B-19)
        shop_full = user.get('shop', '') or ''
        shop_short = shop_full.split(' ')[0] if shop_full else 'Не вказано'
        
        lines.append(f"<b>{idx}. {user_full_name}</b> (ID: <code>{user['user_id']}</code>)")
        lines.append(f"   @{user_username} | Роль: <b>{display_role}</b> | {shop_short}")
        lines.append("───────────────") # Візуальний роздільник

    # --- Pagination Keyboard ---
    # Використовуємо get_pagination_keyboard
    # final_button тут не потрібен, оскільки "⬅️ До меню користувачів" є завжди

    pagination_buttons = []
    # Кнопки навігації (назад/вперед)
    row = []
    if page > 0:
        row.append(InlineKeyboardButton(text="⬅️ Попередня", callback_data=f"dev_users_page:{page - 1}"))
    if page < total_pages - 1:
        row.append(InlineKeyboardButton(text="Наступна ➡️", callback_data=f"dev_users_page:{page + 1}"))
    if row:
        pagination_buttons.append(row)

    # Кнопка повернення до меню користувачів
    pagination_buttons.append([InlineKeyboardButton(text="⬅️ До меню користувачів", callback_data="dev_users_menu")])
    
    await _edit_or_answer(
        callback.message,
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=pagination_buttons),
    )
    await callback.answer()

async def developer_list_users_paginated(callback: CallbackQuery):
    """Handler for user list pagination buttons."""
    try:
        page = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        page = 0
    await developer_list_users(callback, page=page)


async def developer_request_user_search(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_developer(callback):
        return
    await state.set_state(DeveloperStates.waiting_user_search)
    await _edit_or_answer(
        callback.message,
        "🔍 Введіть ID користувача або username (наприклад, 123456 або @username).",
        reply_markup=_users_menu_keyboard(),
    )
    await callback.answer()


async def developer_process_user_search(message: Message, state: FSMContext):
    query = (message.text or "").strip()
    user = None
    if query.startswith("@"):
        user = await get_user_by_username(query)
    else:
        try:
            user_id = int(query)
            user = await get_user_details(user_id)
        except ValueError:
            user = None

    if not user:
        await message.answer("❌ Користувача не знайдено. Спробуйте ще раз або натисніть /cancel.")
        return

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

async def developer_manage_managers_menu(callback: CallbackQuery, state: FSMContext):
    """Об'єднане меню керівників."""
    if not await _ensure_developer(callback, require_main=True):
        return
    text, kb = await _build_managers_team_view()
    msg = await _edit_or_answer(callback.message, text, reply_markup=kb)
    await _remember_panel(state, "managers_panel", msg or callback.message)
    await callback.answer()


async def developer_request_add_manager(callback: CallbackQuery, state: FSMContext):
    """Starts the process of adding a manager by requesting their ID."""
    if not await _ensure_developer(callback, require_main=True):
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
    """Processes the manager ID and shows the city selection menu."""
    if not message.text or not message.text.isdigit():
        await message.answer("❌ ID повинен бути числом. Спробуйте ще раз.")
        return
    
    user_id = int(message.text)
    await state.update_data(new_manager_id=user_id, selected_shops=[])
    await state.set_state(DeveloperStates.waiting_add_manager_city)
    
    buttons = []
    for city in AVAILABLE_CITIES:
        buttons.append([InlineKeyboardButton(text=city, callback_data=f"dev_mgr_city_select:{city}")])
    buttons.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="dev_manage_managers")])
    
    await message.answer(
        f"Керівник ID: {user_id}.\nТепер оберіть місто, до якого належать його магазини:",
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
    
    if not user_id:
        await callback.answer("Помилка: ID керівника не знайдено.", show_alert=True)
        return await developer_manage_managers_menu(callback, state)

    try:
        chat_info = await callback.bot.get_chat(user_id)
        full_name = chat_info.full_name
        username = chat_info.username
    except Exception:
        full_name = ""
        username = ""

    await register_user(user_id, username=username, full_name=full_name)
    await add_manager(
        uid=user_id,
        process="Керівник",
        full_name=full_name,
        username=username,
        shops=selected_shops
    )
    
    await state.clear()
    await callback.answer("✅ Керівника успішно додано/оновлено!", show_alert=True)
    await developer_manage_managers_menu(callback, state)


async def developer_remove_manager_menu(callback: CallbackQuery, state: FSMContext):
    """Меню видалення керівника."""
    if not await _ensure_developer(callback, require_main=True):
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
    if not await _ensure_developer(callback, require_main=True):
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
    if not await _ensure_developer(callback, require_main=True):
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
    if not await _ensure_developer(callback, require_main=True):
        return
    await state.clear()
    # Повертаємо користувача до меню команди розробників
    await developer_dev_team_menu(callback, state)
    await callback.answer("Додавання скасовано.")


async def developer_manage_hrs_menu(callback: CallbackQuery, state: FSMContext):
    await developer_manage_managers_menu(callback, state)


async def developer_request_add_dev(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_developer(callback, require_main=True):
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
    panel_info = data.get("dev_panel")
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
    
    # Отримуємо дані користувача напряму з Telegram API
    try:
        chat_info = await message.bot.get_chat(user_id)
        full_name = chat_info.full_name
        username = chat_info.username
    except Exception as e:
        print(f"Не вдалося отримати дані для {user_id}: {e}")
        full_name = ""
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
        f"✅ Користувача {full_name or user_id} додано до Dev-команди.\n\nВикористайте кнопку нижче, щоб повернутися.",
        "dev_team_back",
    )
    await _refresh_panel_view(message.bot, panel_info, _build_developer_team_view)


async def developer_manage_hrs_menu(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_developer(callback, require_main=True):
        return
    text, kb = await _build_hr_team_view()
    msg = await _edit_or_answer(callback.message, text, reply_markup=kb)
    await _remember_panel(state, "hr_panel", msg or callback.message)
    await callback.answer()


async def developer_request_add_hr(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_developer(callback, require_main=True):
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

    await add_manager(
        user_id,
        process="Керівник",
    )
    await state.set_state(None)
    await state.update_data(hr_prompt=None)
    await _update_prompt_message(
        message.bot,
        prompt_info,
        f"✅ Користувача {user_id} додано до HR-команди.\n\nВикористайте кнопку нижче, щоб повернутися.",
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
    if not await _ensure_developer(callback, require_main=True):
        return
    await state.set_state(None)
    await state.update_data(hr_prompt=None)
    await developer_manage_hrs_menu(callback, state)
    await callback.answer("Додавання скасовано.", show_alert=True)


async def developer_team_member_handler(callback: CallbackQuery, state: FSMContext):
    if not await _ensure_developer(callback, require_main=True):
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
    if not await _ensure_developer(callback, require_main=True):
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
    if not await _ensure_developer(callback, require_main=True):
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
    if not await _ensure_developer(callback, require_main=True):
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
        current_content = material.get("content", "")[:500]
        current_url = material.get("resource_url", "")
        material_id = material.get("id")
        await state.update_data(edit_material_id=material_id)
        
        if content_type == "text":
            preview = current_content if current_content else "(порожньо)"
            text = (
                f"📝 <b>Текстовий матеріал</b>\n\n"
                f"Посада: <b>{role}</b>\n"
                f"День: <b>{day}</b>\n\n"
                f"<b>Поточний контент:</b>\n"
                f"<code>{preview}</code>\n\n"
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
    
    buttons = [
        [InlineKeyboardButton(text="✏️ Редагувати", callback_data=f"dev_mat_edit|{content_type}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev_mat_day|{day}")],
    ]
    
    await _edit_or_answer(
        callback.message,
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
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
    text = message.text.strip()
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
            
        full_content = "\n\n".join(material_parts)
        await _finalize_material_update(message, state, full_content)
    else:
        material_parts.append(text)
        await state.update_data(material_parts=material_parts)

        new_text = f"✅ Отримано {len(material_parts)} частин тексту. Надішліть наступну частину або напишіть 'Готово', щоб завершити."

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
    """Обробка нового текстового контенту — запит на оповіщення."""
    data = await state.get_data()
    role = data.get("edit_role", "")
    day = data.get("edit_day", 1)
    material_id = data.get("edit_material_id")
    
    if not new_content:
        await message.answer("❌ Текст не може бути порожнім.")
        return
    
    # Зберігаємо новий контент у стейті для подальшого збереження
    await state.update_data(
        pending_content=new_content,
        pending_content_type="text",
        pending_material_id=material_id
    )
    
    # Запитуємо про оповіщення
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Так ✅", callback_data="notify_yes"),
            InlineKeyboardButton(text="Ні ❌", callback_data="notify_no"),
        ]
    ])
    
    await message.answer(
        f"📝 <b>Матеріал готовий до збереження</b>\n\n"
        f"Посада: {role}\n"
        f"День: {day}\n\n"
        f"<b>Чи бажаєте зробити оповіщення про зміни?</b>",
        reply_markup=kb
    )
    await state.set_state(DeveloperStates.waiting_notify_decision)


async def developer_process_material_video(message: Message, state: FSMContext):
    """Обробка нового посилання на відео — запит на оповіщення."""
    data = await state.get_data()
    role = data.get("edit_role", "")
    day = data.get("edit_day", 1)
    material_id = data.get("edit_material_id")
    new_url = message.text.strip()
    
    if not new_url:
        await message.answer("❌ Посилання не може бути порожнім.")
        return
    
    # Зберігаємо новий контент у стейті для подальшого збереження
    await state.update_data(
        pending_content=new_url,
        pending_content_type="video",
        pending_material_id=material_id
    )
    
    # Запитуємо про оповіщення
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Так ✅", callback_data="notify_yes"),
            InlineKeyboardButton(text="Ні ❌", callback_data="notify_no"),
        ]
    ])
    
    await message.answer(
        f"🎥 <b>Матеріал готовий до збереження</b>\n\n"
        f"Посада: {role}\n"
        f"День: {day}\n\n"
        f"<b>Чи бажаєте зробити оповіщення про зміни?</b>",
        reply_markup=kb
    )
    await state.set_state(DeveloperStates.waiting_notify_decision)


async def _finalize_video_update(message: Message, state: FSMContext, video_file_ids: list[str]):
    """Обробка завантажених відеофайлів — запит на оповіщення."""
    data = await state.get_data()
    role = data.get("edit_video_role", "")
    day = data.get("edit_video_day", 1)
    material_id = data.get("edit_video_material_id")
    
    if not video_file_ids:
        await message.answer("❌ Немає відеофайлів для збереження.")
        return
    
    # Зберігаємо file_id-и у стейті для подальшого збереження
    await state.update_data(
        pending_content=json.dumps(video_file_ids),
        pending_content_type="video_files", # New content type for multiple video files
        pending_material_id=material_id
    )
    
    # Запитуємо про оповіщення
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Так ✅", callback_data="notify_yes"),
            InlineKeyboardButton(text="Ні ❌", callback_data="notify_no"),
        ]
    ])
    
    await message.answer(
        f"🎥 <b>Відео матеріал готовий до збереження</b>\n\n"
        f"Посада: {role}\n"
        f"День: {day}\n\n"
        f"Завантажено відеофайлів: {len(video_file_ids)}\n\n"
        f"<b>Чи бажаєте зробити оповіщення про зміни?</b>",
        reply_markup=kb
    )
    await state.set_state(DeveloperStates.waiting_notify_decision)


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


async def developer_tests_view(callback: CallbackQuery, state: FSMContext):
    """Перегляд поточного тесту."""
    if not await _ensure_developer(callback):
        return
    
    data = await state.get_data()
    
    try:
        parts = callback.data.split("|")
        if len(parts) == 3: # dev_test_day|{day}|{role_index}
            day = int(parts[1])
            role_index = int(parts[2])
        else: # old format: dev_test_day|{day}
            day = int(parts[1])
            role_index = data.get("test_role_index", 0) # Fallback to stored role index
        role = AVAILABLE_ROLES[role_index]
    except (ValueError, IndexError):
        await callback.answer("Помилка дня або ролі.", show_alert=True)
        return
    
    # role is already determined above from AVAILABLE_ROLES[role_index]
    # update state with current day/role if needed, though role is derived
    await state.update_data(test_day=day, test_role=role, test_role_index=role_index)
    
    test_material = await get_test_by_role_and_day(role, day)
    
    display_text = "Тест ще не створено."
    
    if test_material and test_material.get("content"):
        try:
            current_questions = json.loads(test_material["content"])
            formatted = format_test_display(current_questions)
            display_text = formatted if formatted else "Тест порожній."
        except json.JSONDecodeError:
            display_text = "⚠️ Помилка формату даних тесту."
    
    text = (
        f"📝 <b>Тест: {role} — День {day}</b>\n\n"
        f"{display_text}\n\n"
        f"Натисніть «Редагувати», щоб змінити або створити тест."
    )
    
    buttons = [
        [InlineKeyboardButton(text="✏️ Редагувати", callback_data="dev_test_edit")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"dev_test_role|{data.get('test_role_index')}")]
    ]
    
    await _edit_or_answer(
        callback.message,
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()

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
    
    if current_file_ids:
        preview = f"Завантажено фотофайлів: {len(current_file_ids)}"
        text = (
            f"🖼 <b>Фото матеріал</b>\n\n"
            f"Посада: <b>{role}</b>\n"
            f"День: <b>{day}</b>\n\n"
            f"<b>Поточний контент:</b>\n"
            f"{preview}\n\n"
            f"Натисніть «Редагувати», щоб змінити фотофайли."
        )
    else:
        text = (
            f"🖼 <b>Фото матеріал не знайдено</b>\n\n"
            f"Посада: <b>{role}</b>\n"
            f"День: <b>{day}</b>\n\n"
            f"Натисніть «Редагувати», щоб завантажити новий фото матеріал."
        )
    
    buttons = [
        [InlineKeyboardButton(text="✏️ Редагувати", callback_data="dev_photo_edit")],
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
    """Обробка завантажених фотофайлів — запит на оповіщення."""
    data = await state.get_data()
    role = data.get("edit_photo_role", "")
    day = data.get("edit_photo_day", 1)
    material_id = data.get("edit_photo_material_id")
    
    if not photo_file_ids:
        await message.answer("❌ Немає фотофайлів для збереження.")
        return
    
    # Зберігаємо file_id-и у стейті для подальшого збереження
    await state.update_data(
        pending_content=json.dumps(photo_file_ids),
        pending_content_type="photo_files", 
        pending_material_id=material_id,
        edit_role=role,
        edit_day=day
    )
    
    # Запитуємо про оповіщення
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Так ✅", callback_data="notify_yes"),
            InlineKeyboardButton(text="Ні ❌", callback_data="notify_no"),
        ]
    ])
    
    await message.answer(
        f"🖼 <b>Фото матеріал готовий до збереження</b>\n\n"
        f"Посада: {role}\n"
        f"День: {day}\n\n"
        f"Завантажено фотофайлів: {len(photo_file_ids)}\n\n"
        f"<b>Чи бажаєте зробити оповіщення про зміни?</b>",
        reply_markup=kb
    )
    await state.set_state(DeveloperStates.waiting_notify_decision)


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

async def developer_syllabus_view(callback: CallbackQuery, state: FSMContext):
    """Перегляд поточного змісту для обраної посади."""
    if not await _ensure_developer(callback):
        return
    
    try:
        _, role_part = callback.data.split("|", 1)
        role_index = int(role_part)
        role = AVAILABLE_ROLES[role_index]
    except (ValueError, IndexError):
        await callback.answer("Помилка ролі.", show_alert=True)
        return
    
    await state.update_data(syllabus_role=role, syllabus_role_index=role_index)
    
    # Syllabus is stored with day=0 and content_type='syllabus'
    syllabus_material = await get_material_by_role_day_type(role, 0, "syllabus")
    
    content = syllabus_material.get("content", "") if syllabus_material else ""
    display_content = content[:500] + "..." if len(content) > 500 else (content or "(порожньо)")
    
    text = (
        f"📚 <b>Зміст: {role}</b>\n\n"
        f"{display_content}\n\n"
        f"Натисніть «Редагувати», щоб змінити текст змісту."
    )
    
    buttons = [
        [InlineKeyboardButton(text="✏️ Редагувати", callback_data="dev_syl_edit")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="dev_syllabus_menu")]
    ]
    
    await _edit_or_answer(
        callback.message,
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()

async def developer_syllabus_edit(callback: CallbackQuery, state: FSMContext):
    """Початок редагування змісту."""
    if not await _ensure_developer(callback):
        return
        
    data = await state.get_data()
    role = data.get("syllabus_role", "")
    
    text = (
        f"✏️ <b>Редагування змісту: {role}</b>\n\n"
        f"Надішліть новий текст змісту. Ви можете використовувати HTML-розмітку."
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
    """Меню управління токенами."""
    if not await _ensure_developer(callback):
        return
    
    stats = await get_token_stats()
    
    text = (
        "🎟 <b>Управління токенами</b>\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"• Активні: <b>{stats.get('active', 0)}</b>\n"
        f"• Використані: <b>{stats.get('used', 0)}</b>\n"
        f"• Прострочені: <b>{stats.get('expired', 0)}</b>\n"
        f"• Всього: <b>{stats.get('total', 0)}</b>"
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
    """Показує статус здоров'я бота."""
    if not await _ensure_developer(callback):
        return
    
    status = get_health_status()
    
    health_icon = "✅" if status["status"] == "healthy" else "❌"
    scheduler_icon = "✅" if status["scheduler_healthy"] else "❌"
    reminder_icon = "✅" if status["reminder_healthy"] else "❌"
    
    text = (
        f"💚 <b>Health Status</b>\n\n"
        f"{health_icon} Загальний статус: <b>{status['status']}</b>\n\n"
        f"<b>Компоненти:</b>\n"
        f"{scheduler_icon} Scheduler\n"
        f"{reminder_icon} Reminder Loop\n\n"
        f"<b>Статистика:</b>\n"
        f"⏱ Uptime: {status['uptime_human']}\n"
        f"❌ Помилок: {status['errors_count']}\n\n"
        f"<b>Останні heartbeats:</b>\n"
        f"📅 Scheduler: {status['last_scheduler_heartbeat'] or 'N/A'}\n"
        f"🔔 Reminder: {status['last_reminder_heartbeat'] or 'N/A'}\n"
        f"🧹 Token cleanup: {status['last_token_cleanup'] or 'N/A'}"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Оновити", callback_data="dev_health_status")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="developer_menu")],
    ])
    
    await _edit_or_answer(callback.message, text, reply_markup=kb)
    await callback.answer()


# ... (previous code) ...

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

async def developer_days_manage_menu(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split(":")[1])
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
    # Create a mock callback to pass to the menu function
    from aiogram.types import User
    mock_callback = callback
    mock_callback.data = f"dev_days_manage:{user_id}"
    await developer_days_manage_menu(mock_callback, state)

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
    
    logs = await get_reminder_history(limit=20)
    
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

    lines = ["📜 <b>Історія нагадувань (останні 20)</b>", ""]
    
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
            
        lines.append(f"{icon} <b>{sent_at}</b> → {intern_name}")
        lines.append(f"   <i>Від: {by_whom}</i>")
        lines.append("")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Оновити", callback_data="dev_reminder_history")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="developer_menu")]
    ])
    
    await _edit_or_answer(callback.message, "\n".join(lines), reply_markup=kb)
    await callback.answer()


    
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
        
    data = await get_dropout_funnel()
    total = data['total_users']
    dist = data['distribution']
    
    lines = [
        "📉 <b>Воронка відсіву</b>",
        f"Всього користувачів: <b>{total}</b>",
        "",
        "<b>Розподіл по поточному дню:</b>"
    ]
    
    # Sort keys just in case
    sorted_days = sorted(dist.keys())
    
    for day in sorted_days:
        count = dist[day]
        percent = (count / total * 100) if total > 0 else 0
        # Simple visual bar
        bar_len = int(percent / 5)
        bar = "█" * bar_len
        
        day_label = f"День {day}" if day <= DAYS_TOTAL else "✅ Завершили"
        
        lines.append(f"{day_label}: <b>{count}</b> ({percent:.1f}%)")
        lines.append(f"<pre>{bar}</pre>")
    
    lines.append("")
    lines.append("<i>* Показує, на якому етапі зараз знаходяться користувачі.</i>")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
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
    dp.callback_query.register(developer_list_users_paginated, lambda c: c.data and c.data.startswith("dev_users_page:"))
    dp.callback_query.register(developer_request_user_search, lambda c: c.data == "dev_users_search")
    dp.callback_query.register(developer_request_delete_user, lambda c: c.data == "dev_users_delete")
    dp.message.register(developer_process_user_search, DeveloperStates.waiting_user_search)
    dp.message.register(developer_process_delete_user, DeveloperStates.waiting_delete_user)

    # Managers Team Management
    dp.callback_query.register(developer_manage_managers_menu, lambda c: c.data == "dev_manage_managers")
    dp.callback_query.register(developer_list_managers, lambda c: c.data == "dev_managers_list")
    dp.callback_query.register(developer_request_add_manager, lambda c: c.data == "dev_add_manager")
    dp.message.register(developer_process_add_manager_id, DeveloperStates.waiting_add_manager_id)
    dp.callback_query.register(developer_process_add_manager_city, DeveloperStates.waiting_add_manager_city, lambda c: c.data.startswith("dev_mgr_city_select:"))
    dp.callback_query.register(developer_process_shop_selection, DeveloperStates.waiting_add_manager_shops, lambda c: c.data.startswith("dev_mgr_shop_toggle:"))
    dp.callback_query.register(developer_finish_shop_selection, DeveloperStates.waiting_add_manager_shops, lambda c: c.data == "dev_mgr_shop_done")
    dp.callback_query.register(developer_remove_manager_menu, lambda c: c.data == "dev_remove_manager_menu")
    dp.callback_query.register(developer_remove_manager, lambda c: c.data and c.data.startswith("mgr_remove:"))
    dp.callback_query.register(manager_cancel_add, lambda c: c.data == "mgr_cancel_add")
    dp.callback_query.register(manager_team_back, lambda c: c.data == "mgr_team_back")

    # Tokens & Health
    dp.callback_query.register(developer_tokens_menu, lambda c: c.data == "dev_tokens_menu")
    dp.callback_query.register(developer_tokens_cleanup, lambda c: c.data == "dev_tokens_cleanup")
    dp.callback_query.register(developer_health_status, lambda c: c.data == "dev_health_status")

    # Materials Editor
    dp.callback_query.register(developer_materials_menu, lambda c: c.data == "dev_materials_menu")
    dp.callback_query.register(developer_materials_select_day, lambda c: c.data and c.data.startswith("dev_mat_role|"))
    dp.callback_query.register(developer_materials_select_type, lambda c: c.data and c.data.startswith("dev_mat_day|"))
    dp.callback_query.register(developer_materials_view, lambda c: c.data and c.data.startswith("dev_mat_type|"))
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
    dp.callback_query.register(developer_syllabus_edit, lambda c: c.data == "dev_syl_edit")
    dp.message.register(developer_process_syllabus, DeveloperStates.waiting_syllabus_text)

    # Tests Editor
    dp.callback_query.register(developer_tests_menu, lambda c: c.data == "dev_tests_menu")
    dp.callback_query.register(developer_tests_select_day, lambda c: c.data and c.data.startswith("dev_test_role|"))
    dp.callback_query.register(developer_tests_view, lambda c: c.data and c.data.startswith("dev_test_day|"))
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
