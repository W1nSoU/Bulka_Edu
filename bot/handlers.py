"""
This file contains all the handlers for the bot.
"""
from aiogram import Dispatcher, types
from typing import List, Optional
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile, InputMediaPhoto, Message, ErrorEvent
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from bot.state import get_progress, get_available_day, user_progress, initialize_user_progress, SearchStates
from bot.keyboards import main_menu_keyboard, learning_menu_keyboard, manager_menu_keyboard, get_pagination_keyboard
from bot.config import DAYS_TOTAL, TIMEZONE
# from days.day_handlers import register_day_handlers
from datetime import datetime
from pathlib import Path
import textwrap
import pytz
import aiosqlite
import json
import asyncio
import re
import html
from database.users import (
    register_user, update_progress, get_user_progress, set_intern_extra,
    get_user_details, get_manager_interns, get_inactive_interns_for_manager, get_interns_in_progress_for_manager,
    can_start_conversation, create_conversation, close_conversation, MAX_OPEN_CONVERSATIONS,
    log_support_request
)
from database.managers import (
    get_manager_by_uid, is_territorial_user, is_observer_user, is_manager_user, add_observer
)
from database.tokens import get_token_data, use_token
from database import DB_PATH
from bot.menus.developer import register_developer_menu_handlers
from days.day_handlers import register_day_handlers
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database.hr import is_hr_user, is_developer_user
from bot.services.materials_service import (
    load_grouped_materials,
    describe_available_types,
    type_button_payload,
    CONTENT_TYPE_ORDER,
    CONTENT_TYPE_METADATA,
)
from bot.services.learning_progress import (
    DayStatus,
    get_days_overview,
    get_day_status,
    open_day_manual,
    close_day,
)
from bot.services.reminders import send_intern_reminder
from bot.services.access import is_privileged_user, validate_user_id, parse_callback_id
from bot.services.semantic_search import semantic_search
from bot.services.groq_ai import search_with_ai, is_groq_configured
from bot.services.openai_ai import ask_gpt_tutor, is_openai_configured
from bot.services.logger import get_logger
from bot.services.test_error_monitoring_service import get_test_error_statistics
from database.materials import get_materials_for_day, search_materials as search_materials_db, get_all_materials, get_material_by_id, get_material_by_role_day_type, get_test_by_role_and_day
from bot.constants import is_valid_role, is_valid_city
from typing import List, Optional, cast
from bot.utils.paginator import split_text

BASE_DIR = Path(__file__).resolve().parent.parent
IMG_DIR = BASE_DIR / "img"
SEMANTIC_MIN_KEYWORD_RESULTS = 5
SEMANTIC_RESULT_LIMIT = 10

class SupportStates(StatesGroup):
    waiting_for_message = State()

class ManagerReplyStates(StatesGroup):
    waiting_for_reply = State()

class RegistrationStates(StatesGroup):
    waiting_for_full_name = State()

async def start_menu(message: types.Message, state: FSMContext):
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    user_id = message.from_user.id
    is_observer = await is_observer_user(user_id)
    is_developer = await is_developer_user(user_id)
    is_territorial = await is_territorial_user(user_id)
    is_manager = await is_manager_user(user_id)
    is_hr = await is_hr_user(user_id)

    if is_observer:
        await show_observer_main_menu(
            message,
            allow_edit=False,
        )
        return

    if is_developer or is_territorial:
        await show_developer_main_menu(
            message,
            is_hr=is_hr,
            is_developer=is_developer,
            is_territorial=is_territorial,
            allow_edit=False,
        )
        return

    if is_manager or is_hr:
        await show_manager_main_menu(
            message,
            is_hr=is_hr,
            is_developer=is_developer,
            allow_edit=False,
        )
        return
    
    # Перевірка: якщо керівник звільнений в managers.db — доступ заборонено
    from database.managers import get_manager_by_uid
    mgr_record = await get_manager_by_uid(user_id)
    if mgr_record and mgr_record.get("status") == "fired":
        await message.answer(
            "⚠️ <b>Доступ обмежено</b> ⚠️\n\n"
            "Вибачте, але ваш обліковий запис деактивовано."
        )
        return

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT user_id, role FROM users WHERE user_id = ?", (user_id,))
        existing_user = await cursor.fetchone()
    
    valid_referral = False
    if message.text.startswith("/start") and len(args) > 0:
        start_arg = args[0]
        parts = start_arg.split('-')
        
        if len(parts) == 2:
            try:
                manager_id = int(parts[0])
            except ValueError:
                await message.answer(
                    "⚠️ <b>Помилка реєстрації!</b>\n\n"
                    "Посилання має некоректний формат. "
                    "Попросіть керівника надіслати нове запрошення."
                )
                return
            token = parts[1]
            
            token_data = await get_token_data(token)
            
            if token_data.get("status") == "ok":
                role = token_data["role"]
                city = token_data["city"]
                shop = token_data.get("shop")  # Get shop from token data
                shops = token_data.get("shops") or ([shop] if shop else [])
                extra_data = token_data.get("extra_data") or {}
                transfer_on_reg = token_data.get("transfer_on_reg", 0)
                is_valid_payload, error_text = _validate_invite_payload(role, city)
                if not is_valid_payload:
                    await message.answer(error_text)
                    return
                
                # Start registration flow
                await state.update_data(
                    reg_manager_id=manager_id,
                    reg_role=role,
                    reg_city=city,
                    reg_shop=shop,
                    reg_shops=shops,
                    reg_extra_data=extra_data,
                    reg_transfer_on_reg=transfer_on_reg,
                    reg_token=token
                )
                await state.set_state(RegistrationStates.waiting_for_full_name)
                await message.answer(
                    "Вітаю в команді BULKA! 🥐\n\n"
                    "Будь ласка, напишіть ваше <b>Прізвище Ім'я По батькові (ПІБ)</b> для завершення реєстрації."
                )
                return

            elif token_data.get("status") == "expired":
                await message.answer(
                    "⚠️ <b>Помилка реєстрації!</b>\n\n"
                    "Посилання, за яким ви перейшли, <b>протерміновано</b>. "
                    "Термін дії посилання — 24 години.\n\n"
                    "Зверніться до свого керівника за новим посиланням."
                )
                return
            elif token_data.get("status") == "already_used":
                await message.answer(
                    "⚠️ <b>Помилка реєстрації!</b>\n\n"
                    "Це посилання <b>вже було використане</b> для реєстрації.\n\n"
                    "Зверніться до свого керівника за новим посиланням."
                )
                return
            elif token_data.get("status") == "not_found":
                await message.answer(
                    "⚠️ <b>Помилка реєстрації!</b>\n\n"
                    "Недійсне посилання для реєстрації.\n\n"
                    "Зверніться до свого керівника за коректним посиланням."
                )
                return
        elif len(parts) >= 4:
            try:
                import urllib.parse
                manager_id = int(parts[0])
                role = urllib.parse.unquote(parts[1])
                city = urllib.parse.unquote(parts[2])
                shop = urllib.parse.unquote(parts[3]) if len(parts) >= 4 else None # Get shop from deep-link
                is_valid_payload, error_text = _validate_invite_payload(role, city)
                if not is_valid_payload:
                    await message.answer(error_text)
                    return
                
                # Start registration flow
                await state.update_data(
                    reg_manager_id=manager_id,
                    reg_role=role,
                    reg_city=city,
                    reg_shop=shop
                )
                await state.set_state(RegistrationStates.waiting_for_full_name)
                await message.answer(
                    "Вітаю в команді BULKA! 🥐\n\n"
                    "Будь ласка, напишіть ваше <b>Прізвище Ім'я По батькові (ПІБ)</b> для завершення реєстрації."
                )
                return
                
            except Exception as e:
                print(f"Помилка обробки deep-link параметрів: {e}")

    is_privileged = await is_privileged_user(user_id)

    if not existing_user and not valid_referral:
        if is_privileged:
            await register_user(
                user_id,
                username=message.from_user.username,
                full_name=message.from_user.full_name,
            )
        else:
            await message.answer(
                "⚠️ <b>Доступ обмежено</b> ⚠️\n\n"
                "Вибачте, але у вас немає доступу до корпоративної навчальної платформи BULKA.\n\n"
                "Доступ надається виключно працівникам компанії за запрошенням від керівника.\n\n"
                "Якщо ви співробітник компанії, будь ласка, зверніться до свого керівника для отримання посилання-запрошення."
            )
            return

    # Додатковий захист: якщо користувач має керівну роль, але не має активних привілеїв, блокуємо доступ
    if existing_user and not valid_referral:
        u_role = existing_user["role"]
        from database.users import MANAGEMENT_ROLES
        if u_role in MANAGEMENT_ROLES and not (is_manager or is_territorial or is_developer or is_hr or is_observer):
            await message.answer(
                "⚠️ <b>Доступ обмежено</b> ⚠️\n\n"
                "Вибачте, але у вас немає доступу до корпоративної навчальної платформи BULKA.\n\n"
                "Доступ надається виключно діючим працівникам компанії."
            )
            return

    initialize_user_progress(user_id)
    await show_student_main_menu(
        message,
        user_id,
        is_hr=is_hr,
        is_developer=is_developer,
        allow_edit=False,
    )

async def show_developer_main_menu(
    message: types.Message,
    *,
    is_hr: bool = False,
    is_developer: bool = False,
    is_territorial: bool = False,
    allow_edit: bool = True,
    force_new_message: bool = False,
) -> None:
    caption = (
        "🛠 <b>Панель управління BULKA</b>\n\n"
        "Вітаємо в системі! Оберіть дію:"
    )
    keyboard = main_menu_keyboard(is_hr=is_hr, is_developer=is_developer, is_territorial=is_territorial)
    
    photo_file = (
        "ter_manager/ter_menu.jpg"
        if is_territorial and (IMG_DIR / "ter_manager" / "ter_menu.jpg").exists()
        else "admin/admin_menu.jpg"
    )
    
    if force_new_message:
        if message:
            try:
                await message.delete()
            except Exception:
                pass
        await message.answer_photo(
            photo=FSInputFile(IMG_DIR / photo_file),
            caption=caption,
            reply_markup=keyboard,
        )
        return
        
    await _show_photo_menu(
        message,
        photo_file,
        caption,
        keyboard,
        allow_edit=allow_edit,
    )

async def show_observer_main_menu(
    message: types.Message,
    *,
    allow_edit: bool = True,
    force_new_message: bool = False,
) -> None:
    caption = (
        "👁 <b>Панель управління BULKA (Наглядач)</b>\n\n"
        "Вітаємо в системі! Оберіть дію:"
    )
    keyboard = main_menu_keyboard(is_observer=True)
    
    if force_new_message:
        if message:
            try:
                await message.delete()
            except Exception:
                pass
        await message.answer_photo(
            photo=FSInputFile(IMG_DIR / "admin" / "admin_menu.jpg"),
            caption=caption,
            reply_markup=keyboard,
        )
        return
        
    await _show_photo_menu(
        message,
        "admin/admin_menu.jpg",
        caption,
        keyboard,
        allow_edit=allow_edit,
    )


async def all_available_tests_completed(user_id):
    overview = await get_days_overview(user_id)
    return all(
        status == DayStatus.COMPLETED
        for _, status in overview
        if status != DayStatus.CLOSED
    )

async def menu_days(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_details = None
    
    user_details = await get_user_details(user_id)
    is_privileged = await is_privileged_user(user_id)
    if is_privileged:
        if not user_details:
            user_details = {
                "user_id": user_id,
                "manager_id": None,
                "role": None,
                "city": None,
            }
    else:
        has_role = bool(user_details and user_details.get('role'))
        is_worker = bool(user_details and (user_details.get('status') == 'Працівник' or user_details.get('is_worker')))
        has_manager = bool(user_details and user_details.get('manager_id'))
        
        if not user_details or not has_role or (not is_worker and not has_manager):
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Доступ заблоковано", callback_data="none")]
            ])
            access_denied_msg = (
                "⚠️ <b>Доступ обмежено</b> ⚠️\n\n"
                "Вибачте, але у вас немає доступу до корпоративної навчальної платформи BULKA.\n\n"
                "Доступ надається виключно працівникам компанії за запрошенням від керівника.\n\n"
                "Якщо ви співробітник компанії, будь ласка, зверніться до свого керівника для отримання посилання-запрошення."
            )
            try:
                if callback.message:
                    await callback.message.edit_text(access_denied_msg, reply_markup=kb)
            except Exception:
                if callback.message:
                    await callback.message.answer(access_denied_msg, reply_markup=kb)
            await callback.answer("Доступ заблоковано", show_alert=True)
            return
    
    from bot.state import sync_user_progress_cache
    await sync_user_progress_cache(user_id)
    user_role = user_details.get('role', 'ALL') if user_details else 'ALL'
    day_overview = await get_days_overview(user_id, role=user_role)
    
    try:
        await callback.answer()
    except Exception as e:
        print(f"Не вдалося відповісти на callback: {e}")
    
    # Перевіряємо чи увімкнено зміст для цієї ролі
    syllabus = await get_material_by_role_day_type(user_role, 0, "syllabus")
    is_syl_enabled = bool(syllabus.get('is_enabled', 1)) if syllabus else True

    photo_file = (
        "kerivn_books_study.jpg"
        if (IMG_DIR / "kerivn_books_study.jpg").exists() or (IMG_DIR / "manager" / "kerivn_books_study.jpg").exists()
        else "b_start.jpg"
    )

    if callback.message:
        await _show_photo_menu(
            callback.message,
            photo_file,
            "Оберіть день для навчання:",
            learning_menu_keyboard(day_overview, syllabus_enabled=is_syl_enabled, total_days=len(day_overview), page=0),
            allow_edit=True,
        )

