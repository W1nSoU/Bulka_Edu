import re

file_path = "/Users/daniildusinskij/All/Dev/Bulka_Edu/bot/menus/developer.py"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Update imports
old_mgr_import = """from database.managers import (
    get_all_managers,
    add_manager,
    delete_manager_by_uid,
    get_manager_by_uid,
    get_all_developers as get_all_devs_from_managers_db, # Alias to avoid name conflict if needed
    get_all_kerivnyky,
    is_territorial_user,"""

new_mgr_import = """from database.managers import (
    get_all_managers,
    add_manager,
    delete_manager_by_uid,
    get_manager_by_uid,
    get_all_developers as get_all_devs_from_managers_db, # Alias to avoid name conflict if needed
    get_all_kerivnyky,
    is_territorial_user,
    is_observer_user,
    get_all_observers,
    get_observer_by_uid,
    delete_observer_by_uid,"""

assert old_mgr_import in content, "old_mgr_import not found"
content = content.replace(old_mgr_import, new_mgr_import, 1)

old_token_import = "from database.tokens import get_token_stats, cleanup_expired_tokens"
new_token_import = "from database.tokens import get_token_stats, cleanup_expired_tokens, generate_token"
assert old_token_import in content, "old_token_import not found"
content = content.replace(old_token_import, new_token_import, 1)

# 2. _ensure_developer
old_ensure = """async def _ensure_developer(callback: CallbackQuery, require_main: bool = False) -> bool:
    user_id = callback.from_user.id
    is_dev = await is_developer_user(user_id)
    
    if require_main:
        # is_dev is only true if user is in 'developers' table AND is MAIN_DEVELOPER_ID
        is_dev = is_dev and user_id == MAIN_DEVELOPER_ID
    
    if not is_dev:
        try:
            await callback.answer("⛔️ Доступ заборонено. Ви не маєте ролі Developer.", show_alert=True)
        except Exception:
            pass
        return False
    return True"""

new_ensure = """async def _ensure_developer(callback: CallbackQuery, require_main: bool = False, allow_observer: bool = False) -> bool:
    user_id = callback.from_user.id
    is_dev = await is_developer_user(user_id)
    
    if require_main:
        # is_dev is only true if user is in 'developers' table AND is MAIN_DEVELOPER_ID
        is_dev = is_dev and user_id == MAIN_DEVELOPER_ID
    
    if allow_observer and not is_dev:
        if await is_observer_user(user_id):
            return True
            
    if not is_dev:
        try:
            await callback.answer("⛔️ Доступ заборонено. Ви не маєте відповідних прав.", show_alert=True)
        except Exception:
            pass
        return False
    return True"""

assert old_ensure in content, "old_ensure not found"
content = content.replace(old_ensure, new_ensure, 1)

# 3. _check_access
old_check = """async def _check_access(callback: CallbackQuery) -> tuple[bool, bool, bool]:
    \"\"\"
    Перевіряє доступ для панелі розробника/територіала.
    Повертає кортеж (has_access, is_admin, is_territorial).
    Якщо доступу немає, показує alert.
    \"\"\"
    user_id = callback.from_user.id
    is_admin = await is_developer_user(user_id)
    is_territorial = await is_territorial_user(user_id)
    has_access = is_admin or is_territorial"""

new_check = """async def _check_access(callback: CallbackQuery) -> tuple[bool, bool, bool]:
    \"\"\"
    Перевіряє доступ для панелі розробника/територіала/наглядача.
    Повертає кортеж (has_access, is_admin, is_territorial).
    Якщо доступу немає, показує alert.
    \"\"\"
    user_id = callback.from_user.id
    is_admin = await is_developer_user(user_id)
    is_territorial = await is_territorial_user(user_id)
    is_observer = await is_observer_user(user_id)
    has_access = is_admin or is_territorial or is_observer"""

assert old_check in content, "old_check not found"
content = content.replace(old_check, new_check, 1)

