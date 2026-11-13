# Специфікація: Підтримка «Вибір кількох варіантів» в опитуваннях (`multi_choice`)

Дата: 2026-11-13  
Статус: На затвердженні

## 1. Мета та контекст

Додати до системи розсилки та проходження опитувань третій тип питання - `multi_choice` («Вибір кількох варіантів»), на додачу до наявних `choice` (один варіант) та `text` (вільна відповідь).

Затверджені продуктові вимоги:
- **Створення в адмінці (комбінований підхід):** адміністратор може вказати мультивибір маркером у текстовому шаблоні (аналогічно до `(вільна відповідь)`) **або** перемкнути режим окремим кліком на екрані перевірки перед запуском опитування.
- **Проходження респондентом:** кнопки-чекбокси (`⬜️` / `✅`) + кнопка підтвердження; мінімум 1 обраний варіант, максимум - без обмежень.
- **Аналітика в Excel:** на аркуші «Загальні результати» відсоток рахується **від кількості респондентів, які відповіли на питання** (сума `%` за варіантами може перевищувати 100%), а в підсумку вказується кількість респондентів і загальна сума позначок.

---

## 2. Архітектура та формат даних

### 2.1. База даних ([database/surveys.py](file:///Users/daniildusinskij/All/Dev/Bulka_Edu/database/surveys.py))

Міграції схеми таблиць **не потрібні**:
- `survey_questions.question_type`: допускає три значення - `'choice'`, `'multi_choice'`, `'text'`.
- `survey_answers.answer_text`: для `'multi_choice'` зберігає JSON-масив обраних варіантів у порядку їх розташування в `options`, наприклад:
  ```json
  ["а. Ранкова зміна", "в. Вечірня зміна"]
  ```
- Чинний унікальний індекс `UNIQUE(survey_id, user_id, question_idx)` зберігається 1:1 (один запис на одне питання одного користувача).
- Використання JSON замість плоского рядка гарантує точне співставлення опцій у статистиці навіть тоді, коли текст варіанта містить коми, крапки з комою або переноси рядків.

### 2.2. Парсинг JSON-відповіді (`parse_multi_choice_answer`)

У `database/surveys.py` додається допоміжна функція:
```python
def parse_multi_choice_answer(raw_text: str) -> List[str]:
```
Логіка:
1. Якщо `raw_text` після `.strip()` починається з `[`, спробувати `json.loads(raw_text)`.
2. Якщо результат є `list`, повернути дедуплікований зі збереженням порядку список непорожніх рядків:
   `list(dict.fromkeys(str(item) for item in parsed if item is not None and str(item) != ""))`.
3. Якщо `raw_text` не є JSON-списком або парсинг впав (fallback) і рядок не порожній, повернути `[raw_text]`.

---

## 3. Компоненти та зміни за файлами

### 3.1. Парсер шаблонів ([bot/services/survey_parser.py](file:///Users/daniildusinskij/All/Dev/Bulka_Edu/bot/services/survey_parser.py))

1. Розширити контракт `ParsedQuestion`:
   - `question_type: str  # 'choice' | 'multi_choice' | 'text'`
2. Додати константу маркерів мультивибору:
   - `MULTI_CHOICE_MARKERS = ["(кілька варіантів)", "(вибір кількох варіантів)", "(мультивибір)", "(множинний вибір)", "(можна кілька)"]`
   - `MAX_MULTI_CHOICE_OPTIONS = 45` (обмеження для безпечного вміщення бітової маски в 64-байтний ліміт `callback_data` Telegram).