async def menu_days_page_callback(callback: CallbackQuery):
    """Обробляє перемикання сторінок у меню днів навчання."""
    user_id = callback.from_user.id
    try:
        page = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        page = 0

    user_details = await get_user_details(user_id)
    user_role = user_details.get('role', 'ALL') if user_details else 'ALL'
    
    from bot.state import sync_user_progress_cache
    await sync_user_progress_cache(user_id)
    day_overview = await get_days_overview(user_id, role=user_role)
    
    syllabus = await get_material_by_role_day_type(user_role, 0, "syllabus")
    is_syl_enabled = bool(syllabus.get('is_enabled', 1)) if syllabus else True

    kb = learning_menu_keyboard(
        day_overview,
        syllabus_enabled=is_syl_enabled,
        total_days=len(day_overview),
        page=page
    )
    
    try:
        await callback.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        pass
    await callback.answer()


async def material_notification_page_callback(callback: CallbackQuery):
    """Обробляє пагінацію сторінок у повідомленні про зміну матеріалів."""
    try:
        _, event_id_str, recipient_id_str, page_str = callback.data.split(":")
        event_id = int(event_id_str)
        recipient_id = int(recipient_id_str)
        page = int(page_str)
    except (ValueError, IndexError):
        await callback.answer()
        return

    from database.material_notifications import get_event_by_id, get_recipient_by_id
    from bot.services.wave_broadcaster import format_material_notification_text, build_material_notification_keyboard

    event = await get_event_by_id(event_id)
    recipient = await get_recipient_by_id(recipient_id)
    if not event or not recipient:
        await callback.answer("Матеріал не знайдено.")
        return

    pages = json.loads(event.get("pages_json", "[]"))
    if not pages:
        pages = [event.get("description", "Оновлено матеріали")]

    total_pages = len(pages)
    page = max(0, min(page, total_pages - 1))
    
    is_acknowledged = bool(recipient.get("acknowledged_at"))
    new_text = format_material_notification_text(event["role"], event["day"], pages[page], page, total_pages)
    kb = build_material_notification_keyboard(event_id, recipient_id, page, total_pages, is_acknowledged=is_acknowledged)

    try:
        await callback.message.edit_text(new_text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass
    await callback.answer()


async def material_notification_ack_callback(callback: CallbackQuery):
    """Обробляє натискання кнопки «Зі змінами ознайомлений/а»."""
    try:
        _, event_id_str, recipient_id_str = callback.data.split(":")
        event_id = int(event_id_str)
        recipient_id = int(recipient_id_str)
    except (ValueError, IndexError):
        await callback.answer()
        return

    user_id = callback.from_user.id
    from database.material_notifications import mark_recipient_acknowledged, get_event_by_id
    from bot.services.wave_broadcaster import build_material_notification_keyboard

    success, is_late = await mark_recipient_acknowledged(event_id, user_id)
    if not success:
        await callback.answer("Не вдалося зафіксувати ознайомлення.", show_alert=True)
        return

    event = await get_event_by_id(event_id)
    total_pages = 1
    if event:
        try:
            pages = json.loads(event.get("pages_json", "[]"))
            total_pages = max(1, len(pages))
        except Exception:
            total_pages = 1

    # Оновлюємо клавіатуру на останній сторінці
    kb = build_material_notification_keyboard(event_id, recipient_id, total_pages - 1, total_pages, is_acknowledged=True)
    try:
        await callback.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        pass

    if is_late:
        await callback.answer("⏳ Ви ознайомились зі змінами (зафіксовано після 72 годин).", show_alert=True)
    else:
        await callback.answer("✅ Дякуємо! Ви успішно ознайомились зі змінами.", show_alert=True)


async def locked_day(callback: CallbackQuery):
    try:
        await callback.answer(
            "🐾Мууррр.. Молодець, хороша робота! Наступний етап навчання відкриється завтра - не пропусти нові цікаві матеріали!" 
            if await all_available_tests_completed(callback.from_user.id) 
            else "Пройдіть попередній етап навчання, перш ніж почати цей",
            show_alert=True
        )
    except Exception as e:
        print(f"Помилка відповіді на callback: {e}")

async def _ensure_learning_access(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_details = await get_user_details(user_id)
    is_privileged = await is_privileged_user(user_id)

    if is_privileged:
        if not user_details:
            user_details = {
                "user_id": user_id,
                "manager_id": None,
                "role": None,
                "city": None,
            }
        return user_details
    if user_details and user_details.get('manager_id') and user_details.get('role'):
        return user_details

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Доступ заблоковано", callback_data="none")]
    ])
    
    access_denied_msg = (
        "⚠️ <b>Доступ обмежено</b> ⚠️\n\n"
        "Вибачте, але у вас немає доступу до корпоративної навчальної платформи BULKA.\n\n"
        "Доступ надається виключно працівникам компанії за запрошенням від керівника.\n\n"
        "Якщо ви співробітник компанії, будь ласка, зверніться до свого керівника для отримання посилання-запрошення."
    )
    
    try:
        if callback.message:
            await callback.message.edit_text(access_denied_msg, reply_markup=kb)
    except Exception:
        if callback.message:
            await callback.message.answer(access_denied_msg, reply_markup=kb)
        
    await callback.answer("Доступ заблоковано", show_alert=True)
    return None

def _build_test_callback(day: int) -> str:
    return f"day{day}_test"

async def _has_completed_course(user_id: int, role: Optional[str] = None) -> bool:
    overview = await get_days_overview(user_id, role=role)
    for day_num, status in overview:
        if status == DayStatus.CLOSED:
            return False
    return True

async def _all_days_accessible(user_id: int, role: Optional[str] = None) -> bool:
    overview = await get_days_overview(user_id, role=role)
    for day_num, status in overview:
        if status == DayStatus.CLOSED:
            return False
    return True

def _build_snippet(text: str, limit: int = 240) -> str:
    clean = (text or "").strip()
    if len(clean) <= limit:
        return clean
    return textwrap.shorten(clean, width=limit, placeholder="…")

def _validate_invite_payload(role: Optional[str], city: Optional[str]) -> tuple[bool, Optional[str]]:
    if role in ["Наглядач", "Територіал", "Керівник", "Керівник Стажер"]:
        return True, None
    if not is_valid_role(role):
        return False, (
            "⚠️ <b>Помилка реєстрації!</b>\n\n"
            "Посада у запрошенні не знайдена в довіднику. "
            "Попросіть керівника або HR надіслати актуальне посилання."
        )
    if not is_valid_city(city):
        return False, (
            "⚠️ <b>Помилка реєстрації!</b>\n\n"
            "Місто у запрошенні не підтримується. "
            "Повідомте HR, щоб оновити довідник локацій."
    )
    return True, None

async def _show_text_menu(
    message: types.Message,
    text: str,
    reply_markup: InlineKeyboardMarkup,
    *,
    allow_edit: bool = True,
    allow_caption_edit: bool = True,
) -> None:
    if allow_caption_edit and allow_edit and getattr(message, "photo", None):
        try:
            await message.edit_caption(caption=text, reply_markup=reply_markup)
            return
        except Exception:
            pass
    if allow_edit:
        try:
            await message.edit_text(text, reply_markup=reply_markup)
            return
        except Exception:
            pass
        try:
            await message.delete()
        except Exception:
            pass
    await message.answer(text, reply_markup=reply_markup)

async def _show_photo_menu(
    message: types.Message,
    photo_filename: str,
    caption: str,
    reply_markup: InlineKeyboardMarkup,
    *,
    allow_edit: bool = True,
) -> None:
    photo_path = IMG_DIR / photo_filename
    if not photo_path.exists():
        if (IMG_DIR / "manager" / photo_filename).exists():
            photo_path = IMG_DIR / "manager" / photo_filename
        elif (IMG_DIR / "admin" / photo_filename).exists():
            photo_path = IMG_DIR / "admin" / photo_filename
        elif (IMG_DIR / "ter_manager" / photo_filename).exists():
            photo_path = IMG_DIR / "ter_manager" / photo_filename
        else:
            await _show_text_menu(message, caption, reply_markup, allow_edit=allow_edit)
            return

    has_photo = bool(getattr(message, "photo", None))
    if allow_edit and has_photo:
        try:
            media = InputMediaPhoto(media=FSInputFile(str(photo_path)), caption=caption, parse_mode="HTML")
            await message.edit_media(media=media, reply_markup=reply_markup)
            return
        except Exception:
            pass
        try:
            await message.edit_caption(caption=caption, reply_markup=reply_markup, parse_mode="HTML")
            return
        except Exception:
            pass

    # If message was text-only or edit failed, safely delete old message and send photo
    if message:
        try:
            await message.delete()
        except Exception:
            pass

    await message.answer_photo(
        photo=FSInputFile(str(photo_path)),
        caption=caption,
        reply_markup=reply_markup,
        parse_mode="HTML",
    )

async def show_student_main_menu(
    message: types.Message,
    user_id: int,
    *,
    is_hr: bool = False,
    is_developer: bool = False,
    allow_edit: bool = True,
    force_new_message: bool = False,
) -> None:
    # Захист: якщо користувач має керівну посаду, але не є активним керівником/територіалом/адміном - не показуємо меню стажера
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT role FROM users WHERE user_id = ?", (user_id,))
        u_row = await cursor.fetchone()
        if u_row:
            from database.users import MANAGEMENT_ROLES
            if u_row["role"] in MANAGEMENT_ROLES and not (is_hr or is_developer):
                from database.managers import is_manager_user, is_observer_user, is_territorial_user
                if not (await is_manager_user(user_id) or await is_observer_user(user_id) or await is_territorial_user(user_id)):
                    await message.answer(
                        "⚠️ <b>Доступ обмежено</b> ⚠️\n\n"
                        "Вибачте, але у вас немає доступу до корпоративної навчальної платформи BULKA."
                    )
                    return

    from bot.state import sync_user_progress_cache
    await sync_user_progress_cache(user_id)
    user_details = await get_user_details(user_id)
    user_role = user_details.get('role') if user_details else None
    from database.positions import get_days_count_for_role
    role_days = await get_days_count_for_role(user_role) if user_role else DAYS_TOTAL

    progress_count = get_progress(user_id)
    available_day = get_available_day(user_id, total_days=role_days)
    is_worker = bool(user_details and (user_details.get('status') == 'Працівник' or user_details.get('is_worker')))

    if is_worker:
        percent = 100
        all_completed = True
        all_open_or_completed = True
    else:
        percent = int(progress_count / role_days * 100) if role_days else 0
        all_completed = progress_count >= role_days
        all_open_or_completed = await _all_days_accessible(user_id, role=user_role)

    is_new_user = progress_count == 0 and not is_worker
    can_search = all_completed or all_open_or_completed

    caption = (
        "🍞 <b>Твій булочковий прогрес</b> 🏆\n\n"
        f"🔹 Пройдено: <b>{percent}%</b>\n"
        f"🔹 Отримано матеріалів: <b>{progress_count if not is_worker else role_days}</b>\n"
        f"🔹 Сьогоднішній день: <b>#{available_day if not is_worker else role_days}</b>\n\n"
        f"🌟{'Ви стали частиною команди BULKA!' if is_worker else ('Розпочнімо' if is_new_user else 'Продовжимо') + ' твій шлях до нових знань!'}"
    )
    keyboard = main_menu_keyboard(
        is_new_user=is_new_user,
        is_hr=is_hr,
        is_developer=is_developer,
        can_search=can_search,
    )

    photo_file = "b_start.jpg" if (IMG_DIR / "b_start.jpg").exists() else "start.png"

    if force_new_message:
        if message:
            try:
                await message.delete()
            except Exception:
                pass
        await message.answer_photo(
            photo=FSInputFile(IMG_DIR / photo_file),
            caption=caption,
            reply_markup=keyboard,
        )
        return

    await _show_photo_menu(
        message,
        photo_file,
        caption,
        keyboard,
        allow_edit=allow_edit,
    )

