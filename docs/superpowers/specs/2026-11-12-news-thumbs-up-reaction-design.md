# Дизайн: Додавання реакції "👍" до новин

## 1. Мета та огляд
Додати реакцію "👍" першою в списку доступних реакцій до розсилок новин у боті Bulka Education.
Тепер користувачам доступно 5 реакцій: `["👍", "🔥", "😁", "❤️", "🤔"]`.

## 2. Архітектурні зміни

### 2.1. База даних та бізнес-логіка (`database/news.py`)
- Оновити `NEWS_REACTIONS`:
  ```python
  NEWS_REACTIONS = ["👍", "🔥", "😁", "❤️", "🤔"]
  ```
- Оновити `format_news_reactions_line`:
  ```python
  def format_news_reactions_line(breakdown: dict[str, int]) -> str:
      thumbs = breakdown.get("👍", 0)
      fire = breakdown.get("🔥", 0)
      laugh = breakdown.get("😁", 0) + breakdown.get("👎", 0)
      heart = breakdown.get("❤️", 0)
      think = breakdown.get("🤔", 0)
      return f"{thumbs} 👍 | {fire} 🔥 | {laugh} 😁 | {heart} ❤️ | {think} 🤔"
  ```

### 2.2. Інлайн-клавіатура (`bot/services/news_broadcaster.py`)
- `get_news_reaction_keyboard` автоматично використовує `NEWS_REACTIONS`, генеруючи 5 кнопок у ряд під новиною:
  `[ 👍 ] [ 🔥 ] [ 😁 ] [ ❤️ ] [ 🤔 ]`
  (з позначкою `✅` для поточно обраної реакції).

### 2.3. Генерація Excel-звіту (`bot/services/news_excel.py`)
- Додати `"👍": "Схвалення / Палець вгору"` до `reaction_labels`.

### 2.4. Тестування (`tests/`)
- Оновити тестові очікування у `tests/test_news_live_reactions.py` та `tests/test_news_reactions_and_history.py` на новий формат рядка `0 👍 | 0 🔥 | 0 😁 | 0 ❤️ | 0 🤔`.

## 3. Критерії успішності
1. Клавіатура розсилки містить 5 кнопок, перша з яких `👍`.
2. Натискання на `👍` зберігає реакцію в таблиці `news_reactions`, ставить галочку `👍 ✅` та оновлює живий рядок лічильників.
3. Експорт в Excel коректно відображає `👍` та підраховує частку.
4. Всі тести проходять успішно (100% pass).
