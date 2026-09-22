import os
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch

import aiosqlite

from database.shops import (
    init_shops_db,
    get_cities_with_shops,
    get_shops_by_city,
    get_all_shops,
    get_shop_by_id,
    get_shop_by_name,
    count_users_in_shop,
    get_shop_manager,
    set_shop_manager,
    get_active_managers_for_city,
    add_shop,
    rename_shop,
    change_shop_city,
    delete_shop_and_transfer_users,
)


class TestShopsManagement(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "users.db")
        self.managers_db_path = os.path.join(self.test_dir, "managers.db")
        self.tokens_db_path = os.path.join(self.test_dir, "tokens.db")

        # Create basic tables in users.db
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    uid INTEGER PRIMARY KEY,
                    full_name TEXT,
                    role TEXT,
                    status TEXT,
                    city TEXT,
                    shop TEXT
                );
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS cities (
                    name TEXT PRIMARY KEY
                );
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS training_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_uid INTEGER,
                    shop TEXT
                );
            """)
            await db.commit()

        # Create basic tables in managers.db
        async with aiosqlite.connect(self.managers_db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS managers (
                    uid INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    process TEXT,
                    city TEXT,
                    shops TEXT,
                    status TEXT
                );
            """)
            await db.commit()

        # Create basic tables in tokens.db
        async with aiosqlite.connect(self.tokens_db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tokens (
                    token TEXT PRIMARY KEY,
                    role TEXT,
                    city TEXT,
                    shop TEXT
                );
            """)
            await db.commit()

        # Patch module paths
        self.patcher_db = patch("database.shops.DB_PATH", self.db_path)
        self.patcher_mgr = patch("database.shops.MANAGERS_DB_PATH", self.managers_db_path)
        self.patcher_tok = patch("database.shops.TOKENS_DB_PATH", self.tokens_db_path)

        self.patcher_db.start()
        self.patcher_mgr.start()
        self.patcher_tok.start()

    async def asyncTearDown(self):
        self.patcher_db.stop()
        self.patcher_mgr.stop()
        self.patcher_tok.stop()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    async def test_init_shops_db_auto_seed(self):
        """Auto-seed має заповнити таблицю shops з AVAILABLE_SHOPS, якщо таблиця порожня."""
        await init_shops_db()
        shops = await get_all_shops()
        self.assertGreater(len(shops), 0)

        # Перевірка наявності міст
        cities_with_counts = await get_cities_with_shops()
        city_names = [c["city"] for c in cities_with_counts]
        self.assertIn("Хмельницький", city_names)
        self.assertIn("Камʼянець-Подільський", city_names)

        # Повторний виклик не повинен дублювати записи
        count_before = len(shops)
        await init_shops_db()
        count_after = len(await get_all_shops())
        self.assertEqual(count_before, count_after)

    async def test_add_shop_validation_and_uniqueness(self):
        """Додавання валідує порожні поля та не дозволяє дублювати назви."""
        await init_shops_db()

        # Порожні значення
        ok, msg = await add_shop("", "Хмельницький")
        self.assertFalse(ok)
        ok, msg = await add_shop("B-99 Тестова", "")
        self.assertFalse(ok)

        # Успішне додавання
        ok, msg = await add_shop("B-99 вул. Тестова, 1", "Хмельницький")
        self.assertTrue(ok)
        created = await get_shop_by_name("B-99 вул. Тестова, 1")
        self.assertIsNotNone(created)
        self.assertEqual(created["city"], "Хмельницький")

        # Дублікат
        ok_dup, msg_dup = await add_shop("B-99 вул. Тестова, 1", "Хмельницький")
        self.assertFalse(ok_dup)
        self.assertIn("вже існує", msg_dup)

    async def test_rename_shop_cascade(self):
        """Перейменування магазину оновлює назву в shops, users, tokens, training_events та managers."""
        await init_shops_db()
        await add_shop("B-Original вул. Початкова, 10", "Хмельницький")
        shop = await get_shop_by_name("B-Original вул. Початкова, 10")
        shop_id = shop["id"]

        # Додаємо користувача, токен, івент та керівника з цим магазином
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO users (uid, full_name, status, city, shop) VALUES (101, 'Іван Тест', 'Працівник', 'Хмельницький', ?)",
                ("B-Original вул. Початкова, 10",)
            )
            await db.execute(
                "INSERT INTO training_events (user_uid, shop) VALUES (101, ?)",
                ("B-Original вул. Початкова, 10",)
            )
            await db.commit()

        async with aiosqlite.connect(self.tokens_db_path) as tdb:
            await tdb.execute(
                "INSERT INTO tokens (token, role, city, shop) VALUES ('tok123', 'worker', 'Хмельницький', ?)",
                ("B-Original вул. Початкова, 10",)
            )
            await tdb.commit()

        async with aiosqlite.connect(self.managers_db_path) as mdb:
            await mdb.execute(
                "INSERT INTO managers (uid, full_name, city, shops, status) VALUES (201, 'Керівник Петро', 'Хмельницький', ?, 'active')",
                (json.dumps(["B-Original вул. Початкова, 10", "Інший магазин"], ensure_ascii=False),)
            )
            await mdb.commit()

        # Виконуємо перейменування
        ok, msg = await rename_shop(shop_id, "B-Renamed вул. Оновлена, 20")
        self.assertTrue(ok)

        # Перевірка в shops
        updated_shop = await get_shop_by_id(shop_id)
        self.assertEqual(updated_shop["name"], "B-Renamed вул. Оновлена, 20")

        # Перевірка в users
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT shop FROM users WHERE uid = 101")
            user_shop = (await cursor.fetchone())[0]
            self.assertEqual(user_shop, "B-Renamed вул. Оновлена, 20")

        # Перевірка в tokens
        async with aiosqlite.connect(self.tokens_db_path) as tdb:
            cursor = await tdb.execute("SELECT shop FROM tokens WHERE token = 'tok123'")
            token_shop = (await cursor.fetchone())[0]
            self.assertEqual(token_shop, "B-Renamed вул. Оновлена, 20")

        # Перевірка в managers
        async with aiosqlite.connect(self.managers_db_path) as mdb:
            cursor = await mdb.execute("SELECT shops FROM managers WHERE uid = 201")
            mgr_shops = json.loads((await cursor.fetchone())[0])
            self.assertIn("B-Renamed вул. Оновлена, 20", mgr_shops)
            self.assertNotIn("B-Original вул. Початкова, 10", mgr_shops)

    async def test_change_shop_city(self):
        """Зміна міста оновлює shops, users та tokens."""
        await init_shops_db()
        await add_shop("B-MoveShop", "Хмельницький")
        shop = await get_shop_by_name("B-MoveShop")

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO users (uid, full_name, status, city, shop) VALUES (301, 'Олег', 'Стажер', 'Хмельницький', 'B-MoveShop')"
            )
            await db.commit()

        async with aiosqlite.connect(self.tokens_db_path) as tdb:
            await tdb.execute(
                "INSERT INTO tokens (token, city, shop) VALUES ('mvtok', 'Хмельницький', 'B-MoveShop')"
            )
            await tdb.commit()

        ok, msg = await change_shop_city(shop["id"], "Камʼянець-Подільський")
        self.assertTrue(ok)

        # Перевірка
        updated = await get_shop_by_id(shop["id"])
        self.assertEqual(updated["city"], "Камʼянець-Подільський")

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT city FROM users WHERE uid = 301")
            self.assertEqual((await cursor.fetchone())[0], "Камʼянець-Подільський")

        async with aiosqlite.connect(self.tokens_db_path) as tdb:
            cursor = await tdb.execute("SELECT city FROM tokens WHERE token = 'mvtok'")
            self.assertEqual((await cursor.fetchone())[0], "Камʼянець-Подільський")

    async def test_delete_shop_empty(self):
        """Видалення магазину без людей не вимагає вказання transfer_shop."""
        await init_shops_db()
        await add_shop("B-EmptyShop", "Хмельницький")
        shop = await get_shop_by_name("B-EmptyShop")

        ok, msg = await delete_shop_and_transfer_users(shop["id"])
        self.assertTrue(ok)
        self.assertIsNone(await get_shop_by_id(shop["id"]))

    async def test_delete_shop_with_users_requires_transfer(self):
        """Видалення магазину з користувачами переносить їх до вказаного нового магазину."""
        await init_shops_db()
        await add_shop("B-OldShop", "Хмельницький")
        await add_shop("B-TargetShop", "Хмельницький")
        old_shop = await get_shop_by_name("B-OldShop")

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO users (uid, full_name, status, city, shop) VALUES (401, 'Тарас', 'Працівник', 'Хмельницький', 'B-OldShop')"
            )
            await db.execute(
                "INSERT INTO users (uid, full_name, status, city, shop) VALUES (402, 'Марія', 'Стажер', 'Хмельницький', 'B-OldShop')"
            )
            await db.commit()

        # Без transfer_target повинно бути відхилено
        ok, msg = await delete_shop_and_transfer_users(old_shop["id"], None)
        self.assertFalse(ok)
        self.assertIn("Оберіть магазин для переведення", msg)

        # З валідним цільовим магазином
        ok, msg = await delete_shop_and_transfer_users(old_shop["id"], "B-TargetShop")
        self.assertTrue(ok)
        self.assertIn("2 працівників переведено", msg)

        # Перевірка що користувачі переведені в новий магазин
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT shop FROM users WHERE uid IN (401, 402)")
            shops = [r[0] for r in await cursor.fetchall()]
            self.assertEqual(shops, ["B-TargetShop", "B-TargetShop"])

    async def test_manager_assignment(self):
        """Прив'язка та відкріплення керівника від магазину."""
        await init_shops_db()
        await add_shop("B-ManagedShop", "Хмельницький")

        async with aiosqlite.connect(self.managers_db_path) as mdb:
            await mdb.execute(
                "INSERT INTO managers (uid, full_name, city, shops, status) VALUES (501, 'Олександр Бондар', 'Хмельницький', '[]', 'active')"
            )
            await mdb.execute(
                "INSERT INTO managers (uid, full_name, city, shops, status) VALUES (502, 'Сергій Коваль', 'Хмельницький', '[]', 'active')"
            )
            await mdb.commit()

        # Прив'язуємо до менеджера 501
        res = await set_shop_manager("B-ManagedShop", 501)
        self.assertTrue(res)

        mgr = await get_shop_manager("B-ManagedShop")
        self.assertIsNotNone(mgr)
        self.assertEqual(mgr["uid"], 501)

        # Переприв'язуємо до менеджера 502
        res2 = await set_shop_manager("B-ManagedShop", 502)
        self.assertTrue(res2)

        mgr2 = await get_shop_manager("B-ManagedShop")
        self.assertEqual(mgr2["uid"], 502)

        # Перевіряємо що у 501 магазин знявся
        async with aiosqlite.connect(self.managers_db_path) as mdb:
            cursor = await mdb.execute("SELECT shops FROM managers WHERE uid = 501")
            m1_shops = json.loads((await cursor.fetchone())[0])
            self.assertNotIn("B-ManagedShop", m1_shops)

        # Відкріплюємо взагалі (None)
        await set_shop_manager("B-ManagedShop", None)
        self.assertIsNone(await get_shop_manager("B-ManagedShop"))

    async def test_dynamic_shops_by_city_lifecycle(self):
        """Перевірка життєвого циклу магазинів у get_shops_by_city."""
        await init_shops_db()
        initial_shops = await get_shops_by_city("Хмельницький")
        initial_count = len(initial_shops)

        # 1. Додаємо новий магазин
        ok, msg = await add_shop("B-Dynamic-1 вул. Нова, 1", "Хмельницький")
        self.assertTrue(ok)
        shops_after_add = await get_shops_by_city("Хмельницький")
        self.assertEqual(len(shops_after_add), initial_count + 1)
        names = [s["name"] for s in shops_after_add]
        self.assertIn("B-Dynamic-1 вул. Нова, 1", names)

        # 2. Перейменовуємо
        added = await get_shop_by_name("B-Dynamic-1 вул. Нова, 1")
        ok, msg = await rename_shop(added["id"], "B-Dynamic-Renamed вул. Нова, 1")
        self.assertTrue(ok)
        names_after_rename = [s["name"] for s in await get_shops_by_city("Хмельницький")]
        self.assertNotIn("B-Dynamic-1 вул. Нова, 1", names_after_rename)
        self.assertIn("B-Dynamic-Renamed вул. Нова, 1", names_after_rename)

        # 3. Видаляємо
        ok, msg = await delete_shop_and_transfer_users(added["id"])
        self.assertTrue(ok)
        names_after_delete = [s["name"] for s in await get_shops_by_city("Хмельницький")]
        self.assertEqual(len(names_after_delete), initial_count)
        self.assertNotIn("B-Dynamic-Renamed вул. Нова, 1", names_after_delete)

    async def test_legacy_employees_and_roles_seamless_migration(self):
        """
        Перевірка, що існуючі працівники з прив'язкою до магазинів та посад у коді:
        1. Не втрачають прив'язку до магазину
        2. Не втрачають посаду
        3. Магазини та посади автоматично створюються в БД
        """
        # Створюємо користувачів ДО міграції
        legacy_shop = "B-999 Старий Магазин, 1"
        legacy_role = "ВВ Ексклюзивний Пекар"

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO users (uid, full_name, role, status, city, shop) VALUES (?, ?, ?, ?, ?, ?)",
                (9991, "Іван Працівник", legacy_role, "Працівник", "Хмельницький", legacy_shop)
            )
            await db.commit()

        # Запускаємо ініціалізацію магазинів (як при старті бота)
        await init_shops_db()

        # Перевіряємо, що магазин автоматично додано до таблиці shops
        shop_in_db = await get_shop_by_name(legacy_shop)
        self.assertIsNotNone(shop_in_db)
        self.assertEqual(shop_in_db["name"], legacy_shop)
        self.assertEqual(shop_in_db["city"], "Хмельницький")

        # Перевіряємо, що дані працівника в users залишилися незмінними
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT role, shop, city, status FROM users WHERE uid = 9991")
            row = await cursor.fetchone()
            self.assertEqual(row[0], legacy_role)
            self.assertEqual(row[1], legacy_shop)
            self.assertEqual(row[2], "Хмельницький")
            self.assertEqual(row[3], "Працівник")


if __name__ == "__main__":
    unittest.main()