3. Оновлення `SurveyParser.parse_template`:
   - Перевірка наявності обох типів маркерів (вільна відповідь + мультивибір) в одному заголовку питання: якщо знайдено обидва, повернути `(None, error)` із повідомленням про конфлікт типів у питанні №X.
   - Якщо знайдено один із `MULTI_CHOICE_MARKERS` (перевірка без урахування регістру): вирізати маркер із тексту заголовка (так само case-insensitive, прибравши зайві пробіли) та позначити поточне питання як `multi_choice`.
   - Для `multi_choice`, як і для `choice`, вимагати не менше 2 варіантів (`len(options) >= 2`).
   - Для `multi_choice` перевіряти `len(options) <= MAX_MULTI_CHOICE_OPTIONS` (інакше повернути `(None, error)`).

### 3.2. Адмін-конструктор ([bot/menus/developer.py](file:///Users/daniildusinskij/All/Dev/Bulka_Edu/bot/menus/developer.py))

1. **Крок 2 (`_render_survey_step2_template_text`):**
   - Додати в інструкцію шаблону опис і приклад маркера `(кілька варіантів)` поряд із `(вільна відповідь)`.
2. **Екран перевірки (`_show_survey_summary_view`):**
   - Оновити відображення типу питання в тексті:
     - `'choice'` -> `"один варіант"`
     - `'multi_choice'` -> `"кілька варіантів"`
     - `'text'` -> `"вільна відповідь"`
   - Для кожного питання з варіантами (`question_type in ('choice', 'multi_choice')`) додати inline-кнопку перемикання типу (1 кнопка в ряд, якщо таких питань <= 4, або по 2 кнопки в ряд, якщо > 4; формат тексту `☑️ П1: Кілька варіантів` або `🔘 П1: Один варіант`, `callback_data = f"dev_survey_toggle_qtype:{q_idx}"`).
   - Новий обробник `dev_survey_toggle_qtype`:
     - перевіряє наявність `questions` у FSM `state`;
     - знаходить питання за `q_idx`; якщо поточний тип `'choice'`, перевіряє `len(options) <= MAX_MULTI_CHOICE_OPTIONS` (при перевищенні показує `callback.answer(..., show_alert=True)`), після чого перемикає `'choice' <-> 'multi_choice'`;
     - зберігає оновлений `questions` у `state` та викликає `_show_survey_summary_view` (тому і передперегляд, і фінальний запуск автоматично використовують оновлені типи питань);
     - реєструється в `register_developer_menu_handlers` для `callback.data.startswith("dev_survey_toggle_qtype:")`.
3. **Передперегляд (`dev_survey_preview_look`):**
   - Якщо `question_type == 'multi_choice'`, показувати підпис `☑️ <i>(Кілька варіантів)</i>` та відображати варіанти з префіксом `⬜️` замість одного кружка.

### 3.3. Проходження опитування респондентом ([bot/menus/survey_taking.py](file:///Users/daniildusinskij/All/Dev/Bulka_Edu/bot/menus/survey_taking.py))

1. **Рендеринг питання (`_build_question_render(survey, question, current_q_idx, total_q, selected_mask: int = 0)`):**
   - Для `q_type == 'choice'`: поведінка лишається незмінною (`survey_ans:{survey_id}:{current_q_idx}:{opt_idx}`).
   - Для `q_type == 'multi_choice'`:
     - До тексту питання додається підказка:
       `\n\n<i>☑️ Можна обрати кілька варіантів, після чого натисніть «Підтвердити».</i>`
     - Для кожного `opt_idx, opt in enumerate(options)`:
       - `is_selected = bool((selected_mask >> opt_idx) & 1)`
       - `new_mask = selected_mask ^ (1 << opt_idx)`
       - Кнопка: `InlineKeyboardButton(text=f"{'✅' if is_selected else '⬜️'} {opt}", callback_data=f"survey_mt:{survey_id}:{current_q_idx}:{new_mask}")`
     - Внизу клавіатури додається кнопка підтвердження:
       - Підрахунок обраних у масці (обмежений `len(options)`): `selected_count`
       - Текст кнопки: `f"✅ Підтвердити ({selected_count})"` якщо `selected_count > 0`, інакше `"✅ Підтвердити вибір"`
       - `callback_data = f"survey_mc:{survey_id}:{current_q_idx}:{selected_mask}"`
