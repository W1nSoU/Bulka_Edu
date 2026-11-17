# План реалізації: Кнопка «Перевести на працівника» у профілі стажера для керівника

## 1. Огляд
Додати можливість для керівника перевести стажера в статус працівника безпосередньо з картки стажера в боті (`manager_intern_profile_handler`) із захисним вікном підтвердження.

---

## 2. Покроковий план

### Крок 1: Оновлення картки стажера в `bot/handlers.py`
- У функції `manager_intern_profile_handler` (рядок ~2280):
  - Перевірити статус стажера: `if intern and intern.get("status") != "Працівник":`
  - Додати кнопку:
    `InlineKeyboardButton(text="🎓 Перевести на працівника", callback_data=f"mgr_promote_prompt:{intern_id}:profile")`
  - Розташувати над кнопкою «📅 Навчальні дні».

### Крок 2: Оновлення обробки повернення в `bot/menus/manager.py`
- У `manager_promote_prompt_handler`:
  - Обробка скасування: якщо `back_cb == "profile"`, кнопку скасування формувати з `callback_data=f"manager_intern_profile_{intern_id}"`.
- У `manager_promote_confirm_handler`:
  - Якщо `back_cb == "profile"`:
    - Після виконання `update_user_role`:
      - Встановити `callback.data = f"manager_intern_profile_{intern_id}"`.
      - Викликати `manager_intern_profile_handler(callback)`.

### Крок 3: Створення автоматизованих тестів
- Створити `tests/test_manager_intern_promote_from_profile.py`:
  - Тест 1: Перевірка наявності кнопки `🎓 Перевести на працівника` у картці стажера.
  - Тест 2: Перевірка відсутності кнопки у картці користувача зі статусом `Працівник`.
  - Тест 3: Перевірка вікна підтвердження з поверненням назад у профіль при скасуванні.
  - Тест 4: Перевірка успішного переведення: оновлення статусу, зарахування днів, відправка привітання та повернення в оновлений профіль.

### Крок 4: Запуск тестів та верифікація
- Запустити тест: `./venv/bin/python -m unittest tests/test_manager_intern_promote_from_profile.py`.
- Запустити повний регресійний набір: `./venv/bin/python -m unittest discover tests`.

### Крок 5: Коміт, пуш та інструкція деплою
- Закомітити зміни та відправити в `origin main`.
- Надати Даніку команду для оновлення бота на сервері.