# 4. _admin_cho_keyboard
old_cho_kb = """def _admin_cho_keyboard(is_main_dev: bool, is_admin: bool, is_territorial: bool) -> InlineKeyboardMarkup:
    buttons = []
    if is_admin:
        buttons.append([InlineKeyboardButton(text="📚 Навчальні матеріали", callback_data="dev_main_study")])
    buttons.append([InlineKeyboardButton(text="📊 Аналітика", callback_data="dev_main_analyt")])
    buttons.append([InlineKeyboardButton(text="👥 Команда Bulka", callback_data="dev_main_team")])
    if is_admin:
        buttons.append([InlineKeyboardButton(text="🛠 Інше", callback_data="dev_main_other")])
    buttons.append([InlineKeyboardButton(text="🏠 В головне меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)"""

new_cho_kb = """def _admin_cho_keyboard(is_main_dev: bool, is_admin: bool, is_territorial: bool, is_observer: bool = False) -> InlineKeyboardMarkup:
    buttons = []
    if is_admin or is_observer:
        buttons.append([InlineKeyboardButton(text="📚 Навчальні матеріали", callback_data="dev_main_study")])
    buttons.append([InlineKeyboardButton(text="📊 Аналітика", callback_data="dev_main_analyt")])
    buttons.append([InlineKeyboardButton(text="👥 Команда Bulka", callback_data="dev_main_team")])
    if is_admin:
        buttons.append([InlineKeyboardButton(text="🛠 Інше", callback_data="dev_main_other")])
    buttons.append([InlineKeyboardButton(text="🏠 В головне меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)"""

assert old_cho_kb in content, "old_cho_kb not found"
content = content.replace(old_cho_kb, new_cho_kb, 1)

# 5. _admin_analyt_keyboard
old_analyt_kb = """def _admin_analyt_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="📊 Аналітика", callback_data="dev_analytics_menu"),
            InlineKeyboardButton(text="📊 Помилки тестів", callback_data="show_test_errors")
        ],
        [
            InlineKeyboardButton(text="📜 Історія нагадувань", callback_data="dev_reminder_history"),
            InlineKeyboardButton(text="📊 XLSX звіт", callback_data="dev_xlsx_menu")
        ],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="developer_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)"""

new_analyt_kb = """def _admin_analyt_keyboard(is_observer: bool = False) -> InlineKeyboardMarkup:
    row2 = [InlineKeyboardButton(text="📜 Історія нагадувань", callback_data="dev_reminder_history")]
    if not is_observer:
        row2.append(InlineKeyboardButton(text="📊 XLSX звіт", callback_data="dev_xlsx_menu"))
        
    buttons = [
        [
            InlineKeyboardButton(text="📊 Аналітика", callback_data="dev_analytics_menu"),
            InlineKeyboardButton(text="📊 Помилки тестів", callback_data="show_test_errors")
        ],
        row2,
        [InlineKeyboardButton(text="🔙 Назад", callback_data="developer_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)"""

assert old_analyt_kb in content, "old_analyt_kb not found"
content = content.replace(old_analyt_kb, new_analyt_kb, 1)

# 6. _admin_team_keyboard
old_team_kb = """def _admin_team_keyboard(is_admin: bool, is_territorial: bool) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="👥 Користувачі", callback_data="dev_users_menu"),
            InlineKeyboardButton(text="👔 Команда Керівників", callback_data="dev_manage_managers")
        ]
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton(text="👨‍💻 Команда Адміністраторів", callback_data="dev_team_menu")])
        buttons.append([
            InlineKeyboardButton(text="🗺 Територіали", callback_data="dev_territorials_menu"),
            InlineKeyboardButton(text="👁 Наглядачі", callback_data="dev_observers_menu")
        ])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="developer_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)"""

new_team_kb = """def _admin_team_keyboard(is_admin: bool, is_territorial: bool, is_observer: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="👥 Користувачі", callback_data="dev_users_menu"),
            InlineKeyboardButton(text="👔 Команда Керівників", callback_data="dev_manage_managers")
        ]
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton(text="👨‍💻 Команда Адміністраторів", callback_data="dev_team_menu")])
        buttons.append([
            InlineKeyboardButton(text="🗺 Територіали", callback_data="dev_territorials_menu"),
            InlineKeyboardButton(text="👁 Наглядачі", callback_data="dev_observers_menu")
        ])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="developer_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)"""

assert old_team_kb in content, "old_team_kb not found"
content = content.replace(old_team_kb, new_team_kb, 1)