2. **Обробник перемикання чекбокса (`survey_multi_toggle_callback`, prefix `survey_mt:`):**
   - Парсить `survey_id`, `q_idx`, `new_mask`.
   - Завантажує `survey` та `questions`; перевіряє, що `survey` існує і не закрите (`status != 'closed'`), питання існує, має тип `'multi_choice'`, а `0 <= new_mask < (1 << len(options))`.
   - Оновлює клавіатуру через `_build_question_render(..., selected_mask=new_mask)` і `callback.message.edit_reply_markup(...)`, безпечно ігноруючи помилку Telegram `"message is not modified"`.
3. **Обробник підтвердження (`survey_multi_confirm_callback`, prefix `survey_mc:`):**
   - Парсить `survey_id`, `q_idx`, `selected_mask`.
   - Перевіряє, що `survey` існує і не закрите (`status != 'closed'`), а питання має тип `'multi_choice'`.
   - Перевіряє `existing_answers = await get_survey_answers_for_user(survey_id, user_id)`: якщо відповідь на `q_idx` вже існує (повторний клік по старій кнопці), не перезаписує її і не пропускає питання двічі, а спрямовує до першого невідповідженого питання або екрану завершення.
   - Якщо `selected_mask == 0` або список обраних варіантів за маскою порожній: відповідає `await callback.answer("⚠️ Оберіть хоча б один варіант!", show_alert=True)` без переходу далі.
   - Формує `selected_options = [opt for i, opt in enumerate(options) if (selected_mask >> i) & 1]`.
   - Серіалізує `json.dumps(selected_options, ensure_ascii=False)` і викликає `save_survey_answer(survey_id, user_id, q_idx, answer_payload)`.
   - Виконує перехід до наступного питання або завершення опитування через спільний helper `_advance_survey_progress(...)` (об'єднуючи існуючий перехід із `survey_choice_answer_callback` та `survey_free_text_answer_message`).
4. **Реєстрація обробників:**
   - Додати `survey_multi_toggle_callback` (`survey_mt:`) та `survey_multi_confirm_callback` (`survey_mc:`) у `register_survey_taking_handlers`.

### 3.4. Статистика та Excel-експорт ([database/surveys.py](file:///Users/daniildusinskij/All/Dev/Bulka_Edu/database/surveys.py), [bot/services/survey_excel.py](file:///Users/daniildusinskij/All/Dev/Bulka_Edu/bot/services/survey_excel.py))

1. **`get_survey_question_stats` (`database/surveys.py`):**
   - Завантажувати `question_type, options_json` із `survey_questions` та сирі рядки `answer_text` із `survey_answers`.
   - Для `'multi_choice'` розбирати кожен рядок через `parse_multi_choice_answer`, рахувати по кожній опції (`+1` за респондента, який її обрав) і додавати опції з `options_json` із нулями, якщо їх ніхто не обрав.
   - Для `'choice'` і `'text'` зберегти поточну поведінку.
2. **`get_survey_detailed_results` (`database/surveys.py`):**
   - Для кожного питання в `q_stats[q_idx]`:
     - Для `'choice'`: як і раніше, `opt_counts[ans] += 1`, `total_selections = total_q_ans`.
     - Для `'multi_choice'`:
       - `total_q_ans = len(q_answers)` (кількість респондентів, які відповіли на питання);
       - для кожного запису викликається `parse_multi_choice_answer(raw_ans)`, кожній обраній опції додається `+1` до `opt_counts`, а `total_selections += len(selected)`;
       - `opt_percentages[opt] = round((cnt / total_q_ans * 100.0), 1) if total_q_ans > 0 else 0.0`.
     - У словнику `q_stats[q_idx]` повертати також `"total_selections": total_selections`.
   - Для словника `shops` (деталізація за співробітниками):
     - Якщо `q_type == 'multi_choice'`, форматувати `shops_dict[shop_name][uid]["answers"][q_idx] = "; ".join(parse_multi_choice_answer(a["answer_text"]))`.
3. **`generate_survey_results_xlsx` (`bot/services/survey_excel.py`):**
   - **Аркуш 1 («Загальні результати»):**
     - Бейдж у заголовку питання:
       - `'choice'` -> `" [Вибір варіанту]"`
       - `'multi_choice'` -> `" [Вибір кількох варіантів]"`
       - `'text'` -> `" [Вільна відповідь]"`
     - Для `q_type in ('choice', 'multi_choice')` будувати таблицю розподілу варіантів:
       - для `'multi_choice'` заголовок 3-ї колонки: `"% від респондентів"` (для `'choice'` залишається `"% від відповідей"`);
       - у підсумковому рядку для `'multi_choice'`:
         - колонка 1: `"Всього відповіли респондентів"`
         - колонка 2: `total_q_ans`
         - колонка 3: `f"Всього позначок: {total_selections}"`
         (для `'choice'` лишається `"Всього відповіли на питання"` | `total_q_ans` | `"100%"`).
   - **Аркуші 2..N (вкладки по магазинах):**
     - Якщо значення клітинки містить `"; "` або довше 35 символів, застосовувати `align_wrap` (`wrap_text=True`), а розрахунок автоширини колонки обмежити розумним максимумом (`min(max(max_len + 4, 12), 55)`).

---

## 4. Обробка помилок та граничні випадки

- **Невалідна або застаріла кнопка чекбокса / підтвердження:** якщо опитування вже закрите (`status == 'closed'`) або питання вже має збережену відповідь користувача, обробник не модифікує `survey_answers` і показує коректний стан / алерт.
- **Порожній вибір (`mask == 0`):** чіткий алерт `⚠️ Оберіть хоча б один варіант!`.
- **Занадто багато варіантів (> 45):** блокується як на етапі парсингу шаблону, так і при спробі перемкнути питання з `choice` на `multi_choice` кнопкою в адмінці.
- **Зворотна сумісність:** наявні опитування, збережені як `'choice'` або `'text'`, не змінюються на рівні БД, `callback_data` (`survey_ans:...`), логіки нагадувань та Excel-вивантаження.

---

## 5. План тестування

Додати модульно-інтеграційний набір тестів `tests/test_survey_multi_choice.py` із покриттям:
1. **Парсер (`SurveyParser.parse_template`):**
   - усі підтримувані `MULTI_CHOICE_MARKERS` у різному регістрі та очищення заголовка від маркера;
   - змішане опитування (`choice` + `multi_choice` + `text`);
   - помилка при < 2 варіантах, при > 45 варіантах, при конфлікті з маркером вільної відповіді.
2. **Взаємодія в Telegram (`survey_taking.py` + `developer.py`):**
   - перемикання типу питання в адмінці (`dev_survey_toggle_qtype`);
   - побудова чекбоксів за бітовою маскою, перемикання бітів (`survey_mt`), блокування підтвердження при `mask == 0` (`survey_mc`), збереження JSON-масиву при `mask > 0` та захист від повторного натискання «Підтвердити».
3. **База даних та Excel (`database/surveys.py` + `survey_excel.py`):**
   - `parse_multi_choice_answer` (валідний JSON, варіанти з комами/крапками з комою, не-JSON fallback);
   - `get_survey_question_stats` та `get_survey_detailed_results` (перевірка `%` від респондентів із сумою > 100%, `total_answers`, `total_selections`, форматування `"; "` у `shops`);
   - генерація реального `.xlsx` у пам'яті та перевірка через `openpyxl` комірок Аркуша 1 і вкладки магазину.
4. Повний регресійний прогін `python3 -m unittest discover tests`.
