# Дизайн-специфікація: Живий лічильник реакцій на новини в реальному часі

## 1. Мета та огляд
У корпоративному боті BULKA під кожною опублікованою новиною користувачі можуть ставити емоції. Необхідно:
1. Замінити реакцію дизлайку `👎` на `😁`. Новий набір реакцій: `🔥`, `😁`, `❤️`, `🤔`.
2. Додати внизу кожного повідомлення новини рядок сумарних лічильників формату:
   `0 🔥 | 0 😁 | 0 ❤️ | 0 🤔`
3. Забезпечити відображення та оновлення кількості емоцій для всіх отримувачів новини:
   - Миттєве оновлення для того, хто голосує (затримка < 0.1с).
   - Фонова безпечна пакетна синхронізація (дебаунс 15-30с) через `news_deliveries` для решти користувачів без ризику Telegram Flood Limits.

---

## 2. Архітектура та компоненти

### 2.1 Конфігурація та база даних (`database/news.py`)
- **Константа реакцій:**
  ```python
  NEWS_REACTIONS = ["🔥", "😁", "❤️", "🤔"]
  ```
- **Автоматична міграція старих даних:**
  У функції `init_news_db`:
  ```sql
  UPDATE news_reactions SET reaction = '😁' WHERE reaction = '👎';
  ```
- **Утиліта форматування рядка:**
  ```python
  def format_news_reactions_line(breakdown: dict[str, int]) -> str:
      fire = breakdown.get("🔥", 0)
      laugh = breakdown.get("😁", 0)
      heart = breakdown.get("❤️", 0)
      think = breakdown.get("🤔", 0)
      return f"{fire} 🔥 | {laugh} 😁 | {heart} ❤️ | {think} 🤔"
  ```
- **Утиліта заміни рядка лічильника в тексті:**
  ```python
  def update_text_with_reactions_line(raw_text: str, new_line: str) -> str:
      pattern = r"\d+\s*🔥\s*\|\s*\d+\s*😁\s*\|\s*\d+\s*❤️\s*\|\s*\d+\s*🤔"
      if re.search(pattern, raw_text):
          return re.sub(pattern, new_line, raw_text)
      return f"{raw_text.rstrip()}\n\n{new_line}"
  ```

---

### 2.2 Розсилка новин (`bot/services/news_broadcaster.py`)
- При підготовці новини до відправки:
  1. До тексту новини додається початковий рядок:
     `clean_text = update_text_with_reactions_line(clean_text, "0 🔥 | 0 😁 | 0 ❤️ | 0 🤔")`
  2. Кнопки формуються функцією `get_news_reaction_keyboard(news_id, current_reaction=None)`.
  3. Під час розсилки кожному користувачу фіксується `message_id` у таблиці `news_deliveries`.

---

### 2.3 Обробник реакцій користувача (`bot/handlers.py`)
- Коли користувач натискає інлайн-кнопку емоції `news_react:{news_id}:{emoji}`:
  1. Записуємо реакцію в базу: `upsert_news_reaction(news_id, user_id, emoji)`.
  2. Отримуємо оновлений підсумок: `summary = await get_news_reactions_summary(news_id)`.
  3. Формуємо новий рядок: `reactions_line = format_news_reactions_line(summary["breakdown"])`.
  4. Оновлюємо текст/підпис поточного повідомлення користувача:
     `new_text = update_text_with_reactions_line(caption_or_text, reactions_line)`
  5. Оновлюємо клавіатуру поточного повідомлення:
     `new_kb = get_news_reaction_keyboard(news_id, current_reaction=emoji)`
  6. Відправляємо швидке підтвердження: `await callback.answer("✅ Реакцію враховано!")`.
  7. Передаємо завдання у фонову чергу:
     `news_reaction_sync_queue.schedule_sync(news_id=news_id, trigger_user_id=user_id)`.

---

### 2.4 Фонова черга синхронізації (`NewsReactionSyncQueue`)
- **Розташування:** `bot/services/news_broadcaster.py` (singleton екземпляр).
- **Логіка роботи:**
  1. При виклику `schedule_sync(news_id, trigger_user_id)` додає `news_id` до черги очікування.
  2. Встановлює таймер затримки (дебаунс 15 секунд). Якщо протягом 15 секунд надходять нові кліки для цієї новини, таймер скидається (але не більше 30 секунд з першого кліку).
  3. Коли таймер спрацьовує:
     - З бази вибираються актуальні сумарні лічильники новини `get_news_reactions_summary(news_id)`.
     - З `news_deliveries` вибираються всі успішно доставлені записи:
       `SELECT user_id, message_id FROM news_deliveries WHERE news_id = ? AND status = 'sent' AND message_id IS NOT NULL`
     - Пропускається користувач `trigger_user_id` (якщо його повідомлення вже містить актуальний рядок).
     - Повідомлення оновлюються асинхронно з мікропаузою 0.05-0.08с між викликами:
       `edit_message_caption` (якщо було фото/відео) або `edit_message_text` (якщо текст).
     - Клавіатура для інших користувачів не змінюється (щоб не скидати їхній власний вибір `✅`).
- **Стійкість до помилок:**
  - Обробка винятків:
    - `message is not modified`: ігнорується.
    - `message to edit not found` / `bot was blocked by the user` / `user is deactivated`: ігнорується.
    - `TelegramRetryAfter` / Flood limits: воркер викликає `asyncio.sleep(exc.retry_after)` і продовжує.

---

## 3. План тестування
1. **Тест форматування:** перевірка коректності генерації рядка `0 🔥 | 0 😁 | 0 ❤️ | 0 🤔` та регулярного виразу оновлення тексту без видалення основного змісту.
2. **Тест зміни емодзі:** міграція старих `'👎'` в `'😁'` та заборона невалідних емодзі.
3. **Тест обробника реакцій:** перевірка миттєвого оновлення для автора кліку.
4. **Тест дебаунс-черги:** перевірка, що черга відкладає запуск і пакетно оновлює повідомлення іншим користувачам.