# 7. developer_menu_callback & section handlers
old_menu_cb = """async def developer_menu_callback(callback: CallbackQuery):
    has_access, is_admin, is_territorial = await _check_access(callback)
    if not has_access:
        return
    is_main = callback.from_user.id == MAIN_DEVELOPER_ID
    
    try:
        await callback.message.delete()
    except Exception:
        pass
    
    caption_text = "🛠 <b>Панель Адміністратора</b>\\nОберіть розділ для керування:" if is_admin else "🛠 <b>Панель Територіала</b>\\nОберіть розділ для керування:"
    
    try:
        photo = FSInputFile("img/admin/admin_cho.jpg")
        await callback.message.answer_photo(
            photo=photo,
            caption=caption_text,
            reply_markup=_admin_cho_keyboard(is_main, is_admin, is_territorial)
        )
    except Exception:
        await callback.message.answer(
            caption_text,
            reply_markup=_admin_cho_keyboard(is_main, is_admin, is_territorial)
        )

    try:
        await callback.answer()
    except TelegramBadRequest as e:
        if "query is too old" not in str(e):
            raise e


async def dev_main_study_handler(callback: CallbackQuery):
    has_access, is_admin, is_territorial = await _check_access(callback)
    if not has_access or not is_admin:
        await callback.answer("⛔️ Доступ заборонено.", show_alert=True)
        return
    try:
        await callback.message.delete()
    except Exception:
        pass
    try:
        photo = FSInputFile("img/admin/admin_study.jpg")
        await callback.message.answer_photo(
            photo=photo,
            caption="📚 <b>Навчальні матеріали</b>",
            reply_markup=_admin_study_keyboard()
        )
    except Exception:
        await callback.message.answer(
            "📚 <b>Навчальні матеріали</b>",
            reply_markup=_admin_study_keyboard()
        )
    await callback.answer()


async def dev_main_analyt_handler(callback: CallbackQuery):
    has_access, is_admin, is_territorial = await _check_access(callback)
    if not has_access:
        return
    try:
        await callback.message.delete()
    except Exception:
        pass
    try:
        photo = FSInputFile("img/admin/admin_analyt.jpg")
        await callback.message.answer_photo(
            photo=photo,
            caption="📊 <b>Аналітика</b>",
            reply_markup=_admin_analyt_keyboard()
        )
    except Exception:
        await callback.message.answer(
            "📊 <b>Аналітика</b>",
            reply_markup=_admin_analyt_keyboard()
        )
    await callback.answer()


async def dev_main_team_handler(callback: CallbackQuery):
    has_access, is_admin, is_territorial = await _check_access(callback)
    if not has_access:
        return
    try:
        await callback.message.delete()
    except Exception:
        pass
    try:
        photo = FSInputFile("img/admin/admin_spus.jpg")
        await callback.message.answer_photo(
            photo=photo,
            caption="👥 <b>Команда Bulka</b>",
            reply_markup=_admin_team_keyboard(is_admin, is_territorial)
        )
    except Exception:
        await callback.message.answer(
            "👥 <b>Команда Bulka</b>",
            reply_markup=_admin_team_keyboard(is_admin, is_territorial)
        )
    await callback.answer()"""

