# Дизайн-специфікація: Реакції на новини, історія публікацій та Excel-звіти

**Дата:** 2026-09-24  
**Статус:** Затверджено  
**Гілка:** `main`

---

## 1. Огляд та мета

Функціонал розсилки новин співробітникам компанії розширюється інтерактивними анонімними реакціями для одержувачів, збереженням публікацій в історії (за останні 6 місяців) та формуванням брендованого Excel-звіту для адміністраторів (загальна статистика, список недоставлених з точними причинами, список отриманих реакцій із прив'язкою до співробітника).

---

## 2. Користувацький досвід (UX/UI)

### 2.1 Отримання новини співробітником та реакції
- При розсилці новини під текстом/фото прикріплюється інлайн-клавіатура з 4 емодзі:
  ```
  [ 👎 ]  [ 🤔 ]  [ ❤️ ]  [ 🔥 ]
  ```
  Коди реакцій:
  - `👎` — Не подобається
  - `🤔` — Замислився
  - `❤️` — Чудово / Любов
  - `🔥` — Супер / Вогонь
- **Клік на реакцію:**
  - Користувачу показується спливаюче повідомлення `callback.answer("✅ Вашу реакцію успішно надіслано!")`.
  - У повідомленні новини (текст або caption фото) в самому низу додається/оновлюється рядок:
    ```
    Ваша анонімна реакція: ❤️
    ```
  - Інлайн-клавіатура оновлюється — на обраній реакції з'являється позначка `✅`:
    ```
    [ 👎 ]  [ 🤔 ]  [ ❤️ ✅ ]  [ 🔥 ]
    ```
  - Користувач може змінити реакцію в будь-який момент — повторний клік на інший емодзі оновлює запис у БД, змінює рядок у повідомленні та переміщує позначку `✅`.

### 2.2 Завершення розсилки (сповіщення адміністратору)
- Після проходження всіх хвиль відправки адміністратору надсилається підсумкове повідомлення (без передчасного блоку реакцій, оскільки співробітники ще не встигли відреагувати):
  ```
  🏁 Розсилку новини повністю завершено!
  ───────────────────
  📬 Всього отримувачів: 224
  ✅ Успішно доставлено: 200
  ❌ Не вдалося доставити: 24
  🌊 Всього хвиль: 5
  ```

### 2.3 Меню «Історія новин»
- У головному меню новин (`dev_news_menu`) додається кнопка:
  - `[📚 Історія новин]` (callback `dev_news_history`)
- **Список новин (`dev_news_history`):**
  - Відображаються новини за останні 6 місяців (180 днів), відсортовані від найновіших до старіших.
  - Кнопки інлайну:
    `[ 📅 23.09.2026 · Оновлення стандартів випічки... ]`
  - Пагінація по 6 новин на сторінку: `[⬅️ Попередня] [ 1/3 ] [Наступна ➡️]`, кнопка `[🔙 Назад]`.

### 2.4 Картка новини (`dev_news_view:{news_id}`)
- Відображає фото (якщо було прикріплено) та текст новини.
- Блок статистики:
  ```
  📊 Статистика новини:
  📅 Дата публікації: 23.09.2026 14:30
  📬 Всього отримувачів: 224
  ✅ Успішно доставлено: 200
  ❌ Не вдалося доставити: 24
  💬 Отримано реакцій: 45 (22.5%)

  Емоції:
  👎 2  |  🤔 5  |  ❤️ 28  |  🔥 10
  ```
- Кнопки дій:
  - `[📊 Завантажити звіт (Excel)]` (callback `dev_news_report:{news_id}`)
  - `[🔙 До історії новин]` (callback `dev_news_history`)

---

## 3. Схема бази даних (`users.db`)

У `database/news.py` (і в `init_db` / `init_news_db`) додаються 3 таблиці:

### 3.1 Таблиця `news`
```sql
CREATE TABLE IF NOT EXISTS news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    photo_file_id TEXT,
    selected_roles TEXT,          -- JSON list, e.g. '["Працівник", "Стажер"]'
    selected_city TEXT,           -- 'all' або назва міста
    total_recipients INTEGER DEFAULT 0,
    sent_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    total_waves INTEGER DEFAULT 0,
    status TEXT DEFAULT 'in_progress', -- 'in_progress', 'completed'
    created_at TIMESTAMP,
    created_by INTEGER
);
```

### 3.2 Таблиця `news_deliveries`
```sql
CREATE TABLE IF NOT EXISTS news_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    news_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    status TEXT NOT NULL,         -- 'delivered' або 'failed'
    error_reason TEXT,            -- Людяне пояснення помилки
    raw_error TEXT,               -- Повний текст з логів
    delivered_at TIMESTAMP,
    message_id INTEGER,
    FOREIGN KEY(news_id) REFERENCES news(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_news_deliveries_news_id ON news_deliveries(news_id);
```

### 3.3 Таблиця `news_reactions`
```sql
CREATE TABLE IF NOT EXISTS news_reactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    news_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    reaction TEXT NOT NULL,       -- '👎', '🤔', '❤️', '🔥'
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    UNIQUE(news_id, user_id),
    FOREIGN KEY(news_id) REFERENCES news(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_news_reactions_news_id ON news_reactions(news_id);
```

---

## 4. Класифікація помилок Telegram при розсилці

У `bot/services/news_broadcaster.py`:
```python
def classify_telegram_error(error_str: str) -> str:
    err_lower = error_str.lower()
    if "blocked by the user" in err_lower:
        return "⛔️ Бот заблокований користувачем"
    if "user is deactivated" in err_lower:
        return "👤 Акаунт деактивовано / видалено"
    if "chat not found" in err_lower:
        return "❓ Чат не знайдено"
    if "retry after" in err_lower or "flood" in err_lower:
        return "⏳ Ліміт запитів Telegram (Flood limit)"
    return f"⚠️ {error_str[:80]}"
```

При відправці кожного повідомлення в `send_news_batch`:
- У разі успіху: запис у `news_deliveries(status='delivered', message_id=sent_msg.message_id)`.
- У разі винятку: запис у `news_deliveries(status='failed', error_reason=classify_telegram_error(str(e)), raw_error=str(e))`.

---

## 5. Генерація Excel-звіту (`bot/services/news_excel.py`)

Створюється за допомогою `openpyxl` з використанням фірмового дизайну Bulka (кольори заголовків, автоширина колонок, вирівнювання).

### Аркуш 1: «Загальний»
- Блок метаданих:
  - 📰 Текст новини: повний або перші 500 символів
  - 📅 Дата та час розсилки: `DD.MM.YYYY HH:MM:SS`
  - 👥 Цільові посади / ролі: `...`
  - 🏙 Цільове місто: `...`
- KPI-таблиця:
  - Всього отримувачів
  - Успішно доставлено (% відправки)
  - Не вдалося доставити (% помилок)
  - Кількість реакцій
  - % активності (реакції / доставлено)
- Таблиця розподілу емоцій:
  - 👎 Не подобається: Кількість та %
  - 🤔 Замислився: Кількість та %
  - ❤️ Чудово: Кількість та %
  - 🔥 Супер: Кількість та %

### Аркуш 2: «Не доставлено»
- Заповнюється користувачами з `news_deliveries WHERE status = 'failed'`.
- Збагачується даними з `users` (`full_name`, `role`, `city`, `shop`).
- Стовпці:
  1. `№`
  2. `ПІБ`
  3. `Посада`
  4. `Місто`
  5. `Магазин`
  6. `Telegram ID`
  7. `Причина`
  8. `Технічна помилка`

### Аркуш 3: «Реакції»
- Відображаються **виключно ті користувачі, які поставили реакцію**.
- Стовпці:
  1. `№`
  2. `ПІБ`
  3. `Магазин`
  4. `Посада`
  5. `Місто`
  6. `Реакція` (емодзі)
  7. `Час реакції`

---

## 6. Тестування та верифікація

1. Модульні тести (`tests/test_news_reactions_and_history.py`):
   - Створення новини, запис успішних та неуспішних доставок.
   - Класифікація помилок Telegram.
   - Запис та оновлення (upsert) реакцій користувачів.
   - Отримання списку новин за 6 місяців.
   - Генерація 3-сторінкового Excel-файлу та валідація аркушів і колонок.
2. Прогін повного тестового набору (`python -m unittest discover tests`).
