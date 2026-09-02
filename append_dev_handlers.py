import sys

with open('bot/menus/developer.py', 'r') as f:
    content = f.read()

# 1. Додаємо імпорти в початок файлу
imports_to_add = """
from bot.services.positions import get_all_positions, get_position_by_id, add_position, update_position_name, update_position_days, get_position_stats
from bot.services.cities import get_all_cities, get_city_by_id, add_city, update_city_name, delete_city
"""
if "from bot.services.positions" not in content:
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if line.startswith('from bot.services'):
            lines.insert(i, imports_to_add.strip())
            break
    content = '\n'.join(lines)


# 2. Додаємо функції-обробники перед register_developer_menu_handlers
handlers_code = """
# ==============================================================================
# УПРАВЛІННЯ ПОСАДАМИ
# ==============================================================================

def _positions_keyboard(positions: list, page: int = 1) -> InlineKeyboardMarkup:
    items_per_page = 6
    total_pages = (len(positions) - 1) // items_per_page + 1
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    current_positions = positions[start_idx:end_idx]

    buttons = []
    for pos in current_positions:
        buttons.append([InlineKeyboardButton(text=f"👔 {pos['name']}", callback_data=f"dev_pos_view:{pos['id']}")])
    
    # Пагінація
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"dev_positions_page:{page-1}"))
    nav_row.append(InlineKeyboardButton(text=f"📄 {page}/{total_pages or 1}", callback_data="ignore"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"dev_positions_page:{page+1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton(text="➕ Додати посаду", callback_data="dev_pos_add")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="dev_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def dev_positions_menu(callback: CallbackQuery):
    positions = await get_all_positions()
    await _edit_or_answer(
        callback.message,
        "👔 <b>Управління посадами</b>\nОберіть посаду для редагування або додайте нову:",
        reply_markup=_positions_keyboard(positions, 1)
    )
    await callback.answer()


async def dev_positions_page(callback: CallbackQuery):
    page = int(callback.data.split(":")[1])
    positions = await get_all_positions()
    await _edit_or_answer(
        callback.message,
        "👔 <b>Управління посадами</b>\nОберіть посаду для редагування або додайте нову:",
        reply_markup=_positions_keyboard(positions, page)
    )
    await callback.answer()


async def dev_pos_add_start(callback: CallbackQuery, state: FSMContext):
    await _edit_or_answer(
        callback.message,
        "Введіть назву нової посади:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Скасувати", callback_data="dev_positions_menu")]])
    )
    await state.set_state(DeveloperStates.waiting_add_position_name)
    await callback.answer()


async def dev_pos_add_name(message: Message, state: FSMContext):
    name = message.text.strip()
    await state.update_data(pos_name=name)
    await message.answer(
        f"Посада: <b>{name}</b>\nВведіть кількість днів навчання (за замовчуванням 5):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Залишити 5", callback_data="dev_pos_add_days:5")],
            [InlineKeyboardButton(text="Скасувати", callback_data="dev_positions_menu")]
        ])
    )
    await state.set_state(DeveloperStates.waiting_add_position_days)


async def _dev_pos_finish_add(message: Message, state: FSMContext, pos_name: str, days: int):
    success = await add_position(pos_name, days)
    if success:
        await message.answer(f"✅ Посаду <b>{pos_name}</b> ({days} днів) успішно додано!")
    else:
        await message.answer(f"❌ Помилка: посада <b>{pos_name}</b> вже існує або виникла інша помилка.")
    await state.clear()
    
    # Повертаємось до списку
    positions = await get_all_positions()
    await message.answer(
        "👔 <b>Управління посадами</b>",
        reply_markup=_positions_keyboard(positions, 1)
    )


async def dev_pos_add_days_text(message: Message, state: FSMContext):
    data = await state.get_data()
    pos_name = data.get('pos_name')
    if not pos_name:
        await state.clear()
        return
        
    try:
        days = int(message.text.strip())
        await _dev_pos_finish_add(message, state, pos_name, days)
    except ValueError:
        await message.answer("Будь ласка, введіть числове значення кількості днів.")


async def dev_pos_add_days_callback(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    pos_name = data.get('pos_name')
    if not pos_name:
        await state.clear()
        return
        
    days = int(callback.data.split(":")[1])
    await _dev_pos_finish_add(callback.message, state, pos_name, days)
    await callback.answer()


async def dev_pos_view(callback: CallbackQuery):
    pos_id = int(callback.data.split(":")[1])
    pos = await get_position_by_id(pos_id)
    if not pos:
        await callback.answer("Посаду не знайдено!", show_alert=True)
        return
        
    stats = await get_position_stats(pos['name'])
    
    text = (
        f"👔 <b>Посада:</b> {pos['name']}\n"
        f"📅 <b>Днів навчання:</b> {pos['days_count']}\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"• Працівників: {stats['workers_count']}\n"
        f"• Стажерів: {stats['interns_count']}\n"
        f"• Всього: {stats['total']}"
    )
    
    buttons = [
        [InlineKeyboardButton(text="✏️ Змінити назву", callback_data=f"dev_pos_edit_name:{pos_id}")],
        [InlineKeyboardButton(text="✏️ Змінити кількість днів", callback_data=f"dev_pos_edit_days:{pos_id}")],
        [InlineKeyboardButton(text="🔙 До списку посад", callback_data="dev_positions_menu")]
    ]
    
    await _edit_or_answer(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


async def dev_pos_edit_name_start(callback: CallbackQuery, state: FSMContext):
    pos_id = int(callback.data.split(":")[1])
    pos = await get_position_by_id(pos_id)
    
    await _edit_or_answer(
        callback.message,
        f"Введіть нову назву для посади <b>{pos['name']}</b>:\n\n"
        f"⚠️ <i>Увага: зміна назви автоматично оновить всіх користувачів, матеріали та історію!</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Скасувати", callback_data=f"dev_pos_view:{pos_id}")]])
    )
    await state.update_data(edit_pos_id=pos_id)
    await state.set_state(DeveloperStates.waiting_edit_position_name)
    await callback.answer()


async def dev_pos_edit_name_process(message: Message, state: FSMContext):
    data = await state.get_data()
    pos_id = data.get('edit_pos_id')
    new_name = message.text.strip()
    
    success = await update_position_name(pos_id, new_name)
    if success:
        await message.answer(f"✅ Назву посади змінено на <b>{new_name}</b>, зв'язані сутності оновлено.")
    else:
        await message.answer("❌ Помилка: можливо посада з такою назвою вже існує.")
        
    await state.clear()
    pos = await get_position_by_id(pos_id)
    
    # Повертаємось до перегляду
    stats = await get_position_stats(pos['name'])
    text = (
        f"👔 <b>Посада:</b> {pos['name']}\n"
        f"📅 <b>Днів навчання:</b> {pos['days_count']}\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"• Працівників: {stats['workers_count']}\n"
        f"• Стажерів: {stats['interns_count']}\n"
        f"• Всього: {stats['total']}"
    )
    buttons = [
        [InlineKeyboardButton(text="✏️ Змінити назву", callback_data=f"dev_pos_edit_name:{pos_id}")],
        [InlineKeyboardButton(text="✏️ Змінити кількість днів", callback_data=f"dev_pos_edit_days:{pos_id}")],
        [InlineKeyboardButton(text="🔙 До списку посад", callback_data="dev_positions_menu")]
    ]
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


async def dev_pos_edit_days_start(callback: CallbackQuery, state: FSMContext):
    pos_id = int(callback.data.split(":")[1])
    pos = await get_position_by_id(pos_id)
    
    await _edit_or_answer(
        callback.message,
        f"Введіть нову кількість днів навчання для посади <b>{pos['name']}</b> (зараз {pos['days_count']}):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Скасувати", callback_data=f"dev_pos_view:{pos_id}")]])
    )
    await state.update_data(edit_pos_id=pos_id)
    await state.set_state(DeveloperStates.waiting_edit_position_days)
    await callback.answer()


async def dev_pos_edit_days_process(message: Message, state: FSMContext):
    data = await state.get_data()
    pos_id = data.get('edit_pos_id')
    
    try:
        new_days = int(message.text.strip())
        success = await update_position_days(pos_id, new_days)
        if success:
            await message.answer(f"✅ Кількість днів змінено на {new_days}.")
        else:
            await message.answer("❌ Помилка під час оновлення.")
    except ValueError:
        await message.answer("Будь ласка, введіть число.")
        return
        
    await state.clear()
    pos = await get_position_by_id(pos_id)
    
    # Повертаємось до перегляду
    stats = await get_position_stats(pos['name'])
    text = (
        f"👔 <b>Посада:</b> {pos['name']}\n"
        f"📅 <b>Днів навчання:</b> {pos['days_count']}\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"• Працівників: {stats['workers_count']}\n"
        f"• Стажерів: {stats['interns_count']}\n"
        f"• Всього: {stats['total']}"
    )
    buttons = [
        [InlineKeyboardButton(text="✏️ Змінити назву", callback_data=f"dev_pos_edit_name:{pos_id}")],
        [InlineKeyboardButton(text="✏️ Змінити кількість днів", callback_data=f"dev_pos_edit_days:{pos_id}")],
        [InlineKeyboardButton(text="🔙 До списку посад", callback_data="dev_positions_menu")]
    ]
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


# ==============================================================================
# УПРАВЛІННЯ МІСТАМИ
# ==============================================================================

def _cities_keyboard(cities: list, page: int = 1) -> InlineKeyboardMarkup:
    items_per_page = 10
    total_pages = (len(cities) - 1) // items_per_page + 1
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    current_cities = cities[start_idx:end_idx]

    buttons = []
    for city in current_cities:
        buttons.append([InlineKeyboardButton(text=f"🏙 {city['name']}", callback_data=f"dev_city_view:{city['id']}")])
    
    # Пагінація
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"dev_cities_page:{page-1}"))
    nav_row.append(InlineKeyboardButton(text=f"📄 {page}/{total_pages or 1}", callback_data="ignore"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"dev_cities_page:{page+1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton(text="➕ Додати місто", callback_data="dev_city_add")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="dev_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def dev_cities_menu(callback: CallbackQuery):
    cities = await get_all_cities()
    await _edit_or_answer(
        callback.message,
        "🏙 <b>Управління містами</b>\nОберіть місто для редагування або додайте нове:",
        reply_markup=_cities_keyboard(cities, 1)
    )
    await callback.answer()


async def dev_cities_page(callback: CallbackQuery):
    page = int(callback.data.split(":")[1])
    cities = await get_all_cities()
    await _edit_or_answer(
        callback.message,
        "🏙 <b>Управління містами</b>\nОберіть місто для редагування або додайте нове:",
        reply_markup=_cities_keyboard(cities, page)
    )
    await callback.answer()


async def dev_city_add_start(callback: CallbackQuery, state: FSMContext):
    await _edit_or_answer(
        callback.message,
        "Введіть назву нового міста:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Скасувати", callback_data="dev_cities_menu")]])
    )
    await state.set_state(DeveloperStates.waiting_add_city_name)
    await callback.answer()


async def dev_city_add_name(message: Message, state: FSMContext):
    name = message.text.strip()
    success = await add_city(name)
    if success:
        await message.answer(f"✅ Місто <b>{name}</b> успішно додано!")
    else:
        await message.answer(f"❌ Помилка: місто <b>{name}</b> вже існує.")
    await state.clear()
    
    cities = await get_all_cities()
    await message.answer(
        "🏙 <b>Управління містами</b>",
        reply_markup=_cities_keyboard(cities, 1)
    )


async def dev_city_view(callback: CallbackQuery):
    city_id = int(callback.data.split(":")[1])
    city = await get_city_by_id(city_id)
    if not city:
        await callback.answer("Місто не знайдено!", show_alert=True)
        return
        
    text = f"🏙 <b>Місто:</b> {city['name']}"
    
    buttons = [
        [InlineKeyboardButton(text="✏️ Змінити назву", callback_data=f"dev_city_edit_name:{city_id}")],
        [InlineKeyboardButton(text="🗑 Видалити місто", callback_data=f"dev_city_delete:{city_id}")],
        [InlineKeyboardButton(text="🔙 До списку міст", callback_data="dev_cities_menu")]
    ]
    
    await _edit_or_answer(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


async def dev_city_edit_name_start(callback: CallbackQuery, state: FSMContext):
    city_id = int(callback.data.split(":")[1])
    city = await get_city_by_id(city_id)
    
    await _edit_or_answer(
        callback.message,
        f"Введіть нову назву для міста <b>{city['name']}</b>:\n\n"
        f"⚠️ <i>Увага: зміна назви автоматично оновить всіх користувачів!</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Скасувати", callback_data=f"dev_city_view:{city_id}")]])
    )
    await state.update_data(edit_city_id=city_id)
    await state.set_state(DeveloperStates.waiting_edit_city_name)
    await callback.answer()


async def dev_city_edit_name_process(message: Message, state: FSMContext):
    data = await state.get_data()
    city_id = data.get('edit_city_id')
    new_name = message.text.strip()
    
    success = await update_city_name(city_id, new_name)
    if success:
        await message.answer(f"✅ Назву міста змінено на <b>{new_name}</b>, зв'язані сутності оновлено.")
    else:
        await message.answer("❌ Помилка під час оновлення назви міста.")
        
    await state.clear()
    
    city = await get_city_by_id(city_id)
    text = f"🏙 <b>Місто:</b> {city['name']}"
    buttons = [
        [InlineKeyboardButton(text="✏️ Змінити назву", callback_data=f"dev_city_edit_name:{city_id}")],
        [InlineKeyboardButton(text="🗑 Видалити місто", callback_data=f"dev_city_delete:{city_id}")],
        [InlineKeyboardButton(text="🔙 До списку міст", callback_data="dev_cities_menu")]
    ]
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


async def dev_city_delete(callback: CallbackQuery):
    city_id = int(callback.data.split(":")[1])
    city = await get_city_by_id(city_id)
    
    if not city:
        await callback.answer("Місто не знайдено!", show_alert=True)
        return
        
    await _edit_or_answer(
        callback.message,
        f"❗️ Ви впевнені, що хочете видалити місто <b>{city['name']}</b>?\n\n"
        f"<i>Користувачі з цим містом збережуть його назву, але воно зникне зі списку вибору.</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="❌ Ні, скасувати", callback_data=f"dev_city_view:{city_id}"),
                InlineKeyboardButton(text="✅ Так, видалити", callback_data=f"dev_city_delete_confirm:{city_id}")
            ]
        ])
    )
    await callback.answer()


async def dev_city_delete_confirm(callback: CallbackQuery):
    city_id = int(callback.data.split(":")[1])
    success = await delete_city(city_id)
    
    if success:
        await callback.answer("Місто видалено!", show_alert=True)
    else:
        await callback.answer("Помилка при видаленні!", show_alert=True)
        
    cities = await get_all_cities()
    await _edit_or_answer(
        callback.message,
        "🏙 <b>Управління містами</b>",
        reply_markup=_cities_keyboard(cities, 1)
    )

"""