async def show_manager_main_menu(
    message: types.Message,
    *,
    is_hr: bool = False,
    is_developer: bool = False,
    allow_edit: bool = True,
    force_new_message: bool = False,
) -> None:
    caption = (
        "🥖 Ви увійшли як керівник команди BULKA!\n"
        "Час дбати про розвиток стажерів. Що робимо далі?"
    )
    keyboard = main_menu_keyboard(is_manager=True, is_hr=is_hr, is_developer=is_developer)
    photo_file = (
        "manager/kerivn_option1_bakery.jpg"
        if (IMG_DIR / "manager" / "kerivn_option1_bakery.jpg").exists()
        else ("k_menu.jpg" if (IMG_DIR / "k_menu.jpg").exists() else "kerivn.png")
    )

    if force_new_message:
        if message:
            try:
                await message.delete()
            except Exception:
                pass
        await message.answer_photo(
            photo=FSInputFile(IMG_DIR / photo_file),
            caption=caption,
            reply_markup=keyboard,
        )
        return

    await _show_photo_menu(
        message,
        photo_file,
        caption,
        keyboard,
        allow_edit=allow_edit,
    )

async def _load_day_materials(role: Optional[str], day: int) -> List[dict]:
    normalized_role = role or "ALL"
    materials = await get_materials_for_day(normalized_role, day)
    return sorted(materials, key=lambda m: m.get("order_index", 0))

def parse_material_content(content: str) -> List[dict]:
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

def _format_material_text(material: dict) -> str:
    title = material.get("title") or "Матеріал без назви"
    body = (material.get("content") or "").strip()
    resource_url = (material.get("resource_url") or "").strip()
    ctype = material.get("content_type", "text")
    icon = CONTENT_TYPE_METADATA.get(ctype, {"icon": "📄"}).get("icon", "📄")
    lines = [f"{icon} <b>{title}</b>"]
    if ctype == "video_files":
        lines.append("")
        lines.append("<i>(Кілька відеофайлів доступно)</i>")
    elif body:
        lines.append("")
        lines.append(body)
    if resource_url and ctype != "video_files": # Only show resource_url if it's not a video_files type
        lines.append("")
        lines.append(f"🔗 {resource_url}")
    return "\n".join(lines).strip()

async def _get_day_completion_button(user_id: int, day: int) -> InlineKeyboardButton:
    """Returns the appropriate button for finishing the day content (Test or Complete)."""
    user_details = await get_user_details(user_id)
    role = user_details.get("role", "ALL") if user_details else "ALL"
    
    test_material = await get_test_by_role_and_day(role, day)
    is_test_enabled = True
    if test_material:
        is_test_enabled = bool(test_material.get("is_enabled", 1))
    
    if is_test_enabled:
        return InlineKeyboardButton(text="➡️ До тесту", callback_data=_build_test_callback(day))
    else:
        return InlineKeyboardButton(text="✅ Завершити день", callback_data=f"complete_day_{day}")

async def _show_material_entry(
    callback: CallbackQuery,
    role: Optional[str],
    day: int,
    target_order: int,
    materials: Optional[List[dict]] = None,
    target_ctype: Optional[str] = None,
) -> None:
    entries = materials or await _load_day_materials(role, day)
    if not entries:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Повернутися до блоків навчання", callback_data="continue_learning")]
            ]
        )
        if callback.message:
            await callback.message.edit_text(
                "😿 Поки що для цього дня немає матеріалів у вашій траєкторії.\n"
                "Керівник або команда Адміністраторів вже працюють над оновленням контенту.",
                reply_markup=kb,
            )
        await callback.answer()
        return

    # Find the material by order_index AND content_type if provided
    idx = 0
    found = False
    for i, item in enumerate(entries):
        if item.get("order_index") == target_order:
            if target_ctype:
                if item.get("content_type") == target_ctype:
                    idx = i
                    found = True
                    break
            else:
                idx = i
                found = True
                break
    
    # If explicit match not found (shouldn't happen if logic is correct), fallback to just order
    if not found and target_ctype:
         for i, item in enumerate(entries):
            if item.get("order_index") == target_order:
                idx = i
                break

    material = entries[idx]
    ctype = material.get("content_type", "text")
    
    if ctype == 'text':
        pages = parse_material_content(material.get("content", ""))
        
        # Add metadata (title/url)
        title = material.get("title") or "Матеріал без назви"
        resource_url = (material.get("resource_url") or "").strip()
        icon = CONTENT_TYPE_METADATA.get(ctype, {"icon": "📄"}).get("icon", "📄")
        
        # Prepend title to first page
        if pages:
            # We want to keep the photo of the first page if it exists
            pages[0]["text"] = f"{icon} <b>{title}</b>\n\n{pages[0].get('text', '')}".strip()
        else:
            pages = [{"text": f"{icon} <b>{title}</b>"}]
            
        # Append URL to last page
        if resource_url:
            pages[-1]["text"] = f"{pages[-1].get('text', '')}\n\n🔗 {resource_url}".strip()
            
        final_button = await _get_day_completion_button(callback.from_user.id, day)
        
        # Display first page (0)
        keyboard = get_pagination_keyboard(0, len(pages), str(material.get('id')), day, final_button)
        
        page_0 = pages[0]
        text_0 = page_0.get("text", "")
        photo_0 = page_0.get("photo")
        
        if callback.message:
            is_photo_message = bool(callback.message.photo)
            is_text_message = bool(callback.message.text)
            
            if photo_0:
                if is_photo_message:
                     media = types.InputMediaPhoto(media=photo_0, caption=text_0)
                     await callback.message.edit_media(media=media, reply_markup=keyboard)
                else:
                     try:
                         await callback.message.delete()
                     except Exception:
                         pass
                     await callback.message.answer_photo(photo_0, caption=text_0, reply_markup=keyboard)
            else:
                if is_text_message:
                     await callback.message.edit_text(text_0, reply_markup=keyboard)
                else:
                     try:
                         await callback.message.delete()
                     except Exception:
                         pass
                     await callback.message.answer(text_0, reply_markup=keyboard)
        await callback.answer()
        return

    text = _format_material_text(material)
    pages = split_text(text)
    
    keyboard = None
    final_button = None

    if ctype == 'video':
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➡️ До тексту", callback_data=f"daymat_{day}_text")],
            [InlineKeyboardButton(text="⬅️ Повернутися до вибору", callback_data=f"day_{day}")]
        ])
        if callback.message:
            await _show_text_menu(callback.message, pages[0], keyboard, allow_edit=True, allow_caption_edit=True)
        await callback.answer()
        return
    elif ctype == 'video_files':
        try:
            file_ids = json.loads(material.get("content", "[]"))
            if not file_ids:
                raise ValueError("No video file IDs found.")
            
            # Send the FIRST video with pagination
            first_file_id = file_ids[0]
            
            back_to_menu = InlineKeyboardButton(text="⬅️ Повернутися до вибору", callback_data=f"day_{day}")
            
            keyboard = get_pagination_keyboard(
                current_page=0,
                total_pages=len(file_ids),
                content_identifier=str(material.get('id')),
                day=day,
                final_button=back_to_menu
            )
            
            # If get_pagination_keyboard returns None (single page, no final button handled there usually, 
            # but here we passed final_button, so it should handle it. 
            # However, logic in get_pagination_keyboard: `if total_pages <= 1 and not final_button: return ...` 
            # Since we pass final_button, it returns a keyboard with just that button if pages <= 1.
            # But wait, get_pagination_keyboard logic:
            # if total_pages <= 1 and not final_button: return ...
            # if total_pages > 1: adds page indicator.
            # if final_button and current_page == total_pages - 1: adds final button.
            # So for page 0 of 1: current=0, total=1. 0 == 0. Final button added. 
            
            if callback.message:
                # Delete the previous message if it exists and has content
                if callback.message.text or callback.message.photo:
                    try:
                        await callback.message.delete()
                    except Exception:
                        pass
                
                await callback.message.answer_video(
                    video=first_file_id,
                    caption=f"Відео 1 з {len(file_ids)}",
                    reply_markup=keyboard
                )
            
            await callback.answer()
            return
        except (json.JSONDecodeError, ValueError) as e:
            print(f"Error processing video_files content: {e}")
            if callback.message:
                await callback.message.answer("❌ Помилка завантаження відеоматеріалів.")
            await callback.answer("Помилка завантаження відеоматеріалів.", show_alert=True)
            return

    elif ctype == 'photo_files':
        try:
            file_ids = json.loads(material.get("content", "[]"))
            if not file_ids:
                raise ValueError("No photo file IDs found.")
            
            # Send the FIRST photo with pagination
            first_file_id = file_ids[0]
            
            back_to_menu = InlineKeyboardButton(text="⬅️ Повернутися до вибору", callback_data=f"day_{day}")
            
            keyboard = get_pagination_keyboard(
                current_page=0,
                total_pages=len(file_ids),
                content_identifier=str(material.get('id')),
                day=day,
                final_button=back_to_menu
            )
            
            if callback.message:
                # Delete the previous message if it exists
                if callback.message.text or callback.message.video or callback.message.photo:
                    try:
                        await callback.message.delete()
                    except Exception:
                        pass
                
                await callback.message.answer_photo(
                    photo=first_file_id,
                    caption=f"Фото 1 з {len(file_ids)}",
                    reply_markup=keyboard
                )
            
            await callback.answer()
            return
        except (json.JSONDecodeError, ValueError) as e:
            print(f"Error processing photo_files content: {e}")
            if callback.message:
                await callback.message.answer("❌ Помилка завантаження фотоматеріалів.")
            await callback.answer("Помилка завантаження фотоматеріалів.", show_alert=True)
            return

    elif ctype == 'text':
        final_button = InlineKeyboardButton(text="➡️ До тесту", callback_data=_build_test_callback(day))
        keyboard = get_pagination_keyboard(0, len(pages), str(material.get('id')), day, final_button)
        if callback.message:
            await _show_text_menu(callback.message, pages[0], keyboard, allow_edit=True, allow_caption_edit=True)
        await callback.answer()
        return

    if keyboard is None:
        buttons = [[InlineKeyboardButton(text="⬅️ Повернутися до вибору", callback_data=f"day_{day}")]]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    if callback.message:
      await _show_text_menu(callback.message, pages[0], keyboard, allow_edit=True, allow_caption_edit=True)
    
    await callback.answer()

async def _handle_pagination(callback: CallbackQuery):
    if not callback.data or not callback.message:
        await callback.answer("Помилка: немає даних.")
        return
    try:
        _, material_id_str, day_str, page_str = callback.data.split(":")
        material_id = int(material_id_str)
        day = int(day_str)
        page = int(page_str)
    except (ValueError, IndexError):
        await callback.answer("Помилка: невірні дані пагінації.")
        return

    material = await get_material_by_id(material_id)
    if not material:
        await callback.answer("Помилка: матеріал не знайдено.")
        return
    
    if material.get("content_type") == 'video_files':
        try:
            file_ids = json.loads(material.get("content", "[]"))
            if 0 <= page < len(file_ids):
                file_id = file_ids[page]
                back_to_menu = InlineKeyboardButton(text="⬅️ Повернутися до вибору", callback_data=f"day_{day}")
                
                keyboard = get_pagination_keyboard(
                    current_page=page,
                    total_pages=len(file_ids),
                    content_identifier=str(material_id),
                    day=day,
                    final_button=back_to_menu
                )
                
                media = types.InputMediaVideo(
                    media=file_id,
                    caption=f"Відео {page + 1} з {len(file_ids)}"
                )
                
                await callback.message.edit_media(media=media, reply_markup=keyboard)
            else:
                await callback.answer("Сторінка не знайдена.")
        except Exception as e:
            print(f"Error pagination video: {e}")
            await callback.answer("Помилка відео пагінації.")
        return
    
    if material.get("content_type") == 'photo_files':
        try:
            file_ids = json.loads(material.get("content", "[]"))
            if 0 <= page < len(file_ids):
                file_id = file_ids[page]
                back_to_menu = InlineKeyboardButton(text="⬅️ Повернутися до вибору", callback_data=f"day_{day}")
                
                keyboard = get_pagination_keyboard(
                    current_page=page,
                    total_pages=len(file_ids),
                    content_identifier=str(material_id),
                    day=day,
                    final_button=back_to_menu
                )
                
                media = types.InputMediaPhoto(
                    media=file_id,
                    caption=f"Фото {page + 1} з {len(file_ids)}"
                )
                
                await callback.message.edit_media(media=media, reply_markup=keyboard)
            else:
                await callback.answer("Сторінка не знайдена.")
        except Exception as e:
            print(f"Error pagination photo: {e}")
            await callback.answer("Помилка фото пагінації.")
        return
    
    if material.get("content_type") == 'text':
        pages = parse_material_content(material.get("content", ""))
        
        # Add metadata (title/url)
        title = material.get("title") or "Матеріал без назви"
        resource_url = (material.get("resource_url") or "").strip()
        icon = CONTENT_TYPE_METADATA.get('text', {"icon": "📄"}).get("icon", "📄")
        
        if pages:
            pages[0]["text"] = f"{icon} <b>{title}</b>\n\n{pages[0].get('text', '')}".strip()
        else:
            pages = [{"text": f"{icon} <b>{title}</b>"}]
            
        if resource_url:
            pages[-1]["text"] = f"{pages[-1].get('text', '')}\n\n🔗 {resource_url}".strip()

        final_button = await _get_day_completion_button(callback.from_user.id, day)
        
        if 0 <= page < len(pages):
            keyboard = get_pagination_keyboard(page, len(pages), str(material_id), day, final_button)
            
            page_data = pages[page]
            text = page_data.get("text", "")
            photo = page_data.get("photo")
            
            if isinstance(callback.message, Message):
                is_photo_message = bool(callback.message.photo)
                is_text_message = bool(callback.message.text)
                
                if photo:
                    if is_photo_message:
                        media = types.InputMediaPhoto(media=photo, caption=text)
                        await callback.message.edit_media(media=media, reply_markup=keyboard)
                    else:
                        try:
                            await callback.message.delete()
                        except Exception:
                            pass
                        await callback.message.answer_photo(photo, caption=text, reply_markup=keyboard)
                else:
                    if is_text_message:
                        await callback.message.edit_text(text, reply_markup=keyboard)
                    else:
                        try:
                            await callback.message.delete()
                        except Exception:
                            pass
                        await callback.message.answer(text, reply_markup=keyboard)
        else:
            await callback.answer("Помилка: сторінка не знайдена.")
        return

    full_text = _format_material_text(material)
    pages = split_text(full_text)
    
    final_button = None

    if 0 <= page < len(pages):
        keyboard = get_pagination_keyboard(page, len(pages), str(material_id), day, final_button)
        if isinstance(callback.message, Message):
            await callback.message.edit_text(pages[page], reply_markup=keyboard)
    else:
        await callback.answer("Помилка: сторінка не знайдена.")

