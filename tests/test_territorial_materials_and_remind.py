import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.types import InlineKeyboardMarkup

from bot.handlers import (
    process_keyword_search,
    remind_role_select_callback,
    remind_topic_global_callback,
)
from bot.menus.developer import (
    _ensure_developer,
    developer_materials_view,
    developer_videos_view,
    developer_tests_view,
    developer_test_toggle,
)


class TestTerritorialMaterialsAndRemind(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot = AsyncMock()
        self.user = MagicMock(id=888, is_bot=False, first_name="Territorial Manager")

    @patch("bot.handlers.is_hr_user", new_callable=AsyncMock)
    @patch("bot.handlers.is_developer_user", new_callable=AsyncMock)
    @patch("bot.handlers.is_observer_user", new_callable=AsyncMock)
    @patch("bot.handlers.is_manager_user", new_callable=AsyncMock)
    @patch("bot.handlers.is_territorial_user", new_callable=AsyncMock)
    @patch("bot.handlers.get_searchable_roles", new_callable=AsyncMock)
    async def test_territorial_can_access_remind_topic_global(
        self, mock_roles, mock_is_terr, mock_is_mgr, mock_is_obs, mock_is_dev, mock_is_hr
    ):
        mock_is_hr.return_value = False
        mock_is_dev.return_value = False
        mock_is_obs.return_value = False
        mock_is_mgr.return_value = False
        mock_is_terr.return_value = True
        mock_roles.return_value = ["Бариста", "Касир"]

        cb = AsyncMock()
        cb.from_user = self.user
        cb.message = AsyncMock()
        cb.message.photo = None

        state = AsyncMock()
        state.update_data = AsyncMock()

        await remind_topic_global_callback(cb, state)

        # Ensure no alert error was shown
        for call in cb.answer.call_args_list:
            if call.kwargs.get("show_alert"):
                self.fail(f"Unexpected alert shown: {call}")

        # Check that message was updated with options and back button to dev_main_study
        cb.message.edit_text.assert_called_once()
        _, kwargs = cb.message.edit_text.call_args
        kb: InlineKeyboardMarkup = kwargs.get("reply_markup")
        all_cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
        self.assertIn("dev_main_study", all_cbs)

    @patch("bot.menus.developer.is_developer_user", new_callable=AsyncMock)
    @patch("bot.menus.developer.is_observer_user", new_callable=AsyncMock)
    @patch("bot.menus.developer.is_territorial_user", new_callable=AsyncMock)
    async def test_ensure_developer_allows_territorial_when_flagged(
        self, mock_is_terr, mock_is_obs, mock_is_dev
    ):
        mock_is_dev.return_value = False
        mock_is_obs.return_value = False
        mock_is_terr.return_value = True

        cb = AsyncMock()
        cb.from_user = self.user

        # Without flag -> False
        res_no = await _ensure_developer(cb, allow_territorial=False)
        self.assertFalse(res_no)

        # With flag -> True
        res_yes = await _ensure_developer(cb, allow_territorial=True)
        self.assertTrue(res_yes)

    @patch("bot.menus.developer.is_developer_user", new_callable=AsyncMock)
    @patch("bot.menus.developer.is_observer_user", new_callable=AsyncMock)
    @patch("bot.menus.developer.is_territorial_user", new_callable=AsyncMock)
    @patch("bot.menus.developer.get_material_by_role_day_type", new_callable=AsyncMock)
    @patch("bot.menus.developer._edit_or_answer", new_callable=AsyncMock)
    async def test_materials_view_is_readonly_for_territorial(
        self, mock_edit, mock_get_mat, mock_is_terr, mock_is_obs, mock_is_dev
    ):
        mock_is_dev.return_value = False
        mock_is_obs.return_value = False
        mock_is_terr.return_value = True
        mock_get_mat.return_value = {"id": 1, "content": "Текст уроку", "resource_url": None}

        cb = AsyncMock()
        cb.from_user = self.user
        cb.data = "dev_mat_type|text"

        state = AsyncMock()
        state.get_data.return_value = {"edit_role": "Бариста", "edit_day": 1}

        await developer_materials_view(cb, state)

        self.assertTrue(mock_edit.called)
        _, kwargs = mock_edit.call_args
        kb: InlineKeyboardMarkup = kwargs.get("reply_markup")
        all_button_texts = [b.text for row in kb.inline_keyboard for b in row]

        # Buttons for edit/delete/complement must NOT be present
        self.assertNotIn("➕ Додати навчання", all_button_texts)
        self.assertNotIn("➕ Доповнити", all_button_texts)
        self.assertNotIn("🔄 Змінити діапазон сторінок", all_button_texts)
        # Read-only buttons should be present
        self.assertIn("🔍 Повний перегляд", all_button_texts)
        self.assertIn("⬅️ Назад", all_button_texts)

    @patch("bot.menus.developer.is_developer_user", new_callable=AsyncMock)
    @patch("bot.menus.developer.is_observer_user", new_callable=AsyncMock)
    @patch("bot.menus.developer.is_territorial_user", new_callable=AsyncMock)
    @patch("bot.menus.developer.get_material_by_role_day_type", new_callable=AsyncMock)
    @patch("bot.menus.developer._edit_or_answer", new_callable=AsyncMock)
    async def test_videos_view_is_readonly_for_territorial(
        self, mock_edit, mock_get_mat, mock_is_terr, mock_is_obs, mock_is_dev
    ):
        mock_is_dev.return_value = False
        mock_is_obs.return_value = False
        mock_is_terr.return_value = True
        mock_get_mat.return_value = {"id": 2, "content": '["video_file_id_1"]'}

        cb = AsyncMock()
        cb.from_user = self.user
        cb.data = "dev_video_day|1"

        state = AsyncMock()
        state.get_data.return_value = {"edit_video_role": "Бариста", "edit_video_role_index": 0}

        await developer_videos_view(cb, state)

        self.assertTrue(mock_edit.called)
        _, kwargs = mock_edit.call_args
        kb: InlineKeyboardMarkup = kwargs.get("reply_markup")
        all_button_texts = [b.text for row in kb.inline_keyboard for b in row]

        self.assertNotIn("✏️ Редагувати", all_button_texts)
        self.assertIn("⬅️ Назад", all_button_texts)

    @patch("bot.menus.developer.is_developer_user", new_callable=AsyncMock)
    @patch("bot.menus.developer.is_observer_user", new_callable=AsyncMock)
    @patch("bot.menus.developer.is_territorial_user", new_callable=AsyncMock)
    @patch("bot.menus.developer.get_test_by_role_and_day", new_callable=AsyncMock)
    @patch("bot.menus.developer._edit_or_answer", new_callable=AsyncMock)
    async def test_tests_view_is_readonly_for_territorial(
        self, mock_edit, mock_get_test, mock_is_terr, mock_is_obs, mock_is_dev
    ):
        mock_is_dev.return_value = False
        mock_is_obs.return_value = False
        mock_is_terr.return_value = True
        mock_get_test.return_value = {"id": 3, "content": "[]", "is_enabled": 1}

        cb = AsyncMock()
        cb.from_user = self.user
        cb.data = "dev_test_day|1|0"

        state = AsyncMock()
        state.get_data.return_value = {"test_role": "Бариста", "test_role_index": 0}

        await developer_tests_view(cb, state, day=1, role_index=0)

        self.assertTrue(mock_edit.called)
        _, kwargs = mock_edit.call_args
        kb: InlineKeyboardMarkup = kwargs.get("reply_markup")
        all_button_texts = [b.text for row in kb.inline_keyboard for b in row]

        self.assertNotIn("✏️ Редагувати", all_button_texts)
        self.assertNotIn("🔴 Вимкнути тест", all_button_texts)
        self.assertNotIn("🟢 Увімкнути тест", all_button_texts)
        self.assertIn("⬅️ Назад", all_button_texts)

    @patch("bot.menus.developer.is_developer_user", new_callable=AsyncMock)
    @patch("bot.menus.developer.is_observer_user", new_callable=AsyncMock)
    @patch("bot.menus.developer.is_territorial_user", new_callable=AsyncMock)
    @patch("bot.menus.developer.get_material_by_role_day_type", new_callable=AsyncMock)
    @patch("bot.menus.developer._edit_or_answer", new_callable=AsyncMock)
    async def test_photos_view_is_readonly_for_territorial(
        self, mock_edit, mock_get_mat, mock_is_terr, mock_is_obs, mock_is_dev
    ):
        from bot.menus.developer import developer_photos_view
        mock_is_dev.return_value = False
        mock_is_obs.return_value = False
        mock_is_terr.return_value = True
        mock_get_mat.return_value = {"id": 4, "content": '["photo_fid_1"]'}

        cb = AsyncMock()
        cb.from_user = self.user
        cb.data = "dev_photo_day|1"

        state = AsyncMock()
        state.get_data.return_value = {"edit_photo_role": "Бариста", "edit_photo_role_index": 0}

        await developer_photos_view(cb, state)

        self.assertTrue(mock_edit.called)
        _, kwargs = mock_edit.call_args
        kb: InlineKeyboardMarkup = kwargs.get("reply_markup")
        all_button_texts = [b.text for row in kb.inline_keyboard for b in row]

        self.assertNotIn("➕ Додати навчання", all_button_texts)
        self.assertIn("🔍 Повний перегляд", all_button_texts)
        self.assertIn("⬅️ Назад", all_button_texts)

    @patch("bot.menus.developer.is_developer_user", new_callable=AsyncMock)
    @patch("bot.menus.developer.is_observer_user", new_callable=AsyncMock)
    @patch("bot.menus.developer.is_territorial_user", new_callable=AsyncMock)
    async def test_territorial_cannot_toggle_test(
        self, mock_is_terr, mock_is_obs, mock_is_dev
    ):
        mock_is_dev.return_value = False
        mock_is_obs.return_value = False
        mock_is_terr.return_value = True

        cb = AsyncMock()
        cb.from_user = self.user
        cb.data = "dev_test_toggle:disable"

        state = AsyncMock()

        await developer_test_toggle(cb, state)

        # Blocked with alert
        cb.answer.assert_called_with("⛔️ Доступ заборонено. Ви не маєте відповідних прав.", show_alert=True)

    @patch("bot.handlers.answer_remind_topic", new_callable=AsyncMock)
    @patch("bot.handlers.is_hr_user", new_callable=AsyncMock)
    @patch("bot.handlers.is_developer_user", new_callable=AsyncMock)
    @patch("bot.handlers.is_observer_user", new_callable=AsyncMock)
    @patch("bot.handlers.is_manager_user", new_callable=AsyncMock)
    @patch("bot.handlers.is_territorial_user", new_callable=AsyncMock)
    @patch("bot.handlers.get_searchable_roles", new_callable=AsyncMock)
    async def test_territorial_can_complete_remind_role_select_and_keyword_search(
        self,
        mock_roles,
        mock_is_terr,
        mock_is_mgr,
        mock_is_obs,
        mock_is_dev,
        mock_is_hr,
        mock_answer_remind,
    ):
        mock_is_hr.return_value = False
        mock_is_dev.return_value = False
        mock_is_obs.return_value = False
        mock_is_mgr.return_value = False
        mock_is_terr.return_value = True
        mock_roles.return_value = ["Бариста", "Касир"]
        mock_answer_remind.return_value = {
            "status": "ok",
            "text": "Стандарт приготування еспресо.",
            "used_network_fallback": False,
            "used_gpt": True,
            "matches": [],
        }

        state_store = {}

        async def _update_data(**kwargs):
            state_store.update(kwargs)

        async def _get_data():
            return dict(state_store)

        state = AsyncMock()
        state.update_data.side_effect = _update_data
        state.get_data.side_effect = _get_data
        state.set_state = AsyncMock()
        state.clear = AsyncMock()

        # 1. Вибір ролі для «Нагадати тему»
        cb = AsyncMock()
        cb.from_user = self.user
        cb.data = "remind_role_select:0"
        cb.message = AsyncMock()
        cb.message.photo = None

        await remind_role_select_callback(cb, state)
        self.assertEqual(state_store.get("mode"), "dev_test")
        self.assertEqual(state_store.get("role"), "Бариста")

        # 2. Відправка пошукового запиту територіалом
        msg = AsyncMock()
        msg.from_user = self.user
        msg.text = "Яка температура води для еспресо?"
        thinking_msg = AsyncMock()
        thinking_msg.delete = AsyncMock()
        msg.answer = AsyncMock(side_effect=[thinking_msg, AsyncMock()])

        await process_keyword_search(msg, state)

        mock_answer_remind.assert_awaited_once_with(
            question="Яка температура води для еспресо?",
            role_filter="Бариста",
            user_id=self.user.id,
        )
        sent_texts = [call.args[0] for call in msg.answer.call_args_list if call.args]
        self.assertFalse(any("Цей режим доступний лише для керівництва." in t for t in sent_texts))
        self.assertTrue(any("Стандарт приготування еспресо." in t for t in sent_texts))

        # Також перевіримо mode == "global" для територіала
        state_store["mode"] = "global"
        msg_global = AsyncMock()
        msg_global.from_user = self.user
        msg_global.text = "Глобальний запит"
        thinking_global = AsyncMock()
        thinking_global.delete = AsyncMock()
        msg_global.answer = AsyncMock(side_effect=[thinking_global, AsyncMock()])

        await process_keyword_search(msg_global, state)

        global_texts = [call.args[0] for call in msg_global.answer.call_args_list if call.args]
        self.assertFalse(any("Цей режим доступний лише HR" in t for t in global_texts))
        self.assertTrue(any("Стандарт приготування еспресо." in t for t in global_texts))
