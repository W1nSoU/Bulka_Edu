import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.types import InlineKeyboardMarkup

from bot.handlers import remind_topic_global_callback
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
