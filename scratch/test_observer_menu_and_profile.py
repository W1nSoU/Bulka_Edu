import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ["BOT_TOKEN"] = "test_token"

from database.managers import (
    add_observer,
    delete_observer_by_uid,
    is_observer_user,
    get_all_managers
)
from database.users import get_all_users
from bot.menus.developer import (
    _admin_cho_keyboard,
    _admin_study_keyboard,
    _admin_other_keyboard,
    _get_dev_pagination_keyboard,
    _positions_keyboard,
    _cities_keyboard,
    _show_user_profile_card,
    developer_material_complement_menu,
    developer_test_toggle,
    developer_tests_edit_start,
    developer_tests_view,
    developer_videos_view,
    developer_video_edit_start,
    developer_photos_view,
    developer_photo_edit_start,
    dev_pos_add_start,
    dev_pos_toggle_type,
    dev_pos_edit_name_start,
    dev_pos_edit_days_start,
    dev_pos_view,
    dev_city_add_start,
    dev_city_edit_name_start,
    dev_city_delete,
    dev_city_delete_confirm,
    dev_city_view
)
from bot.handlers import profile_handler_router, observer_profile_handler


class TestObserverMenuAndProfile(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.obs_uid = 777123456
        self.admin_uid = 999111222
        # Clean up and add observer in DB
        await delete_observer_by_uid(self.obs_uid)
        await add_observer(
            uid=self.obs_uid,
            full_name="Тестовий Наглядач",
            username="test_observer",
            responsible_uid=self.admin_uid
        )

    async def asyncTearDown(self):
        await delete_observer_by_uid(self.obs_uid)

    async def test_keyboards_visibility(self):
        # 1. _admin_cho_keyboard
        kb_cho = _admin_cho_keyboard(False, False, is_territorial=False, is_observer=True)
        cho_texts = [btn.text for row in kb_cho.inline_keyboard for btn in row]
        self.assertIn("🛠 Інше", cho_texts)
        self.assertIn("👥 Команда Bulka", cho_texts)
        self.assertIn("📊 Аналітика", cho_texts)
        self.assertIn("📚 Навчальні матеріали", cho_texts)

        # 2. _admin_study_keyboard
        kb_study = _admin_study_keyboard(is_observer=True)
        study_texts = [btn.text for row in kb_study.inline_keyboard for btn in row]
        self.assertNotIn("📚 Змінити змісти", study_texts)
        self.assertIn("📝 Матеріали", study_texts)
        self.assertIn("🎥 Відео", study_texts)
        self.assertIn("🖼 Фото", study_texts)
        self.assertIn("📝 Тести", study_texts)

        # 3. _admin_other_keyboard
        kb_other = _admin_other_keyboard(is_observer=True)
        other_texts = [btn.text for row in kb_other.inline_keyboard for btn in row]
        self.assertNotIn("🎟 Токени", other_texts)
        self.assertNotIn("⚙️ Сервісні функції", other_texts)
        self.assertIn("💚 Health Status", other_texts)
        self.assertIn("👔 Посади", other_texts)
        self.assertIn("🏙 Міста", other_texts)

    async def test_material_pagination_and_complement_guard(self):
        # Pagination for observer: no edit / delete / add buttons, back button exists
        kb_pag = _get_dev_pagination_keyboard(
            current_page=0, total_pages=3, material_id=1, day=1,
            content_type="materials", is_observer=True
        )
        pag_texts = [btn.text for row in kb_pag.inline_keyboard for btn in row]
        self.assertNotIn("✏️ Виправити", pag_texts)
        self.assertNotIn("🗑 Видалити сторінку", pag_texts)
        self.assertNotIn("➕ Додати навчання", pag_texts)
        self.assertIn("⬅️ Назад", pag_texts)

        # Write guard on developer_material_complement_menu
        cb = MagicMock()
        cb.from_user.id = self.obs_uid
        cb.answer = AsyncMock()
        with patch("bot.menus.developer._ensure_developer", new=AsyncMock(return_value=True)):
            await developer_material_complement_menu(cb, MagicMock())
            cb.answer.assert_called_with("⛔️ У вас режим перегляду (тільки читання).", show_alert=True)

    async def test_tests_videos_photos_restrictions(self):
        cb = MagicMock()
        cb.from_user.id = self.obs_uid
        cb.answer = AsyncMock()
        state = MagicMock()
        state.get_data = AsyncMock(return_value={"test_role": "Касир", "test_day": 1, "test_role_index": 0})
        cb.data = "dev_test_toggle:enable"

        # Toggle test guard
        with patch("bot.menus.developer._ensure_developer", new=AsyncMock(return_value=True)):
            await developer_test_toggle(cb, state)
            cb.answer.assert_called_with("⛔️ У вас режим перегляду (тільки читання).", show_alert=True)

        # Edit test guard
        cb.answer.reset_mock()
        with patch("bot.menus.developer._ensure_developer", new=AsyncMock(return_value=True)):
            await developer_tests_edit_start(cb, state)
            cb.answer.assert_called_with("⛔️ У вас режим перегляду (тільки читання).", show_alert=True)

        # Video edit start guard
        cb.answer.reset_mock()
        with patch("bot.menus.developer._ensure_developer", new=AsyncMock(return_value=True)):
            await developer_video_edit_start(cb, state)
            cb.answer.assert_called_with("⛔️ У вас режим перегляду (тільки читання).", show_alert=True)

        # Photo edit start guard
        cb.answer.reset_mock()
        with patch("bot.menus.developer._ensure_developer", new=AsyncMock(return_value=True)):
            await developer_photo_edit_start(cb, state)
            cb.answer.assert_called_with("⛔️ У вас режим перегляду (тільки читання).", show_alert=True)

    async def test_positions_and_cities_restrictions(self):
        # Keyboard for positions
        kb_pos = _positions_keyboard([{"id": 1, "name": "Касир"}], page=1, is_observer=True)
        pos_texts = [btn.text for row in kb_pos.inline_keyboard for btn in row]
        self.assertNotIn("➕ Додати посаду", pos_texts)

        # Keyboard for cities
        kb_cities = _cities_keyboard([{"id": 1, "name": "Київ"}], page=1, is_observer=True)
        cities_texts = [btn.text for row in kb_cities.inline_keyboard for btn in row]
        self.assertNotIn("➕ Додати місто", cities_texts)

        # Guards on write actions
        cb = MagicMock()
        cb.from_user.id = self.obs_uid
        cb.answer = AsyncMock()

        for handler, args in [
            (dev_pos_add_start, [cb, MagicMock()]),
            (dev_pos_toggle_type, [cb]),
            (dev_pos_edit_name_start, [cb, MagicMock()]),
            (dev_pos_edit_days_start, [cb, MagicMock()]),
            (dev_city_add_start, [cb, MagicMock()]),
            (dev_city_edit_name_start, [cb, MagicMock()]),
            (dev_city_delete, [cb]),
            (dev_city_delete_confirm, [cb]),
        ]:
            cb.answer.reset_mock()
            await handler(*args)
            cb.answer.assert_called_with("⛔️ У вас режим перегляду (тільки читання).", show_alert=True)

    async def test_observer_profile(self):
        cb = MagicMock()
        cb.from_user.id = self.obs_uid
        cb.from_user.full_name = "Тестовий Наглядач"
        cb.from_user.username = "test_observer"
        cb.message = MagicMock()
        cb.message.photo = None
        cb.answer = AsyncMock()
        cb.bot = MagicMock()

        captured_text = []
        captured_markup = []

        async def mock_send_card(callback, photo_input, text, reply_markup=None):
            captured_text.append(text)
            captured_markup.append(reply_markup)

        with patch("bot.utils.avatar._send_or_edit_card_photo", side_effect=mock_send_card), \
             patch("bot.utils._send_or_edit_card_photo", side_effect=mock_send_card), \
             patch("bot.utils.get_user_avatar_input", new=AsyncMock(return_value=None)), \
             patch("bot.utils.avatar.get_user_avatar_input", new=AsyncMock(return_value=None)):
            await profile_handler_router(cb)

        self.assertTrue(len(captured_text) > 0)
        profile_text = captured_text[0]
        self.assertIn("Профіль наглядача BULKA", profile_text)
        self.assertIn("Посада: <b>Наглядач</b>", profile_text)
        self.assertIn("Загальна статистика мережі:", profile_text)

        profile_kb = captured_markup[0]
        btn_texts = [btn.text for row in profile_kb.inline_keyboard for btn in row]
        self.assertIn("📋 Меню наглядача", btn_texts)
        self.assertIn("🏠 В головне меню", btn_texts)


if __name__ == "__main__":
    unittest.main()
