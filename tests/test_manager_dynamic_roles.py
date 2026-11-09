import unittest
import asyncio
import aiosqlite

from database import DB_PATH
from database.positions import add_position, delete_position, get_position_by_name
from bot.constants import is_valid_role, is_valid_city
from bot.handlers import _validate_invite_payload
from bot.menus.manager import _get_manager_add_roles, _render_add_roles_keyboard, _get_manager_add_cities

class TestManagerDynamicRoles(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Ensure test position exists in DB
        self.test_role_name = "Формувальник листкового тіста"
        existing = await get_position_by_name(self.test_role_name)
        if not existing:
            self.created_pos_id = await add_position(self.test_role_name, days_count=5, territorial_type="ВВ")
        else:
            self.created_pos_id = existing["id"]

    async def asyncTearDown(self):
        try:
            if self.created_pos_id:
                await delete_position(self.created_pos_id)
        except Exception:
            pass

    async def test_get_manager_add_roles_includes_db_position(self):
        roles = await _get_manager_add_roles()
        self.assertIn(self.test_role_name, roles)
        self.assertNotIn("Керівник", roles)
        self.assertNotIn("Керівник Стажер", roles)

    def test_is_valid_role_accepts_db_position(self):
        self.assertTrue(is_valid_role(self.test_role_name))
        self.assertFalse(is_valid_role("НезрозумілаПосада12345"))

    def test_validate_invite_payload_accepts_db_position(self):
        valid, err = _validate_invite_payload(self.test_role_name, "Хмельницький")
        self.assertTrue(valid)
        self.assertIsNone(err)

    def test_render_add_roles_keyboard_pagination(self):
        sample_roles = [f"Посада {i}" for i in range(15)]
        
        # Page 0 (8 items per page)
        kb_page0 = _render_add_roles_keyboard(sample_roles, page=0, page_size=8)
        cbs_p0 = [btn.callback_data for row in kb_page0.inline_keyboard for btn in row]
        self.assertIn("add_role:0", cbs_p0)
        self.assertIn("add_role:7", cbs_p0)
        self.assertNotIn("add_role:8", cbs_p0)
        self.assertIn("add_role_page:1", cbs_p0)

        # Page 1
        kb_page1 = _render_add_roles_keyboard(sample_roles, page=1, page_size=8)
        cbs_p1 = [btn.callback_data for row in kb_page1.inline_keyboard for btn in row]
        self.assertIn("add_role:8", cbs_p1)
        self.assertIn("add_role:14", cbs_p1)
        self.assertIn("add_role_page:0", cbs_p1)

    def test_is_valid_city_handles_apostrophes_and_whitespace(self):
        self.assertTrue(is_valid_city("Хмельницький"))
        self.assertTrue(is_valid_city("Камʼянець-Подільський"))
        self.assertTrue(is_valid_city("Кам'янець-Подільський"))
        self.assertTrue(is_valid_city("Кам’янець-Подільський"))
        self.assertTrue(is_valid_city("  Хмельницький  "))
        self.assertTrue(is_valid_city("хмельницький"))
        self.assertFalse(is_valid_city(None))
        self.assertFalse(is_valid_city(""))
        self.assertFalse(is_valid_city("НеіснуючеМісто"))

    async def test_is_valid_city_accepts_db_city(self):
        test_city = "ТестовеМістоРегресія"
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT OR IGNORE INTO cities (name) VALUES (?)", (test_city,))
            await db.commit()

        try:
            self.assertTrue(is_valid_city(test_city))
            valid, err = _validate_invite_payload(self.test_role_name, test_city)
            self.assertTrue(valid)
            self.assertIsNone(err)
        finally:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("DELETE FROM cities WHERE name = ?", (test_city,))
                await db.commit()

    async def test_get_manager_add_cities_returns_cities(self):
        cities = await _get_manager_add_cities()
        self.assertIn("Хмельницький", cities)

if __name__ == "__main__":
    unittest.main()