async def day_content(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_details = await _ensure_learning_access(callback)
    if not user_details:
        return
        
    day = int(callback.data.split("_")[1])
    initialize_user_progress(user_id)
    status = await get_day_status(user_id, day)
    if status == DayStatus.CLOSED:
        await callback.answer("Пройдіть попередній етап навчання, перш ніж почати цей", show_alert=True)
        return

    grouped_materials = await load_grouped_materials(user_details.get('role'), day)
    if grouped_materials:
        summary_lines = describe_available_types(grouped_materials)
        summary_text = (
            f"🍞 <b>День {day}</b> • {user_details.get('role', 'Без ролі')}\n\n"
            "Оберіть формат матеріалу:\n"
        )
        summary_text += "\n".join(summary_lines) if summary_lines else "Матеріали доступні у кількох форматах."

        buttons = []
        for ctype in CONTENT_TYPE_ORDER:
            if ctype in grouped_materials:
                text, cb = type_button_payload(day, ctype)
                buttons.append([InlineKeyboardButton(text=text, callback_data=cb)])
        
        test_button = await _get_day_completion_button(user_id, day)
        if "test" in test_button.callback_data:
             test_button.text = "📝 Тести"
        buttons.append([test_button])
        
        buttons.append([InlineKeyboardButton(text="⬅️ Повернутися до блоків навчання", callback_data="continue_learning")])

        if callback.message:
            await _show_text_menu(
                callback.message,
                summary_text,
                InlineKeyboardMarkup(inline_keyboard=buttons),
                allow_edit=True,
                allow_caption_edit=True,
            )
        await callback.answer()
        return

    fallback_text = (
        "😿 Поки що для цього дня немає матеріалів у вашій траєкторії.\n"
        "Керівник або команда Адміністраторів вже працюють над оновленням контенту."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Повернутися до блоків навчання", callback_data="continue_learning")]
    ])
    if callback.message:
        await _show_text_menu(
            callback.message,
            fallback_text,
            kb,
            allow_edit=True,
            allow_caption_edit=True,
        )
    await callback.answer("Матеріали ще не готові", show_alert=True)

async def day_material_detail(callback: CallbackQuery):
    user_details = await _ensure_learning_access(callback)
    if not user_details:
        return

    try:
        _, day_str, ctype = callback.data.split("_", 2)
        day = int(day_str)
    except (ValueError, IndexError):
        await callback.answer("Невідомий формат матеріалу", show_alert=True)
        return

    entries = await _load_day_materials(user_details.get('role'), day)
    selected = next((m for m in entries if m.get("content_type") == ctype), None)
    if not selected:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Повернутися до форматів", callback_data=f"day_{day}")]
            ]
        )
        if callback.message:
            await callback.message.edit_text(
                "Цей формат ще не містить матеріалів. Будь ласка, оберіть інший.",
                reply_markup=kb
            )
        await callback.answer()
        return

    await _show_material_entry(
        callback,
        user_details.get('role'),
        day,
        selected.get("order_index", 0),
        materials=entries,
        target_ctype=ctype,
    )

async def show_syllabus(callback: CallbackQuery):
    user_details = await _ensure_learning_access(callback)
    if not user_details:
        return

    role = user_details.get('role')
    # Syllabus stored as day=0, type='syllabus'
    material = await get_material_by_role_day_type(role, 0, "syllabus")

    if not material or not material.get("content") or not material.get("is_enabled", 1):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ В головне меню", callback_data="main_menu")]
        ])
        msg = "Зміст для вашої посади ще не додано або він тимчасово вимкнений."
        if callback.message:
            await callback.message.edit_text(msg, reply_markup=kb)
        await callback.answer()
        return

    text = material.get("content", "")
    pages = split_text(text)
    
    # We use material_id for pagination callback identification
    # But since it's a specific "show_syllabus" action, we might need a distinct pagination handler 
    # OR we reuse get_pagination_keyboard with a specific identifier.
    # Let's reuse existing pagination logic. If I pass material_id, _handle_pagination will try to fetch it.
    # _handle_pagination uses get_material_by_id. So if I pass the correct ID, it should work!
    # BUT _handle_pagination formats text using _format_material_text which adds title/url/etc.
    # Syllabus is just text.
    # Let's check _format_material_text in handlers.py.
    
    # _format_material_text does:
    # icon + title
    # body
    # url
    
    # This is fine for syllabus too.
    
    final_button = InlineKeyboardButton(text="⬅️ В головне меню", callback_data="main_menu")
    keyboard = get_pagination_keyboard(0, len(pages), str(material.get('id')), 0, final_button)
    
    if callback.message:
        await _show_text_menu(callback.message, pages[0], keyboard, allow_edit=True, allow_caption_edit=True)
    await callback.answer()

async def syllabus_locked(callback: CallbackQuery):
    await callback.answer("🔒 Зміст стане доступним після завершення 5-го дня навчання!", show_alert=True)

async def remind_topic_self_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user_details = await get_user_details(user_id)
    privileged = await is_privileged_user(user_id)

    if not privileged:
        if not user_details or not user_details.get("manager_id") or not user_details.get("role"):
            await callback.answer(
                "Виглядає, що твій профіль стажера не знайдено. Напиши, будь ласка керівнику.",
                show_alert=True,
            )
            return
        if not await _has_completed_course(user_id):
            await callback.answer(
                "Ця функція стане доступною після завершення всіх днів навчання.",
                show_alert=True,
            )
            return

    await state.update_data(
        role=(user_details or {}).get("role"),
        mode="self",
        intern_id=user_id,
    )
    await state.set_state(SearchStates.waiting_for_query)
    prompt = (
        "🧠 <b>Пошук по ключових словах</b>\n\n"
        "Введи слово, фразу або коротке запитання, і я знайду згадки в навчальних матеріалах.\n"
        "Наприклад: <i>мотивація</i>, <i>робота з клієнтом</i>, <i>як працює каса</i>."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В головне меню", callback_data="main_menu")]
    ])
    if callback.message:
        if callback.message.photo:
            await callback.message.edit_caption(caption=prompt, reply_markup=kb)
        else:
            await callback.message.edit_text(prompt, reply_markup=kb)
    await callback.answer()

async def remind_topic_global_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    is_hr = await is_hr_user(user_id)
    is_dev = await is_developer_user(user_id)
    is_obs = await is_observer_user(user_id)
    is_mgr = await is_manager_user(user_id)
    if not (is_hr or is_dev or is_obs or is_mgr):
        await callback.answer("Ця функція доступна лише для керівництва.", show_alert=True)
        return

    if is_dev or is_hr or is_obs or is_mgr:
        from bot.constants import AVAILABLE_ROLES
        filtered_roles = [r for r in AVAILABLE_ROLES if r not in ("Керівник", "Керівник Стажер")] if is_mgr else AVAILABLE_ROLES
        buttons = []
        for i, role in enumerate(AVAILABLE_ROLES):
            if role in filtered_roles:
                buttons.append([InlineKeyboardButton(
                    text=f"👤 {role}",
                    callback_data=f"remind_role_select:{i}"
                )])
        if not is_mgr:
            buttons.append([InlineKeyboardButton(text="🌐 Всі посади", callback_data="remind_role_select:ALL")])
        
        back_button_cb = "mgr_materials_catalog" if is_mgr else ("dev_main_study" if (is_dev or is_obs) else "manager_menu")
        buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=back_button_cb)])
        
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        prompt = (
            "🧠 <b>Нагадати тему</b>\n\n"
            "Обери посаду, по якій шукати матеріали:"
        )
        if callback.message:
            if callback.message.photo:
                await callback.message.edit_caption(caption=prompt, reply_markup=kb)
            else:
                await callback.message.edit_text(prompt, reply_markup=kb)
        await callback.answer()
        return

    await state.update_data(role=None, mode="global", intern_id=None)
    await state.set_state(SearchStates.waiting_for_query)
    prompt = (
        "🧠 <b>Глобальний пошук по матеріалах</b>\n\n"
        "Введіть слово, фразу або питання, і я знайду відповідні матеріали для HR/Адміністраторів.\n"
        "Наприклад: <i>мотивація</i>, <i>стандарти продажу</i>, <i>каса</i>."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В головне меню", callback_data="main_menu")]
    ])
    if callback.message:
        if callback.message.photo:
            await callback.message.edit_caption(caption=prompt, reply_markup=kb)
        else:
            await callback.message.edit_text(prompt, reply_markup=kb)
    await callback.answer()

async def remind_role_select_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    is_hr = await is_hr_user(user_id)
    is_dev = await is_developer_user(user_id)
    is_obs = await is_observer_user(user_id)
    is_mgr = await is_manager_user(user_id)

    if not (is_hr or is_dev or is_obs or is_mgr):
        await callback.answer("Ця функція доступна лише для керівництва.", show_alert=True)
        return
    
    parts = callback.data.split(":", 1)
    if len(parts) != 2:
        await callback.answer("Невірний формат.", show_alert=True)
        return
    
    from bot.constants import AVAILABLE_ROLES
    role_part = parts[1]
    
    if role_part == "ALL":
        role = None
    else:
        try:
            role_index = int(role_part)
            if 0 <= role_index < len(AVAILABLE_ROLES):
                role = AVAILABLE_ROLES[role_index]
            else:
                await callback.answer("Невідома роль.", show_alert=True)
                return
        except ValueError:
            await callback.answer("Невірний формат ролі.", show_alert=True)
            return

    await state.update_data(role=role, mode="dev_test", intern_id=None)
    await state.set_state(SearchStates.waiting_for_query)
    
    role_text = role if role else "всіх посад"
    prompt = (
        f"🧠 <b>Пошук матеріалів</b>\n\n"
        f"Посада: <b>{role_text}</b>\n\n"
        "Введи слово, фразу або питання:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="remind_topic_global")]
    ])
    if callback.message:
        if callback.message.photo:
            await callback.message.edit_caption(caption=prompt, reply_markup=kb)
        else:
            await callback.message.edit_text(prompt, reply_markup=kb)
    await callback.answer()

