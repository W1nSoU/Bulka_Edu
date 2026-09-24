# План реалізації: Підрахунок неактивності стажерів за робочими днями та автовидалення

**Специфікація:** [2026-09-24-business-days-inactivity-auto-delete-design.md](file:///Users/daniildusinskij/All/Dev/Bulka_Edu/docs/superpowers/specs/2026-09-24-business-days-inactivity-auto-delete-design.md)  
**Дата:** 2026-09-24  

---

## Крок 1: Утиліта розрахунку робочих днів (`database/users.py`)
- Реалізувати функцію:
  ```python
  def get_business_days_cutoff(now: Optional[datetime] = None, business_days: int = 3) -> datetime:
  ```
- Алгоритм:
  - Визначає `now` в часовому поясі Kyiv.
  - Якщо `now` припадає на суботу (weekday=5) або неділю (weekday=6), коригує точку відліку до пʼятниці відповідного часу.
  - Покроково віднімає робочі дні, оминаючи сб і нд.
  - Повертає `datetime`.

## Крок 2: Модульні тести для математики робочих днів (`tests/test_business_days.py`)
- Тест 1: Активність у пʼятницю 15:00:
  - У понеділок 15:00 -> минув 1 робочий день (не підпадає під поріг 3 днів).
  - У вівторок 15:00 -> минуло 2 робочих дні.
  - У середу 14:59 -> ще не минуло 3 робочих дні.
  - У середу 15:01 -> минуло 3 робочих дні (підпадає).
- Тест 2: Активність у середу 15:00:
  - У четвер 15:00 -> 1 робочий день.
  - У пʼятницю 15:00 -> 2 робочих дні.
  - У суботу / неділю -> все ще 2 робочих дні.
  - У понеділок 15:01 -> 3 робочих дні (підпадає).

## Крок 3: Оновлення функцій у `database/users.py`
- `get_inactive_interns_for_auto_delete(days: int = 3) -> list[dict]`:
  - Замінити `now - timedelta(days=days)` на `get_business_days_cutoff(now, days)`.
- `get_inactive_interns_for_auto_reminder(now: datetime, inactive_days: int, cooldown_hours: int) -> list[dict]`:
  - Замінити `now - timedelta(days=inactive_days)` на `get_business_days_cutoff(now, inactive_days)`.
- `get_inactive_interns_for_manager(manager_id, days=3) -> list[dict]`:
  - Замінити `now - timedelta(days=days)` на `get_business_days_cutoff(now, days)`.

## Крок 4: Впровадження автовидалення та сповіщень керівників (`bot/services/reminders.py`)
- У функції `auto_reminder_loop`:
  - Додати перевірку на вихідні: `if now.weekday() in (5, 6):` — автовидалення пропускається (пауза у сб-нд).
  - Отримати `interns_to_delete = await get_inactive_interns_for_auto_delete(days=3)`.
  - Для кожного стажера:
    1. Отримати дані стажера (`full_name`, `username`, `role`, `city`, `shop`, `manager_id`, `last_activity`).
    2. Зафіксувати подію `await log_training_event(user_id=uid, event_type="auto_deleted_inactive", ...)`.
    3. Викликати `await delete_user(uid)`.
    4. Якщо `manager_id` існує, надіслати керівнику повідомлення через `bot.send_message`.
    5. Огорнути кожне видалення в `try/except` для захисту від збоїв одного чату.

## Крок 5: Комплексне тестування та валідація
- Запустити всі модульні тести (`unittest discover tests`).
- Перевірити відсутність регресій.
- Закомітити та запушити в `origin/main`.
