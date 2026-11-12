# План реалізації: Зміна порогу автоматичного видалення неактивних стажерів з 3 на 7 робочих днів

**Специфікація:** [2026-11-12-inactivity-auto-delete-threshold-design.md](file:///Users/daniildusinskij/All/Dev/Bulka_Edu/docs/superpowers/specs/2026-11-12-inactivity-auto-delete-threshold-design.md)  
**Дата:** 2026-11-12  

---

## Крок 1: Оновлення конфігурації
- Файл: `.env.example`
  - Встановити `INACTIVE_DAYS_THRESHOLD=7`.
- Файл: `bot/config.py`
  - Змінити дефолт: `INACTIVE_DAYS_THRESHOLD = int(os.getenv("INACTIVE_DAYS_THRESHOLD", "7"))`.

## Крок 2: Оновлення сервісного шару бази даних (`database/users.py`)
- Змінити дефолтне значення аргументу в `get_business_days_cutoff(now: Optional[datetime] = None, business_days: int = 7) -> datetime`.
- Змінити дефолтне значення аргументу в `get_inactive_interns_for_auto_delete(days: int = 7) -> list[dict]`.

## Крок 3: Оновлення сервісу нагадувань та фонових завдань (`bot/services/reminders.py`)
- Використовувати `INACTIVE_DAYS_THRESHOLD` з `bot.config`.
- Передавати `days=INACTIVE_DAYS_THRESHOLD` у виклик `get_inactive_interns_for_auto_delete`.
- Оновити текст сповіщення керівнику при видаленні стажера:
  динамічно підставляти `{INACTIVE_DAYS_THRESHOLD}` днів замість захардкодженного числа `3`.

## Крок 4: Оновлення та перевірка тестів
- Файл: `tests/test_business_days.py`
  - Додати тест для відсічення за 7 робочих днів.
  - Запустити тест `python3 -m unittest tests/test_business_days.py` та переконатися в проходженні всіх тестів.