async def remind_topic_for_intern_callback(callback: CallbackQuery, state: FSMContext):
    logger = get_logger()
    logger.debug(f"remind_topic_for_intern callback: {callback.data!r}")
    
    raw_id = parse_callback_id(callback.data, "remind_topic_for_intern")
    if raw_id is None:
        logger.warning(f"Invalid callback format: {callback.data!r}")
        await callback.answer("Невірний формат запиту.", show_alert=True)
        return
    
    intern_id = await validate_user_id(raw_id, context="remind_topic_for_intern")
    if intern_id is None:
        await callback.answer("Стажера не знайдено або ID невалідний.", show_alert=True)
        return

    intern_details = await get_user_details(intern_id)
    
    caller_id = callback.from_user.id
    is_caller_privileged = await is_privileged_user(caller_id)
    manager_info = await get_manager_by_uid(caller_id)
    
    if not is_caller_privileged and not manager_info:
        logger.warning(f"Unauthorized remind_topic call from {caller_id}")
        await callback.answer("Ця функція доступна лише керівникам.", show_alert=True)
        return

    await state.update_data(
        role=intern_details.get("role") if intern_details else None,
        mode="for_intern",
        intern_id=intern_id,
    )
    await state.set_state(SearchStates.waiting_for_query)

    intern_name = (intern_details.get("full_name") if intern_details else None) or f"ID {intern_id}"
    prompt = (
        f"🧠 <b>Пошук тем для {intern_name}</b>\n\n"
        "Введи ключові слова або коротке питання – зберу добірку матеріалів, якими можна поділитися зі стажером."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В головне меню", callback_data="main_menu")]
    ])
    if callback.message:
        if callback.message.photo:
            await callback.message.edit_caption(caption=prompt, reply_markup=kb)
        else:
            await callback.message.edit_text(prompt, reply_markup=kb)
    await callback.answer()

async def process_keyword_search(message: types.Message, state: FSMContext):
    data = await state.get_data()
    mode = data.get("mode", "self")
    target_role = data.get("role")
    user_id = message.from_user.id
    query = (message.text or "").strip()
    new_search_callback = "remind_topic_self"
    role_filter = None
    user_details = None

    if not query:
        await message.answer("Будь ласка, введи своє питання.")
        return

    # --- Перевірка доступу і визначення ролі ---
    if mode == "global":
        if not (await is_hr_user(user_id) or await is_developer_user(user_id)):
            await message.answer("Цей режим доступний лише HR та Адміністраторам.")
            await state.clear()
            return
        role_filter = None
        new_search_callback = "remind_topic_global"
    elif mode == "manager_global":
        if not await is_privileged_user(user_id):
            await message.answer("Цей режим доступний лише керівникам.")
            await state.clear()
            return
        role_filter = target_role
        new_search_callback = "mgr_remind_menu"
    elif mode == "for_intern":
        intern_id = data.get("intern_id")
        if not intern_id:
            await message.answer("Невірний формат стажера в запиті.")
            await state.clear()
            return
        intern_details = await get_user_details(intern_id)
        if not intern_details:
            await message.answer("Не вдалося знайти цього стажера. Спробуйте оновити список.")
            await state.clear()
            return
        role_filter = intern_details.get("role")
        new_search_callback = f"remind_topic_for_intern:{intern_id}"
    else:
        user_details = await get_user_details(user_id)
        privileged = await is_privileged_user(user_id)
        if not privileged:
            if not user_details or not user_details.get("manager_id") or not user_details.get("role"):
                await message.answer("Виглядає, що твій профіль стажера не знайдено. Напиши, будь ласка, HR.")
                await state.clear()
                return
            if not await _has_completed_course(user_id):
                await message.answer("Нагадування доступне після завершення всіх навчальних днів.")
                await state.clear()
                return
        role_filter = target_role or (user_details or {}).get("role")
        new_search_callback = "remind_topic_self"

    logger = get_logger()
    logger.info(f"GPT tutor request: user={user_id}, mode='{mode}', role='{role_filter}', query='{query[:80]}'")

    # Показуємо індикатор "думає"
    thinking_msg = await message.answer("🥐 <b>BULKA радник</b> аналізує навчальні матеріали...", parse_mode="HTML")

    # --- Завантажуємо всі матеріали для ролі ---
    all_mats = await get_all_materials()
    if role_filter:
        role_mats = [m for m in all_mats if m.get("role") == role_filter]
    else:
        # global mode (для HR/Адміністратора) — всі матеріали
        role_mats = all_mats

    # --- GPT-наставник (2-Step Router) ---
    ai_response = None
    if is_openai_configured() and role_mats:
        ai_response = await ask_gpt_tutor(
            question=query,
            all_materials=role_mats,
            role=role_filter or "загальна",
            user_id=user_id,
        )

    # --- Fallback: якщо GPT недоступний, показати keyword результати ---
    if not ai_response:
        logger.warning(f"GPT unavailable or no materials, falling back to keyword search for user={user_id}")
        keyword_results = await search_materials_db(query, role=role_filter, limit=5)
        if keyword_results:
            lines = [
                f"🔎 <b>Результати пошуку за запитом «{query}»</b>",
                "<i>BULKA радник тимчасово недоступний. Показую знайдене за ключовими словами:</i>",
                "",
            ]
            for idx, item in enumerate(keyword_results, 1):
                day = item.get("day", "?")
                title = item.get("title", "Без назви")
                content_snippet = _build_snippet(item.get("content", ""), 200)
                lines.append(f"{idx}. <b>День {day}</b> — {title}")
                if content_snippet:
                    lines.append(f"   {content_snippet}")
                lines.append("")
            text = "\n".join(lines).strip()
        else:
            text = (
                f"😿 На жаль, я не знайшов інформації за запитом <b>«{query}»</b>.\n"
                "Спробуй інше формулювання або постав питання більш конкретно."
            )
    else:
        # Чиста відповідь від BULKA радник
        text = f"🥐 <b>BULKA радник</b>\n\n{ai_response}"

    # Видаляємо індикатор "думає"
    try:
        await thinking_msg.delete()
    except Exception:
        pass

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔁 Нове питання", callback_data=new_search_callback)],
            [InlineKeyboardButton(text="🏠 В головне меню", callback_data="main_menu")],
        ]
    )

    # Telegram ліміт 4096 символів
    MAX_MESSAGE_LENGTH = 4000
    if len(text) <= MAX_MESSAGE_LENGTH:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        truncated = text[:MAX_MESSAGE_LENGTH - 100] + "\n\n<i>... (відповідь обрізано через довжину)</i>"
        await message.answer(truncated, reply_markup=kb, parse_mode="HTML")
        logger.warning(f"GPT response truncated: {len(text)} -> {len(truncated)} chars")

    await state.clear()


async def main_menu_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    is_developer = await is_developer_user(user_id)
    is_hr = await is_hr_user(user_id)
    is_territorial = await is_territorial_user(user_id)
    is_observer = await is_observer_user(user_id)
    is_manager = await is_manager_user(user_id)

    if callback.message:
        if is_observer:
            await show_observer_main_menu(
                callback.message,
                allow_edit=True,
            )
        elif is_developer or is_territorial:
            await show_developer_main_menu(
                callback.message,
                is_hr=is_hr,
                is_developer=is_developer,
                is_territorial=is_territorial,
                allow_edit=True,
            )
        elif is_manager or is_hr:
            await show_manager_main_menu(
                callback.message,
                is_hr=is_hr,
                is_developer=is_developer,
                allow_edit=True,
            )
        else:
            await show_student_main_menu(
                callback.message,
                user_id,
                is_hr=is_hr,
                is_developer=is_developer,
                allow_edit=True,
            )
    await callback.answer()

async def main_menu_callback_force_photo(callback: CallbackQuery):
    user_id = callback.from_user.id
    is_developer = await is_developer_user(user_id)
    is_hr = await is_hr_user(user_id)
    is_territorial = await is_territorial_user(user_id)
    is_observer = await is_observer_user(user_id)
    is_manager = await is_manager_user(user_id)

    if callback.message:
        if is_observer:
            await show_observer_main_menu(
                callback.message,
                force_new_message=True,
            )
        elif is_developer or is_territorial:
            await show_developer_main_menu(
                callback.message,
                is_hr=is_hr,
                is_developer=is_developer,
                is_territorial=is_territorial,
                force_new_message=True,
            )
        elif is_manager or is_hr:
            await show_manager_main_menu(
                callback.message,
                is_hr=is_hr,
                is_developer=is_developer,
                force_new_message=True,
            )
        else:
            await show_student_main_menu(
                callback.message,
                user_id,
                is_hr=is_hr,
                is_developer=is_developer,
                force_new_message=True,
            )
    await callback.answer()

async def manager_support(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user_details = await get_user_details(user_id)
    manager_id = user_details.get('manager_id') if user_details else None

    if not user_details or not manager_id:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="В головне меню", callback_data="main_menu")]
        ])
        if callback.message:
            try:
                await callback.message.edit_text(
                    "⚠️ У вас не призначено керівника. Зверніться до адміністратора.",
                    reply_markup=kb
                )
            except Exception:
                await callback.message.answer(
                    "⚠️ У вас не призначено керівника. Зверніться до адміністратора.",
                    reply_markup=kb
                )
        return

    can_start = await can_start_conversation(user_id)
    if not can_start:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 В головне меню", callback_data="main_menu")]
        ])
        if callback.message:
            try:
                await callback.message.edit_text(
                    f"⚠️ <b>Досягнуто ліміт діалогів</b>\n\n"
                    f"У вас вже є {MAX_OPEN_CONVERSATIONS} активних повідомлень до керівника.\n"
                    f"Дочекайтесь відповіді, перш ніж надсилати нові.",
                    reply_markup=kb
                )
            except Exception:
                await callback.message.answer(
                    f"⚠️ <b>Досягнуто ліміт діалогів</b>\n\n"
                    f"У вас вже є {MAX_OPEN_CONVERSATIONS} активних повідомлень до керівника.\n"
                    f"Дочекайтесь відповіді, перш ніж надсилати нові.",
                    reply_markup=kb
                )
        return

    welcome_text = (
        "🌟 <b>Привіт, Булка-котик!</b> 🌟\n\n"
        "Я твій керівник — провідник у світ знань і можливостей. "
        "Завжди готовий підтримати тебе на шляху навчання!\n\n"
        "Напиши своє запитання або думку, і я обов'язково відповім! "
        "Кожен крок твого навчання важливий. 🍞✨\n\n"
        "Введи повідомлення зараз або натисни кнопку 'Скасувати'."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_support")]
    ])
    if callback.message:
        try:
            await callback.message.edit_text(welcome_text, reply_markup=kb)
        except Exception:
            await callback.message.answer(welcome_text, reply_markup=kb)
    await state.update_data(manager_id=manager_id)
    await state.set_state(SupportStates.waiting_for_message)

async def cancel_support(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await main_menu_callback(callback)

async def process_support_message(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_details = await get_user_details(user_id)
    data = await state.get_data()
    manager_id = data.get('manager_id')
    await state.clear()

    manager_message = (
        f"📨 <b>Привіт керівнику!</b>\n\n"
        f"Вам нове повідомлення від булка-котика – <b>{user_details.get('full_name') if user_details else 'Невідомий стажер'}</b>!\n\n"
        f"Нагадаю, його посада – <b>{user_details.get('role') if user_details else 'Не вказано'}</b>, а сам він з <b>{user_details.get('city') if user_details else 'Не вказано'}</b>.\n\n"
        f"🛠Його повідомлення:🛠\n\n<b>{message.text}</b>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✉️ Відповісти", callback_data=f"reply_to_{user_id}")],
        [InlineKeyboardButton(text="🏠 Головна сторінка", callback_data="main_menu")]
    ])
    try:
        if message.bot:
            await message.bot.send_message(manager_id, manager_message, reply_markup=kb)
            await create_conversation(user_id, manager_id)
            await log_support_request(user_id) # Log for analytics
            await message.answer(
                "<b>✅ Ваше повідомлення успішно надіслано керівнику!</b>\nОчікуйте на відповідь.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 В головне меню", callback_data="main_menu")]
                ])
            )
    except Exception as e:
        await message.answer(
            "<b>⚠️ На жаль, не вдалося надіслати повідомлення. Спробуйте пізніше.</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 В головне меню", callback_data="main_menu")]
            ])
        )
        print(f"Помилка надсилання повідомлення керівнику: {e}")

async def manager_reply_callback(callback: CallbackQuery, state: FSMContext):
    intern_id = int(callback.data.split("_")[-1])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_manager_reply")]
    ])
    if callback.message and not callback.message.text:
        await callback.message.answer(
            "<b>✍️ Введіть відповідь для стажера. Ваша відповідь буде надіслана особисто цьому Булка-котику.</b>",
            reply_markup=kb
        )
    elif callback.message:
        try:
            await callback.message.edit_text(
                "<b>✍️ Введіть відповідь для стажера. Ваша відповідь буде надіслана особисто цьому Булка-котику.</b>",
                reply_markup=kb
            )
        except Exception:
            await callback.message.answer(
                "<b>✍️ Введіть відповідь для стажера. Ваша відповідь буде надіслана особисто цьому Булка-котику.</b>",
                reply_markup=kb
            )
    await state.update_data(intern_id=intern_id)
    await state.set_state(ManagerReplyStates.waiting_for_reply)

async def cancel_manager_reply(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if callback.message:
        await callback.message.edit_text(
            "Відповідь скасовано.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 В головне меню", callback_data="main_menu")]
            ])
        )

