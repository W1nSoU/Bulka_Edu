# Дизайн: Зміна ПІБ користувача адміністратором

## 1. Огляд та мета
Надати адміністратору можливість редагувати повне ім'я (ПІБ) будь-якого користувача через меню "✍️ Змінити" в картці користувача.
Обов'язкова валідація: ПІБ повинно містити щонайменше 3 слова (Прізвище, Ім'я, По батькові).

## 2. Архітектурні зміни

### 2.1. FSM-стани (`bot/menus/developer.py`)
- Додати новий стан:
  ```python
  waiting_change_fullname = State()
  ```

### 2.2. Меню редагування (`developer_user_modify_menu`)
- Додати кнопку `👤 Змінити ПІБ` першою в клавіатурі:
  ```python
  [InlineKeyboardButton(text="👤 Змінити ПІБ", callback_data=f"dev_change_fullname:{user_id}")]
  ```

### 2.3. Обробники (`bot/menus/developer.py`)
- `developer_change_fullname_start(callback: CallbackQuery, state: FSMContext)`:
  - Зчитує `user_id` з callback_data.
  - Встановлює стан `DeveloperStates.waiting_change_fullname`.
  - Запитує текст: *"Введіть нове повне ПІБ користувача (Прізвище, Ім'я, По батькові):"*.
  - Надає кнопку скасування: `_cancel_keyboard(f"dev_user_modify:{user_id}")`.
- `developer_process_change_fullname(message: Message, state: FSMContext)`:
  - Отримує введений текст, очищає зайві пробіли: `words = message.text.strip().split()`.
  - Валідація: якщо `len(words) < 3`, надсилає повідомлення про помилку:
    *"❌ ПІБ має містити щонайменше 3 слова (Прізвище, Ім'я, По батькові). Спробуйте ще раз:"* і залишається в стані.
  - Зберігає нове ПІБ у `database/users.db`:
    ```sql
    UPDATE users SET full_name = ? WHERE user_id = ?
    ```
  - Очищає стан `state.clear()`.
  - Надсилає підтвердження: *"✅ ПІБ користувача успішно змінено на <b>{new_fullname}</b>!"*.
  - Відображає оновлену картку користувача `get_user_days_report(user_id)`.

### 2.4. Реєстрація хендлерів
- Зареєструвати `developer_change_fullname_start` на `dev_change_fullname:`.
- Зареєструвати `developer_process_change_fullname` на стан `waiting_change_fullname`.

## 3. Критерії успішності
1. Кнопка `👤 Змінити ПІБ` з'являється в меню "Змінити".
2. Введення 1 або 2 слів блокується з повідомленням про помилку.
3. Введення 3+ слів успішно оновлює `full_name` у базі даних.
4. Оновлене ПІБ відображається в картці користувача.
5. Усі тести проходять успішно (100% pass).
