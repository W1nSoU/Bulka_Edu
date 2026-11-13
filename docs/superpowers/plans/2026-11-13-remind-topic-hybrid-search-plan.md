# План реалізації: Гібридний пошук та крос-рольова база знань для «Нагадати тему»

**Специфікація:** [2026-11-13-remind-topic-hybrid-search-design.md](file:///Users/daniildusinskij/All/Dev/Bulka_Edu/docs/superpowers/specs/2026-11-13-remind-topic-hybrid-search-design.md)
**Дата:** 2026-11-13

## Огляд завдання
Замінити крихкий 2-кроковий роутер по `summary` (`route_question_to_days`) на дедуплікований гібридний пошук (Vector `text-embedding-3-small` у SQLite-кеші + український лексичний/стем-пошук + обов'язковий Exact-Token Scan), реалізувати 2-етапну крос-рольову логіку пошуку, виправити баг `mode="dev_test"`, динамізувати вибір посад та покрити все `unittest`-тестами.

---

## Покроковий план виконання

### Крок 1: Модуль парсингу, чанкінгу та дедуплікації (`bot/services/knowledge_chunker.py`)
- Створити `bot/services/knowledge_chunker.py` з чистими функціями:
  - `extract_clean_text(raw_content: str, content_type: str) -> str`: відсіює `"test"`, `"photo_files"`, `"video_files"`; розбирає JSON-масиви `[{"text": ..., "photo": ...}]`, залишаючи виключно текстовий зміст без `file_id`.
  - `split_into_chunks(text: str, target_chars: int = 750, overlap_chars: int = 120) -> list[str]`: ріже текст по абзацах/рядках/реченнях із перекриттям.
  - `compute_chunk_hash(text: str) -> str`: SHA-256 від пробільно-нормалізованого тексту.
  - `build_deduplicated_chunks(materials: list[dict]) -> list[dict]`: дедуплікує ідентичні чанки між ролями та днями, накопичуючи `sources` (`material_id`, `role`, `day`, `title`). Для порожнього `role` виставляє `role = "__UNASSIGNED__"` та `display_role = "Загальні матеріали"`.

### Крок 2: SQLite-таблиця `material_chunks` (`database/knowledge_chunks.py` і `database/schema.py`)
- Створити `database/knowledge_chunks.py`:
  - `init_knowledge_chunks_db(db_path: str = DB_PATH)`: створює таблицю `material_chunks`.
  - `get_all_knowledge_chunks(db_path: str = DB_PATH) -> list[dict]`.
  - `get_materials_fingerprint(db_path: str = DB_PATH) -> tuple[int, str]`: швидка перевірка `COUNT(*)` та `COALESCE(MAX(updated_at), '')` у таблиці `materials`.
  - `sync_knowledge_chunk_rows(chunks: list[dict], embedding_model: str, db_path: str = DB_PATH) -> list[str]`: синхронізує чанки, видаляє застарілі хеші, оновлює `sources_json` без скидання вже порахованих ембедінгів і повертає хеші, для яких потрібне обчислення ембедінга.
  - `save_chunk_embeddings(hash_to_embedding: dict[str, list[float]], model: str, db_path: str = DB_PATH) -> None`.
- Зареєструвати `await init_knowledge_chunks_db(DB_PATH)` у `database/schema.py:init_db()`.

### Крок 3: Гібридний пошук та індексація (`bot/services/semantic_search.py`)
- Переписати `bot/services/semantic_search.py` (без `faiss`, `numpy`, `sentence_transformers`):
  - Український токенізатор + суфіксний стеммер (`uk_stem`) для слів `>= 5` символів (короткі абревіатури `"РЦ"`, `"ВВ"`, `"ТЗ"` зберігаються недоторканими).
  - Exact-Token Scan з межами слова (`(?<![\wа-яіїєґ'])<token>(?![\wа-яіїєґ'])`) + збігом за основою.
  - Чисто-Python косинусна подібність + гібридний скор.
  - `sync_knowledge_index(compute_embeddings: bool = True, db_path: str = DB_PATH)` + автоперевірка відбитка `materials` перед пошуком.
  - Зберегти сумісність `build_and_reset_embeddings()` (для `bot/menus/developer.py`) та `reset_semantic_search_index()`.
  - `hybrid_search_chunks(query: str, role_filter: str | None = None, scope: str = "role", max_context_chars: int = 35000, db_path: str = DB_PATH, query_embedding: list[float] | None = None)`:
    - Повертає топ повних чанків + **усі** додаткові точні збіги (`is_exact_match=True`), екстрактивно витягуючи відповідні абзаци/вікна `±2` речення навколо входження в межах `max_context_chars`.

### Крок 4: 2-етапний наставник та HTML-безпека (`bot/services/openai_ai.py`)
- Оновити `bot/services/openai_ai.py`:
  - Додати безпечну Telegram HTML-санітизацію/конвертацію виводу GPT (щоб прибирати непідтримувані теги типу `<ul>`, `<li>`, `<p>`).
  - Оновити `ask_gpt_tutor(...)` для використання `hybrid_search_chunks`:
    - `role_filter is None`: прямий пошук по всій мережі.
    - `role_filter` задано: спочатку Stage 1 (лише `role_filter` + `'ALL'`); якщо у ролі `0` матеріалів, низька релевантність або GPT повернув `__NO_ANSWER_IN_MATERIALS__` -> Stage 2 по всій мережі з прозорою преамбулою і посиланням на посаду та день кожного пункту.
  - Додати екстрактивний фолбек-форматер без GPT (чисті цитати з чанків, без JSON-шуму).

### Крок 5: Фікси хендлерів, меню вибору ролей і фоновий запуск (`bot/handlers.py`, `bot/menus/manager.py`, `main.py`)
- У `bot/handlers.py`:
  - Додати `_get_remind_searchable_roles(exclude_manager_roles: bool = False) -> list[str]` (об'єднання `get_all_positions()` і `get_unique_roles_from_materials()`).
  - Замінити `AVAILABLE_ROLES` у `remind_topic_global_callback` і `remind_role_select_callback` на динамічні ролі зі збереженням у FSM state (`remind_roles_list`).
  - У `process_keyword_search`: додати гілку `elif mode == "dev_test":`, прибрати блокуючу перевірку `if is_openai_configured() and role_mats:` (щоб працювало при `0` матеріалах у посаді), використовувати 2-етапний сервіс та коректну розбивку відповідей >4000 символів без поломки HTML.
- У `bot/menus/manager.py`:
  - Оновити `manager_remind_menu` (динамічні ролі + кнопка `🌐 Всі посади` -> `mgr_remind_role:ALL`).
  - Оновити `manager_process_remind_role` для підтримки `ALL`.
- У `main.py`:
  - Запускати `asyncio.create_task(build_and_reset_embeddings())` замість застарілого `backfill_materials_summaries_background()` при старті.

### Крок 6: Юніт- та інтеграційні тести (`tests/test_remind_topic_hybrid_search.py`)
- Створити `tests/test_remind_topic_hybrid_search.py` на `unittest.IsolatedAsyncioTestCase` із тимчасовим SQLite-файлом та моками OpenAI API:
  - Парсинг JSON + ігнорування `test`/`photo_files` + дедуплікація.
  - Інкрементальний кеш ембедінгів (0 повторних викликів при незмінених хешах; очистка застарілих чанків).
  - Exact-Token Scan ("Списування алкоголю" -> День 1; "РЦ" -> усі згадки без помилкового збігу на `"серце"`).
  - 2-етапний пошук (своя посада без домішування інших -> мережа при 0 матеріалів / `__NO_ANSWER_IN_MATERIALS__` -> глобальний пошук).
  - `process_keyword_search` (`mode="dev_test"`, `role=None`), динамічні ролі (`Керівник ТТ`, `Комплектувальник-приймальник`), фолбек без OpenAI.
- Запустити `uv run --with-requirements requirements.txt python3 -m unittest tests/test_remind_topic_hybrid_search.py` і весь набір `uv run --with-requirements requirements.txt python3 -m unittest discover tests`.