new_menu_cb = """async def developer_menu_callback(callback: CallbackQuery):
    has_access, is_admin, is_territorial = await _check_access(callback)
    if not has_access:
        return
    is_main = callback.from_user.id == MAIN_DEVELOPER_ID
    is_observer = await is_observer_user(callback.from_user.id)
    
    try:
        await callback.message.delete()
    except Exception:
        pass
    
    if is_admin:
        caption_text = "🛠 <b>Панель Адміністратора</b>\\nОберіть розділ для керування:"
    elif is_observer:
        caption_text = "👁 <b>Панель Наглядача</b>\\nОберіть розділ для перегляду:"
    else:
        caption_text = "🛠 <b>Панель Територіала</b>\\nОберіть розділ для керування:"
    
    try:
        photo = FSInputFile("img/admin/admin_cho.jpg")
        await callback.message.answer_photo(
            photo=photo,
            caption=caption_text,
            reply_markup=_admin_cho_keyboard(is_main, is_admin, is_territorial, is_observer=is_observer)
        )
    except Exception:
        await callback.message.answer(
            caption_text,
            reply_markup=_admin_cho_keyboard(is_main, is_admin, is_territorial, is_observer=is_observer)
        )

    try:
        await callback.answer()
    except TelegramBadRequest as e:
        if "query is too old" not in str(e):
            raise e


async def dev_main_study_handler(callback: CallbackQuery):
    has_access, is_admin, is_territorial = await _check_access(callback)
    is_observer = await is_observer_user(callback.from_user.id)
    if not has_access or (not is_admin and not is_observer):
        await callback.answer("⛔️ Доступ заборонено.", show_alert=True)
        return
    try:
        await callback.message.delete()
    except Exception:
        pass
    try:
        photo = FSInputFile("img/admin/admin_study.jpg")
        await callback.message.answer_photo(
            photo=photo,
            caption="📚 <b>Навчальні матеріали</b>",
            reply_markup=_admin_study_keyboard()
        )
    except Exception:
        await callback.message.answer(
            "📚 <b>Навчальні матеріали</b>",
            reply_markup=_admin_study_keyboard()
        )
    await callback.answer()


async def dev_main_analyt_handler(callback: CallbackQuery):
    has_access, is_admin, is_territorial = await _check_access(callback)
    if not has_access:
        return
    is_observer = await is_observer_user(callback.from_user.id)
    try:
        await callback.message.delete()
    except Exception:
        pass
    try:
        photo = FSInputFile("img/admin/admin_analyt.jpg")
        await callback.message.answer_photo(
            photo=photo,
            caption="📊 <b>Аналітика</b>",
            reply_markup=_admin_analyt_keyboard(is_observer=is_observer)
        )
    except Exception:
        await callback.message.answer(
            "📊 <b>Аналітика</b>",
            reply_markup=_admin_analyt_keyboard(is_observer=is_observer)
        )
    await callback.answer()


async def dev_main_team_handler(callback: CallbackQuery):
    has_access, is_admin, is_territorial = await _check_access(callback)
    if not has_access:
        return
    is_observer = await is_observer_user(callback.from_user.id)
    try:
        await callback.message.delete()
    except Exception:
        pass
    try:
        photo = FSInputFile("img/admin/admin_spus.jpg")
        await callback.message.answer_photo(
            photo=photo,
            caption="👥 <b>Команда Bulka</b>",
            reply_markup=_admin_team_keyboard(is_admin, is_territorial, is_observer=is_observer)
        )
    except Exception:
        await callback.message.answer(
            "👥 <b>Команда Bulka</b>",
            reply_markup=_admin_team_keyboard(is_admin, is_territorial, is_observer=is_observer)
        )
    await callback.answer()"""

assert old_menu_cb in content, "old_menu_cb not found"
content = content.replace(old_menu_cb, new_menu_cb, 1)

# 8. _build_managers_team_view
old_mgr_view = """async def _build_managers_team_view(is_admin: bool, is_territorial: bool, user_id: int, page: int = 0):
    \"\"\"Список керівників з пагінацією, пошуком та прямим переходом до карток.\"\"\"
    if is_admin:
        all_hrs = await get_all_kerivnyky()
    elif is_territorial:
        all_hrs = await get_managers_by_responsible(user_id)
    else:
        all_hrs = []"""

new_mgr_view = """async def _build_managers_team_view(is_admin: bool, is_territorial: bool, user_id: int, page: int = 0):
    \"\"\"Список керівників з пагінацією, пошуком та прямим переходом до карток.\"\"\"
    is_obs = await is_observer_user(user_id)
    if is_admin or is_obs:
        all_hrs = await get_all_kerivnyky()
    elif is_territorial:
        all_hrs = await get_managers_by_responsible(user_id)
    else:
        all_hrs = []"""

assert old_mgr_view in content, "old_mgr_view not found"
content = content.replace(old_mgr_view, new_mgr_view, 1)