async def process_manager_reply(message: types.Message, state: FSMContext):
    data = await state.get_data()
    intern_id = data.get('intern_id')
    await state.clear()
    manager_info = await get_manager_by_uid(message.from_user.id)
    manager_name = manager_info.get('full_name', 'Керівник') if manager_info else 'Керівник'
    reply_text = (
        f"🌟 <b>Повідомлення від вашого керівника</b> 🌟\n\n"
        f"👨‍🏫 <b>{manager_name}</b> надіслав вам:\n\n"
        f"💬 <b>{message.text}</b>\n\n"
        f"🍞✨ Щоб відповісти, натисніть кнопку нижче ✨🍞"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✉️ Написати керівнику", callback_data="support")],
        [InlineKeyboardButton(text="⬅️ Повернутися до навчання", callback_data="continue_learning")]
    ])
    if message.bot:
        try:
            await message.bot.send_message(chat_id=intern_id, text=reply_text, reply_markup=kb, parse_mode="HTML")
            await close_conversation(intern_id, message.from_user.id)
            await message.answer(
                "<b>✅ Ваше повідомлення успішно надіслано стажеру!</b>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 В головне меню", callback_data="main_menu")]
                ])
            )
        except Exception as e:
            await message.answer(
                "<b>⚠️ Не вдалося надіслати відповідь стажеру.</b>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 В головне меню", callback_data="main_menu")]
                ])
            )

async def profile_handler_router(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if callback.message and callback.message.photo:
        try:
            await callback.message.delete()
        except Exception as e:
            print(f"Помилка видалення повідомлення: {e}")
    
    is_developer = await is_developer_user(user_id)
    if is_developer:
        await developer_profile_handler(callback)
        return

    is_observer = await is_observer_user(user_id)
    if is_observer:
        await observer_profile_handler(callback)
        return

    is_territorial = await is_territorial_user(user_id)
    if is_territorial:
        await developer_profile_handler(callback)
        return

    is_manager = await is_manager_user(user_id)
    if is_manager:
        if callback.message and callback.message.photo:
            await manager_profile_handler_new_message(callback)
        else:
            await manager_profile_handler(callback)
        return

    await profile_handler_new_message(callback)


async def developer_profile_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_details = await get_user_details(user_id)
    
    from database.users import get_all_users
    from database.managers import get_all_kerivnyky, is_territorial_user
    from database.hr import is_developer_user
    from database.materials import get_all_materials
    from bot.utils import get_user_avatar_input, _send_or_edit_card_photo
    
    all_users = await get_all_users()
    all_managers = await get_all_kerivnyky()
    all_materials = await get_all_materials()
    
    # Safely get names with fallback if user_details is None
    full_name = user_details.get('full_name', 'Без імені') if user_details else callback.from_user.full_name or "Без імені"
    username = user_details.get('username', 'немає') if user_details else callback.from_user.username or "немає"
    username_str = f"@{username}" if username and username != "немає" else "немає"

    is_dev = await is_developer_user(user_id)
    is_terr = await is_territorial_user(user_id)

    if is_terr and not is_dev:
        profile_title = "🗺️ <b>Профіль територіального керуючого</b> 🗺️"
    else:
        profile_title = "🛠️ <b>Профіль адміністратора</b> 🛠️"

    text = (
        f"{profile_title}\n\n"
        f"👤 <b>{full_name}</b> ({username_str})\n\n"
        f"📊 <b>Статистика системи:</b>\n"
        f"— Всього користувачів: <b>{len(all_users)}</b>\n"
        f"— Всього керівників: <b>{len(all_managers)}</b>\n"
        f"— Всього матеріалів: <b>{len(all_materials)}</b>\n"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 В головне меню", callback_data="main_menu")]
    ])
    
    photo_input = await get_user_avatar_input(callback.bot, user_id)
    await _send_or_edit_card_photo(callback, photo_input, text, reply_markup=kb)


async def observer_profile_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_details = await get_user_details(user_id)
    
    from database.users import get_all_users
    from database.managers import get_all_kerivnyky, get_manager_by_uid
    from bot.utils import get_user_avatar_input, _send_or_edit_card_photo
    
    all_users = await get_all_users()
    all_managers = await get_all_kerivnyky()
    
    interns_count = sum(1 for u in all_users if not (u.get("status") == "Працівник" or u.get("is_worker")))
    workers_count = sum(1 for u in all_users if (u.get("status") == "Працівник" or u.get("is_worker")))
    managers_count = len(all_managers)
    total_users = len(all_users)
    
    manager_info = await get_manager_by_uid(user_id)
    full_name = (
        (manager_info.get("full_name") if manager_info else None)
        or (user_details.get("full_name") if user_details else None)
        or callback.from_user.full_name
        or "Наглядач"
    )
    username = callback.from_user.username or (user_details.get("username") if user_details else None) or "немає"
    username_str = f"@{username}" if username and username != "немає" else "немає"
    
    text = (
        f"🍞 <b>Профіль наглядача BULKA</b> 🍞\n\n"
        f"👤 <b>{html.escape(full_name)}</b> ({username_str})\n"
        f"💼 Посада: <b>Наглядач</b>\n\n"
        f"📊 <b>Загальна статистика мережі:</b>\n"
        f"— Всього зареєстровано: <b>{total_users}</b>\n"
        f"— Активних стажерів: <b>{interns_count}</b>\n"
        f"— Працівників мережі: <b>{workers_count}</b>\n"
        f"— Керівників та наставників: <b>{managers_count}</b>\n\n"
        f"👁️ <i>Режим спостереження: у вас є повний доступ до перегляду списків, аналітики та навчальних матеріалів.</i>"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Меню наглядача", callback_data="developer_menu")],
        [InlineKeyboardButton(text="🏠 В головне меню", callback_data="main_menu")]
    ])
    
    photo_input = await get_user_avatar_input(callback.bot, user_id)
    await _send_or_edit_card_photo(callback, photo_input, text, reply_markup=kb)

async def manager_profile_handler_new_message(callback: CallbackQuery):
    await manager_profile_handler(callback)

async def profile_handler_new_message(callback: CallbackQuery):
    user_id = callback.from_user.id
    from bot.utils import get_user_avatar_input, _send_or_edit_card_photo, get_manager_display_title
    from database.positions import get_days_count_for_role
    from bot.state import sync_user_progress_cache
    
    user_details = await get_user_details(user_id)
    if not user_details:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 В головне меню", callback_data="main_menu")]
        ])
        photo_input = await get_user_avatar_input(callback.bot, user_id)
        await _send_or_edit_card_photo(callback, photo_input, "⚠️ Помилка: інформація про користувача не знайдена", reply_markup=kb)
        return
        
    manager_id = user_details.get('manager_id')
    manager_name_display = await get_manager_display_title(callback.bot, manager_id)

    await sync_user_progress_cache(user_id)
    progress_count = get_progress(user_id)
    user_role = user_details.get('role', 'Не вказано')
    total_days = await get_days_count_for_role(user_role) if user_role != 'Не вказано' else DAYS_TOTAL
    available_day = get_available_day(user_id, total_days=total_days)

    is_worker = bool(user_details.get('status') == 'Працівник' or user_details.get('is_worker'))
    user_name = user_details.get('full_name') or callback.from_user.full_name or ("Працівник" if is_worker else "Стажер")

    if is_worker:
        progress_bar = "🟢" * 10
        status_line = "💼 Статус: <b>Працівник компанії</b> 🌟"
        worker_since = user_details.get('worker_since')
        if worker_since:
            try:
                dt = datetime.fromisoformat(worker_since)
                status_line += f" <i>(з {dt.strftime('%d.%m.%Y')})</i>"
            except Exception:
                status_line += f" <i>(з {worker_since})</i>"

        motivation = "🎉 Ви успішно завершили навчання та є частиною дружньої команди BULKA! Бажаємо нових досягнень та успіхів у роботі! 🥐✨"

        text = (
            f"🍞 <b>Персональний профіль BULKA: {user_name}</b> 🍞\n\n"
            f"{status_line}\n"
            f"🔹 Ваша посада: <b>{user_role}</b>\n"
            f"🔹 Місто: <b>{user_details.get('city', 'Не вказано')}</b>\n"
            f"🔹 Магазин: <b>{user_details.get('shop', 'Не вказано')}</b>\n"
            f"🔹 Керівник: <b>{html.escape(manager_name_display)}</b>\n\n"
            f"📊 <b>Матеріали курсу:</b>\n"
            f"{progress_bar} 100% ({total_days}/{total_days})\n\n"
            f"{motivation}"
        )
    else:
        percent = int(progress_count / total_days * 100) if total_days else 0
        progress_bar_length = 10
        filled_length = int(progress_bar_length * percent / 100)
        progress_bar = "🟢" * filled_length + "⚪" * (progress_bar_length - filled_length)

        if percent == 0:
            motivation = "🌱 Ваша подорож тільки починається! Вперед до нових знань!"
        elif percent < 30:
            motivation = "🌿 Хороший початок - половина справи! Продовжуйте в тому ж дусі!"
        elif percent < 70:
            motivation = "🌲 Ви на правильному шляху до досконалості!"
        else:
            motivation = "✨ Ви дуже близько до початку нових звершень!"

        text = (
            f"🍞 <b>Персональний профіль BULKA: {user_name}</b> 🍞\n\n"
            f"🔹 Поточний день навчання: <b>День {available_day}</b>\n"
            f"🔹 Ваша посада: <b>{user_role}</b>\n"
            f"🔹 Місто: <b>{user_details.get('city', 'Не вказано')}</b>\n"
            f"🔹 Магазин: <b>{user_details.get('shop', 'Не вказано')}</b>\n"
            f"🔹 Керівник: <b>{html.escape(manager_name_display)}</b>\n\n"
            f"📊 <b>Ваш прогрес:</b>\n"
            f"{progress_bar} {percent}% ({progress_count}/{total_days})\n\n"
            f"{motivation}"
        )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 В головне меню", callback_data="main_menu")]
    ])
    
    photo_input = await get_user_avatar_input(callback.bot, user_id)
    await _send_or_edit_card_photo(callback, photo_input, text, reply_markup=kb)

async def manager_intern_profile_handler(callback: CallbackQuery):
    intern_id = int(callback.data.split("_")[-1])
    intern = await get_user_details(intern_id)
    progress_data = await get_user_progress(intern_id)
    completed_days = len([p for p in progress_data if p.get("completed")])
    from bot.utils import get_user_avatar_input, _send_or_edit_card_photo

    last_activity = intern.get('last_activity') if intern else None
    last_activity_str = "Невідомо"
    if last_activity:
        try:
            dt = datetime.fromisoformat(last_activity)
            if dt.tzinfo is None:
                dt = pytz.timezone(TIMEZONE).localize(dt)
            now = datetime.now(pytz.timezone(TIMEZONE))
            ago = now - dt
            if ago.days == 0:
                if ago.seconds < 3600:
                    last_activity_str = f"{ago.seconds // 60} хв. тому"
                else:
                    last_activity_str = f"{ago.seconds // 3600} год. тому"
            else:
                last_activity_str = f"{ago.days} дн. тому"
        except Exception:
            last_activity_str = last_activity

    intern_name = intern.get('full_name', 'Невідомий стажер') if intern else 'Невідомий стажер'
    intern_role = intern.get('role', 'Не вказано') if intern else 'Не вказано'
    from database.positions import get_days_count_for_role
    role_days = await get_days_count_for_role(intern_role) if intern_role != 'Не вказано' else DAYS_TOTAL
    text = (
        f"🐾 <b>Це – {intern_name}</b> і він(вона) один з твоїх Булка Котиків!\n"
        f"Давай поглянемо про цього більше:\n\n"
        f"🔷 Посада: <b>{intern_role}</b>\n"
        f"🔷 Місто: <b>{intern.get('city', 'Не вказано') if intern else 'Не вказано'}</b>\n"
        f"🔷 Магазин: <b>{intern.get('shop', 'Не вказано') if intern else 'Не вказано'}</b>\n"
        f"📊 Днів пройдено: <b>{completed_days} із {role_days}</b>\n"
        f"🕒 Остання активність: <b>{last_activity_str}</b>"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✉️ Надіслати повідомлення", callback_data=f"reply_to_{intern_id}")],
        [InlineKeyboardButton(text="🔔 Нагадати", callback_data=f"remind_{intern_id}")],
        [InlineKeyboardButton(text="📅 Навчальні дні", callback_data=f"manager_intern_learning_{intern_id}")],
        [InlineKeyboardButton(text="⬅️ Повернутися до списку", callback_data="manager_interns_list")],
        [InlineKeyboardButton(text="🏠 Головне меню", callback_data="main_menu")],
    ])
    photo_input = await get_user_avatar_input(callback.bot, intern_id)
    await _send_or_edit_card_photo(callback, photo_input, text, reply_markup=kb)


