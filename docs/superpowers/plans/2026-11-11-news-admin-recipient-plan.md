# План реалізації: Додавання категорії «Адміністратор» до аудиторії новин

**Специфікація:** [2026-11-11-news-admin-recipient-design.md](file:///Users/daniildusinskij/All/Dev/Bulka_Edu/docs/superpowers/specs/2026-11-11-news-admin-recipient-design.md)  
**Дата:** 2026-11-11  

---

## Крок 1: Оновлення вибірки отримувачів у базі даних (`database/surveys.py`)
- [ ] У функції `get_matching_survey_recipients` додати блок `if "Адміністратор" in target_roles:`:
  - Вибірка з `users.db`:
    ```sql
    SELECT user_id FROM users WHERE role IN ('Адміністратор', 'Developer', 'Dev')
    ```
  - Вибірка з `managers.db`:
    ```sql
    SELECT uid FROM managers WHERE process IN ('Developer', 'Адміністратор') AND (status = 'active' OR status IS NULL)
    ```
  - Додавання `MAIN_DEVELOPER_ID` з конфігурації (якщо > 0).
  - Адміністратори отримують новину незалежно від вибору міста (глобальний пріоритет).
  - Додати всі знайдені `user_id` до `matched_uids`.

---

## Крок 2: Оновлення інтерфейсу вибору ролей у боті (`bot/menus/developer.py`)
- [ ] У функції `_show_news_roles_selection`:
  - Додати `"Адміністратор"` до списку `all_roles = ["Працівник", "Стажер", "Керівник", "Територіал", "Наглядач", "Адміністратор"]`.
- [ ] Перевірити роботу обробника `dev_news_toggle_role_handler`:
  - Забезпечити безперешкодне перемикання прапорця ролі `"Адміністратор"`.
  - Валідація: не дозволяти зняти всі прапорці.

---

## Крок 3: Написання автоматичних тестів (`tests/test_news_admin_recipients.py`)
- [ ] Створити тестовий файл `tests/test_news_admin_recipients.py` з перевірками:
  - 1. Вибірка адміністраторів з `users.db` за ролями `'Адміністратор'`, `'Developer'`, `'Dev'`.
  - 2. Вибірка з `managers.db` за процесами `'Developer'`, `'Адміністратор'`.
  - 3. Включення `MAIN_DEVELOPER_ID`.
  - 4. Робота міського фільтра (адміністратори включаються навіть при `target_city="Львів"`).
  - 5. Виключення адміністраторів зі статусом `'fired'` у `get_matching_news_recipients`.
  - 6. Перемикання ролі в `_show_news_roles_selection` / `dev_news_toggle_role_handler`.
- [ ] Запустити повний тестовий набір (`python3 -m unittest discover tests`).

---

## Крок 4: Фіксація змін та підготовка до деплою
- [ ] Перевірити `git status` та `git diff`.
- [ ] Зробити git commit та push на GitHub (`main`).
