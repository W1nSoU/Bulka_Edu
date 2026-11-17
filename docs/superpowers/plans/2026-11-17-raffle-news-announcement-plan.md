# План реалізації: Новина про початок розіграшу та захист від порожніх заявок

**Дата:** 2026-11-17
**Специфікація:** [2026-11-17-raffle-news-announcement-design.md](../../specs/2026-11-17-raffle-news-announcement-design.md)

## Завдання 1: Розширення `bot/services/news_broadcaster.py`
1. Оновити `get_news_reaction_keyboard(news_id, current_reaction=None, extra_buttons=None)` для підтримки додаткового рядка інлайн-кнопок (наприклад, «🎁 Взяти участь у розіграші») над рядом реакцій.
2. Додати підтримку `extra_buttons` у `send_news_batch`, `dispatch_news_waves` і `start_news_wave_broadcast` (зворотно сумісно, за замовчуванням `None`).
3. Зберігати/відновлювати `extra_buttons` або передавати їх у розсилці, а в `news_react` обробнику (`bot/menus/developer.py`) зберігати верхні не-реакційні кнопки при оновленні реакції користувача.

## Завдання 2: Автоматична новина при запуску розіграшу (`bot/menus/raffles.py`)
1. Встановити `send_announcement=True` за замовчуванням у `dev_raffle_create_start`.
2. У `dev_raffle_launch_handler`:
   - Якщо `send_ann` (за замовчуванням `True`), формувати текст новини у стилі BULKA з назвою, умовами, форматом участі, дедлайном та закликом до участі.
   - Визначати аудиторію через `get_matching_news_recipients(selected_roles, selected_city)`.
   - Створювати запис у таблиці `news` через `create_news(...)`.
   - Запускати `start_news_wave_broadcast(...)` із додатковою кнопкою `[InlineKeyboardButton(text="🎁 Взяти участь у розіграші", callback_data="user_raffle_menu")]`.

## Завдання 3: Захист від порожніх заявок у `user_raffle_confirm_sub_handler` (`bot/menus/raffles.py`)
1. Якщо `ptype in ("text", "formatted_text")` і `not draft_text` (або `ptype in ("media", "document")` і `not file_id`), не викликати `add_raffle_submission`, а повернути користувача до `RaffleParticipationStates.waiting_submission` із проханням надіслати відповідь повторно.

## Завдання 4: Тести та верифікація
1. Додати тести в `tests/test_raffles.py`:
   - За замовчуванням `send_announcement=True`, при запуску розіграшу створюється запис у `news` і запускається `start_news_wave_broadcast` з кнопкою участі.
   - `user_raffle_confirm_sub_handler` відхиляє порожній `draft_text` для текстового розіграшу.
   - `get_news_reaction_keyboard` коректно поєднує `extra_buttons` та реакції.
2. Запустити `./venv/bin/python -m unittest discover tests`.
3. Закомітити та запушити в `origin/main`.
