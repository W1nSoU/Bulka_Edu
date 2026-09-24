# План реалізації: Очищення та видалення опитувань

Цей план описує покроковий процес впровадження функціональності видалення окремого опитування з картки та масового очищення завершених опитувань.

---

### Крок 1. Функції бази даних (`database/surveys.py`)
- [ ] Додати функцію `delete_survey(survey_id: int, db_path: str = DB_PATH) -> bool`:
  - В одній транзакції видаляє всі записи з `survey_answers`, `survey_recipients`, `survey_questions` та `surveys`.
- [ ] Додати функцію `get_closed_surveys_count(db_path: str = DB_PATH) -> int`:
  - Повертає кількість опитувань зі статусом `closed`.
- [ ] Додати функцію `delete_closed_surveys(db_path: str = DB_PATH) -> int`:
  - Знаходить усі опитування зі статусом `closed` та каскадно видаляє їх і всі пов'язані з ними записи.
  - Повертає кількість видалених опитувань.

---

### Крок 2. Модульні тести для операцій видалення (`tests/test_survey_cleanup.py`)
- [ ] Створити тестовий набір:
  - Перевірка `delete_survey`: створення опитування з питаннями, реципієнтами та відповідями -> виклик `delete_survey` -> перевірка відсутності записів у всіх 4 таблицях.
  - Перевірка `get_closed_surveys_count`: створення закритих та активних опитувань -> правильний підрахунок.
  - Перевірка `delete_closed_surveys`: закриті опитування видаляються, активні залишаються неушкодженими.
- [ ] Запустити тест через `./venv/bin/python -m unittest tests/test_survey_cleanup.py`.

---

### Крок 3. Інтерфейс у меню розробника (`bot/menus/developer.py`)
- [ ] Оновити `_show_survey_card_view`:
  - Додати кнопку `[🗑 Видалити опитування]` (callback: `dev_survey_del_confirm:{survey_id}`) для адміністраторів (`not is_obs`).
- [ ] Реалізувати `dev_survey_del_confirm_handler`:
  - Відображає екран попередження з підтвердженням `[🔴 Так, видалити]` та `[🔙 Скасувати]`.
- [ ] Реалізувати `dev_survey_del_do_handler`:
  - Перевіряє права (`allow_observer=False`).
  - Викликає `delete_survey(survey_id)`.
  - Показує алерт `✅ Опитування успішно видалено!`.
  - Повертає до списку опитувань `dev_surveys_list_handler`.
- [ ] Оновити `dev_surveys_list_handler`:
  - Отримувати кількість закритих опитувань через `get_closed_surveys_count()`.
  - Якщо `closed_count > 0` і `not is_obs`, додавати кнопку `[🧹 Очистити завершені ({closed_count})]` (callback: `dev_surveys_clear_closed_confirm`).
- [ ] Реалізувати `dev_surveys_clear_closed_confirm_handler`:
  - Показує екран підтвердження з кнопками `[🔴 Так, очистити все]` та `[🔙 Скасувати]`.
- [ ] Реалізувати `dev_surveys_clear_closed_do_handler`:
  - Перевіряє права (`allow_observer=False`).
  - Викликає `delete_closed_surveys()`.
  - Показує алерт `✅ Очищено опитувань: {deleted_count} шт.`.
  - Оновлює список опитувань `dev_surveys_list_handler`.
- [ ] Зареєструвати всі нові callback-обробники у `register_developer_menu_handlers`.

---

### Крок 4. Запуск повного набору тестів та валідація
- [ ] Запустити `./venv/bin/python -m unittest discover tests`.
- [ ] Перевірити компіляцію через `py_compile`.

---

### Крок 5. Фіксація змін (Git Commit & Push)
- [ ] Зафіксувати зміни з повідомленням `feat(surveys): add single survey deletion and bulk closed surveys cleanup`.
- [ ] Відправити коміт у віддалений репозиторій `origin/main`.
