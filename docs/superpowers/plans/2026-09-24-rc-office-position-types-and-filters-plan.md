# План реалізації: Додавання типів посад РЦ та ОФІС, фільтрація та закріплення за адміністратором

**Специфікація:** [2026-09-24-rc-office-position-types-and-filters-design.md](file:///Users/daniildusinskij/All/Dev/Bulka_Edu/docs/superpowers/specs/2026-09-24-rc-office-position-types-and-filters-design.md)  
**Дата:** 2026-09-24  

---

## Крок 1: Константи та валідація типів посад
- **Файл:** `bot/constants.py`
  - Додати `POSITION_TYPES = {"ТЗ": "🏪 ТЗ", "ВВ": "🍞 ВВ", "РЦ": "📦 РЦ", "ОФІС": "🏢 ОФІС"}`.
  - Додати `VALID_POSITION_TYPES = tuple(POSITION_TYPES.keys())`.
  - Експортувати їх у `__all__`.
- **Файл:** `database/positions.py`
  - Імпортувати `VALID_POSITION_TYPES`.
  - Оновити `add_position`: валідувати `territorial_type in VALID_POSITION_TYPES`.
  - Оновити `update_territorial_type`: валідувати `new_type in VALID_POSITION_TYPES`.
  - Оновити `get_position_direction`: повертати точний збережений `territorial_type` (включно з `"РЦ"` та `"ОФІС"`).
- **Файл:** `bot/services/positions.py`
  - Оновити `update_position_type` та `add_position` для підтримки всіх 4 типів з `VALID_POSITION_TYPES`.

## Крок 2: Отримання користувачів за типом посади
- **Файл:** `database/users.py`
  - Реалізувати функцію:
    ```python
    async def get_users_by_position_type(territorial_type: str) -> list[dict]:
    ```
  - Робить запит із зв'язком `users.role = positions.name` де `positions.territorial_type = ?`.
  - Повертає список словників користувачів.

## Крок 3: UI створення посади та картки посади
- **Файл:** `bot/menus/developer.py`
  - **Створення посади:**
    - Оновити `_dev_pos_prompt_type`: сітка 2х2 (`[🏪 ТЗ, 🍞 ВВ]`, `[📦 РЦ, 🏢 ОФІС]`, `[❌ Скасувати]`).
    - Оновити `dev_pos_add_type_callback`: використання `POSITION_TYPES` для назви типу.
  - **Картка посади (`dev_pos_view`):**
    - Відображати актуальну іконку типу через `POSITION_TYPES.get(t_type, t_type)`.
    - Замінити старий toggle на кнопку `[🏷 Змінити тип]` (callback `dev_pos_type_menu:{pos_id}`).
  - **Підменю зміни типу:**
    - Додати функцію `dev_pos_type_menu(callback: CallbackQuery)`: виводить сітку 2х2, поточний тип помічено `✅`, кнопка назад `[🔙 Назад до посади]`.
    - Додати функцію `dev_pos_set_type(callback: CallbackQuery)`: оновлює тип, показує `callback.answer`, повертає картку посади.
    - Зареєструвати нові callback-хендлери в `register_developer_handlers`.

## Крок 4: Фільтрація користувачів за типом у меню фільтрів
- **Файл:** `bot/menus/developer.py`
  - В `_users_filters_keyboard`: додати кнопку `[🏷️ За типом]` (callback `dev_users_by_type`) у 2-й рядок поруч із `👔 За керівниками`.
  - Додати функцію `developer_users_by_type_menu(callback: CallbackQuery)`: виводить сітку вибору типу `[🏪 ТЗ, 🍞 ВВ]`, `[📦 РЦ, 🏢 ОФІС]`, `[⬅️ Назад]`.
  - Додати функцію `developer_users_filter_type(callback: CallbackQuery)`: отримує користувачів через `get_users_by_position_type`, враховує територіалів (якщо не адмін) та викликає `_developer_show_users_list(..., mode=f"type:{t_type}")`.
  - В `developer_users_pagination_handler`: додати обробку `parts[1] == "type"` для пагінації за типом.
  - Зареєструвати callback-хендлери для `dev_users_by_type` та `dev_users_filter_type:`.

## Крок 5: Закріплення стажерів РЦ та ОФІС за адміністратором
- **Файл:** `bot/menus/developer.py` (`developer_users_add_role`):
  - Перевірити напрямок посади `direction = await get_position_direction(role)`.
  - Якщо `direction in ("РЦ", "ОФІС")`:
    - `target_supervisor_uid = creator_id`.
    - `extra_data = {"creator_id": creator_id, "target_manager_id": creator_id}`.
    - Відобразити в тексті `👤 Закріплено за: <b>Адміністратор (ви)</b>`.
- **Файл:** `bot/handlers.py` (реєстрація стажера):
  - Якщо `role` має напрямок `РЦ` чи `ОФІС`:
    - `assigned_manager_id = target_manager_id or creator_id`.
    - Запобігти призначенню на `shop_mgr` або територіала.
- **Файл:** `database/managers.py` (`find_best_territorial_for_city`):
  - Якщо `direction in ("РЦ", "ОФІС")`: одразу повертати `None`.

## Крок 6: Тестування та верифікація
- Створити `tests/test_position_types.py`:
  - Перевірка валідації 4 типів посад при додаванні та оновленні.
  - Перевірка `get_position_direction` для РЦ та ОФІС.
  - Перевірка `get_users_by_position_type`.
  - Перевірка ізоляції від територіалів (`find_best_territorial_for_city`).
  - Перевірка закріплення за адміністратором для РЦ/ОФІС.
- Запуск усіх тестів (`python -m unittest discover tests`).
- Перевірка відсутності помилок лінтера.
- Закомітити зміни та запушити в репозиторій.
