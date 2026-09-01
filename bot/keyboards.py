from typing import Optional
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from bot.services.learning_progress import DayStatus

def main_menu_keyboard(is_new_user=False, is_manager=False, is_hr=False, is_developer=False, is_territorial=False, is_observer=False, can_search=False):
    """
    Створює клавіатуру головного меню.
    Якщо is_developer=True, показує меню для розробника.
    Якщо is_manager=True, показує меню для керівника.
    Якщо is_hr=True, додає кнопку Панелі керівника.
    Якщо is_territorial=True, додає кнопку Панелі Територіала.
    Якщо is_observer=True, додає кнопку Панелі Наглядача.
    """
    if is_observer:
        buttons = [
            [InlineKeyboardButton(text="👁 Панель Наглядача", callback_data="developer_menu")],
            [InlineKeyboardButton(text="👤 Профіль", callback_data="profile")]
        ]
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    if is_developer:
        buttons = [
            [InlineKeyboardButton(text="🛠 Панель Адміністратора", callback_data="developer_menu")],
            [InlineKeyboardButton(text="👑 Панель керівника", callback_data="manager_menu")], # Always add for developers
        ]
        buttons.append([InlineKeyboardButton(text="👤 Профіль", callback_data="profile")])
        return InlineKeyboardMarkup(inline_keyboard=buttons)
        
    if is_territorial:
        buttons = [
            [InlineKeyboardButton(text="🗺 Панель Територіала", callback_data="developer_menu")],
            [InlineKeyboardButton(text="👑 Панель керівника", callback_data="manager_menu")],
            [InlineKeyboardButton(text="👤 Профіль", callback_data="profile")]
        ]
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    if is_manager:
        buttons = [
            [InlineKeyboardButton(text="📋 Адміністрування стажерів", callback_data="manager_menu")],
            [InlineKeyboardButton(text="👤 Профіль", callback_data="profile")]
        ]
        if is_hr:
            buttons.insert(0, [InlineKeyboardButton(text="👑 Панель керівника", callback_data="manager_menu")])
        
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
    button_text = "📁 Розпочати навчання" if is_new_user else "📁 Продовжити навчання"
    buttons = [
        [InlineKeyboardButton(text=button_text, callback_data="continue_learning")],
    ]
    if can_search:
        buttons.append([InlineKeyboardButton(text="🧠 Нагадати тему", callback_data="remind_topic_self")])
    if is_hr or is_developer or is_territorial:
        buttons.append([InlineKeyboardButton(text="🧠 Нагадати тему", callback_data="remind_topic_global")])
    buttons.extend([
        [InlineKeyboardButton(text="👤 Профіль", callback_data="profile")],
        [InlineKeyboardButton(text="🛡️ Зв'язок з керівником", callback_data="support")],
    ])
    
    # Додаємо кнопки адмін-панелей для тих, хто має доступ
    prefix_buttons = []
    if is_developer:
        prefix_buttons.append([InlineKeyboardButton(text="🛠 Панель Адміністратора", callback_data="developer_menu")])
    elif is_territorial:
        prefix_buttons.append([InlineKeyboardButton(text="🗺 Панель Територіала", callback_data="developer_menu")])
        
    if is_hr:
        prefix_buttons.append([InlineKeyboardButton(text="👑 Панель керівника", callback_data="manager_menu")])
    if prefix_buttons:
        buttons = prefix_buttons + buttons
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def manager_menu_keyboard():
    """Клавіатура головного меню керівника"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 Навчання", callback_data="continue_learning")],
        [InlineKeyboardButton(text="👨‍💼 Керівники", callback_data="mgr_managers_list")],
        [InlineKeyboardButton(text="👨‍🎓 Стажери", callback_data="mgr_interns|all")],
        [InlineKeyboardButton(text="📊 Звіт стажерів", callback_data="mgr_report")],
        [InlineKeyboardButton(text="🏠 Головне меню", callback_data="main_menu")]
    ])

def learning_menu_keyboard(day_statuses, syllabus_enabled=True, total_days=None, page: int = 0):
    """
    Клавіатура меню навчання з підтримкою пагінації (по 6 днів на сторінку).

    Args:
        day_statuses: список (day, DayStatus) із get_days_overview().
        syllabus_enabled: чи показувати кнопку «Зміст».
        total_days: загальна кількість днів навчання для цієї посади.
                    Якщо None — визначається автоматично як останній день у списку.
        page: номер сторінки (0-indexed).
    """
    from bot.config import DAYS_TOTAL  # локальний імпорт щоб уникнути циклу

    PER_PAGE = 6
    total_count = len(day_statuses)
    pages_total = max(1, (total_count + PER_PAGE - 1) // PER_PAGE)
    page = max(0, min(page, pages_total - 1))

    # Визначаємо останній день курсу
    if total_days is None:
        if day_statuses:
            total_days = day_statuses[-1][0]  # останній день у списку
        else:
            total_days = DAYS_TOTAL

    syllabus_unlocked = False
    for day, status in day_statuses:
        if day == total_days and status != DayStatus.CLOSED:
            syllabus_unlocked = True

    start = page * PER_PAGE
    paginated_days = day_statuses[start:start + PER_PAGE]

    kb_rows = []
    for day, status in paginated_days:
        if status == DayStatus.COMPLETED:
            txt = f"✅ День {day}"
            cb = f"day_{day}"
        elif status == DayStatus.OPEN:
            txt = f"День {day}"
            cb = f"day_{day}"
        else:
            txt = f"🔒 День {day}"
            cb = f"locked_{day}"
        kb_rows.append([InlineKeyboardButton(text=txt, callback_data=cb)])

    # Рядок пагінації, якщо сторінок більше 1
    if pages_total > 1:
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"learning_days_page:{page - 1}"))
        nav_row.append(InlineKeyboardButton(text=f"📄 {page + 1}/{pages_total}", callback_data="ignore"))
        if page < pages_total - 1:
            nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"learning_days_page:{page + 1}"))
        kb_rows.append(nav_row)

    # Показуємо зміст лише якщо він увімкнений адміном
    if syllabus_enabled:
        if syllabus_unlocked:
            kb_rows.append([InlineKeyboardButton(text="📚 Зміст", callback_data="show_syllabus")])
        else:
            kb_rows.append([InlineKeyboardButton(text="🔒 Зміст", callback_data="syllabus_locked")])
        
    kb_rows.append([InlineKeyboardButton(text="В головне меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)


def manager_interns_list_keyboard(interns):
    kb_rows = []
    for intern in interns:
        kb_rows.append([
            InlineKeyboardButton(
                text=f"{intern.get('full_name', 'Невідомий')} ({intern.get('user_id')})",
                callback_data=f"manager_intern_learning_{intern['user_id']}"
            )
        ])
    kb_rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)

def manager_intern_actions_keyboard(intern_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💌 Надіслати повідомлення", callback_data=f"manager_sendmsg_{intern_id}")],
        [InlineKeyboardButton(text="🔔 Нагадати про навчання", callback_data=f"remind_{intern_id}")],
        [InlineKeyboardButton(text="🧠 Нагадати тему", callback_data=f"remind_topic_for_intern:{intern_id}")],
        [InlineKeyboardButton(text="🔙 До списку стажерів", callback_data="manager_list")],
        [InlineKeyboardButton(text="🏠 Головне меню", callback_data="main_menu")]
    ])

def back_to_manager_menu_keyboard():
    """Клавіатура для повернення до меню керівника"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад до панелі керівника", callback_data="manager_menu")]
    ])

