# План реалізації: Підтримка фото та відео у новинах із текстом та реакціями

Цей план описує покроковий процес впровадження підтримки фото та відео для новин, роздільної відправки медіа та тексту з реакціями, а також налаштування ШІ-покращення лише для тексту.

---

### Крок 1. База даних новин (`database/news.py`)
- [x] Оновити схему `news` у функції `init_news_db`:
  - Додати авто-міграцію через перевірку колонок у `news`:
    - Додати `video_file_id TEXT`, якщо відсутня.
    - Додати `media_type TEXT`, якщо відсутня.
- [x] Оновити функцію `create_news`:
  - Додати параметри `video_file_id: Optional[str] = None` та `media_type: Optional[str] = None`.
  - Зберігати їх у таблиці `news`.
- [x] Оновити функції читання новин (`get_news_by_id`, `get_news_history_last_6_months`, `get_all_news`):
  - Повертати `video_file_id` та `media_type` у словниках новин.

---

### Крок 2. Сервіс розсилки новин (`bot/services/news_broadcaster.py`)
- [x] Оновити `send_news_batch`:
  - Додати параметри `video_file_id: Optional[str] = None`, `media_type: Optional[str] = None`.
  - Реалізувати роздільну доставку:
    - Якщо `media_type == "video"` і є `video_file_id`:
      1. `await bot.send_video(chat_id=user_id, video=video_file_id)`
      2. `sent_msg = await bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup, parse_mode="HTML")`
    - Якщо `media_type == "photo"` і є `photo_file_id`:
      1. `await bot.send_photo(chat_id=user_id, photo=photo_file_id)`
      2. `sent_msg = await bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup, parse_mode="HTML")`
    - Якщо без медіа:
      - `sent_msg = await bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup, parse_mode="HTML")`
  - Зберігати `message_id` текстового повідомлення для коректної прив'язки інлайн-реакцій.
- [x] Оновити виклики `send_news_batch` у `start_news_wave_broadcast` та `resume_news_wave_broadcast`:
  - Прокидати `video_file_id` та `media_type` з об'єкта новини.

---

### Крок 3. Інтерфейс створення та попереднього перегляду (`bot/menus/developer.py`)
- [x] Оновити `dev_news_create_start`:
  - Ініціалізувати в FSM-стані: `media_type=None, photo_file_id=None, video_file_id=None`.
  - Оновити текст підказки: повідомити про підтримку тексту, фото та відео (як разом, так і окремо).
- [x] Оновити `dev_news_process_content`:
  - Додати обробку `message.video`: зберегти `video_file_id`, встановити `media_type = "video"`.
  - Якщо фото або відео надіслані без підпису:
    - Зберегти медіа в стані.
    - Вивести підказку: *«✅ Медіа збережено! Тепер надішліть текст новини:»* (залишатися в `waiting_content`).
  - Якщо текст надіслано наступним повідомленням або був підписом:
    - Зберегти `text_content` та перейти до вибору категорій `selecting_categories`.
- [x] Оновити `_show_news_preview`:
  - Відображати медіа (фото чи відео) та під ним блок тексту новини, метадані аудиторії і кнопки дій.
- [x] Перевірити `dev_news_ai_improve_handler`:
  - Переконатися, що функція змінює лише `text_content`, залишаючи медіа без змін.
- [x] Оновити `dev_news_launch_handler`:
  - Передавати `video_file_id` та `media_type` у `create_news` та фоновий броадкаст.

---

### Крок 4. Модульні тести (`tests/test_news_media_broadcaster.py`)
- [x] Створити тести:
  - Авто-міграція БД та збереження/отримання новини з відео та фото.
  - Емуляція розсилки `send_news_batch` для відео (перевірка послідовності `send_video` -> `send_message`).
  - Емуляція розсилки `send_news_batch` для фото (перевірка послідовності `send_photo` -> `send_message`).
  - Емуляція розсилки без медіа (перевірка `send_message`).
- [x] Запустити тест через `./venv/bin/python -m unittest tests/test_news_media_broadcaster.py`.

---

### Крок 5. Валідація, запуск повного набору тестів та коміт
- [x] Запустити перевірку синтаксису `python -m py_compile ...`.
- [x] Запустити повний тестовий набір `python -m unittest discover tests`.
- [x] Закомітити зміни та відправити на сервер (`git push`).
