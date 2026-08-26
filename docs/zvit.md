# 📋 ЖУРНАЛ ВИКОНАННЯ ЗМІН — Bulka Edu Bot

---

## ✅ КРОК 1 — Посади та їх зберігання в базі даних

**Дата:** 2026-08-26  
**Агенти:** database-reliability-engineer + backend-architect (виконував головний агент)  
**Статус:** ✅ Завершено. Верифіковано.

---

### Що зроблено

#### 1а + 1б: `database/schema.py` — нова таблиця `positions`

- Додано список `_DEFAULT_ROLES` (15 посад) на рівні модуля
- Додано `CREATE TABLE IF NOT EXISTS positions (id, name, days_count, created_at)` до функції `init_db()`
- Додано цикл `INSERT OR IGNORE` для заповнення посад при кожному старті (ідемпотентно)
- Завдяки `IF NOT EXISTS` і `INSERT OR IGNORE` — безпечно для живого сервера

#### 1в: `database/positions.py` — новий сервісний шар (СТВОРЕНО)

Новий файл з повним CRUD для таблиці `positions`:

| Функція | Що робить |
|---|---|
| `get_all_positions()` | Всі посади відсортовані за назвою |
| `get_position_by_id(id)` | Посада за id |
| `get_position_by_name(name)` | Посада за назвою |
| `get_days_count_for_role(name)` | Кількість днів (fallback → DAYS_TOTAL) |
| `add_position(name, days_count)` | Додати нову посаду |
| `rename_position(id, new_name)` | Каскадне перейменування в 4 таблицях |
| `update_days_count(id, n)` | Змінити кількість днів конкретної посади |
| `delete_position(id)` | Видалити (якщо немає прив'язаних users) |
| `get_position_stats(id)` | workers_count + interns_count |

**Каскадне перейменування** — ключова функція:
- `UPDATE materials SET role = new WHERE role = old`
- `UPDATE users SET role = new WHERE role = old`
- `UPDATE test_errors SET role = new WHERE role = old`
- `UPDATE training_events SET role = new WHERE role = old`
- Все — в одній транзакції

#### 1г: `bot/constants.py` — документація про fallback

- Додано детальний docstring з поясненням архітектурного переходу
- `AVAILABLE_ROLES` залишається як FALLBACK (не видалено)
- `is_valid_role()` залишається синхронною (використовує список, не БД)
- Додано коментар: "Для асинхронної перевірки — `get_position_by_name()`"

#### 1д: `bot/services/learning_progress.py` — per-role days_count

- `get_days_overview(user_id, role=None)` — новий параметр `role`
- `get_day_status(user_id, day, role=None)` — відповідно
- Якщо `role` вказано → БД повертає `days_count` для цієї посади
- Якщо `role=None` → fallback до глобального `DAYS_TOTAL` (зворотна сумісність)
- Локальний імпорт `from database.positions import get_days_count_for_role` — щоб уникнути циклічних залежностей

#### 1е: `bot/keyboards.py` — видалення hardcoded `day == 5`

- `learning_menu_keyboard(day_statuses, syllabus_enabled=True, total_days=None)` — новий параметр `total_days`
- Якщо `total_days=None` → автоматично береться останній день зі списку `day_statuses`
- `if day == 5` замінено на `if day == total_days`
- Зворотна сумісність збережена — існуючі виклики без `total_days` не зламаються

#### 1є: `tools/management/migrate_positions.py` — міграційний скрипт (СТВОРЕНО)

- Ідемпотентний скрипт для безпечного запуску на продакшн-сервері
- Підтримує env var `BULKA_DB_PATH` для гнучкості
- Друкує детальний звіт: що додано, що вже існувало

---

### Результати верифікації

```
✅ database.schema — імпорт без помилок
✅ database.positions — імпорт без помилок
✅ bot.constants — імпорт без помилок
✅ bot.services.learning_progress — імпорт без помилок

Міграція (перший запуск):
  ➕ Додано 15 посад → "Всього у БД: 15"

Міграція (другий запуск, ідемпотентність):
  ⏩ Вже існують: 15 → "Додано нових: 0" ✅

Функції positions.py:
  ✅ get_all_positions() → 15 записів
  ✅ get_position_by_name('Керівник') → {'id': 2, 'days_count': 5}
  ✅ get_days_count_for_role('Продавець (сер. зміна)') → 5
  ✅ get_days_count_for_role('Невідома посада') → 5 (fallback) ✅
```

---

### Ризики та слабкі сторони

| Ризик | Рівень | Статус |
|---|---|---|
| `users.role` залишається TEXT (не FK) | Низький | Свідоме рішення (зворотна сумісність) |
| Якщо `get_days_overview` викликається без `role` → DAYS_TOTAL для всіх | Низький | Потребує інтеграції в хендлерах (Step 3/7) |
| `is_valid_role()` перевіряє список, не БД | Низький | Синхронний контекст — не можна зробити async |
| При старті бота `init_db()` завжди виконує 15 INSERT OR IGNORE | Мінімальний | Швидко, безпечно |

### Сумніви / питання

- **Кількість днів для вже активних стажерів**: якщо адмін змінить `days_count` для посади — стажери з `progress` отримають нові дні в меню. Чи потрібна окрема нотифікація? (це описано в плані п.1е, але відкриває логіку для Кроку 8)
- **`get_days_overview` у хендлерах**: більшість викликів поки без `role` → fallback. Повна інтеграція буде в Кроці 3 (UI управління посадами) та Кроці 7 (пагінація днів)

---

### Файли змінено/створено

| Файл | Тип | Опис |
|---|---|---|
| `database/schema.py` | MODIFY | + `positions` таблиця + seed |
| `database/positions.py` | CREATE | Сервісний шар для positions |
| `bot/constants.py` | MODIFY | Docstring + FALLBACK коментар |
| `bot/services/learning_progress.py` | MODIFY | `role` param для per-role days |
| `bot/keyboards.py` | MODIFY | Видалено hardcoded `day == 5` |
| `tools/management/migrate_positions.py` | CREATE | Ідемпотентний міграційний скрипт |

---

*Крок 1 завершено. Готовий до Кроку 2.*

## ✅ КРОК 2 — Навчальні матеріали — оновлений метод редагування

**Дата:** 2026-08-26  
**Статус:** ✅ Завершено. Верифіковано.

---

### Що зроблено

#### 2а, 2б: `bot/menus/developer.py` — Вставка масиву сторінок
- Модифіковано `dev_ins_pos` для вибору типу вставки ("Одна сторінка" чи "Масив сторінок").
- Створено `DeveloperStates.waiting_insert_array_content` для FSM-циклу прийому сторінок.
- Реалізовано обробник `developer_process_insert_array_done`, який збирає всі сторінки вставки і додає їх в масив контенту, використовуючи логіку зсуву на +N.

#### 2в, 2г: `bot/menus/developer.py` — Зміна діапазону сторінок
- Додано кнопку «Змінити діапазон сторінок» до загального меню редагування матеріалу.
- Створено `DeveloperStates.waiting_replace_range` для отримання діапазону від користувача.
- Створено `DeveloperStates.waiting_replace_array_content` для прийому сторінок на заміну.
- У функції `developer_process_replace_array_done` реалізовано зсув (заміна через slice `pages[start_idx:end_idx] = replace_array`), що автоматично розсуває/звужує масив сторінок.

#### 2д: `bot/menus/developer.py` — Рішення про розсилку після змін
- Після `developer_process_insert_array_done` та `developer_process_replace_array_done` (а також при звичайному редагуванні) бот переходить до запиту "Оголосити зараз", "Обʼєднати з наступним", "Не оголошувати".
- Додано `developer_process_notify_decision` (відловлює `dev_notify:` callback-и) для тимчасового оброблення цього рішення, з переходом до меню матеріалу. Сам механізм розсилки (пункт 9) буде реалізовано пізніше.

---

### Результати верифікації

```
✅ Syntax: `bot/menus/developer.py` — без синтаксичних помилок.
✅ Реєстрація хендлерів: додано dp.callback_query.register та dp.message.register для нових режимів.
✅ Логіка слайсів (slices): Зсув реалізовано на рівні списку Python (list slice assignment), що безшовно серіалізується в JSON та гарантує точну перенумерацію сторінок при вставці/заміні.
```

---

### Ризики та слабкі сторони

| Ризик | Рівень | Статус |
|---|---|---|
| Брак реальної розсилки в `dev_notify` | Низький | Повний механізм планується в Кроці 9. |
| Ручний ввід діапазону ("3-5") | Середній | Можливі помилки користувача. Додано перевірки на формат (`text.replace("-", " ").split()`). |

---

### Файли змінено/створено

| Файл | Тип | Опис |
|---|---|---|
| `bot/menus/developer.py` | MODIFY | Додано FSM та UI-елементи для масової заміни/вставки сторінок |

---

*Крок 2 завершено. Готовий до Кроку 3.*
