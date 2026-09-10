import asyncio
import aiosqlite
import os
import sys

# Додаємо корінь проєкту до sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import DB_PATH
from database.tokens import TOKENS_DB_PATH
from database.positions import (
    add_position,
    rename_position,
    delete_position as db_delete_position,
    get_position_by_name,
    get_days_count_for_role,
)
from bot.services.positions import (
    update_position_name,
    delete_position as svc_delete_position,
    get_position_stats,
)
from database.users import (
    register_user,
    delete_user,
    change_user_role,
    get_user_details,
    get_user_progress,
)
from bot.services.learning_progress import get_days_overview, DayStatus
from bot.state import user_progress


async def test_all():
    print("🚀 Starting test_position_and_role_transfer...")

    TEST_ROLE_OLD = "Тестова Посада 1"
    TEST_ROLE_NEW = "Тестова Посада Оновлена"
    TEST_ROLE_EMPTY = "Тестова Порожня Посада"

    TEST_USER_WORKER = 9999901
    TEST_USER_INTERN = 9999902

    ROLE_BAKER = "Тестовий Пекар"

    # Clean up before start
    await delete_user(TEST_USER_WORKER)
    await delete_user(TEST_USER_INTERN)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM positions WHERE name IN (?, ?, ?, ?)", (TEST_ROLE_OLD, TEST_ROLE_NEW, TEST_ROLE_EMPTY, ROLE_BAKER))
        await db.execute("DELETE FROM materials WHERE role IN (?, ?, ?, ?)", (TEST_ROLE_OLD, TEST_ROLE_NEW, TEST_ROLE_EMPTY, ROLE_BAKER))
        await db.execute("DELETE FROM test_errors WHERE role IN (?, ?, ?, ?)", (TEST_ROLE_OLD, TEST_ROLE_NEW, TEST_ROLE_EMPTY, ROLE_BAKER))
        await db.commit()

    async with aiosqlite.connect(TOKENS_DB_PATH) as tdb:
        await tdb.execute("DELETE FROM tokens WHERE role IN (?, ?, ?, ?)", (TEST_ROLE_OLD, TEST_ROLE_NEW, TEST_ROLE_EMPTY, ROLE_BAKER))
        await tdb.commit()

    # ==========================================
    # ТЕСТ 1: Завдання 63 (Перейменування посади)
    # ==========================================
    print("\n--- ТЕСТ 1: Завдання 63 (Перейменування посади та каскад) ---")
    pos_id = await add_position(TEST_ROLE_OLD, days_count=4, territorial_type="ТЗ")
    assert pos_id is not None, "Failed to add position"

    # Додаємо тестові дані в materials, test_errors, tokens
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO materials (role, day, title, content_type, content) VALUES (?, 1, 'Test Material', 'text', 'Content')",
            (TEST_ROLE_OLD,),
        )
        await db.execute(
            "INSERT INTO test_errors (role, day, question_idx, error_count) VALUES (?, 1, 0, 5)",
            (TEST_ROLE_OLD,),
        )
        await db.commit()

    async with aiosqlite.connect(TOKENS_DB_PATH) as tdb:
        await tdb.execute(
            "INSERT INTO tokens (token, role, city, shop, created_at) VALUES ('tok_test_63', ?, 'Київ', 'Shop-1', CURRENT_TIMESTAMP)",
            (TEST_ROLE_OLD,),
        )
        await tdb.commit()

    # Створюємо користувача з цією роллю
    await register_user(TEST_USER_INTERN, "intern_63", "Тестовий Стажер 63")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET role = ?, city = 'Київ', shop = 'Shop-1' WHERE user_id = ?", (TEST_ROLE_OLD, TEST_USER_INTERN))
        await db.commit()

    # Викликаємо оновлення назви посади через сервіс
    res_rename = await update_position_name(pos_id, TEST_ROLE_NEW)
    assert res_rename is True, "update_position_name should succeed"

    # Перевіряємо каскад у positions, materials, test_errors, users, tokens
    pos_check = await get_position_by_name(TEST_ROLE_NEW)
    assert pos_check is not None, "Position name should be updated in positions table"

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM materials WHERE role = ?", (TEST_ROLE_NEW,))
        assert (await cursor.fetchone())[0] == 1, "materials.role must be updated to TEST_ROLE_NEW"

        cursor = await db.execute("SELECT COUNT(*) FROM test_errors WHERE role = ?", (TEST_ROLE_NEW,))
        assert (await cursor.fetchone())[0] == 1, "test_errors.role must be updated to TEST_ROLE_NEW"

        cursor = await db.execute("SELECT role FROM users WHERE user_id = ?", (TEST_USER_INTERN,))
        assert (await cursor.fetchone())[0] == TEST_ROLE_NEW, "users.role must be updated to TEST_ROLE_NEW"

    async with aiosqlite.connect(TOKENS_DB_PATH) as tdb:
        cursor = await tdb.execute("SELECT role FROM tokens WHERE token = 'tok_test_63'")
        assert (await cursor.fetchone())[0] == TEST_ROLE_NEW, "tokens.role must be updated to TEST_ROLE_NEW in tokens.db"

    print("✅ ТЕСТ 1 пройдено: перейменування посади успішно каскадується у всі таблиці та tokens.db.")

    # ==========================================
    # ТЕСТ 2: Завдання 64 (Видалення посади)
    # ==========================================
    print("\n--- ТЕСТ 2: Завдання 64 (Видалення посади з перевіркою) ---")
    # 2.1 Спроба видалити посаду, де є користувач (TEST_USER_INTERN)
    succ_del, msg_del = await svc_delete_position(pos_id)
    assert succ_del is False, "delete_position should fail when users exist"
    assert "закріплено" in msg_del, f"Expected warning about users, got: {msg_del}"
    print(f"✅ Блокування видалення при наявності користувачів спрацювало: {msg_del}")

    # 2.2 Створюємо порожню посаду та видаляємо її
    empty_pos_id = await add_position(TEST_ROLE_EMPTY, days_count=3, territorial_type="ВВ")
    # Додамо матеріали та невикористаний токен для неї
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO materials (role, day, title, content_type, content) VALUES (?, 1, 'Empty Pos Mat', 'text', 'Mat')",
            (TEST_ROLE_EMPTY,),
        )
        await db.commit()

    async with aiosqlite.connect(TOKENS_DB_PATH) as tdb:
        await tdb.execute(
            "INSERT INTO tokens (token, role, city, created_at) VALUES ('tok_test_empty', ?, 'Київ', CURRENT_TIMESTAMP)",
            (TEST_ROLE_EMPTY,),
        )
        await tdb.commit()

    succ_del2, msg_del2 = await svc_delete_position(empty_pos_id)
    assert succ_del2 is True, f"delete_position for empty position should succeed, got: {msg_del2}"

    # Перевіряємо що посади, її матеріалів та токенів більше немає
    assert await get_position_by_name(TEST_ROLE_EMPTY) is None, "Position must be deleted"
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM materials WHERE role = ?", (TEST_ROLE_EMPTY,))
        assert (await cursor.fetchone())[0] == 0, "Materials for deleted position must be cleaned up"
    async with aiosqlite.connect(TOKENS_DB_PATH) as tdb:
        cursor = await tdb.execute("SELECT COUNT(*) FROM tokens WHERE token = 'tok_test_empty'")
        assert (await cursor.fetchone())[0] == 0, "Unused tokens for deleted position must be cleaned up"

    print("✅ ТЕСТ 2 пройдено: видалення посади очищує матеріали та токени, коли користувачів 0.")

    # ==========================================
    # ТЕСТ 3: Завдання 65 (Зміна посади Працівнику)
    # ==========================================
    print("\n--- ТЕСТ 3: Завдання 65 (Зміна посади Працівнику - всі дні відкриті) ---")
    # Реєструємо працівника
    await register_user(TEST_USER_WORKER, "worker_65", "Тестовий Працівник 65")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET role = 'Бариста', status = 'Працівник', city = 'Київ', shop = 'Shop-1' WHERE user_id = ?", (TEST_USER_WORKER,))
        await db.commit()

    # Змінюємо посаду Працівнику на TEST_ROLE_NEW (де days_count=4)
    res_worker_role = await change_user_role(TEST_USER_WORKER, TEST_ROLE_NEW)
    assert res_worker_role["success"] is True, "change_user_role should succeed"
    assert res_worker_role["status"] == "Працівник", "Status must remain 'Працівник'"
    assert res_worker_role["new_role"] == TEST_ROLE_NEW, "Role must be updated"

    # Перевіряємо дні в базі
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM progress WHERE user_id = ? ORDER BY day", (TEST_USER_WORKER,))
        rows = [dict(r) for r in await cursor.fetchall()]
        assert len(rows) == 4, f"Worker must have progress rows for all 4 days, got {len(rows)}"
        for r in rows:
            assert r["manual_open"] == 1, f"Day {r['day']} must have manual_open = 1"
            assert r["completed"] == 1, f"Day {r['day']} must have completed = 1"

    # Перевіряємо overview через learning_progress
    overview = await get_days_overview(TEST_USER_WORKER, role=TEST_ROLE_NEW)
    assert len(overview) == 4, f"Overview must have 4 days, got {len(overview)}"
    for day_num, status in overview:
        assert status == DayStatus.COMPLETED, f"Day {day_num} for worker should be COMPLETED, got {status}"

    print("✅ ТЕСТ 3 пройдено: Працівнику відкрито всі дні нової посади, статус збережено.")

    # ==========================================
    # ТЕСТ 4: Завдання 65 (Зміна посади Стажеру)
    # ==========================================
    print("\n--- ТЕСТ 4: Завдання 65 (Зміна посади Стажеру - рестарт з дня 1) ---")
    # Додамо стажеру старий прогрес: пройшов день 1 та день 2
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO progress (user_id, day, completed) VALUES (?, 1, 1)", (TEST_USER_INTERN,))
        await db.execute("INSERT OR REPLACE INTO progress (user_id, day, completed) VALUES (?, 2, 1)", (TEST_USER_INTERN,))
        await db.commit()
    user_progress[TEST_USER_INTERN] = {1: {"completed": True}, 2: {"completed": True}}

    # Створимо нову цільову посаду для переводу стажера
    ROLE_BAKER = "Тестовий Пекар"
    await add_position(ROLE_BAKER, days_count=5, territorial_type="ВВ")

    res_intern_role = await change_user_role(TEST_USER_INTERN, ROLE_BAKER)
    assert res_intern_role["success"] is True, "change_user_role for intern should succeed"
    assert res_intern_role["status"] != "Працівник", "Intern status must not be 'Працівник'"

    # Перевіряємо що кеш пам'яті очищено
    assert TEST_USER_INTERN not in user_progress or not user_progress[TEST_USER_INTERN], "Memory cache must be cleared"

    # Перевіряємо дні в базі
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM progress WHERE user_id = ? ORDER BY day", (TEST_USER_INTERN,))
        rows = [dict(r) for r in await cursor.fetchall()]
        assert len(rows) == 1, f"Intern must only have Day 1 row, got {len(rows)}"
        assert rows[0]["day"] == 1, "Only Day 1 should exist in progress"
        assert rows[0]["manual_open"] == 1, "Day 1 must be open"
        assert rows[0]["completed"] == 0, "Day 1 must not be completed yet"

    # Перевіряємо через get_days_overview
    intern_overview = await get_days_overview(TEST_USER_INTERN, role=ROLE_BAKER)
    assert len(intern_overview) == 5, f"Intern overview must have 5 days, got {len(intern_overview)}"
    assert intern_overview[0][1] == DayStatus.OPEN, f"Day 1 must be OPEN, got {intern_overview[0][1]}"
    for day_num, status in intern_overview[1:]:
        assert status == DayStatus.CLOSED, f"Day {day_num} must be CLOSED for intern, got {status}"

    print("✅ ТЕСТ 4 пройдено: Стажеру скинуто прогрес, навчання розпочато з дня 1, дні 2+ заблоковані.")

    # ==========================================
    # ТЕСТ 5: Завдання 66 (Повне видалення стажера)
    # ==========================================
    print("\n--- ТЕСТ 5: Завдання 66 (Повне видалення стажера без фантомних записів) ---")
    # Додамо токен, використаний стажером
    async with aiosqlite.connect(TOKENS_DB_PATH) as tdb:
        await tdb.execute(
            "INSERT INTO tokens (token, role, city, used_by, created_at) VALUES ('tok_used_by_intern', ?, 'Київ', ?, CURRENT_TIMESTAMP)",
            (ROLE_BAKER, TEST_USER_INTERN),
        )
        await tdb.commit()

    # Видаляємо користувача
    del_res = await delete_user(TEST_USER_INTERN)
    assert del_res is True, "delete_user should return True"

    # Перевіряємо що всі сліди стерто
    assert await get_user_details(TEST_USER_INTERN) is None, "User must not exist in users"
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM progress WHERE user_id = ?", (TEST_USER_INTERN,))
        assert (await cursor.fetchone())[0] == 0, "Progress must be deleted"
    async with aiosqlite.connect(TOKENS_DB_PATH) as tdb:
        cursor = await tdb.execute("SELECT COUNT(*) FROM tokens WHERE used_by = ?", (TEST_USER_INTERN,))
        assert (await cursor.fetchone())[0] == 0, "Used tokens must be deleted from tokens.db"
    assert TEST_USER_INTERN not in user_progress, "Cache must not have deleted user"

    # Тепер повторна реєстрація з іншою роллю
    await register_user(TEST_USER_INTERN, "re_intern", "Повторний Стажер")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET role = ?, city = 'Київ', shop = 'Shop-1' WHERE user_id = ?", (TEST_ROLE_NEW, TEST_USER_INTERN))
        await db.commit()
    re_details = await get_user_details(TEST_USER_INTERN)
    assert re_details is not None, "Re-registration must succeed cleanly"
    assert re_details["role"] == TEST_ROLE_NEW, "Re-registered role should be accurate"

    print("✅ ТЕСТ 5 пройдено: видалення користувача каскадно очищує базу, повторна реєстрація без помилок.")

    # Cleanup test data
    await delete_user(TEST_USER_WORKER)
    await delete_user(TEST_USER_INTERN)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM positions WHERE name IN (?, ?, ?)", (TEST_ROLE_OLD, TEST_ROLE_NEW, ROLE_BAKER))
        await db.commit()

    print("\n🎉 ВСІ 5 ТЕСТІВ УСПІШНО ПРОЙДЕНО!")


if __name__ == "__main__":
    asyncio.run(test_all())