async def manager_profile_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    manager_info = await get_manager_by_uid(user_id)
    from bot.utils import get_user_avatar_input, _send_or_edit_card_photo
    
    all_interns = await get_manager_interns(user_id)
    interns_in_progress = await get_interns_in_progress_for_manager(user_id)
    inactive_interns = await get_inactive_interns_for_manager(user_id, days=1)
    
    if not all_interns:
        cute_msg = "Ваша команда ще попереду, але кожна велика історія починається з першого стажера! 🐾"
    elif len(all_interns) < 3:
        cute_msg = "Ваша команда зростає разом з BULKA — з професіоналізмом та турботою! 🥐"
    elif len(interns_in_progress) == 0:
        cute_msg = "Всі ваші стажери вже стали повноцінними працівниками BULKA! 🎉"
    else:
        cute_msg = "Ваша підтримка важлива для кожного стажера. Разом до нових успіхів у BULKA! 🍞✨"

    manager_display_name = manager_info.get("full_name", "Невідоме ім'я") if manager_info else "Невідоме ім'я"
    manager_shops = manager_info.get("shops", []) if manager_info else []

    shop_line = ""
    if manager_shops:
        if len(manager_shops) == 1:
            shop_line = f"🔹 Магазин: <b>{manager_shops[0]}</b>\n"
        else:
            shop_line = "🔹 Магазини: <b>" + ", ".join(manager_shops) + "</b>\n"

    text = (
        f"🍞 <b>Профіль керівника BULKA</b> 🍞\n\n"
        f"👤 <b>{manager_display_name}</b>\n"
        f"🔹 Посада: <b>{manager_info.get('process', 'Не вказано') if manager_info else 'Не вказано'}</b>\n"
        f"{shop_line}"
        f"📈 <b>Аналітика вашої команди:</b>\n"
        f"— Стажерів за весь час: <b>{len(all_interns)}</b>\n"
        f"— У процесі навчання: <b>{len(interns_in_progress)}</b>\n\n"
        f"⚠️ <b>Потребують уваги:</b>\n{len(inactive_interns)} стажери(-ів) сьогодні без активності\n\n"
        f"{cute_msg}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 В головне меню", callback_data="main_menu")]
    ])

    photo_input = await get_user_avatar_input(callback.bot, user_id)
    await _send_or_edit_card_photo(callback, photo_input, text, reply_markup=kb)

def _format_last_activity(last_activity: Optional[str], now: datetime) -> str:
    if not last_activity:
        return "Невідомо"
    try:
        dt = datetime.fromisoformat(last_activity)
        if dt.tzinfo is None:
            dt = pytz.timezone(TIMEZONE).localize(dt)
        ago = now - dt
        if ago.days == 0:
            if ago.seconds < 3600:
                return f"{ago.seconds // 60} хв. тому"
            return f"{ago.seconds // 3600} год. тому"
        return f"{ago.days} дн. тому"
    except Exception:
        return last_activity

async def _get_active_interns(user_id: int) -> List[dict]:
    all_interns = await get_manager_interns(user_id)
    now = datetime.now(pytz.timezone(TIMEZONE))
    active: List[dict] = []
    for intern in all_interns:
        progress_data = await get_user_progress(intern['user_id'])
        role = intern.get("role")
        from database.positions import get_days_count_for_role
        role_days = await get_days_count_for_role(role) if role else DAYS_TOTAL
        if completed_days >= role_days:
            continue
        last_activity = intern.get('last_activity')
        if last_activity:
            try:
                dt = datetime.fromisoformat(last_activity)
                if dt.tzinfo is None:
                    dt = pytz.timezone(TIMEZONE).localize(dt)
                if (now - dt).days >= 3:
                    continue
            except Exception:
                pass
        active.append({
            "intern": intern,
            "display_name": intern.get('full_name', 'Невідомий стажер'),
            "last_activity_str": _format_last_activity(last_activity, now),
        })
    return active

async def manager_menu_callback(callback: CallbackQuery):
    if callback.message and callback.message.photo:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(
            "📋 <b>Адміністрування стажерів</b>\nОберіть дію:",
            reply_markup=manager_menu_keyboard()
        )
        return
    
    if callback.message:
        try:
            await callback.message.edit_text(
                "📋 <b>Адміністрування стажерів</b>\nОберіть дію:",
                reply_markup=manager_menu_keyboard()
            )
        except Exception:
            await callback.message.answer(
                "📋 <b>Адміністрування стажерів</b>\nОберіть дію:",
                reply_markup=manager_menu_keyboard()
            )

async def manager_interns_list_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    interns = await _get_active_interns(user_id)
    total = len(interns)
    text = (
        "🐾 <b>Список ваших булка-кошенят</b> 🐾\n\n"
        "Тут лише ті, хто ще навчається та активний!\n"
        f"Загалом: <b>{total}</b>"
    )

    if not interns:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="manager_menu")]])
        if callback.message:
            await callback.message.edit_text("У вас немає активних булка-кошенят 😸", reply_markup=kb)
        return

    buttons = [
        [InlineKeyboardButton(text=item["display_name"], callback_data=f"manager_intern_profile_{item['intern']['user_id']}")]
        for item in interns
    ]
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="manager_menu")])

    if callback.message:
        try:
            await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        except Exception:
            await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

async def manager_intern_learning_menu(callback: CallbackQuery, intern_id: Optional[int] = None):
    if intern_id is None:
        intern_id = int(callback.data.split("_")[-1])
    intern_details = await get_user_details(intern_id)
    overview = await get_days_overview(intern_id)
    progress_rows = await get_user_progress(intern_id)
    progress_map = {row["day"]: row for row in progress_rows}
    kb_rows = []
    for day, status in overview:
        row = progress_map.get(day, {})
        manual_flag = bool(row.get("manual_open"))
        opened_by = row.get("manual_opened_by")

        if status == DayStatus.COMPLETED:
            text = f"✅ День {day} — Пройдений"
            action = "noop"
        elif status == DayStatus.OPEN:
            if manual_flag:
                source_label = {
                    "dev": "Dev",
                    "manager": "керівник",
                    "hr": "HR",
                    "auto": "авто",
                }.get(opened_by, "вручну")
                text = f"🟢 День {day} — Відкритий вручну ({source_label})"
            else:
                text = f"🟢 День {day} — Відкритий"
            action = "close" if manual_flag else "noop"
        else:
            text = f"🔒 День {day} — Закритий"
            action = "open"

        callback_data = f"manager_day:{intern_id}:{day}:{action}"
        kb_rows.append([InlineKeyboardButton(text=text, callback_data=callback_data)])

    kb_rows.append([InlineKeyboardButton(text="⬅️ Назад до списку", callback_data="mgr_manage_days")])
    text = (
        f"Навчання стажера <b>{intern_details.get('full_name', 'Невідомий') if intern_details else 'Невідомий'}</b>\n"
        f"Оберіть день, щоб змінити його доступність:"
    )
    if callback.message:
        try:
            await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
        except Exception:
            await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))

async def manager_intern_day_action(callback: CallbackQuery):
    try:
        _, intern_id_str, day_str, action = callback.data.split(":")
    except ValueError:
        await callback.answer("Невірний формат дії.", show_alert=True)
        return

    intern_id = int(intern_id_str)
    day = int(day_str)
    overview = await get_days_overview(intern_id)
    status = next((s for d, s in overview if d == day), DayStatus.CLOSED)
    progress_rows = await get_user_progress(intern_id)
    row = next((p for p in progress_rows if p["day"] == day), {})
    manual_flag = bool(row.get("manual_open"))
    manual_source = row.get("manual_opened_by")

    if action == "open":
        if status == DayStatus.CLOSED:
            await open_day_manual(intern_id, day, opened_by="manager")
            await callback.answer(f"День {day} відкрито вручну.", show_alert=True)
        else:
            await callback.answer("Цей день вже доступний.", show_alert=True)
    elif action == "close":
        if manual_flag and manual_source in {"manager", "dev", "hr"}:
            await close_day(intern_id, day)
            await callback.answer(f"День {day} закрито.", show_alert=True)
        else:
            await callback.answer("Неможливо закрити день, відкритий автоматично.", show_alert=True)
    else:
        await callback.answer("День вже пройдений або не потребує змін.", show_alert=True)

    await manager_intern_learning_menu(callback, intern_id=intern_id)

async def manager_remind_intern_callback(callback: CallbackQuery):
    try:
        intern_id = int(callback.data.split("_")[-1])
    except (ValueError, IndexError):
        await callback.answer("Неправильний формат запиту до стажера.", show_alert=True)
        return

    intern = await get_user_details(intern_id)
    if not intern:
        await callback.answer("Стажера не знайдено.", show_alert=True)
        return

    ok = await send_intern_reminder(
        callback.bot,
        intern_id=intern_id,
        source="manager",
        sender_id=callback.from_user.id,
    )
    if ok:
        await callback.answer("Нагадування надіслано стажеру.", show_alert=True)
    else:
        await callback.answer("Не вдалося надіслати нагадування.", show_alert=True)

async def show_test_error_statistics(callback: CallbackQuery):
    user_id = callback.from_user.id
    is_hr = await is_hr_user(user_id)
    is_dev = await is_developer_user(user_id)

    if not (is_hr or is_dev):
        await callback.answer("Ця функція доступна лише для HR та Адміністраторів.", show_alert=True)
        return

    errors = await get_test_error_statistics()

    if not errors:
        text = "📊 Наразі немає статистики помилок в тестах. Все чисто! ✨"
    else:
        text_lines = ["📊 <b>Топ помилок у тестах</b>", ""]
        # Sort by error_count in descending order and take top 10
        sorted_errors = sorted(errors, key=lambda x: x['error_count'], reverse=True)[:10]
        for idx, error in enumerate(sorted_errors, 1):
            role = error['role']
            day = error['day']
            question_idx = error['question_idx']
            count = error['error_count']
            
            text_lines.append(f"<b>{idx}. {role}</b>")
            text_lines.append(f"   └ 📅 День {day} | ❓ Питання №{question_idx + 1}")
            text_lines.append(f"   └ ❌ Кількість помилок: <b>{count}</b>")
            text_lines.append("───────────────")
        
        # Додаємо інформацію про останнє скидання
        if sorted_errors:
            last_reset = sorted_errors[0].get('last_reset_at')
            if last_reset:
                try:
                    dt = datetime.fromisoformat(last_reset).strftime('%d.%m.%Y')
                    text_lines.append(f"\n<i>* Статистика збирається з {dt}</i>")
                    text_lines.append("<i>* Скидання відбувається автоматично 1-го числа кожного місяця.</i>")
                except:
                    pass
            text_lines.append("")
            
        text = "\n".join(text_lines)

    back_cb = "dev_main_analyt" if is_dev else "main_menu_photo"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=back_cb)]
    ])
    
    if callback.message:
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(text, reply_markup=kb)
        else:
            try:
                await callback.message.edit_text(text, reply_markup=kb)
            except Exception:
                await callback.message.answer(text, reply_markup=kb)
    await callback.answer()



