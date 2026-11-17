# Дизайн-специфікація: Редагування профілів користувачів усіх ролей адміністратором

## 1. Мета та контекст
Адміністратор системи повинен мати можливість безпосередньо з Telegram-бота вносити зміни до профілів усіх категорій користувачів:
- **Стажери та Працівники** (таблиця `users` у `users.db`)
- **Керівники** (таблиця `managers` у `managers.db`, `process IN ('Керівник', 'Керівник Стажер')`)
- **Територіали** (таблиця `managers` у `managers.db`, `process = 'Територіал'`)
- **Наглядачі** (таблиця `observers` у `managers.db`)
- **Адміністратори** (таблиця `managers` з `process = 'Developer'` та `hr_users` у `users.db`)

Кожна роль отримує контекстне меню «✍️ Редагувати» (або «✍️ Змінити») з можливістю змінювати поля відповідно до специфіки ролі (ПІБ, посада, статус, місто, закріплення).

---

## 2. Деталізація функціоналу по ролях

### 2.1. Стажери та Працівники (`users.db`)
У картці `_show_user_profile_card` розширюється наявне меню `developer_user_modify_menu`:
1. **Зміна ПІБ (`dev_change_fullname`):** FSM `waiting_change_fullname`, валідація від 3 слів (Прізвище, Ім'я, По батькові), оновлення `users.full_name`.
2. **Зміна посади (`dev_change_role`):** інлайн-вибір актуальної посади з `positions.db`, оновлення `users.role`.
3. **Зміна статусу (`dev_change_status`):** перемикання між `Стажер` та `Працівник` (`users.status`).
4. **Зміна міста (`dev_change_city`):** вибір зі списку діючих міст мережі, оновлення `users.city`.
5. **Зміна керівника (`dev_change_manager`):** закріплення за новим `manager_id`.

### 2.2. Керівники магазинів (`managers.db`)
У меню `dev_mgr_edit_menu` до наявних опцій (ім'я, місто, магазини, звільнення) додається:
1. **Зміна статусу ролі (`dev_mgr_ch_status`):** перемикання між `Керівник` та `Керівник Стажер` (`managers.process`).
   - Якщо стажер: зберігається трек проходження 11 навчальних днів.
   - Якщо випущений керівник: дні вважаються пройденими.

### 2.3. Територіальні керівники (`managers.db`)
У картці `developer_territorial_view` додається кнопка `✍️ Редагувати` (`dev_terr_edit_menu:{t_uid}`):
1. **Зміна ПІБ (`dev_terr_ch_name`):** FSM `waiting_edit_territorial_name`, валідація від 3 слів, оновлення `managers.full_name`.
2. **Зміна міста (`dev_terr_ch_city`):** вибір міста мережі або «🌐 Вся мережа (Всі міста)», оновлення `managers.city`.
3. **Зміна напряму ТЗ/ВВ (`dev_terr_ch_type`):** перемикання `managers.territorial_type` між `ТЗ` та `ВВ`.

### 2.4. Наглядачі (`managers.db`)
У картці `developer_observer_view` додається кнопка `✍️ Редагувати` (`dev_obs_edit_menu:{obs_uid}`):
1. **Зміна ПІБ (`dev_obs_ch_name`):** FSM `waiting_edit_observer_name`, валідація від 3 слів, оновлення `observers.full_name`.
2. **Зміна куратора (`dev_obs_ch_resp`):** вибір відповідального керівника / адміністратора, оновлення `observers.responsible_uid`.

### 2.5. Адміністратори (`managers.db` / `hr_users`)
У картці `developer_admin_view` додається кнопка `✍️ Редагувати` (`dev_admin_edit_menu:{admin_uid}`):
1. **Зміна ПІБ (`dev_admin_ch_name`):** FSM `waiting_edit_developer_name`, валідація, оновлення `managers.full_name` та синхронізація в `hr_users`.
2. **Захист:** акаунт `MAIN_DEVELOPER_ID` захищений від випадкового видалення або зміни системних прав.

---

## 3. Сервісні функції бази даних
- `database/managers.py`:
  - `update_manager_status(uid: int, new_process: str) -> bool`
  - `update_territorial_city(uid: int, new_city: str) -> bool`
  - `update_territorial_type(uid: int, new_type: str) -> bool`
  - `update_observer_name(uid: int, new_name: str) -> bool`
  - `update_observer_responsible(uid: int, resp_uid: int) -> bool`
- `database/users.py`:
  - `update_user_status(user_id: int, new_status: str) -> bool`

---

## 4. План тестування та валідації
- Створити `tests/test_admin_edit_profiles.py`:
  - Тест 1: Зміна статусу стажера на працівника та назад через `dev_change_status`.
  - Тест 2: Зміна статусу керівника (`Керівник` ↔ `Керівник Стажер`).
  - Тест 3: Редагування територіала (зміна імені, міста та напряму ТЗ/ВВ).
  - Тест 4: Редагування наглядача (зміна імені та відповідального).
  - Тест 5: Редагування адміністратора (зміна імені).
- Запустити весь набір тестів `unittest discover tests` для підтвердження відсутності регресій.
