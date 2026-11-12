# План реалізації: Кнопка переведення стажера у статус Працівника в профілі

## 1. Огляд завдання
Додати можливість для Керівника та Адміністратора/Розробника переводити стажера у статус «Працівник» безпосередньо з картки користувача у боті з модальним підтвердженням дій.

---

## 2. Покроковий план виконання

### Крок 1: Оновлення картки та хендлерів Керівника (`bot/menus/manager.py`)
- У функції `_show_intern_details`:
  - Отримувати статус стажера через `get_user_details(intern_id)`.
  - Якщо `status != 'Працівник'`, додавати кнопку `[🎓 Перевести у працівники]` з `callback_data=f"mgr_promote_prompt:{intern_id}:{back_callback}"`.
- Додати хендлер `manager_promote_prompt_handler(callback: CallbackQuery)`:
  - Відображає текст підтвердження та кнопки `[✅ Так, перевести]` (`mgr_promote_confirm:{intern_id}:{back_cb}`) і `[⬅️ Скасувати]` (`mgr_view_intern_{intern_id}:{back_cb}`).
- Додати хендлер `manager_promote_confirm_handler(callback: CallbackQuery)`:
  - Перевіряє права менеджера через `_ensure_manager(callback)`.
  - Викликає `update_user_role(intern_id, "Працівник", actor_id=callback.from_user.id)`.
  - Надсилає вітальне повідомлення стажеру (обгорнуте в `try/except`).
  - Відповідає callback toast: `✅ Статус оновлено: Працівник`.
  - Оновлює картку через виклик `_show_intern_details`.
- Зареєструвати нові callback-патерни у `register_manager_handlers(dp)`.

### Крок 2: Оновлення картки та хендлерів Developer/Admin (`bot/menus/developer.py`)
- У функції `_show_user_profile_card`:
  - Отримувати деталі користувача `get_user_details(user_id)`.
  - Якщо `not is_obs` та `status != 'Працівник'`, додавати кнопку `[🎓 Перевести у працівники]` з `callback_data=f"dev_u_promote_prompt:{user_id}:{ret_code}"`.
- Додати хендлер `developer_user_promote_prompt_handler(callback: CallbackQuery)`:
  - Відображає екран підтвердження з кнопками `[✅ Так, перевести]` (`dev_u_promote_confirm:{user_id}:{ret_code}`) та `[⬅️ Скасувати]` (`dev_u_card:{user_id}:{ret_code}`).
- Додати хендлер `developer_user_promote_confirm_handler(callback: CallbackQuery)`:
  - Викликає `update_user_role(user_id, "Працівник", actor_id=callback.from_user.id)`.
  - Надсилає вітальне повідомлення стажеру в приватні повідомлення (обгорнуте в `try/except`).
  - Відповідає callback toast: `✅ Статус оновлено: Працівник`.
  - Перемальовує картку `_show_user_profile_card`.
- Зареєструвати callback-патерни у `register_developer_handlers(dp)`.

### Крок 3: Юніт-тести
- Створити `tests/test_intern_profile_promote.py`:
  - Тест 1: Перевірка клавіатури менеджера для стажера (є кнопка `🎓 Перевести у працівники`).
  - Тест 2: Перевірка клавіатури менеджера для працівника (кнопки немає).
  - Тест 3: Виклик `mgr_promote_confirm` викликає `update_user_role` і шле привітання.
  - Тест 4: Перевірка клавіатури dev картки для стажера та виклик `dev_u_promote_confirm`.
- Запустити весь тестовий набір через `uv run --with-requirements requirements.txt python3 -m unittest discover tests`.

### Крок 4: Фіксація та деплой
- Закомітити зміни в git та пушнути в `origin/main`.
- Надати Даніку команду для оновлення бота на сервері (`git pull && sudo systemctl restart bulka-edu`).
