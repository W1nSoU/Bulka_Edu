# План реалізації: Живий лічильник реакцій на новини в реальному часі

**Специфікація:** [2026-11-11-news-live-reactions-counter-design.md](file:///Users/daniildusinskij/All/Dev/Bulka_Edu/docs/superpowers/specs/2026-11-11-news-live-reactions-counter-design.md)  
**Дата:** 2026-11-11  

---

## Крок 1: База даних та форматування (`database/news.py`)
- [ ] Оновити список реакцій: `NEWS_REACTIONS = ["🔥", "😁", "❤️", "🤔"]`.
- [ ] В `init_news_db` додати міграцію старих реакцій:
  `UPDATE news_reactions SET reaction = '😁' WHERE reaction = '👎';`
- [ ] Реалізувати утиліту `format_news_reactions_line(breakdown: dict[str, int]) -> str`:
  Повертає рядок формату: `{fire} 🔥 | {laugh} 😁 | {heart} ❤️ | {think} 🤔`.
- [ ] Реалізувати утиліту `update_text_with_reactions_line(raw_text: str, new_line: str) -> str`:
  Шукає рядок лічильників за регексом або додає в кінець тексту.
- [ ] Додати функцію `get_delivered_news_messages(news_id: int, exclude_user_id: int | None = None) -> list[dict]`:
  Повертає список `{user_id, message_id}` для всіх успішно надісланих новин.

---

## Крок 2: Фонова дебаунс-черга та розсилка (`bot/services/news_broadcaster.py`)
- [ ] Створити клас `NewsReactionSyncQueue`:
  - `schedule_sync(bot, news_id: int, trigger_user_id: int | None = None)`
  - Дебаунс 15 секунд (максимум 30 секунд при частих кліках).
  - Асинхронний воркер оновлює повідомлення у фоні з мікропаузами (0.05-0.08с) та обробкою винятків (Flood limits, видалені повідомлення).
- [ ] Оновити `get_news_reaction_keyboard`:
  - Використовувати оновлений список `NEWS_REACTIONS` (`🔥`, `😁`, `❤️`, `🤔`).
  - Позначка `✅` для поточної реакції користувача.
- [ ] Оновити `send_news_batch`:
  - Додавати початковий рядок лічильників `0 🔥 | 0 😁 | 0 ❤️ | 0 🤔` до тексту/підпису новини перед відправкою.

---

## Крок 3: Обробник реакцій користувача (`bot/handlers.py`)
- [ ] Оновити `news_reaction_handler`:
  - Валідація за новим `NEWS_REACTIONS`.
  - Збереження реакції в БД через `upsert_news_reaction`.
  - Оновлення лічильника в поточному повідомленні користувача через `update_text_with_reactions_line`.
  - Оновлення клавіатури з позначкою `✅`.
  - Виклик `news_reaction_sync_queue.schedule_sync(callback.bot, news_id, trigger_user_id=user_id)`.
  - Швидкий спливаючий `callback.answer("✅ Реакцію враховано!")`.

---

## Крок 4: Оновлення звітів та меню (`bot/services/news_excel.py`, `bot/menus/developer.py`)
- [ ] Перевірити Excel-генератор реакцій (`news_excel.py`), щоб стовпчик дизлайку замінився на `😁`.
- [ ] Перевірити перегляд детальних реакцій у меню адміністратора.

---

## Крок 5: Тестування та перевірка (`tests/test_news_live_reactions.py`)
- [ ] Написати юніт-тести для:
  - `format_news_reactions_line` та `update_text_with_reactions_line`.
  - Міграції реакцій `👎` -> `😁`.
  - `NewsReactionSyncQueue` (дебаунс і синхронізація).
- [ ] Запустити повний тестовий набір (`./venv/bin/python3 -m unittest discover tests`).
- [ ] Зафіксувати зміни та передати для деплою.