# Legacy aliases for backward compatibility
def hr_menu_keyboard():
    """Deprecated: use manager_menu_keyboard instead"""
    return manager_menu_keyboard()

def back_to_hr_menu_keyboard():
    """Deprecated: use back_to_manager_menu_keyboard instead"""
    return back_to_manager_menu_keyboard()


def get_pagination_keyboard(
    current_page: int,
    total_pages: int,
    content_identifier: str,
    day: int,
    final_button: Optional[InlineKeyboardButton] = None,
) -> Optional[InlineKeyboardMarkup]:
    """
    Generates a pagination keyboard.
    If a final_button is provided, it's added on the last page.
    """
    if total_pages <= 1 and not final_button:
        return InlineKeyboardMarkup(inline_keyboard=[[final_button]]) if final_button else None
    
    buttons = []
    row = []

    # Back button
    if current_page > 0:
        row.append(
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=f"paginate:{content_identifier}:{day}:{current_page - 1}",
            )
        )

    # Page indicator (only if there are multiple pages)
    if total_pages > 1:
        row.append(
            InlineKeyboardButton(
                text=f"📄 {current_page + 1}/{total_pages}",
                callback_data="do_nothing",  # A dummy callback
            )
        )

    # Next button
    if current_page < total_pages - 1:
        row.append(
            InlineKeyboardButton(
                text="Далі ➡️",
                callback_data=f"paginate:{content_identifier}:{day}:{current_page + 1}",
            )
        )

    if row:
        buttons.append(row)

    # Add the final button on the last page
    if final_button and current_page == total_pages - 1:
        buttons.append([final_button])
        
    return InlineKeyboardMarkup(inline_keyboard=buttons)
