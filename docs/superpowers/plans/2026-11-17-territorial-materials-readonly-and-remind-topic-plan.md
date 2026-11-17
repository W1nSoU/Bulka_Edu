# План реалізації: Доступ Територіального керівника до «Нагадати тему» та перегляд навчання (Read-Only)

## 1. Огляд завдання
Надати активному Територіальному керівникові (`process = 'Територіал'` у `managers.db`):
1. Повний доступ до функції «🧠 Нагадати тему» (`remind_topic_global` та `remind_topic_for_intern`).
2. Доступ до перегляду всіх навчальних матеріалів («Матеріали», «Відео», «Тести», «Фото») до всіх посад у режимі **тільки перегляд (Read-Only)** без можливості редагування, додавання чи видалення.

---

## 2. Покроковий план виконання

### Крок 1: Оновлення перевірки прав `_ensure_developer` (`bot/menus/developer.py`)
- Додати аргумент `allow_territorial: bool = False` у `_ensure_developer`.
- Якщо `allow_territorial and not is_dev`:
  - Перевірити `await is_territorial_user(user_id)`. Якщо користувач територіал — повертати `True`.

### Крок 2: Оновлення хендлерів «Нагадати тему» (`bot/handlers.py`)
- У `remind_topic_global_callback`:
  - Додати `is_terr = await is_territorial_user(user_id)`.
  - Змінити перевірку: `if not (is_hr or is_dev or is_obs or is_mgr or is_terr): ...`
  - Виставити кнопку повернення «⬅️ Назад» для територіала на `dev_main_study`.
- У `remind_topic_for_intern_callback`:
  - Додати перевірку `await is_territorial_user(caller_id)`, щоб територіал міг викликати нагадування з картки підпорядкованого стажера.

### Крок 3: Надання доступу до розділів навчання в режимі Read-Only (`bot/menus/developer.py`)
- Оновити перевірку прав у хендлерах вибору посади та перегляду днів:
  - `developer_materials_menu` (`allow_territorial=True`)
  - `developer_materials_select_day` (`allow_territorial=True`)
  - `developer_materials_select_type` (`allow_territorial=True`)
  - `developer_videos_menu` та перегляд відео (`allow_territorial=True`)
  - `developer_tests_menu` та перегляд питань тесту (`allow_territorial=True`)
  - `developer_photos_menu` та перегляд фото (`allow_territorial=True`)
- У генераторах інлайн-клавіатур перегляду:
  - Перевіряти `is_readonly = await is_observer_user(user_id) or await is_territorial_user(user_id)`.
  - Якщо `is_readonly == True`:
    - Приховувати всі кнопки змін (`✏️ Редагувати`, `🗑 Видалити`, `➕ Додати`, заміна файлів).
    - Залишати тільки навігацію сторінками/блоками та кнопку «⬅️ Назад».
- Хендлери мутацій залишаються під `_ensure_developer(callback, allow_territorial=False)`.

### Крок 4: Автоматизовані тести
- Створити `tests/test_territorial_materials_and_remind.py`:
  - Тест 1: Перевірка, що територіал відкриває `remind_topic_global` і бачить список посад.
  - Тест 2: Перевірка переходу по `dev_materials_menu` і днях без помилки 403.
  - Тест 3: Перевірка відсутності кнопок редагування в клавіатурі перегляду для територіала.
  - Тест 4: Перевірка відхилення спроби викликати збереження матеріалу територіалом.
- Запустити тест через `./venv/bin/pytest tests/test_territorial_materials_and_remind.py -v`.
- Запустити повний тестовий набір для перевірки відсутності регресій: `./venv/bin/pytest tests/ -v`.

### Крок 5: Фіксація змін та інструкція деплою
- Закомітити зміни в git.
- Надати Даніку команду для оновлення бота на бойовому сервері.
