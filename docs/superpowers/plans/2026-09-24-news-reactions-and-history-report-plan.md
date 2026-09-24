# План реалізації: Реакції на новини, історія публікацій та Excel-звіти

**Специфікація:** [2026-09-24-news-reactions-and-history-report-design.md](file:///Users/daniildusinskij/All/Dev/Bulka_Edu/docs/superpowers/specs/2026-09-24-news-reactions-and-history-report-design.md)  
**Дата:** 2026-09-24  

---

## Крок 1: База даних новин, доставок та реакцій
- **Файл:** `database/news.py`
  - Константи реакцій: `NEWS_REACTIONS = ["👎", "🤔", "❤️", "🔥"]`.
  - В `init_news_db`:
    - Створити таблицю `news` (id, text, photo_file_id, selected_roles, selected_city, total_recipients, sent_count, failed_count, total_waves, status, created_at, created_by).
    - Створити таблицю `news_deliveries` (id, news_id, user_id, status, error_reason, raw_error, delivered_at, message_id). Індекс за `news_id`.
    - Створити таблицю `news_reactions` (id, news_id, user_id, reaction, created_at, updated_at). `UNIQUE(news_id, user_id)`. Індекс за `news_id`.
  - Реалізувати сервісні функції:
    - `create_news(text, photo_file_id, selected_roles, selected_city, total_recipients, total_waves, created_by) -> int`
    - `update_news_stats(news_id, sent_count, failed_count, status)`
    - `record_delivery(news_id, user_id, status, error_reason=None, raw_error=None, message_id=None)`
    - `record_deliveries_batch(deliveries: list[dict])`
    - `get_news_by_id(news_id: int) -> dict | None`
    - `get_news_history_last_6_months() -> list[dict]`
    - `upsert_news_reaction(news_id: int, user_id: int, reaction: str) -> bool`
    - `get_user_news_reaction(news_id: int, user_id: int) -> str | None`
    - `get_news_reactions_summary(news_id: int) -> dict` (загальна кількість та розбивка по емодзі)
    - `get_news_failed_deliveries_detailed(news_id: int) -> list[dict]` (із збагаченням ПІБ, посади, магазину)
    - `get_news_reactions_detailed(news_id: int) -> list[dict]` (із збагаченням ПІБ, посади, магазину)
- **Файл:** `database/schema.py`
  - Викликати `init_news_db` під час `init_db`.

## Крок 2: Розсилка з реакціями та трекінгом доставки
- **Файл:** `bot/services/news_broadcaster.py`
  - Реалізувати функцію класифікації помилок:
    ```python
    def classify_telegram_error(error_str: str) -> str:
        # 'bot was blocked by the user' -> '⛔️ Бот заблокований користувачем'
        # 'user is deactivated' -> '👤 Акаунт деактивовано / видалено'
        # 'chat not found' -> '❓ Чат не знайдено'
        # 'retry after' / 'flood' -> '⏳ Ліміт запитів Telegram (Flood limit)'
        # fallback -> '⚠️ {error_str}'
    ```
  - Функція побудови клавіатури реакцій:
    `get_news_reaction_keyboard(news_id: int, current_reaction: str | None = None) -> InlineKeyboardMarkup`
  - Оновити `send_news_batch`:
    - Прикріплювати інлайн-клавіатуру з 4 реакціями до кожного повідомлення/фото.
    - Фіксувати кожну успішну доставку (`status='delivered'`, `message_id`).
    - Фіксувати невдачі доставки (`status='failed'`, `error_reason`, `raw_error`).
    - Пакетно зберігати результати в `news_deliveries` через `record_deliveries_batch`.
  - Оновити `dispatch_news_waves`:
    - Оновлювати `news.sent_count`, `news.failed_count`, `news.status` після завершення всіх хвиль.
    - Зберегти підсумкове повідомлення адміністратору у незмінному форматі.
- **Файл:** `bot/menus/developer.py` (`dev_news_launch_handler`):
  - При запуску розсилки створювати запис у `news` (`create_news`), отримувати `news_id` та передавати його в `start_news_wave_broadcast`.

## Крок 3: Обробка реакцій користувачів
- **Файл:** `bot/handlers.py`
  - Додати callback-хендлер `news_react:{news_id}:{emoji}`:
    - Зберегти реакцію в БД через `upsert_news_reaction(news_id, user_id, emoji)`.
    - Показати `callback.answer("✅ Вашу реакцію успішно надіслано!")`.
    - Оновити текст повідомлення:
      - Знайти або додати рядок: `\n\nВаша анонімна реакція: {emoji}`.
      - Відредагувати повідомлення через `callback.message.edit_text` або `callback.message.edit_caption`.
    - Оновити клавіатуру з позначкою `✅` біля обраного емодзі через `get_news_reaction_keyboard(news_id, current_reaction=emoji)`.
  - Зареєструвати хендлер у роутері бота.

## Крок 4: Сервіс генерації Excel-звіту
- **Файл:** `bot/services/news_excel.py`
  - Реалізувати функцію:
    `async def generate_news_report_xlsx(news_id: int) -> io.BytesIO`
  - Стилі Bulka (фірмовий колір заголовків, межі, автоширина колонок).
  - **Аркуш 1: «Загальний»:**
    - Метадані розсилки (дата, цільова аудиторія, текст новини).
    - KPI блок (всього отримувачів, доставлено, не доставлено, відсоток реакцій).
    - Таблиця розподілу кожної з 4 емоцій (кількість, відсоток).
  - **Аркуш 2: «Не доставлено»:**
    - Колонки: `№`, `ПІБ`, `Посада`, `Місто`, `Магазин`, `Telegram ID`, `Причина`, `Технічний опис`.
  - **Аркуш 3: «Реакції»:**
    - Лише співробітники, які відреагували.
    - Колонки: `№`, `ПІБ`, `Магазин`, `Посада`, `Місто`, `Реакція`, `Час реакції`.

## Крок 5: Меню «Історія новин» та картка новини
- **Файл:** `bot/menus/developer.py`
  - В `dev_news_menu_handler` додати кнопку `[📚 Історія новин]` (callback `dev_news_history`).
  - Додати функцію `dev_news_history_handler(callback: CallbackQuery)`:
    - Отримує новини за останні 6 місяців через `get_news_history_last_6_months()`.
    - Виводить список кнопок `📅 DD.MM.YYYY · {текст...}`.
    - Підтримка пагінації (`dev_news_hist_page:{page}`) та кнопка `[🔙 Назад]`.
  - Додати функцію `dev_news_view_handler(callback: CallbackQuery)` (`dev_news_view:{news_id}`):
    - Виводить фото (якщо було) та повний текст новини.
    - Виводить блок аналітики: дата, всього отримувачів, доставлено, не доставлено, реакцій, розподіл 4 емодзі.
    - Кнопки: `[📊 Завантажити звіт (Excel)]` (callback `dev_news_report:{news_id}`), `[🔙 До історії новин]`.
  - Додати функцію `dev_news_report_handler(callback: CallbackQuery)`:
    - Генерує `.xlsx` через `generate_news_report_xlsx(news_id)`.
    - Надсилає файл документ у чат адміна (`BufferedInputFile`).
  - Зареєструвати всі callback-хендлери в `register_developer_menu_handlers`.

## Крок 6: Тестування та верифікація
- Створити `tests/test_news_reactions_and_history.py`:
  - Перевірка створення новини та запису доставок.
  - Перевірка функції `classify_telegram_error`.
  - Перевірка `upsert_news_reaction` та перемикання реакції.
  - Перевірка фільтру новин за останні 6 місяців.
  - Перевірка створення Excel-файлу та структури його трьох аркушів.
- Запуск повного набору тестів (`./venv/bin/python -m unittest discover tests`).
- Перевірка відсутності помилок синтаксису / лінтера.
- Закомітити та запушити зміни.
