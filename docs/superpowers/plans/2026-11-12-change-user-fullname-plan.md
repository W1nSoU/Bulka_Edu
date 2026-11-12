# План реалізації: Зміна ПІБ користувача адміністратором

## Завдання 1: Додавання стану FSM та кнопки в меню
- [ ] У `bot/menus/developer.py` в класі `DeveloperStates` додати `waiting_change_fullname = State()`.
- [ ] У функції `developer_user_modify_menu` додати кнопку `[InlineKeyboardButton(text="👤 Змінити ПІБ", callback_data=f"dev_change_fullname:{user_id}")]`.

## Завдання 2: Реалізація обробників введення та валідації
- [ ] Створити функцію `developer_change_fullname_start(callback, state)`: запит введення ПІБ + перехід у стан `waiting_change_fullname`.
- [ ] Створити функцію `developer_process_change_fullname(message, state)`:
  - валідація на щонайменше 3 слова (`len(words) >= 3`);
  - при помилці — підказка про необхідність 3 слів;
  - при успіху — `UPDATE users SET full_name = ? WHERE user_id = ?`;
  - виведення повідомлення про успіх та оновленого профілю користувача.

## Завдання 3: Реєстрація хендлерів
- [ ] У `register_developer_handlers` зареєструвати callback `dev_change_fullname:` та message handler на `waiting_change_fullname`.

## Завдання 4: Написання тестів та верифікація
- [ ] Написати юніт-тести для перевірки валідації 3 слів та успішного оновлення ПІБ у базі.
- [ ] Запустити повний тестовий набір (100% pass).

## Завдання 5: Фіксація та публікація
- [ ] Закомітити та запушити зміни в `origin/main`.