if "УПРАВЛІННЯ ПОСАДАМИ" not in content:
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if line.startswith('def register_developer_menu_handlers'):
            lines.insert(i, handlers_code)
            break
    content = '\n'.join(lines)


# 3. Додаємо реєстрацію роутів
routes_to_add = """
    # Positions
    dp.callback_query.register(dev_positions_menu, lambda c: c.data == "dev_positions_menu")
    dp.callback_query.register(dev_positions_page, lambda c: c.data and c.data.startswith("dev_positions_page:"))
    dp.callback_query.register(dev_pos_add_start, lambda c: c.data == "dev_pos_add")
    dp.message.register(dev_pos_add_name, DeveloperStates.waiting_add_position_name)
    dp.message.register(dev_pos_add_days_text, DeveloperStates.waiting_add_position_days)
    dp.callback_query.register(dev_pos_add_days_callback, DeveloperStates.waiting_add_position_days, lambda c: c.data and c.data.startswith("dev_pos_add_days:"))
    dp.callback_query.register(dev_pos_view, lambda c: c.data and c.data.startswith("dev_pos_view:"))
    dp.callback_query.register(dev_pos_edit_name_start, lambda c: c.data and c.data.startswith("dev_pos_edit_name:"))
    dp.message.register(dev_pos_edit_name_process, DeveloperStates.waiting_edit_position_name)
    dp.callback_query.register(dev_pos_edit_days_start, lambda c: c.data and c.data.startswith("dev_pos_edit_days:"))
    dp.message.register(dev_pos_edit_days_process, DeveloperStates.waiting_edit_position_days)

    # Cities
    dp.callback_query.register(dev_cities_menu, lambda c: c.data == "dev_cities_menu")
    dp.callback_query.register(dev_cities_page, lambda c: c.data and c.data.startswith("dev_cities_page:"))
    dp.callback_query.register(dev_city_add_start, lambda c: c.data == "dev_city_add")
    dp.message.register(dev_city_add_name, DeveloperStates.waiting_add_city_name)
    dp.callback_query.register(dev_city_view, lambda c: c.data and c.data.startswith("dev_city_view:"))
    dp.callback_query.register(dev_city_edit_name_start, lambda c: c.data and c.data.startswith("dev_city_edit_name:"))
    dp.message.register(dev_city_edit_name_process, DeveloperStates.waiting_edit_city_name)
    dp.callback_query.register(dev_city_delete, lambda c: c.data and c.data.startswith("dev_city_delete:"))
    dp.callback_query.register(dev_city_delete_confirm, lambda c: c.data and c.data.startswith("dev_city_delete_confirm:"))
"""
if "dev_positions_menu" not in content.split("def register_developer_menu_handlers(dp: Dispatcher):")[1]:
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if "def register_developer_menu_handlers(dp: Dispatcher):" in line:
            lines.insert(i + 1, routes_to_add)
            break
    content = '\n'.join(lines)

with open('bot/menus/developer.py', 'w') as f:
    f.write(content)
