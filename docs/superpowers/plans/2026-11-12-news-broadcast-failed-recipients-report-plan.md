# План реалізації: Відображення списку користувачів, які заблокували бота / не отримали новину, у фінальному звіті розсилки

## 1. Огляд
Розширити фінальне повідомлення про завершення розсилки новини в `bot/services/news_broadcaster.py`: якщо є невдалі доставки (`total_failed > 0`), виводити поіменний перелік співробітників з їхніми ID, посадою/магазином та точною причиною з `news_deliveries` (наприклад, `⛔️ Бот заблокований користувачем`).

---

## 2. Покроковий план

### Крок 1: Оновлення формування фінального звіту в `bot/services/news_broadcaster.py`
- Імпортувати `html` (для екранування імен) та `get_news_failed_deliveries_detailed` з `database.news`.
- У функції `dispatch_news_waves`:
  - Якщо `admin_chat_id` та `total_failed > 0` і `news_id`:
    - Викликати `failed_details = await get_news_failed_deliveries_detailed(news_id)`.
    - Якщо список не порожній:
      - Додати заголовок: `\n\n⚠️ <b>Не отримали повідомлення:</b>\n`.
      - Сформувати рядки для перших до 15 користувачів:
        `• <b>{name}</b> (<code>{user_id}</code>{meta}) — {reason}`
      - Якщо записів більше 15, додати `<i>...та ще {len(failed_details) - 15} осіб</i>`.
  - Надіслати збагачений текст звіту через `bot.send_message`.

### Крок 2: Юніт-тести
- Створити `tests/test_news_failed_report.py`:
  - Тест 1: Розсилка з `total_failed == 0` надсилає звичайний звіт без блоку `⚠️ Не отримали повідомлення`.
  - Тест 2: Розсилка з `total_failed > 0` підтягує записи з `get_news_failed_deliveries_detailed` і виводить ПІБ та причину відмови.
  - Тест 3: Обмеження до 15 записів при 20 невдалих доставках.
- Запустити тест через `uv run --with-requirements requirements.txt python3 -m unittest tests/test_news_failed_report.py`.
- Запустити повний тестовий набір через `uv run --with-requirements requirements.txt python3 -m unittest discover tests`.

### Крок 3: Фіксація та деплой
- Закомітити зміни та пушнути в `origin/main`.
- Надати Даніку команду для оновлення бота на сервері (`git pull && sudo systemctl restart bulka-edu`).
