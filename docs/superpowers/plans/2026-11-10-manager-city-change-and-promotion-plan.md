# План реалізації: Зміна міста керівників та переведення на Керівника

Цей план описує покроковий процес впровадження зміни міста для керівників магазинів та кнопки переведення керівника-стажера в статус повноцінного керівника в системі Bulka Education.

---

### Крок 1. База даних керівників (`database/managers.py`)
- [x] Оновити `promote_manager_trainee(uid: int) -> bool`:
  - Перевірити та оновити таблицю `managers`: `UPDATE managers SET process = 'Керівник' WHERE uid = ? AND process = 'Керівник Стажер'`.
  - Оновити таблицю `users`: `UPDATE users SET status = 'Працівник' WHERE user_id = ?`.
  - Повертати `True` при успішному оновленні та `False`, якщо запис уже був оновлений (захист від повторних спрацьовувань).
- [x] Реалізувати `update_manager_city(uid: int, new_city: str) -> bool`:
  - Отримати поточний профіль керівника через `get_manager_by_uid(uid)`.
  - Якщо `new_city == old_city`: завершити без дій і повернути `True`.
  - Якщо у керівника були магазини (`old_shops`): викликати `reassign_removed_shops_users_to_territorial(old_city, old_shops, uid)` для безпечної передачі всіх підлеглих Територіалу.
  - Оновити `managers`: `UPDATE managers SET city = ?, shops = '[]' WHERE uid = ?`.
  - Оновити `users`: `UPDATE users SET city = ? WHERE user_id = ?`.
  - Повернути `True`.

---

### Крок 2. Інтерфейс карток та підменю (`bot/menus/developer.py`)
- [x] Додати кнопку «🎓 Перевести на Керівника» в `_build_manager_card`:
  - Перевірка: `mgr.get("process") == "Керівник Стажер" and mgr.get("status") != "fired" and not is_observer`.
  - Додати кнопку `[🎓 Перевести на Керівника] -> dev_mgr_promote_ask:{uid}`.
- [x] Створити обробники переведення:
  - `dev_mgr_promote_ask`: виводить екран підтвердження з описом наслідків, кнопками `[✅ Так, перевести]` (`dev_mgr_promote_confirm:{uid}`) та `[⬅️ Скасувати]` (`dev_mgr_view:{uid}`).
  - `dev_mgr_promote_confirm`:
    - Перевіряє актуальний статус у базі (захист від повторних натискань).
    - Викликає `promote_manager_trainee(uid)`.
    - Надсилає вітальне повідомлення керівнику через `bot.send_message` з перехопленням можливих помилок блокування бота.
    - Оновлює картку керівника з підтвердженням успішного переведення.
- [x] Додати кнопку «🏙️ Змінити місто» в `dev_mgr_edit_menu`:
  - Оновити розмітку кнопок підменю: додати кнопку `[🏙️ Змінити місто] -> dev_mgr_ch_city:{manager_uid}`.
- [x] Створити обробники зміни міста:
  - `dev_mgr_change_city_start`:
    - Отримує список міст через `_get_active_city_names()`.
    - Будує клавіатуру міст із зазначенням `(поточне)` та кнопкою скасування.
  - `dev_mgr_process_city_set`:
    - Перевіряє, якщо обрано те саме місто: видає alert.
    - Викликає `update_manager_city(manager_uid, new_city)`.
    - Ініціалізує FSM-стан вибору магазинів `DeveloperStates.waiting_edit_manager_shops` для `new_city` з порожніми магазинами `[]`.
    - Відображає інтерфейс вибору магазинів у новому місті (з інформативною підказкою, якщо в місті ще немає точок).
- [x] Зареєструвати нові callback-обробники в `register_developer_handlers`:
  - `dev_mgr_promote_ask:`
  - `dev_mgr_promote_confirm:`
  - `dev_mgr_ch_city:`
  - `dev_mgr_city_set:`

---

### Крок 3. Тестування (`tests/test_manager_city_and_promotion.py`)
- [x] Створити набір тестів:
  - Тест `test_promote_manager_trainee`: перевірка оновлення в `managers` та `users` та захисту від дублікатів.
  - Тест `test_update_manager_city`: перевірка скидання магазинів у `managers`, оновлення міста в `users` та безпечної передачі працівників.
  - Тест генерації кнопок у `_build_manager_card` для стажера та звичайного керівника.
- [x] Запустити тести через `unittest` та переконатися в 100% проходженні (3 з 3 нових тестів, 94 з 94 тестів усього проєкту).

---

### Крок 4. Фіксація змін та документація
- [ ] Зафіксувати зміни в git (`git add` + `git commit` + `git push`).
- [ ] Оновити робочий щоденник Obsidian `10.11.2026.md` та `Журнал Змін та Синхронізації`.
- [ ] Надати команду для оновлення бойового сервера.
