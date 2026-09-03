import asyncio
import os
import sys
import unittest
import json
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bot.menus.developer import (
    developer_request_add_manager,
    developer_process_add_manager_city,
    developer_process_shop_selection,
    developer_finish_shop_selection,
    developer_mgr_link_transfer_choice,
    developer_add_territorial_start,
    developer_add_territorial_city,
    developer_add_territorial_type,
    developer_add_territorial_finish,
    _build_managers_team_view,
)
from database.schema import init_db
from database.managers import (
    init_managers_db,
    add_manager,
    delete_manager_by_uid,
    get_manager_by_uid,
    reassign_city_managers_to_territorial,
    transfer_users_by_shops,
)
from database.tokens import (
    init_tokens_db,
    generate_token,
    get_token_data,
)
from bot.handlers import process_registration_full_name, RegistrationStates
import aiosqlite
from database import DB_PATH
from database.tokens import TOKENS_DB_PATH
from database.managers import MANAGERS_DB_PATH

class TestManagerTerritorialInviteLinks(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        await init_managers_db()
        await init_tokens_db()
        self.created_tokens = []
        self.test_uids = []

    async def asyncTearDown(self):
        # Cleanup tokens
        async with aiosqlite.connect(TOKENS_DB_PATH) as db:
            for t in self.created_tokens:
                await db.execute("DELETE FROM tokens WHERE token = ?", (t,))
            await db.commit()

        # Cleanup users & managers
        async with aiosqlite.connect(DB_PATH) as db:
            for u in self.test_uids:
                await db.execute("DELETE FROM users WHERE user_id = ?", (u,))
            await db.commit()

        async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
            for u in self.test_uids:
                await db.execute("DELETE FROM managers WHERE uid = ?", (u,))
            await db.commit()

    async def test_manager_keyboard_has_add_button_for_admin_and_territorial(self):
        """Check button '➕ Додати керівника' in _build_managers_team_view for admin & territorial."""
        bot_mock = MagicMock()
        
        # Admin view
        _, kb_admin = await _build_managers_team_view(is_admin=True, is_territorial=False, user_id=999, page=0, bot=bot_mock)
        callbacks_admin = [b.callback_data for row in kb_admin.inline_keyboard for b in row]
        self.assertIn("dev_add_manager", callbacks_admin)

        # Territorial view
        _, kb_terr = await _build_managers_team_view(is_admin=False, is_territorial=True, user_id=999, page=0, bot=bot_mock)
        callbacks_terr = [b.callback_data for row in kb_terr.inline_keyboard for b in row]
        self.assertIn("dev_add_manager", callbacks_terr)

    async def test_manager_invite_wizard_admin_flow(self):
        """Admin creates manager link: choose city -> select shops -> prompt transfer -> generate link."""
        admin_uid = 99911101
        self.test_uids.append(admin_uid)

        mock_cb = MagicMock()
        mock_cb.from_user.id = admin_uid
        mock_cb.message = MagicMock()
        mock_cb.message.photo = None
        mock_cb.message.edit_text = AsyncMock()
        mock_cb.message.edit_reply_markup = AsyncMock()
        mock_cb.message.answer = AsyncMock()
        mock_cb.answer = AsyncMock()

        mock_bot_user = MagicMock()
        mock_bot_user.username = "Bulka_Test_Bot"
        mock_cb.bot = MagicMock()
        mock_cb.bot.get_me = AsyncMock(return_value=mock_bot_user)

        state_data = {}
        mock_state = MagicMock()
        mock_state.clear = AsyncMock(side_effect=lambda: state_data.clear())
        mock_state.set_state = AsyncMock()
        mock_state.update_data = AsyncMock(side_effect=lambda **kwargs: state_data.update(kwargs))
        mock_state.get_data = AsyncMock(side_effect=lambda: state_data)

        # 1. Start as Admin
        with patch("bot.menus.developer._check_access", return_value=(True, True, False)):
            await developer_request_add_manager(mock_cb, mock_state)
            self.assertTrue(mock_cb.message.edit_text.called or mock_cb.message.answer.called)

            # 2. Pick city
            mock_cb.data = "dev_mgr_city_select:Кам'янець-Подільський"
            await developer_process_add_manager_city(mock_cb, mock_state)
            self.assertEqual(state_data.get("manager_city"), "Кам'янець-Подільський")

            # 3. Toggle shop 0
            mock_cb.data = "dev_mgr_shop_toggle:0"
            await developer_process_shop_selection(mock_cb, mock_state)
            selected = state_data.get("selected_shops", [])
            self.assertEqual(len(selected), 1)

            # 4. Finish selection with mock count > 0 -> should ask about transfer
            with patch("bot.menus.developer.count_users_in_shops", return_value=(2, 3)):
                mock_cb.message.edit_text.reset_mock()
                mock_cb.message.answer.reset_mock()
                await developer_finish_shop_selection(mock_cb, mock_state)
                
                # Verify transfer prompt was shown
                sent_text = (mock_cb.message.edit_text.call_args[0][0] 
                             if mock_cb.message.edit_text.called 
                             else mock_cb.message.answer.call_args[0][0])
                self.assertIn("Перевести їх під керівництво цього керівника", sent_text)

            # 5. Answer YES to transfer
            mock_cb.data = "dev_mgr_link_tr:yes"
            mock_cb.message.edit_text.reset_mock()
            mock_cb.message.answer.reset_mock()
            await developer_mgr_link_transfer_choice(mock_cb, mock_state)

            final_text = (mock_cb.message.edit_text.call_args[0][0]
                          if mock_cb.message.edit_text.called
                          else mock_cb.message.answer.call_args[0][0])
            self.assertIn("Посилання для запрошення Керівника створено!", final_text)
            self.assertIn("https://t.me/Bulka_Test_Bot?start=", final_text)
            self.assertIn("✅ Так", final_text)

            # Extract token from link
            start_param = final_text.split("?start=")[1].split("</code>")[0].strip()
            creator_id_str, token = start_param.split("-")
            self.assertEqual(int(creator_id_str), admin_uid)
            self.created_tokens.append(token)

            # Verify token payload in DB
            token_data = await get_token_data(token)
            self.assertIsNotNone(token_data)
            self.assertEqual(token_data["role"], "Керівник Стажер")
            self.assertEqual(token_data["city"], "Кам'янець-Подільський")
            self.assertEqual(token_data["transfer_on_reg"], 1)
            self.assertEqual(len(token_data["shops"]), 1)

    async def test_manager_invite_wizard_territorial_flow(self):
        """Territorial creates manager link: auto-detects city, skips city selection."""
        terr_uid = 99911102
        self.test_uids.append(terr_uid)
        await add_manager(terr_uid, "Територіал", full_name="Тест Територіал", city="Чернівці", territorial_type="ТЗ")

        mock_cb = MagicMock()
        mock_cb.from_user.id = terr_uid
        mock_cb.message = MagicMock()
        mock_cb.message.photo = None
        mock_cb.message.edit_text = AsyncMock()
        mock_cb.message.answer = AsyncMock()
        mock_cb.answer = AsyncMock()

        state_data = {}
        mock_state = MagicMock()
        mock_state.clear = AsyncMock(side_effect=lambda: state_data.clear())
        mock_state.set_state = AsyncMock()
        mock_state.update_data = AsyncMock(side_effect=lambda **kwargs: state_data.update(kwargs))
        mock_state.get_data = AsyncMock(side_effect=lambda: state_data)

        # 1. Territorial triggers add manager
        with patch("bot.menus.developer._check_access", return_value=(True, False, True)):
            await developer_request_add_manager(mock_cb, mock_state)
            self.assertEqual(state_data.get("manager_city"), "Чернівці")

    async def test_territorial_invite_wizard_admin_flow_and_non_admin_blocking(self):
        """Admin creates territorial link; non-admin is rejected."""
        admin_uid = 99911103
        terr_candidate_uid = 99911104
        self.test_uids.extend([admin_uid, terr_candidate_uid])

        mock_cb = MagicMock()
        mock_cb.from_user.id = admin_uid
        mock_cb.message = MagicMock()
        mock_cb.message.photo = None
        mock_cb.message.edit_text = AsyncMock()
        mock_cb.message.answer = AsyncMock()
        mock_cb.answer = AsyncMock()

        mock_bot_user = MagicMock()
        mock_bot_user.username = "Bulka_Test_Bot"
        mock_cb.bot = MagicMock()
        mock_cb.bot.get_me = AsyncMock(return_value=mock_bot_user)

        state_data = {}
        mock_state = MagicMock()
        mock_state.clear = AsyncMock(side_effect=lambda: state_data.clear())
        mock_state.set_state = AsyncMock()
        mock_state.update_data = AsyncMock(side_effect=lambda **kwargs: state_data.update(kwargs))
        mock_state.get_data = AsyncMock(side_effect=lambda: state_data)

        # 1. Non-admin (e.g. territorial) tries to create territorial link -> BLOCKED
        with patch("bot.menus.developer._check_access", return_value=(True, False, True)):
            await developer_add_territorial_start(mock_cb, mock_state)
            mock_cb.answer.assert_called_with("Ця дія доступна лише Адміністратору.", show_alert=True)

        # 2. Admin creates territorial link
        with patch("bot.menus.developer._check_access", return_value=(True, True, False)), \
             patch("bot.menus.developer.get_all_cities", return_value=[{"id": 1, "name": "Хмельницький"}]), \
             patch("bot.menus.developer.get_city_by_id", return_value={"id": 1, "name": "Хмельницький"}):
            
            mock_cb.answer.reset_mock()
            await developer_add_territorial_start(mock_cb, mock_state)
            self.assertTrue(mock_cb.message.edit_text.called or mock_cb.message.answer.called)

            # Choose city
            mock_cb.data = "dev_t_city:1"
            await developer_add_territorial_city(mock_cb, mock_state)
            self.assertEqual(state_data.get("t_city"), "Хмельницький")

            # Choose type: ТЗ
            mock_cb.data = "dev_t_type:ТЗ"
            await developer_add_territorial_type(mock_cb, mock_state)
            self.assertEqual(state_data.get("t_type"), "ТЗ")

            # Transfer yes
            mock_cb.data = "dev_t_transfer:yes"
            mock_cb.message.edit_text.reset_mock()
            mock_cb.message.answer.reset_mock()
            await developer_add_territorial_finish(mock_cb, mock_state)

            final_text = (mock_cb.message.edit_text.call_args[0][0]
                          if mock_cb.message.edit_text.called
                          else mock_cb.message.answer.call_args[0][0])
            self.assertIn("Посилання для запрошення Територіала створено!", final_text)
            self.assertIn("ТЗ", final_text)
            self.assertIn("✅ Так", final_text)

            start_param = final_text.split("?start=")[1].split("</code>")[0].strip()
            creator_id_str, token = start_param.split("-")
            self.assertEqual(int(creator_id_str), admin_uid)
            self.created_tokens.append(token)

            token_data = await get_token_data(token)
            self.assertEqual(token_data["role"], "Територіал")
            self.assertEqual(token_data["city"], "Хмельницький")
            self.assertEqual(token_data["transfer_on_reg"], 1)
            self.assertEqual(token_data["extra_data"].get("territorial_type"), "ТЗ")

    async def test_territorial_registration_auto_transfers_managers(self):
        """When new territorial completes registration, city managers are auto-reassigned if transfer_on_reg=1."""
        creator_id = 99911105
        new_terr_uid = 99911106
        test_mgr_uid = 99911107
        self.test_uids.extend([creator_id, new_terr_uid, test_mgr_uid])

        # Existing manager in Тернопіль currently attached to creator_id
        await add_manager(test_mgr_uid, "Керівник", full_name="Старий Керівник", city="Тернопіль", shops=["Т01"], responsible_uid=creator_id)

        # Generate token for Territorial with transfer_on_reg=1
        token = await generate_token(
            manager_id=creator_id,
            role="Територіал",
            city="Тернопіль",
            expires_in_hours=24,
            extra_data={"territorial_type": "ТЗ", "transfer_on_reg": 1},
            transfer_on_reg=1
        )
        self.created_tokens.append(token)

        mock_msg = MagicMock()
        mock_msg.from_user.id = new_terr_uid
        mock_msg.from_user.username = "new_terr_user"
        mock_msg.text = "Новий Територіал Петрович"
        mock_msg.answer = AsyncMock()
        mock_msg.bot = MagicMock()
        mock_msg.bot.send_message = AsyncMock()

        mock_state = MagicMock()
        mock_state.get_data = AsyncMock(return_value={
            "reg_role": "Територіал",
            "reg_city": "Тернопіль",
            "reg_shop": None,
            "reg_shops": [],
            "reg_manager_id": creator_id,
            "reg_token": token,
            "reg_extra_data": {"territorial_type": "ТЗ", "transfer_on_reg": 1},
            "reg_transfer_on_reg": 1
        })
        mock_state.clear = AsyncMock()

        with patch("bot.handlers.show_developer_main_menu", new_callable=AsyncMock) as mock_panel:
            await process_registration_full_name(mock_msg, mock_state)

        # Check territorial is in DB
        terr_mgr = await get_manager_by_uid(new_terr_uid)
        self.assertIsNotNone(terr_mgr)
        self.assertEqual(terr_mgr["process"], "Територіал")
        self.assertEqual(terr_mgr["territorial_type"], "ТЗ")
        self.assertEqual(terr_mgr["city"], "Тернопіль")

        # Check old manager in Ternopil now has responsible_uid == new_terr_uid
        mgr = await get_manager_by_uid(test_mgr_uid)
        self.assertEqual(mgr["responsible_uid"], new_terr_uid)

        # Check creator received notification
        mock_msg.bot.send_message.assert_called()
        notif_text = mock_msg.bot.send_message.call_args[0][1]
        self.assertIn("Територіал зареєструвався!", notif_text)
        self.assertIn("ТЗ", notif_text)

    async def test_manager_registration_auto_transfers_users(self):
        """When new manager completes registration, shop users are auto-reassigned if transfer_on_reg=1."""
        creator_id = 99911108
        new_mgr_uid = 99911109
        subordinate_uid = 99911110
        self.test_uids.extend([creator_id, new_mgr_uid, subordinate_uid])

        # Create subordinate user in store 'Б01' attached to creator_id
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT OR REPLACE INTO users 
                   (user_id, username, full_name, role, status, city, shop, manager_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (subordinate_uid, "sub_user", "Підлеглий Працівник", "Бариста", "Працює", "Рівне", "Б01", creator_id)
            )
            await db.commit()

        # Generate manager token for 'Б01' in Рівне with transfer_on_reg=1
        token = await generate_token(
            manager_id=creator_id,
            role="Керівник Стажер",
            city="Рівне",
            shop=["Б01"],
            expires_in_hours=24,
            extra_data={"shops": ["Б01"], "responsible_uid": creator_id, "transfer_on_reg": 1},
            transfer_on_reg=1
        )
        self.created_tokens.append(token)

        mock_msg = MagicMock()
        mock_msg.from_user.id = new_mgr_uid
        mock_msg.from_user.username = "new_mgr_user"
        mock_msg.text = "Новий Керівник Іванович"
        mock_msg.answer = AsyncMock()
        mock_msg.bot = MagicMock()
        mock_msg.bot.send_message = AsyncMock()

        mock_state = MagicMock()
        mock_state.get_data = AsyncMock(return_value={
            "reg_role": "Керівник",
            "reg_city": "Рівне",
            "reg_shop": "Б01",
            "reg_shops": ["Б01"],
            "reg_manager_id": creator_id,
            "reg_token": token,
            "reg_extra_data": {"shops": ["Б01"], "responsible_uid": creator_id, "transfer_on_reg": 1},
            "reg_transfer_on_reg": 1
        })
        mock_state.clear = AsyncMock()

        with patch("bot.handlers.show_student_main_menu", new_callable=AsyncMock) as mock_menu:
            await process_registration_full_name(mock_msg, mock_state)

        # Check new manager is in DB
        mgr = await get_manager_by_uid(new_mgr_uid)
        self.assertIsNotNone(mgr)
        self.assertEqual(mgr["process"], "Керівник Стажер")
        self.assertEqual(mgr["city"], "Рівне")
        shops = json.loads(mgr["shops"]) if isinstance(mgr["shops"], str) else mgr["shops"]
        self.assertIn("Б01", shops)

        # Check subordinate user was transferred to new manager!
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT manager_id FROM users WHERE user_id = ?", (subordinate_uid,)) as cursor:
                row = await cursor.fetchone()
                self.assertEqual(row[0], new_mgr_uid)

        # Check creator was notified
        mock_msg.bot.send_message.assert_called()
        notif_text = mock_msg.bot.send_message.call_args[0][1]
        self.assertIn("Керівник зареєструвався!", notif_text)

if __name__ == "__main__":
    unittest.main()