# 9. _users_menu_keyboard & _get_users_menu_kb
old_users_kb = """def _users_menu_keyboard(is_admin: bool, is_territorial: bool) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="🎓 Стажери", callback_data="dev_users_interns"),
            InlineKeyboardButton(text="👷 Працівники", callback_data="dev_users_workers"),
        ],
        [
            InlineKeyboardButton(text="🚀 Активні стажери", callback_data="dev_users_active"),
            InlineKeyboardButton(text="😴 Неактивні", callback_data="dev_users_inactive"),
        ],
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton(text="🏙️ За містом", callback_data="dev_users_by_city")])
        buttons.append([InlineKeyboardButton(text="✅ Перевести завершених у працівники", callback_data="dev_users_bulk_promote")])
        buttons.append([InlineKeyboardButton(text="📋 Список користувачів", callback_data="dev_users_list")])
        buttons.append([InlineKeyboardButton(text="🔍 Пошук", callback_data="dev_users_search")])
        buttons.append([InlineKeyboardButton(text="❌ Видалити", callback_data="dev_users_delete")])

    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="developer_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def _get_users_menu_kb(user_id: int) -> InlineKeyboardMarkup:
    from database.hr import is_developer_user
    from database.managers import is_territorial_user
    is_admin = await is_developer_user(user_id)
    is_territorial = await is_territorial_user(user_id)
    return _users_menu_keyboard(is_admin, is_territorial)"""

new_users_kb = """def _users_menu_keyboard(is_admin: bool, is_territorial: bool, is_observer: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="🎓 Стажери", callback_data="dev_users_interns"),
            InlineKeyboardButton(text="👷 Працівники", callback_data="dev_users_workers"),
        ],
        [
            InlineKeyboardButton(text="🚀 Активні стажери", callback_data="dev_users_active"),
            InlineKeyboardButton(text="😴 Неактивні", callback_data="dev_users_inactive"),
        ],
    ]
    if is_admin or is_observer:
        buttons.append([InlineKeyboardButton(text="🏙️ За містом", callback_data="dev_users_by_city")])
        if is_admin:
            buttons.append([InlineKeyboardButton(text="✅ Перевести завершених у працівники", callback_data="dev_users_bulk_promote")])
        buttons.append([InlineKeyboardButton(text="📋 Список користувачів", callback_data="dev_users_list")])
        buttons.append([InlineKeyboardButton(text="🔍 Пошук", callback_data="dev_users_search")])
        if is_admin:
            buttons.append([InlineKeyboardButton(text="❌ Видалити", callback_data="dev_users_delete")])

    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="developer_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def _get_users_menu_kb(user_id: int) -> InlineKeyboardMarkup:
    from database.hr import is_developer_user
    from database.managers import is_territorial_user, is_observer_user
    is_admin = await is_developer_user(user_id)
    is_territorial = await is_territorial_user(user_id)
    is_observer = await is_observer_user(user_id)
    return _users_menu_keyboard(is_admin, is_territorial, is_observer=is_observer)"""

assert old_users_kb in content, "old_users_kb not found"
content = content.replace(old_users_kb, new_users_kb, 1)

# 10. _build_manager_card & dev_mgr_view
old_card = """async def _build_manager_card(manager_uid: int, is_admin: bool, is_territorial: bool):
    mgr = await get_manager_by_uid(manager_uid)
    if not mgr:
        return None"""

new_card = """async def _build_manager_card(manager_uid: int, is_admin: bool, is_territorial: bool, is_observer: bool = False):
    mgr = await get_manager_by_uid(manager_uid)
    if not mgr:
        return None"""

assert old_card in content, "old_card not found"
content = content.replace(old_card, new_card, 1)

old_card_btns = """    buttons = []
    if mgr.get("status") != "fired":
        buttons.append([InlineKeyboardButton(text="✏️ Змінити", callback_data=f"dev_mgr_edit_menu:{manager_uid}")])
        if is_admin:
            buttons.append([InlineKeyboardButton(text="🔄 Перепривʼязати", callback_data=f"dev_mgr_reassign_menu:{manager_uid}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад до списку", callback_data="dev_manage_managers")])"""

new_card_btns = """    buttons = []
    if mgr.get("status") != "fired" and not is_observer:
        buttons.append([InlineKeyboardButton(text="✏️ Змінити", callback_data=f"dev_mgr_edit_menu:{manager_uid}")])
        if is_admin:
            buttons.append([InlineKeyboardButton(text="🔄 Перепривʼязати", callback_data=f"dev_mgr_reassign_menu:{manager_uid}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад до списку", callback_data="dev_manage_managers")])"""

