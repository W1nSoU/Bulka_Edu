import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import aiosqlite

import bot.menus.manager as mgr_menu
import bot.handlers as handlers
import database.positions as positions_db
import database.users as users_db


class RoleGuardsAndSearchTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "users.db")
        self._orig_users_db = users_db.DB_PATH
        self._orig_pos_db = positions_db.DB_PATH
        users_db.DB_PATH = self.db_path
        positions_db.DB_PATH = self.db_path

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    days_count INTEGER DEFAULT 5,
                    territorial_type TEXT DEFAULT 'ТЗ',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE users (
                    user_id INTEGER PRIMARY KEY,
                    full_name TEXT,
                    username TEXT,
                    role TEXT,
                    city TEXT,
                    shop TEXT,
                    status TEXT
                )
                """
            )
            await db.commit()

    async def asyncTearDown(self):
        users_db.DB_PATH = self._orig_users_db
        positions_db.DB_PATH = self._orig_pos_db
        self.tmpdir.cleanup()

    async def test_manager_cannot_see_or_assign_admin_or_developer(self):
        fake_positions = [
            {"name": "Старший продавець"},
            {"name": "Адміністратор"},
            {"name": "Developer"},
            {"name": "dev"},
            {"name": "Керівник"},
            {"name": "Наглядач"},
            {"name": "Територіал"},
            {"name": "HR"},
            {"name": "Продавець-приймальник"},
        ]
        with patch("database.positions.get_all_positions", new=AsyncMock(return_value=fake_positions)):
            roles = await mgr_menu._get_manager_add_roles()
            self.assertEqual(roles, ["Старший продавець", "Продавець-приймальник"])

        for forbidden in ("Адміністратор", "адміністратор", "Developer", "developer", "Dev", "Керівник", "HR", ""):
            self.assertTrue(mgr_menu.is_forbidden_manager_assign_role(forbidden))
        self.assertFalse(mgr_menu.is_forbidden_manager_assign_role("Старший продавець"))

    def test_invite_payload_rejects_system_admin_and_developer_roles(self):
        for role in ("Адміністратор", "Developer", "Dev", "HR"):
            ok, err = handlers._validate_invite_payload(role, "Хмельницький")
            self.assertFalse(ok)
            self.assertIn("Системні ролі", err)

    async def test_add_position_rejects_reserved_system_roles(self):
        for bad_name in ("Адміністратор", "Developer", "dev", "Наглядач", "Територіал", "HR"):
            with self.assertRaises(ValueError):
                await positions_db.add_position(bad_name)

        pid = await positions_db.add_position("Старший продавець", days_count=5, territorial_type="ТЗ")
        self.assertIsNotNone(pid)

    async def test_cyrillic_case_and_word_order_user_search(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO users VALUES (5382469891, 'ЛИСАК ІРИНА ВІКТОРІВНА', 'Irunalysak', 'Старший продавець', 'Камʼянець-Подільський', 'B-16', 'Стажер')"
            )
            await db.commit()

        # Lowercase Cyrillic, mixed case, reversed word order, Latin I/i
        for query in (
            "лисак ірина вікторівна",
            "Лисак Ірина",
            "Ірина Лисак",
            "Лисак Iрина",
            "ЛИСАК",
        ):
            res = await users_db.get_users_by_full_name(query)
            self.assertEqual(len(res), 1, f"Failed for query={query!r}")
            self.assertEqual(res[0]["user_id"], 5382469891)


if __name__ == "__main__":
    unittest.main()
