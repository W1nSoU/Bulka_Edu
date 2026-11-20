# Дизайн-специфікація: Виправлення HTML-підпису `dev_news_view` та тижневий звіт по новинах

**Дата:** 2026-11-20  
**Проєкт:** `Bulka_Edu`

---

## 1. Виправлення `dev_news_view_handler` (`Unclosed start tag`)

**Причина багу:** У `bot/menus/developer.py` (`dev_news_view_handler`) при довжині тексту > 1024 символів робився сирий зріз `text[:1020] + "..."`. Це розрізало відкриті HTML-теги (`<b>`, `<i>`, `<a href=...>`) і обрізало блок статистики внизу, що призводило до `TelegramBadRequest: can't parse entities: Unclosed start tag`.

**Рішення:**
- Додаємо чистий хелпер `build_safe_news_media_caption(news_id, raw_body, stats_block, limit=1024)` (у `bot/services/news_excel.py` або спільному утилітному місці, щоб легко покрити тестами):
  - Якщо `header + sanitized_body + stats_block` <= `limit`: повертає повний HTML-текст.
  - Якщо > `limit`: знімає HTML-теги з тіла новини, екранує спецсимволи (`html.escape`) і обрізає **тільки тіло новини**, залишаючи шапку та весь блок `📊 Статистика новини:` повністю цілими і з валідним HTML.
  - В `dev_news_view_handler` додаємо `try/except TelegramBadRequest`: при будь-якій помилці парсингу HTML робиться повторна відправка з повністю екранованим тілом (та fallback без `parse_mode`), щоб картка новини ніколи не падала.
  - Додаємо пропущений лічильник реакції `👍` у рядок емоцій картки новини (`👍 | 🔥 | 😁 | ❤️ | 🤔`).

---

## 2. Тижневий звіт по всіх новинах

### 2.1 База даних (`database/news.py`)
- `get_weekly_news_report_data(days: int = 7, db_path: str = DB_PATH) -> Dict[str, Any]`:
  - Обчислює вікно `[now_kyiv - timedelta(days=days), now_kyiv]` у `Europe/Kyiv`.
  - Вибирає всі новини з `news` за цей період (`created_at >= start_str`), відсортовані за `created_at DESC, id DESC`.
  - Для кожної новини збирає зведення реакцій (`👍`, `🔥`, `😁`, `❤️`, `🤔`), детальний список реакцій (ПІБ, посада, магазин, місто, емодзі, час) та детальний список недоставлених із причинами.
  - Рахує сумарні KPI: `news_count`, `total_recipients`, `sent_count`, `failed_count`, `sent_pct`, `failed_pct`, `total_reactions`, `reaction_pct`, сумарний розподіл емоцій та топ-новину за реакціями.
- `get_news_report_recipient_ids() -> List[int]`:
  - Повертає відсортований унікальний список `user_id` усіх Адміністраторів (`get_all_developers()`) + активних Наглядачів (`managers.process = 'Наглядач' AND (status IS NULL OR status != 'fired')`).

### 2.2 Генератор Excel та плановий відправник (`bot/services/news_excel.py`)
- `generate_weekly_news_report_xlsx(days: int = 7, db_path: str = DB_PATH) -> Tuple[io.BytesIO, Dict[str, Any]]`:
  - **Аркуш 1 «Зведення тижня»:** період, сумарні KPI + таблиця всіх новин тижня (ID, дата, текст-превʼю, аудиторія, місто, всього, доставлено, %, помилки, реакції, %, `👍`, `🔥`, `😁`, `❤️`, `🤔`).
  - **Аркуш 2 «Реакції за тиждень»:** усі персональні реакції по всіх новинах тижня (`Новина #`, `Дата новини`, `ПІБ`, `Посада`, `Магазин`, `Місто`, `Реакція`, `Час реакції`).
  - **Аркуш 3 «Не доставлено»:** усі помилки доставки за тиждень (`Новина #`, `Дата новини`, `ПІБ`, `Посада`, `Магазин`, `Місто`, `Причина`).
- `format_weekly_news_summary_caption(report_data: Dict[str, Any]) -> str`: коротке HTML-зведення для підпису документа в Telegram.
- `auto_weekly_news_report_sender(bot: Bot)`:
  - Формує тижневий звіт (`days=7`). Якщо новин за період немає (`news_count == 0`), логує і завершує роботу без спаму.
  - Надсилає Excel-файл + зведення усім `get_news_report_recipient_ids()` з безпечною затримкою і обробкою помилок доставки.

### 2.3 UI та планувальник (`bot/menus/developer.py`, `main.py`)
- У `dev_news_menu_handler` додаємо кнопку `📊 Тижневий звіт (Excel)` (`dev_news_weekly_report`), доступну через `_check_news_access` (Адміни + Наглядачі).
- Обробник `dev_news_weekly_report_handler` формує звіт за останні 7 днів та надсилає `.xlsx` із коротким зведенням (якщо новин немає - інформує в чаті).
- У `main.py` додаємо job у APScheduler: `auto_weekly_news_report_sender`, `cron`, `day_of_week="mon"`, `hour=9`, `minute=0`, `id="weekly_news_report"`.

---

## 3. Верифікація
- `tests/test_news_weekly_report.py`: тести на безпечне обрізання довгого HTML-caption (з тегами на межі 1024 байтів), агрегацію тижневих даних, 3-аркушевий Excel-файл (`openpyxl`), та авто-розсилку з пропуском порожнього тижня.
- `py_compile` та smoke-тест реєстрації хендлерів у `venv`.