async def process_registration_full_name(message: types.Message, state: FSMContext):
    full_name = message.text.strip()
    if len(full_name.split()) < 2:
        await message.answer("Будь ласка, введіть повне ім'я та прізвище (мінімум 2 слова).")
        return

    data = await state.get_data()
    manager_id = data.get("reg_manager_id")
    role = data.get("reg_role")
    city = data.get("reg_city")
    shop = data.get("reg_shop")
    shops = data.get("reg_shops") or ([shop] if shop else [])
    extra_data = data.get("reg_extra_data") or {}
    transfer_on_reg = data.get("reg_transfer_on_reg", 0)
    token = data.get("reg_token")
    
    user_id = message.from_user.id
    username = message.from_user.username

    if role == "Наглядач":
        await register_user(user_id, username=username, full_name=full_name)
        await add_observer(user_id, full_name, username, responsible_uid=manager_id)
        if token:
            await use_token(token, user_id)
        await message.answer(f"Вітаємо, {full_name}! Реєстрацію Наглядача успішно завершено. 👁✅")
        from bot.menus.developer import show_observer_main_menu
        await show_observer_main_menu(message, allow_edit=False, force_new_message=True)
        await state.clear()
        return

    if role == "Територіал":
        await register_user(user_id, username=username, full_name=full_name)
        t_type = extra_data.get("territorial_type") or "ТЗ"
        from database.managers import add_manager, reassign_city_managers_to_territorial
        await add_manager(
            uid=user_id,
            process="Територіал",
            full_name=full_name,
            username=username or "",
            city=city,
            territorial_type=t_type
        )
        if token:
            await use_token(token, user_id)
            
        transferred_count = 0
        if transfer_on_reg:
            transferred_count = await reassign_city_managers_to_territorial(city, user_id)
            
        # Сповіщення адміністратору, який створив посилання
        if manager_id:
            try:
                from bot.constants import TERRITORIAL_TYPES
                type_label = TERRITORIAL_TYPES.get(t_type, t_type)
                report_text = (
                    f"🗺 <b>Територіал зареєструвався!</b>\n\n"
                    f"👤 <b>ПІБ:</b> {html.escape(full_name)}\n"
                    f"🏙 <b>Місто:</b> {city}\n"
                    f"💼 <b>Тип:</b> {type_label} ({t_type})\n"
                )
                if transfer_on_reg:
                    report_text += f"✅ Керівників міста перепідпорядковано: <b>{transferred_count}</b>"
                await message.bot.send_message(manager_id, report_text, parse_mode="HTML")
            except Exception as exc:
                from bot.services.logger import get_logger
                get_logger().warning(f"Could not notify admin {manager_id} about territorial registration: {exc}")

        await message.answer(f"Вітаємо, {full_name}! Реєстрацію Територіала успішно завершено. 🗺✅")
        await show_developer_main_menu(message, is_territorial=True, allow_edit=False, force_new_message=True)
        await state.clear()
        return

    if role in ("Керівник", "Керівник Стажер"):
        await register_user(user_id, username=username, full_name=full_name)
        primary_shop = shops[0] if (shops and isinstance(shops, list)) else (shop if isinstance(shop, str) else None)
        await set_intern_extra(user_id, manager_id, "Керівник", city, shop=primary_shop)
        from database.managers import add_manager, transfer_users_by_shops
        
        responsible_uid = extra_data.get("responsible_uid") or manager_id
        mgr_shops = shops if shops else (shop if isinstance(shop, list) else ([shop] if shop else []))
        await add_manager(
            uid=user_id,
            username=username or "",
            full_name=full_name,
            process="Керівник Стажер",
            shops=mgr_shops,
            city=city,
            responsible_uid=responsible_uid
        )
        if token:
            await use_token(token, user_id)
            
        transferred_count = 0
        if transfer_on_reg and mgr_shops:
            transferred_count = await transfer_users_by_shops(city, mgr_shops, user_id)
            
        # Сповіщення творцю посилання (Територіалу або Адміну)
        if manager_id:
            try:
                shops_str = ", ".join(mgr_shops) if mgr_shops else (shop or "не вказано")
                report_text = (
                    f"👔 <b>Керівник зареєструвався!</b>\n\n"
                    f"👤 <b>ПІБ:</b> {html.escape(full_name)}\n"
                    f"🏙 <b>Місто:</b> {city}\n"
                    f"🏪 <b>Магазини:</b> {html.escape(shops_str)}\n"
                )
                if transfer_on_reg:
                    report_text += f"✅ Під його керівництво переведено: <b>{transferred_count}</b> співробітників."
                await message.bot.send_message(manager_id, report_text, parse_mode="HTML")
            except Exception as exc:
                from bot.services.logger import get_logger
                get_logger().warning(f"Could not notify creator {manager_id} about manager registration: {exc}")

        await message.answer(f"Вітаємо, {full_name}! Реєстрацію Керівника-стажера успішно завершено. 👔✅")
        initialize_user_progress(user_id)
        await show_manager_main_menu(message, allow_edit=False, force_new_message=True)
        await state.clear()
        return

    # Register/Update user with provided full_name
    await register_user(user_id, username=username, full_name=full_name)
    
    # Динамічно визначаємо дійсного керівника:
    # 1. Пріоритет: цільовий керівник/територіал, обраний адміністратором вручну
    # 2. Якщо обрано авто: керівник активного магазину
    # 3. Якщо в магазині немає керівника -> закріплюємо за Територіалом міста за напрямком (ВВ або ТЗ)
    from database.managers import get_manager_by_shop, get_appropriate_territorial_for_user, is_manager_user, get_manager_by_uid
    assigned_manager_id = None

    target_manager_id = extra_data.get("target_manager_id") if isinstance(extra_data, dict) else None
    if target_manager_id and await is_manager_user(target_manager_id):
        assigned_manager_id = target_manager_id
    elif shop:
        shop_mgr = await get_manager_by_shop(city, shop)
        if shop_mgr:
            assigned_manager_id = shop_mgr["uid"]
            
    if not assigned_manager_id:
        if manager_id and await is_manager_user(manager_id):
            assigned_manager_id = manager_id
        else:
            assigned_manager_id = await get_appropriate_territorial_for_user(city, role)
            if not assigned_manager_id:
                assigned_manager_id = manager_id

    await set_intern_extra(user_id, assigned_manager_id, role, city, shop=shop)
    
    if assigned_manager_id:
        try:
            await message.bot.send_message(
                assigned_manager_id,
                f"👤 <b>Новий співробітник зареєструвався!</b>\n\n"
                f"👤 <b>ПІБ:</b> {html.escape(full_name)}\n"
                f"💼 <b>Посада:</b> {role}\n"
                f"🏙 <b>Місто:</b> {city}\n"
                f"🏪 <b>Магазин:</b> {shop or 'не вказано'}",
                parse_mode="HTML"
            )
        except Exception:
            pass

    # Сповіщення адміністратору (якщо посилання створив адміністратор, відмінний від закріпленого керівника)
    creator_id = extra_data.get("creator_id") if isinstance(extra_data, dict) else None
    if creator_id and creator_id != assigned_manager_id:
        try:
            sup_mgr = await get_manager_by_uid(assigned_manager_id) if assigned_manager_id else None
            sup_name = sup_mgr.get("full_name") if sup_mgr else "не визначено"
            sup_proc = sup_mgr.get("process") if sup_mgr else ""
            sup_role_str = f" ({sup_proc})" if sup_proc else ""
            await message.bot.send_message(
                creator_id,
                f"✅ <b>Стажер зареєструвався за вашим посиланням!</b>\n\n"
                f"👤 <b>ПІБ:</b> {html.escape(full_name)}\n"
                f"💼 <b>Посада:</b> {role}\n"
                f"🏙 <b>Місто:</b> {city}\n"
                f"🏪 <b>Магазин:</b> {shop or 'не вказано'}\n"
                f"👔 <b>Закріплено за:</b> {html.escape(sup_name)}{sup_role_str}",
                parse_mode="HTML"
            )
        except Exception:
            pass
    
    if token:
        await use_token(token, user_id)
    
    # Скидаємо прогрес у БД та оперативній пам'яті для нового старту стажера
    from bot.state import user_progress
    user_progress[user_id] = {}
    try:
        from database import DB_PATH
        import aiosqlite
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM progress WHERE user_id = ?", (user_id,))
            await db.commit()
    except Exception as e:
        logger.warning(f"Failed to reset progress table for user {user_id}: {e}")

    await message.answer(f"Дякую, {full_name}! Реєстрацію завершено. ✅")
    
    initialize_user_progress(user_id)
    await show_student_main_menu(message, user_id, allow_edit=False)
    await state.clear()


async def global_error_handler(event: ErrorEvent):
    """
    Глобальний обробник помилок для Aiogram dispatcher.
    Витягує контекст користувача (ID, нікнейм, дію), придушує нешкідливі помилки мережі/API
    та передає виняток у логер для генерації Telegram-алерту.
    """
    exception = event.exception
    from bot.services.logger import get_logger
    logger = get_logger()

    # Log incoming callback data if available for debugging
    if hasattr(event, 'update') and event.update and event.update.callback_query:
        logger.debug(f"DEBUG: Incoming callback: {event.update.callback_query.data}")

    if isinstance(exception, TelegramBadRequest):
        error_message = str(exception).lower()
        # Suppress harmless Telegram API exceptions
        if any(msg in error_message for msg in [
            "query is too old", 
            "message is not modified",
            "message can't be deleted for everyone",
            "message to delete not found",
            "canceled by new editmessagemedia request"
        ]):
            return

    # Suppress Windows-specific network errors (WinError 64, 121) and timeouts
    error_str = str(exception).lower()
    if any(msg in error_str for msg in [
        "winerror 64", 
        "winerror 121", 
        "specified network name is no longer available", 
        "semaphore timeout period has expired",
        "request timeout error",
        "timeouterror"
    ]):
        logger.debug(f"Network transient error suppressed: {exception}")
        return

    # Витягуємо контекст користувача та події
    user_info = "Невідомо"
    action_info = "Невідома дія"

    if hasattr(event, "update") and event.update:
        upd = event.update
        if upd.callback_query:
            cq = upd.callback_query
            u = cq.from_user
            user_info = f"@{u.username} (ID: {u.id})" if u.username else f"{u.full_name} (ID: {u.id})"
            action_info = f"Кнопка: {cq.data}"
        elif upd.message:
            m = upd.message
            u = m.from_user
            if u:
                user_info = f"@{u.username} (ID: {u.id})" if u.username else f"{u.full_name} (ID: {u.id})"
            msg_preview = m.text[:120] if m.text else m.content_type
            action_info = f"Повідомлення: {msg_preview}"

    tg_context = f"{user_info} | {action_info}"

    # Логуємо помилку з трейсбеком та контекстом
    exc_info_tuple = (type(exception), exception, exception.__traceback__) if exception else True
    logger.error(
        f"Aiogram Handler Exception: {exception}",
        exc_info=exc_info_tuple,
        extra={"tg_context": tg_context}
    )


def register_handlers(dp: Dispatcher):
    # Register global error handler
    dp.error.register(global_error_handler)

    # 1. Developer & Admin menus (Priority)
    register_developer_menu_handlers(dp)
    from bot.menus.manager import register_manager_handlers
    register_manager_handlers(dp)
    from bot.menus.survey_taking import register_survey_taking_handlers
    register_survey_taking_handlers(dp)

    # 2. Main handlers
    dp.message.register(start_menu, Command("start"))
    dp.message.register(process_registration_full_name, RegistrationStates.waiting_for_full_name)
    dp.callback_query.register(menu_days, lambda c: c.data == "continue_learning")
    dp.callback_query.register(locked_day, lambda c: c.data.startswith("locked_"))
    dp.callback_query.register(day_content, lambda c: c.data.startswith("day_"))
    dp.callback_query.register(day_material_detail, lambda c: c.data.startswith("daymat_"))
    dp.callback_query.register(show_syllabus, lambda c: c.data == "show_syllabus")
    dp.callback_query.register(syllabus_locked, lambda c: c.data == "syllabus_locked")
    dp.callback_query.register(menu_days_page_callback, lambda c: c.data and c.data.startswith("learning_days_page:"))
    dp.callback_query.register(material_notification_page_callback, lambda c: c.data and c.data.startswith("mat_ch_pag:"))
    dp.callback_query.register(material_notification_ack_callback, lambda c: c.data and c.data.startswith("mat_ch_ack:"))
    
    dp.callback_query.register(_handle_pagination, lambda c: c.data and c.data.startswith("paginate:"))

    register_day_handlers(dp)
    
    dp.callback_query.register(main_menu_callback, lambda c: c.data == "main_menu")
    dp.callback_query.register(main_menu_callback_force_photo, lambda c: c.data == "main_menu_photo")
    # dp.callback_query.register(manager_menu_callback, lambda c: c.data == "manager_menu") # Removed to use new manager menu
    # dp.callback_query.register(manager_interns_list_handler, lambda c: c.data == "manager_list")
    dp.callback_query.register(manager_support, lambda c: c.data == "support")
    dp.callback_query.register(cancel_support, lambda c: c.data == "cancel_support")
    dp.message.register(process_support_message, SupportStates.waiting_for_message)
    dp.callback_query.register(manager_reply_callback, lambda c: c.data.startswith("reply_to_"))
    dp.callback_query.register(cancel_manager_reply, lambda c: c.data == "cancel_manager_reply")
    dp.message.register(process_manager_reply, ManagerReplyStates.waiting_for_reply)
    dp.callback_query.register(profile_handler_router, lambda c: c.data == "profile")
    dp.callback_query.register(manager_intern_profile_handler, lambda c: c.data.startswith("manager_intern_profile_"))
    dp.callback_query.register(manager_intern_learning_menu, lambda c: c.data.startswith("manager_intern_learning_"))
    dp.callback_query.register(manager_intern_day_action, lambda c: c.data.startswith("manager_day:"))
    dp.callback_query.register(manager_remind_intern_callback, lambda c: c.data and c.data.startswith("remind_") and c.data.split("_")[-1].isdigit())
    
    dp.callback_query.register(remind_topic_self_callback, lambda c: c.data == "remind_topic_self")
    dp.callback_query.register(remind_topic_global_callback, lambda c: c.data == "remind_topic_global")
    dp.callback_query.register(remind_role_select_callback, lambda c: c.data and c.data.startswith("remind_role_select:"))
    dp.callback_query.register(remind_topic_for_intern_callback, lambda c: c.data.startswith("remind_topic_for_intern:"))
    dp.callback_query.register(show_test_error_statistics, lambda c: c.data == "show_test_errors")
    dp.message.register(process_keyword_search, SearchStates.waiting_for_query)