# План реалізації: Редагування профілів користувачів усіх ролей адміністратором

## 1. Огляд завдання
Додати та розширити інструменти редагування профілів адміністратором для всіх ролей системи:
- Стажери та працівники (`users`)
- Керівники магазинів (`managers`)
- Територіальні керівники (`managers`)
- Наглядачі (`observers`)
- Адміністратори (`managers` / `hr_users`)

---

## 2. Покроковий план виконання

### Крок 1: Функції оновлення даних у БД
1. **`database/managers.py`**:
   - `update_manager_process(uid: int, new_process: str) -> bool` — зміна процесу/статусу керівника (`Керівник` ↔ `Керівник Стажер`).
   - `update_territorial_city(uid: int, new_city: str) -> bool` — зміна закріпленого міста територіала.
   - `update_territorial_type(uid: int, new_type: str) -> bool` — зміна напряму територіала (`ТЗ` ↔ `ВВ`).
   - `update_observer_name(uid: int, new_name: str) -> bool` — зміна ПІБ наглядача.
   - `update_observer_responsible(uid: int, resp_uid: int) -> bool` — зміна куратора наглядача.
2. **`database/users.py`**:
   - `update_user_status(user_id: int, new_status: str) -> bool` — перемикання статусу користувача (`Стажер` ↔ `Працівник`).

### Крок 2: Розширення станів FSM у `bot/menus/developer.py`
У клас `DeveloperStates`:
- `waiting_edit_territorial_name`
- `waiting_edit_observer_name`
- `waiting_edit_developer_name`

### Крок 3: Меню та хендлери редагування Стажерів і Працівників (`bot/menus/developer.py`)
- У `developer_user_modify_menu`:
  - Додати кнопку `🎓 Змінити статус (Стажер/Працівник)` з колбеком `dev_change_status:{user_id}`.
- Додати хендлер `developer_toggle_user_status(callback: CallbackQuery)`:
  - Змінює статус користувача на протилежний (`Стажер` ↔ `Працівник`), показує підтвердження і повертає в меню модифікації.

### Крок 4: Меню та хендлери редагування Керівників (`bot/menus/developer.py`)
- У `dev_mgr_edit_menu`:
  - Додати кнопку перемикача `🎓 Роль: Керівник ↔ Керівник Стажер` (`dev_mgr_ch_status:{mgr_uid}`).
- Додати хендлер `dev_mgr_toggle_status_handler(callback: CallbackQuery)`:
  - Перемикає `process` між `'Керівник'` та `'Керівник Стажер'`.

### Крок 5: Меню та хендлери редагування Територіалів (`bot/menus/developer.py`)
- У картці `developer_territorial_view`:
  - Додати кнопку `✍️ Редагувати` (`dev_terr_edit_menu:{t_uid}`).
- Додати меню `developer_territorial_edit_menu(callback: CallbackQuery)`:
  - Кнопка `👤 Змінити ПІБ` (`dev_terr_ch_name:{t_uid}`).
  - Кнопка `🏙 Змінити місто` (`dev_terr_ch_city:{t_uid}`).
  - Кнопка `🏷 Змінити напрям (ТЗ ↔ ВВ)` (`dev_terr_ch_type:{t_uid}`).
  - Кнопка `⬅️ Назад до картки` (`dev_territorial_view:{t_uid}`).
- Додати обробники вводу нового імені, вибору міста та перемикання типу ТЗ/ВВ.

### Крок 6: Меню та хендлери редагування Наглядачів (`bot/menus/developer.py`)
- У картці `developer_observer_view`:
  - Додати кнопку `✍️ Редагувати` (`dev_obs_edit_menu:{obs_uid}`).
- Додати меню `developer_observer_edit_menu(callback: CallbackQuery)`:
  - Кнопка `👤 Змінити ПІБ` (`dev_obs_ch_name:{obs_uid}`).
  - Кнопка `⬅️ Назад до картки` (`dev_observer_view:{obs_uid}`).
- Додати обробник введення нового імені наглядача з валідацією.

### Крок 7: Меню та хендлери редагування Адміністраторів (`bot/menus/developer.py`)
- У картці `developer_admin_view`:
  - Додати кнопку `✍️ Редагувати` (`dev_admin_edit_menu:{admin_uid}`).
- Додати меню `developer_admin_edit_menu(callback: CallbackQuery)`:
  - Кнопка `👤 Змінити ПІБ` (`dev_admin_ch_name:{admin_uid}`).
  - Кнопка `⬅️ Назад до картки` (`dev_admin_view:{admin_uid}`).
- Додати обробник введення нового імені адміністратора з валідацією.

### Крок 8: Реєстрація всіх нових хендлерів у `register_developer_handlers(dp)`

### Крок 9: Автоматизовані тести
- Створити `tests/test_admin_edit_profiles.py`:
  - Тест зміни статусу стажера/працівника.
  - Тест зміни статусу керівника.
  - Тест зміни ПІБ, міста та типу ТЗ/ВВ територіала.
  - Тест зміни ПІБ наглядача.
  - Тест зміни ПІБ адміністратора.
- Запустити тест: `./venv/bin/python -m unittest tests/test_admin_edit_profiles.py`.
- Запустити весь тестовий набір проєкту: `./venv/bin/python -m unittest discover tests`.

### Крок 10: Фіксація та деплой
- Закомітити зміни та відправити в `origin main`.
- Надати Даніку команду для оновлення бота на сервері.
