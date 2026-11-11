import unittest
import os
import aiosqlite
import tempfile
from unittest.mock import patch, AsyncMock, MagicMock

from database.news import get_matching_news_recipients
from database.surveys import get_matching_survey_recipients
from bot.menus.developer import _show_news_roles_selection, dev_news_toggle_role_handler


class TestNewsAdminRecipients(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "users.db")
        self.managers_db_path = os.path.join(self.temp_dir.name, "managers.db")

        # users.db
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    full_name TEXT,
                    username TEXT,
                    role TEXT,
                    status TEXT,
                    city TEXT,
                    shop TEXT
                )
            """)
            await db.execute("""
                INSERT INTO users (user_id, full_name, username, role, status, city, shop)
                VALUES
                    (101, 'Працівник Львів', 'worker_lviv', 'Працівник', 'Працівник', 'Львів', 'Пекарня 1'),
                    (102, 'Адмін 1', 'admin_user1', 'Адміністратор', NULL, 'Київ', NULL),
                    (103, 'Розробник 1', 'dev_user1', 'Developer', NULL, 'Рівне', NULL),
                    (104, 'Дев 2', 'dev_user2', 'Dev', NULL, NULL, NULL)
            """)
            await db.commit()

        # managers.db
        async with aiosqlite.connect(self.managers_db_path) as m_db:
            await m_db.execute("""
                CREATE TABLE IF NOT EXISTS managers (
                    uid INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    process TEXT,
                    city TEXT,
                    shops TEXT,
                    status TEXT
                )
            """)
            await m_db.execute("""
                INSERT INTO managers (uid, username, full_name, process, city, status)
                VALUES
                    (201, 'mgr_dev', 'Менеджер Дев', 'Developer', 'Київ', 'active'),
                    (202, 'mgr_admin', 'Менеджер Адмін', 'Адміністратор', 'Львів', 'active'),
                    (203, 'mgr_dev_fired', 'Звільнений Дев', 'Developer', 'Київ', 'fired')
            """)
            await m_db.commit()

        self.patch_mgr = patch("database.managers.MANAGERS_DB_PATH", self.managers_db_path)
        self.patch_mgr.start()

    async def asyncTearDown(self):
        self.patch_mgr.stop()
        self.temp_dir.cleanup()

    async def test_get_matching_survey_recipients_admin_role(self):
        """Перевіряє коректну вибірку адміністраторів з users.db, managers.db та MAIN_DEVELOPER_ID."""
        with patch("bot.config.MAIN_DEVELOPER_ID", 999999):
            recipients = await get_matching_survey_recipients(["Адміністратор"], db_path=self.db_path)

        # Повинні бути присутні: 102, 103, 104 (users.db), 201, 202 (managers.db), 999999 (MAIN_DEVELOPER_ID)
        self.assertIn(102, recipients)
        self.assertIn(103, recipients)
        self.assertIn(104, recipients)
        self.assertIn(201, recipients)
        self.assertIn(202, recipients)
        self.assertIn(999999, recipients)
        # Звичайний працівник не повинен потрапити
        self.assertNotIn(101, recipients)

    async def test_admin_recipients_with_city_filter(self):
        """Перевіряє, що адміністратори отримують новини незалежно від фільтра міста."""
        recipients = await get_matching_survey_recipients(["Адміністратор"], target_city="Львів", db_path=self.db_path)

        # Адміністратор з Києва (102) та Рівного (103) все одно повинні бути включені
        self.assertIn(102, recipients)
        self.assertIn(103, recipients)
        self.assertIn(201, recipients)
        self.assertIn(202, recipients)

    async def test_fired_admin_excluded_in_news(self):
        """Перевіряє, що звільнений менеджер (status='fired') виключається з розсилки новин."""
        recipients = await get_matching_news_recipients(["Адміністратор"], db_path=self.db_path)
        self.assertNotIn(203, recipients)

    async def test_news_roles_ui_contains_admin(self):
        """Перевіряє, що в меню вибору ролей для новин присутня кнопка 'Адміністратор'."""
        mock_cb = MagicMock()
        mock_cb.message = AsyncMock()
        mock_cb.message.photo = None
        mock_cb.message.edit_text = AsyncMock()
        mock_cb.message.edit_caption = AsyncMock()
        mock_cb.message.answer = AsyncMock()
        mock_cb.answer = AsyncMock()

        mock_state = MagicMock()
        mock_state.get_data = AsyncMock(return_value={"selected_roles": ["Працівник", "Адміністратор"]})

        await _show_news_roles_selection(mock_cb, mock_state)

        # Перевіряємо, що в reply_markup є кнопка для ролі 'Адміністратор'
        self.assertTrue(mock_cb.message.edit_text.called or mock_cb.message.answer.called)
        call_args = mock_cb.message.edit_text.call_args or mock_cb.message.answer.call_args
        args, kwargs = call_args
        reply_markup = kwargs.get("reply_markup")
        all_button_texts = [btn.text for row in reply_markup.inline_keyboard for btn in row]
        all_callbacks = [btn.callback_data for row in reply_markup.inline_keyboard for btn in row]

        self.assertTrue(any("Адміністратор" in t for t in all_button_texts))
        self.assertIn("dev_news_toggle_role:Адміністратор", all_callbacks)
        self.assertTrue(any("✅" in t and "Адміністратор" in t for t in all_button_texts))

    async def test_toggle_admin_role_handler(self):
        """Перевіряє успішне додавання/зняття прапорця 'Адміністратор' через handler."""
        mock_cb = MagicMock()
        mock_cb.from_user.id = 12345
        mock_cb.data = "dev_news_toggle_role:Адміністратор"
        mock_cb.answer = AsyncMock()
        mock_cb.message = AsyncMock()
        mock_cb.message.photo = None
        mock_cb.message.edit_text = AsyncMock()
        mock_cb.message.edit_caption = AsyncMock()
        mock_cb.message.answer = AsyncMock()

        mock_state = MagicMock()
        # Початковий стан без адміністратора
        mock_state.get_data = AsyncMock(return_value={"selected_roles": ["Працівник"]})
        mock_state.update_data = AsyncMock()

        with patch("bot.menus.developer._check_news_access", AsyncMock(return_value=True)):
            await dev_news_toggle_role_handler(mock_cb, mock_state)

        mock_state.update_data.assert_called_once_with(selected_roles=["Працівник", "Адміністратор"])
