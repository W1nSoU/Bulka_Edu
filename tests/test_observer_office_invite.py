import os
import tempfile
import unittest

import database
import database.schema as schema_mod
import database.tokens as tokens_mod
import database.managers as managers_mod
import database.users as users_mod
import database.shops as shops_mod
import database.hr as hr_mod
from database.schema import init_db


class TestObserverOfficeInvite(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        tmpdir = self._tmpdir.name
        self.users_db = os.path.join(tmpdir, "users.db")
        self.tokens_db = os.path.join(tmpdir, "tokens.db")
        self.managers_db = os.path.join(tmpdir, "managers.db")

        self._orig_db = database.DB_PATH
        self._orig_schema_db = schema_mod.DB_PATH
        self._orig_users_db = users_mod.DB_PATH
        self._orig_mgr_db = managers_mod.DB_PATH
        self._orig_mgr_path = managers_mod.MANAGERS_DB_PATH
        self._orig_tok_path = tokens_mod.TOKENS_DB_PATH
        self._orig_shops_db = shops_mod.DB_PATH
        self._orig_shops_mgr = shops_mod.MANAGERS_DB_PATH
        self._orig_shops_tok = shops_mod.TOKENS_DB_PATH

        self._orig_hr_db = hr_mod.DB_PATH
        self._orig_hr_mgr = hr_mod.MANAGERS_DB_PATH

        database.DB_PATH = self.users_db
        schema_mod.DB_PATH = self.users_db
        users_mod.DB_PATH = self.users_db
        managers_mod.DB_PATH = self.users_db
        managers_mod.MANAGERS_DB_PATH = self.managers_db
        tokens_mod.TOKENS_DB_PATH = self.tokens_db
        shops_mod.DB_PATH = self.users_db
        shops_mod.MANAGERS_DB_PATH = self.managers_db
        shops_mod.TOKENS_DB_PATH = self.tokens_db
        hr_mod.DB_PATH = self.users_db
        hr_mod.MANAGERS_DB_PATH = self.managers_db

        await init_db()
        await hr_mod.init_hr_db()
        await tokens_mod.init_tokens_db()
        await managers_mod.init_managers_db()

    async def asyncTearDown(self):
        database.DB_PATH = self._orig_db
        schema_mod.DB_PATH = self._orig_schema_db
        users_mod.DB_PATH = self._orig_users_db
        managers_mod.DB_PATH = self._orig_mgr_db
        managers_mod.MANAGERS_DB_PATH = self._orig_mgr_path
        tokens_mod.TOKENS_DB_PATH = self._orig_tok_path
        shops_mod.DB_PATH = self._orig_shops_db
        shops_mod.MANAGERS_DB_PATH = self._orig_shops_mgr
        shops_mod.TOKENS_DB_PATH = self._orig_shops_tok
        hr_mod.DB_PATH = self._orig_hr_db
        hr_mod.MANAGERS_DB_PATH = self._orig_hr_mgr
        self._tmpdir.cleanup()

    async def test_multi_use_office_token_allows_multiple_observers(self):
        admin_uid = 999001
        token = await tokens_mod.generate_token(
            manager_id=admin_uid,
            role="Наглядач",
            expires_in_hours=24,
            extra_data={"multi_use": True, "used_by_list": []},
        )

        # Перевіряємо активний багаторазовий токен (0 використань)
        active = await tokens_mod.get_active_multi_use_token("Наглядач")
        self.assertIsNotNone(active)
        self.assertEqual(active["token"], token)
        self.assertEqual(active["used_count"], 0)

        # Три різних працівники офісу переходять за одним і тим самим посиланням
        office_users = [
            (1001, "Іваненко Іван", "ivan_obs"),
            (1002, "Петренко Марія", "maria_obs"),
            (1003, "Сидоренко Олег", None),
        ]

        for uid, full_name, uname in office_users:
            tdata = await tokens_mod.get_token_data(token)
            self.assertEqual(tdata["status"], "ok")
            self.assertEqual(tdata["role"], "Наглядач")
            self.assertTrue(tdata["extra_data"].get("multi_use"))

            await users_mod.register_user(uid, username=uname, full_name=full_name)
            await managers_mod.add_observer(uid, full_name, uname, responsible_uid=admin_uid)
            used_ok = await tokens_mod.use_token(token, uid)
            self.assertTrue(used_ok)
            self.assertTrue(await managers_mod.is_observer_user(uid))

            user_row = await users_mod.get_user_details(uid)
            self.assertEqual(user_row["role"], "Наглядач")

        # Після 3 реєстрацій токен досі активний і показує used_count == 3
        active_after = await tokens_mod.get_active_multi_use_token("Наглядач")
        self.assertIsNotNone(active_after)
        self.assertEqual(active_after["token"], token)
        self.assertEqual(active_after["used_count"], 3)

        all_obs = await managers_mod.get_all_observers()
        self.assertEqual(len(all_obs), 3)

        # Деактивуємо спільне посилання вручну
        revoked = await tokens_mod.revoke_token(token)
        self.assertTrue(revoked)

        # Після деактивації токен більше не дійсний
        tdata_revoked = await tokens_mod.get_token_data(token)
        self.assertEqual(tdata_revoked["status"], "expired")
        self.assertIsNone(await tokens_mod.get_active_multi_use_token("Наглядач"))

    async def test_single_use_observer_token_locks_after_first_use(self):
        admin_uid = 999001
        token = await tokens_mod.generate_token(
            manager_id=admin_uid,
            role="Наглядач",
            expires_in_hours=24,
        )

        # Перший користувач успішно використовує одноразовий токен
        tdata1 = await tokens_mod.get_token_data(token)
        self.assertEqual(tdata1["status"], "ok")
        self.assertTrue(await tokens_mod.use_token(token, 2001))

        # Другий користувач отримує already_used
        tdata2 = await tokens_mod.get_token_data(token)
        self.assertEqual(tdata2["status"], "already_used")
        self.assertFalse(await tokens_mod.use_token(token, 2002))

    async def test_observers_menu_has_both_single_and_office_buttons(self):
        from bot.menus.developer import _build_observers_menu_view

        _, kb = await _build_observers_menu_view(page=0, bot=None, is_observer=False)
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        self.assertIn("dev_obs_create_invite", callbacks)
        self.assertIn("dev_obs_office_invite", callbacks)

        # Для самого наглядача кнопки створення запрошень приховані
        _, kb_obs = await _build_observers_menu_view(page=0, bot=None, is_observer=True)
        callbacks_obs = [btn.callback_data for row in kb_obs.inline_keyboard for btn in row]
        self.assertNotIn("dev_obs_create_invite", callbacks_obs)
        self.assertNotIn("dev_obs_office_invite", callbacks_obs)

    async def test_dev_add_manager_callback_data_within_64_bytes(self):
        from unittest.mock import AsyncMock, MagicMock
        import bot.services.cities as cities_mod
        from bot.menus.developer import developer_request_add_manager, developer_process_add_manager_city
        from bot.config import MAIN_DEVELOPER_ID

        orig_cities_db = cities_mod.DB_PATH
        cities_mod.DB_PATH = self.users_db
        try:
            long_city = "Камʼянець-Подільський (Центральний регіон Хмельниччини)"
            await cities_mod.add_city(long_city)

            callback = MagicMock()
            callback.from_user.id = MAIN_DEVELOPER_ID
            callback.data = "dev_add_manager"
            callback.answer = AsyncMock()
            callback.message = MagicMock()
            callback.message.photo = None
            callback.message.edit_text = AsyncMock()
            callback.message.answer = AsyncMock()

            state = MagicMock()
            state.clear = AsyncMock()
            state.set_state = AsyncMock()
            state.update_data = AsyncMock()

            await developer_request_add_manager(callback, state)

            # Перевіряємо передану клавіатуру і те, що всі callback_data <= 64 байтів
            call_kwargs = callback.message.edit_text.call_args.kwargs
            kb = call_kwargs["reply_markup"]
            city_btn = None
            for row in kb.inline_keyboard:
                for btn in row:
                    self.assertLessEqual(len(btn.callback_data.encode("utf-8")), 64)
                    if btn.text == long_city:
                        city_btn = btn

            self.assertIsNotNone(city_btn)
            self.assertTrue(city_btn.callback_data.startswith("dev_mgr_city_select:"))

            # Тепер симулюємо натискання на кнопку цього міста
            callback.data = city_btn.callback_data
            await developer_process_add_manager_city(callback, state)
            state.update_data.assert_called_with(manager_city=long_city, selected_shops=[])
        finally:
            cities_mod.DB_PATH = orig_cities_db


    async def test_token_case_insensitivity_and_strip(self):
        admin_uid = 999003
        token = await tokens_mod.generate_token(
            manager_id=admin_uid,
            role="Наглядач",
            expires_in_hours=24,
            extra_data={"multi_use": True, "used_by_list": []}
        )

        # 1. Пошук токена у нижньому регістрі з пробілами
        lower_token = f"  {token.lower()} \n"
        data_lower = await tokens_mod.get_token_data(lower_token)
        self.assertEqual(data_lower.get("status"), "ok")
        self.assertEqual(data_lower.get("role"), "Наглядач")

        # 2. Використання токена у нижньому регістрі
        used_ok = await tokens_mod.use_token(lower_token, 777001)
        self.assertTrue(used_ok)

        # 3. Перевірка оновлення
        data_after = await tokens_mod.get_token_data(token)
        self.assertIn(777001, data_after["extra_data"]["used_by_list"])


    async def test_access_middleware_allows_fsm_registration_and_observers(self):
        from bot.middleware import AccessMiddleware
        from unittest.mock import AsyncMock, MagicMock
        from aiogram.types import Message, User

        middleware = AccessMiddleware()
        handler = AsyncMock(return_value="OK")

        # 1. Новий невідомий користувач відправляє своє ПІБ без FSM стану -> блокується
        user_new = User(id=999888, is_bot=False, first_name="Петро")
        msg_without_state = MagicMock(spec=Message)
        msg_without_state.from_user = user_new
        msg_without_state.text = "Петренко Петро Петрович"
        msg_without_state.answer = AsyncMock()

        res = await middleware(handler, msg_without_state, {"state": None})
        self.assertIsNone(res)
        msg_without_state.answer.assert_called_once()
        self.assertIn("Доступ обмежено", msg_without_state.answer.call_args[0][0])

        # 2. Новий невідомий користувач відправляє ПІБ з активним станом реєстрації -> ДОЗВОЛЕНО!
        handler.reset_mock()
        mock_state = MagicMock()
        mock_state.get_state = AsyncMock(return_value="RegistrationStates:waiting_for_full_name")

        res_fsm = await middleware(handler, msg_without_state, {"state": mock_state})
        self.assertEqual(res_fsm, "OK")
        handler.assert_called_once_with(msg_without_state, {"state": mock_state})

        # 3. Зареєстрований наглядач відправляє будь-яке повідомлення -> ДОЗВОЛЕНО!
        await managers_mod.add_observer(999888, "Петренко Петро", "petro")
        handler.reset_mock()
        res_obs = await middleware(handler, msg_without_state, {"state": None})
        self.assertEqual(res_obs, "OK")
        handler.assert_called_once()


if __name__ == "__main__":
    unittest.main()