assert old_card_btns in content, "old_card_btns not found"
content = content.replace(old_card_btns, new_card_btns, 1)

old_mgr_view_call = """    card_data = await _build_manager_card(manager_uid, is_admin, is_territorial)"""
new_mgr_view_call = """    is_obs = await is_observer_user(callback.from_user.id)
    card_data = await _build_manager_card(manager_uid, is_admin, is_territorial, is_observer=is_obs)"""

assert old_mgr_view_call in content, "old_mgr_view_call not found"
content = content.replace(old_mgr_view_call, new_mgr_view_call, 1)

# 11. Add Observer views before register_developer_menu_handlers
observer_funcs = """

# ==============================================================================
# УПРАВЛІННЯ НАГЛЯДАЧАМИ (ПУНКТ 6)
# ==============================================================================

async def _build_observers_menu_view(page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    \"\"\"Будує інтерфейс списку наглядачів для адмін-панелі.\"\"\"
    observers = await get_all_observers()
    
    PER_PAGE = 6
    total_count = len(observers)
    pages_total = max(1, (total_count + PER_PAGE - 1) // PER_PAGE)
    page = max(0, min(page, pages_total - 1))
    
    start = page * PER_PAGE
    paginated_obs = observers[start:start + PER_PAGE]
    
    lines = [
        f"👁 <b>Команда Наглядачів (всього: {total_count})</b>",
        "Наглядачі мають доступ лише до перегляду матеріалів та аналітики.",
        ""
    ]
    
    if not observers:
        lines.append("  <i>У системі поки немає призначених наглядачів.</i>")
    
    buttons = []
    for obs in paginated_obs:
        name, _ = await _format_identity(obs["uid"], obs.get("full_name"), obs.get("username"))
        btn_text = f"👁 {name}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"dev_obs_view:{obs['uid']}")])
    
    # Кнопки пагінації
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"dev_obs_page:{page - 1}"))
    if pages_total > 1:
        nav_row.append(InlineKeyboardButton(text=f"📄 {page + 1}/{pages_total}", callback_data="ignore"))
    if page < pages_total - 1:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"dev_obs_page:{page + 1}"))
    
    if nav_row:
        buttons.append(nav_row)
        
    buttons.append([InlineKeyboardButton(text="➕ Створити запрошення", callback_data="dev_obs_create_invite")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="dev_main_team")])
    
    return "\\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


async def developer_observers_menu(callback: CallbackQuery):
    \"\"\"Показує список наглядачів.\"\"\"
    if not await _ensure_developer(callback):
        return
    page = 0
    if callback.data and callback.data.startswith("dev_obs_page:"):
        try:
            page = int(callback.data.split(":")[1])
        except (ValueError, IndexError):
            page = 0
            
    text, kb = await _build_observers_menu_view(page=page)
    await _edit_or_answer(callback.message, text, reply_markup=kb)
    await callback.answer()


async def developer_observer_create_invite(callback: CallbackQuery):
    \"\"\"Генерує токен та посилання для нового наглядача.\"\"\"
    if not await _ensure_developer(callback):
        return
    
    admin_uid = callback.from_user.id
    token = await generate_token(manager_id=admin_uid, role="Наглядач", expires_in_hours=24)
    bot_info = await callback.bot.get_me()
    bot_username = bot_info.username
    invite_link = f"https://t.me/{bot_username}?start={admin_uid}-{token}"
    
    text = (
        "👁 <b>Запрошення для Наглядача</b>\\n\\n"
        "🔗 <b>Одноразове посилання:</b>\\n"
        f"<code>{invite_link}</code>\\n\\n"
        "⏳ <b>Термін дії:</b> 24 години.\\n"
        "👤 Надішліть це посилання людині, яку призначаєте Наглядачем.\\n"
        "Після переходу за посиланням користувач введе своє ПІБ та автоматично отримає роль <b>Наглядач</b>."
    )
    
    buttons = [
        [InlineKeyboardButton(text="⬅️ До списку наглядачів", callback_data="dev_observers_menu")]
    ]
    
    await _edit_or_answer(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


async def developer_observer_view(callback: CallbackQuery):
    \"\"\"Показує картку наглядача.\"\"\"
    if not await _ensure_developer(callback):
        return
    try:
        obs_uid = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Помилка ідентифікатора.", show_alert=True)
        return
        
    obs = await get_observer_by_uid(obs_uid)
    if not obs:
        await callback.answer("Наглядача не знайдено або він вже видалений.", show_alert=True)
        return
        
    name, username = await _format_identity(obs["uid"], obs.get("full_name"), obs.get("username"))
    
    resp_name = "Адміністратор"
    if obs.get("responsible_uid"):
        resp_mgr = await get_manager_by_uid(obs["responsible_uid"])
        if resp_mgr and resp_mgr.get("full_name"):
            resp_name = resp_mgr["full_name"]
            
    text = (
        f"👁 <b>Картка Наглядача</b>\\n\\n"
        f"👤 <b>ПІБ:</b> {html.escape(name)}\\n"
        f"🆔 <b>Telegram ID:</b> <code>{obs['uid']}</code>\\n"
        f"📱 <b>Username:</b> {html.escape(username)}\\n"
        f"👑 <b>Призначив:</b> {html.escape(resp_name)}\\n"
        f"🟢 <b>Статус:</b> Активний (лише перегляд)"
    )
    
    buttons = [
        [InlineKeyboardButton(text="🗑 Видалити наглядача", callback_data=f"dev_obs_del_confirm:{obs_uid}")],
        [InlineKeyboardButton(text="⬅️ До списку наглядачів", callback_data="dev_observers_menu")]
    ]
    
    await _edit_or_answer(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


async def developer_observer_delete_confirm(callback: CallbackQuery):
    \"\"\"Підтвердження видалення наглядача.\"\"\"
    if not await _ensure_developer(callback):
        return
    try:
        obs_uid = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Помилка ідентифікатора.", show_alert=True)
        return
        
    obs = await get_observer_by_uid(obs_uid)
    if not obs:
        await callback.answer("Наглядача не знайдено.", show_alert=True)
        return
        
    name, _ = await _format_identity(obs["uid"], obs.get("full_name"))
    
    text = (
        f"⚠️ <b>Видалення Наглядача</b>\\n\\n"
        f"Ви впевнені, що хочете видалити наглядача <b>{html.escape(name)}</b>?\\n"
        f"Користувач втратить доступ до панелі наглядача."
    )
    
    buttons = [
        [InlineKeyboardButton(text="🗑 Так, видалити", callback_data=f"dev_obs_del_do:{obs_uid}")],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data=f"dev_obs_view:{obs_uid}")]
    ]
    
    await _edit_or_answer(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


async def developer_observer_delete_do(callback: CallbackQuery):
    \"\"\"Виконує видалення наглядача.\"\"\"
    if not await _ensure_developer(callback):
        return
    try:
        obs_uid = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Помилка ідентифікатора.", show_alert=True)
        return
        
    await delete_observer_by_uid(obs_uid)
    await callback.answer("✅ Наглядача успішно видалено.", show_alert=True)
    text, kb = await _build_observers_menu_view(page=0)
    await _edit_or_answer(callback.message, text, reply_markup=kb)

"""

old_reg = "def register_developer_menu_handlers(dp: Dispatcher):"
new_reg = observer_funcs + "\ndef register_developer_menu_handlers(dp: Dispatcher):\n\n    # Observers (Пункт 6)\n    dp.callback_query.register(developer_observers_menu, lambda c: c.data == \"dev_observers_menu\" or (c.data and c.data.startswith(\"dev_obs_page:\")))\n    dp.callback_query.register(developer_observer_create_invite, lambda c: c.data == \"dev_obs_create_invite\")\n    dp.callback_query.register(developer_observer_view, lambda c: c.data and c.data.startswith(\"dev_obs_view:\"))\n    dp.callback_query.register(developer_observer_delete_confirm, lambda c: c.data and c.data.startswith(\"dev_obs_del_confirm:\"))\n    dp.callback_query.register(developer_observer_delete_do, lambda c: c.data and c.data.startswith(\"dev_obs_del_do:\"))"

assert old_reg in content, "old_reg not found"
content = content.replace(old_reg, new_reg, 1)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("Patch applied successfully!")
