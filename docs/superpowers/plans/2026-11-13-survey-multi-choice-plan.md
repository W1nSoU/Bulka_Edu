# План реалізації: Підтримка «Вибір кількох варіантів» в опитуваннях (`multi_choice`)

Специфікація: [2026-11-13-survey-multi-choice-design.md](file:///Users/daniildusinskij/All/Dev/Bulka_Edu/docs/superpowers/specs/2026-11-13-survey-multi-choice-design.md)

## Завдання 1: Парсер шаблонів (`bot/services/survey_parser.py`)
- [x] Оновити `ParsedQuestion` для підтримки типу `'multi_choice'`.
- [x] Додати `MULTI_CHOICE_MARKERS` та `MAX_MULTI_CHOICE_OPTIONS = 45`.
- [x] У `SurveyParser.parse_template`:
  - розпізнавати маркери мультивибору без урахування регістру та вирізати їх із заголовка питання;
  - блокувати конфлікт, коли в одному питанні вказано одночасно маркер вільної відповіді та маркер мультивибору;
  - вимагати щонайменше 2 варіанти і не більше 45 варіантів для `'multi_choice'`.

## Завдання 2: База даних і статистика (`database/surveys.py`)
- [x] Додати функцію `parse_multi_choice_answer(raw_text: Optional[str]) -> List[str]` для безпечного розбору JSON-списків із fallback і дедуплікацією.
- [x] Додати спільний helper `_aggregate_choice_counts` для підрахунку відповідей і загальної кількості позначок без дублювання логіки.
- [x] Оновити `get_survey_question_stats` та `get_survey_detailed_results` для підтримки `'multi_choice'`, розрахунку `%` від респондентів, які відповіли на питання, поля `total_selections` та форматування `"; "` у `shops`.

## Завдання 3: Генератор Excel-звітів (`bot/services/survey_excel.py`)
- [x] На Аркуші 1 («Загальні результати») додати бейдж `" [Вибір кількох варіантів]"`, шапку `"% від респондентів"` та підсумковий рядок із кількістю респондентів і `"Всього позначок: {total_selections}"`.
- [x] На вкладках по магазинах забезпечити охайне перенесення тексту (`wrap_text=True`) для довгих відповідей через `"; "` і обмеження максимальної ширини колонки.

## Завдання 4: Адмін-інтерфейс (`bot/menus/developer.py`)
- [x] Оновити інструкцію Кроку 2 (`_render_survey_step2_template_text`) з прикладом маркера `(кілька варіантів)`.
- [x] У `dev_survey_process_template` зберігати `questions` як словники в `FSMContext` для зручного редагування.
- [x] Оновити `_show_survey_summary_view` та `dev_survey_preview_look` для відображення `'multi_choice'` та кнопок перемикання режиму `dev_survey_toggle_qtype:<q_idx>`.
- [x] Реалізувати та зареєструвати обробник `dev_survey_toggle_qtype` із перевіркою ліміту варіантів.

## Завдання 5: Проходження опитування в Telegram (`bot/menus/survey_taking.py`)
- [x] Оновити `_build_question_render(..., selected_mask: int = 0)` для рендерингу чекбоксів `⬜️` / `✅` (`survey_mt:...`) і кнопки підтвердження (`survey_mc:...`) з лічильником обраних пунктів.
- [x] Виділити спільні хелпери валідації питання та переходу після відповіді (`_validate_question_callback`, `_deliver_next_or_complete`).
- [x] Реалізувати та зареєструвати `survey_multi_toggle_callback` (`survey_mt:`) та `survey_multi_confirm_callback` (`survey_mc:`) із вимогою мінімум 1 обраного варіанта та захистом від повторних натискань.

## Завдання 6: Автотести та верифікація
- [x] Створити `tests/test_survey_multi_choice.py` із тестами парсера, БД, Excel-генератора, адмін-перемикача та сценаріїв проходження опитування.
- [x] Запустити повний набір тестів (`python3 -m unittest discover tests`) і перевірити 100% проходження.
- [x] Закомітити зміни.
