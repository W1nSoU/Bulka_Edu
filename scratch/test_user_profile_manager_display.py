import unittest
import asyncio
from unittest.mock import AsyncMock, MagicMock
import aiosqlite

from database import DB_PATH
from database.managers import MANAGERS_DB_PATH, init_managers_db, add_manager, delete_manager_by_uid
from database.schema import init_db as init_users_db
from database.users import register_user, set_intern_extra, delete_user
from database.hr import init_hr_db, add_hr, remove_hr
from bot.utils.manager import get_manager_display_title
from bot.handlers import profile_handler_new_message


class TestUserProfileManagerDisplay(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_users_db()
        await init_managers_db()
        await init_hr_db()
        
        self.mgr_uid = 999111001
        self.terr_uid = 999111002
        self.admin_uid = 999111003
        self.user_uid = 999111004
        
        # Очищення перед тестом
        await delete_manager_by_uid(self.mgr_uid)
        await delete_manager_by_uid(self.terr_uid)
        await delete_manager_by_uid(self.admin_uid)
        await delete_user(self.user_uid)
        await delete_user(self.mgr_uid)
        await delete_user(self.terr_uid)
        await delete_user(self.admin_uid)
        await remove_hr(self.admin_uid)

    async def asyncTearDown(self):
        await delete_manager_by_uid(self.mgr_uid)
        await delete_manager_by_uid(self.terr_uid)
        await delete_manager_by_uid(self.admin_uid)
        await delete_user(self.user_uid)
        await delete_user(self.mgr_uid)
        await delete_user(self.terr_uid)
        await delete_user(self.admin_uid)
        await remove_hr(self.admin_uid)

    async def test_unassigned_manager(self):
        mock_bot = MagicMock()
        title = await get_manager_display_title(mock_bot, None)
        self.assertEqual(title, "Не призначено")
        
        title_zero = await get_manager_display_title(mock_bot, 0)
        self.assertEqual(title_zero, "Не призначено")

    async def test_regular_manager_display(self):
        mock_bot = MagicMock()
        await add_manager(
            uid=self.mgr_uid,
            username="mgr_taras",
            full_name="Тарас Керівниченко",
            process="Керівник",
            shops=["вул. Хрещатик, 1"],
            city="Київ"
        )
        title = await get_manager_display_title(mock_bot, self.mgr_uid)
        # Суворо ПІБ без приписки ролі
        self.assertEqual(title, "Тарас Керівниченко")

    async def test_territorial_display(self):
        mock_bot = MagicMock()
        await add_manager(
            uid=self.terr_uid,
            username="terr_olena",
            full_name="Олена Територіальна",
            process="Територіал",
            city="Київ",
            territorial_type="ТЗ"
        )
        title = await get_manager_display_title(mock_bot, self.terr_uid)
        # ПІБ з суфіксом (Територіал)
        self.assertEqual(title, "Олена Територіальна (Територіал)")

    async def test_admin_display(self):
        mock_bot = MagicMock()
        # Додаємо як Developer/HR
        await add_hr(self.admin_uid, username="admin_ivan", full_name="Іван Адміністратор", role="Developer")
        await register_user(self.admin_uid, username="admin_ivan", full_name="Іван Адміністратор")
        
        title = await get_manager_display_title(mock_bot, self.admin_uid)
        # ПІБ з суфіксом (Адміністратор)
        self.assertEqual(title, "Іван Адміністратор (Адміністратор)")

    async def test_telegram_fallback_when_name_empty(self):
        # Керівник створений без імені в БД
        await add_manager(
            uid=self.mgr_uid,
            username="tg_user",
            full_name="",
            process="Керівник",
            city="Київ"
        )
        
        mock_bot = MagicMock()
        mock_chat = MagicMock()
        mock_chat.first_name = "Петро"
        mock_chat.last_name = "Телеграмний"
        mock_chat.full_name = "Петро Телеграмний"
        mock_chat.username = "petro_tg"
        mock_bot.get_chat = AsyncMock(return_value=mock_chat)
        
        title = await get_manager_display_title(mock_bot, self.mgr_uid)
        self.assertEqual(title, "Петро Телеграмний")
        
        # Перевіряємо, що ім'я збереглося в базі
        async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
            cursor = await db.execute("SELECT full_name FROM managers WHERE uid = ?", (self.mgr_uid,))
            row = await cursor.fetchone()
            self.assertEqual(row[0], "Петро Телеграмний")

    async def test_profile_handler_integration(self):
        # Створюємо територіала
        await add_manager(
            uid=self.terr_uid,
            username="terr_olena",
            full_name="Олена Територіальна",
            process="Територіал",
            city="Київ",
            territorial_type="ТЗ"
        )
        # Реєструємо користувача з цим керівником
        await register_user(self.user_uid, username="test_bulka", full_name="Тестова Булочка")
        await set_intern_extra(self.user_uid, self.terr_uid, "Касир", "Київ", shop="вул. Тестова, 1")
        
        # Мокаємо callback
        callback = MagicMock()
        callback.from_user.id = self.user_uid
        callback.from_user.full_name = "Тестова Булочка"
        callback.message = MagicMock()
        callback.message.photo = None
        callback.message.edit_text = AsyncMock()
        callback.message.answer_photo = AsyncMock()
        callback.bot = MagicMock()
        callback.bot.get_user_profile_photos = AsyncMock(return_value=MagicMock(photos=[]))
        
        await profile_handler_new_message(callback)
        
        # Перевіряємо, що в повідомленні профіль містить ПІБ (Територіал)
        # Оскільки аватарки використовують answer_photo або edit_text/caption:
        calls = callback.message.answer_photo.call_args_list
        found = False
        for c in calls:
            caption = c.kwargs.get("caption") or ""
            if "🔹 Керівник: <b>Олена Територіальна (Територіал)</b>" in caption:
                found = True
                break
        self.assertTrue(found, f"Expected caption with 'Олена Територіальна (Територіал)' in calls: {calls}")


if __name__ == "__main__":
    unittest.main()
