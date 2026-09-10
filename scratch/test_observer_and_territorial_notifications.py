import asyncio
import aiosqlite
import json
from datetime import datetime

from database import DB_PATH
from database.managers import MANAGERS_DB_PATH, init_managers_db
from database.positions import (
    add_position,
    delete_position,
    get_position_by_name,
    get_position_direction
)
from database.material_notifications import (
    NOTIFICATIONS_DB_PATH,
    init_material_notifications_db,
    create_material_change_event,
    create_recipients_for_event,
    get_event_analytics_for_category,
    mark_recipient_acknowledged,
    get_pending_wave_recipients,
)


async def run_tests():
    print("=== START TEST: Observer Exclusion & Territorial Inclusion in Material Notifications ===")

    await init_managers_db()
    await init_material_notifications_db()

    # Створюємо 2 тестові посади: ТЗ та ВВ
    role_tz = "Тест_Касир_ТЗ"
    role_vv = "Тест_Пекар_ВВ"

    pos_tz = await get_position_by_name(role_tz)
    if not pos_tz:
        await add_position(role_tz, days_count=3, territorial_type="ТЗ")
    pos_vv = await get_position_by_name(role_vv)
    if not pos_vv:
        await add_position(role_vv, days_count=3, territorial_type="ВВ")

    dir_tz = await get_position_direction(role_tz)
    dir_vv = await get_position_direction(role_vv)
    assert dir_tz == "ТЗ", f"Expected ТЗ, got {dir_tz}"
    assert dir_vv == "ВВ", f"Expected ВВ, got {dir_vv}"
    print(f"✅ Посади створено: {role_tz} ({dir_tz}), {role_vv} ({dir_vv})")

    # Створюємо тестових користувачів
    u_worker_tz = 999101
    u_manager = 999102
    u_observer = 999103
    u_observer_worker = 999104
    u_ter_tz = 999105
    u_ter_vv = 999106

    all_test_uids = [u_worker_tz, u_manager, u_observer, u_observer_worker, u_ter_tz, u_ter_vv]

    # Додаємо в users.db
    async with aiosqlite.connect(DB_PATH) as db:
        for uid in all_test_uids:
            await db.execute("DELETE FROM users WHERE user_id = ?", (uid,))
        # Worker ТЗ
        await db.execute(
            "INSERT INTO users (user_id, full_name, username, role, city, shop, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (u_worker_tz, "Тест Працівник ТЗ", "t_worker_tz", role_tz, "Хмельницький", "Магазин 1", "Працівник")
        )
        # Observer, який також чомусь записаний у users.db
        await db.execute(
            "INSERT INTO users (user_id, full_name, username, role, city, shop, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (u_observer_worker, "Тест Наглядач-Юзер", "t_obs_u", role_tz, "Хмельницький", "Магазин 1", "Працівник")
        )
        await db.commit()

    # Додаємо в managers.db
    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        for uid in all_test_uids:
            await db.execute("DELETE FROM managers WHERE uid = ?", (uid,))
        # Manager
        await db.execute(
            "INSERT INTO managers (uid, full_name, username, process, shops, city, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (u_manager, "Тест Керівник", "t_mgr", "Керівник", json.dumps(["Магазин 1"]), "Хмельницький", "active")
        )
        # Observer 1
        await db.execute(
            "INSERT INTO managers (uid, full_name, username, process, city, status) VALUES (?, ?, ?, ?, ?, ?)",
            (u_observer, "Тест Наглядач", "t_obs", "Наглядач", "Хмельницький", "active")
        )
        # Observer 2 (також у users.db)
        await db.execute(
            "INSERT INTO managers (uid, full_name, username, process, city, status) VALUES (?, ?, ?, ?, ?, ?)",
            (u_observer_worker, "Тест Наглядач-Юзер", "t_obs_u", "Наглядач", "Хмельницький", "active")
        )
        # Territorial ТЗ
        await db.execute(
            "INSERT INTO managers (uid, full_name, username, process, territorial_type, city, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (u_ter_tz, "Тест Тер ТЗ", "t_ter_tz", "Територіал", "ТЗ", "Хмельницький", "active")
        )
        # Territorial ВВ
        await db.execute(
            "INSERT INTO managers (uid, full_name, username, process, territorial_type, city, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (u_ter_vv, "Тест Тер ВВ", "t_ter_vv", "Територіал", "ВВ", "Хмельницький", "active")
        )
        await db.commit()

    print("✅ Тестових користувачів та менеджерів успішно створено")

    # ----------------------------------------------------
    # ТЕСТ 1: Подія зміни матеріалу для посади ТЗ
    # ----------------------------------------------------
    ev_tz_id = await create_material_change_event(
        role=role_tz,
        day=1,
        content_type="text",
        description="Тестова зміна матеріалу ТЗ",
        pages=["Сторінка 1", "Сторінка 2"]
    )
    rec_tz_count = await create_recipients_for_event(ev_tz_id, role_tz)
    print(f"Подія ТЗ #{ev_tz_id}: створено {rec_tz_count} отримувачів")

    # Отримуємо всіх отримувачів події ev_tz_id
    async with aiosqlite.connect(NOTIFICATIONS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT user_id, role_type FROM material_change_recipients WHERE event_id = ?", (ev_tz_id,))
        rows = await cur.fetchall()
        tz_recipients = {r["user_id"]: r["role_type"] for r in rows}

    # Перевірки для ТЗ
    assert u_worker_tz in tz_recipients, f"Працівник ТЗ ({u_worker_tz}) мав отримати сповіщення!"
    assert tz_recipients[u_worker_tz] == "працівник"
    assert u_manager in tz_recipients, f"Керівник ({u_manager}) мав отримати сповіщення!"
    assert tz_recipients[u_manager] == "керівник"
    assert u_ter_tz in tz_recipients, f"Територіал ТЗ ({u_ter_tz}) мав отримати сповіщення!"
    assert tz_recipients[u_ter_tz] == "територіал"

    # Негативні перевірки для ТЗ
    assert u_ter_vv not in tz_recipients, f"Територіал ВВ ({u_ter_vv}) НЕ мав отримати сповіщення для посади ТЗ!"
    assert u_observer not in tz_recipients, f"Наглядач ({u_observer}) НЕ мав отримати сповіщення!"
    assert u_observer_worker not in tz_recipients, f"Наглядач-користувач ({u_observer_worker}) НЕ мав отримати сповіщення!"
    print("✅ ТЕСТ 1 пройдено: Працівник ТЗ, Керівник та Тер ТЗ отримали сповіщення; Тер ВВ та Наглядачі виключені!")

    # ----------------------------------------------------
    # ТЕСТ 2: Подія зміни матеріалу для посади ВВ
    # ----------------------------------------------------
    ev_vv_id = await create_material_change_event(
        role=role_vv,
        day=1,
        content_type="text",
        description="Тестова зміна матеріалу ВВ",
        pages=["Сторінка ВВ"]
    )
    rec_vv_count = await create_recipients_for_event(ev_vv_id, role_vv)
    print(f"Подія ВВ #{ev_vv_id}: створено {rec_vv_count} отримувачів")

    async with aiosqlite.connect(NOTIFICATIONS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT user_id, role_type FROM material_change_recipients WHERE event_id = ?", (ev_vv_id,))
        rows = await cur.fetchall()
        vv_recipients = {r["user_id"]: r["role_type"] for r in rows}

    # Перевірки для ВВ
    assert u_manager in vv_recipients, f"Керівник ({u_manager}) мав отримати сповіщення для ВВ!"
    assert u_ter_vv in vv_recipients, f"Територіал ВВ ({u_ter_vv}) мав отримати сповіщення для ВВ!"
    assert vv_recipients[u_ter_vv] == "територіал"

    # Негативні перевірки для ВВ
    assert u_ter_tz not in vv_recipients, f"Територіал ТЗ ({u_ter_tz}) НЕ мав отримати сповіщення для посади ВВ!"
    assert u_observer not in vv_recipients, f"Наглядач ({u_observer}) НЕ мав отримати сповіщення для ВВ!"
    print("✅ ТЕСТ 2 пройдено: Тер ВВ отримав сповіщення для ВВ; Тер ТЗ та Наглядачі виключені!")

    # ----------------------------------------------------
    # ТЕСТ 3: Фіксація ознайомлення та аналітика для категорії 'територіал'
    # ----------------------------------------------------
    # Перед ознайомленням
    stats_before = await get_event_analytics_for_category(ev_tz_id, "територіал")
    assert stats_before["total"] >= 1
    assert stats_before["acknowledged_count"] == 0

    # Фіксуємо ознайомлення для територіала
    success, is_late = await mark_recipient_acknowledged(ev_tz_id, u_ter_tz)
    assert success is True, "mark_recipient_acknowledged failed!"

    # Після ознайомлення
    stats_after = await get_event_analytics_for_category(ev_tz_id, "територіал")
    assert stats_after["acknowledged_count"] == 1
    expected_pct = round((1 / stats_after["total"]) * 100, 1)
    assert stats_after["ack_percent"] == expected_pct, f"Expected {expected_pct}%, got {stats_after['ack_percent']}%"
    print(f"✅ ТЕСТ 3 пройдено: Ознайомлення територіала зафіксовано, аналітика розрахована коректно ({expected_pct}%)!")

    # ----------------------------------------------------
    # Очищення тестових даних
    # ----------------------------------------------------
    async with aiosqlite.connect(DB_PATH) as db:
        for uid in all_test_uids:
            await db.execute("DELETE FROM users WHERE user_id = ?", (uid,))
        await db.commit()

    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        for uid in all_test_uids:
            await db.execute("DELETE FROM managers WHERE uid = ?", (uid,))
        await db.commit()

    async with aiosqlite.connect(NOTIFICATIONS_DB_PATH) as db:
        await db.execute("DELETE FROM material_change_recipients WHERE event_id IN (?, ?)", (ev_tz_id, ev_vv_id))
        await db.execute("DELETE FROM material_change_events WHERE id IN (?, ?)", (ev_tz_id, ev_vv_id))
        await db.commit()

    pos_tz_dict = await get_position_by_name(role_tz)
    if pos_tz_dict:
        await delete_position(pos_tz_dict["id"])
    pos_vv_dict = await get_position_by_name(role_vv)
    if pos_vv_dict:
        await delete_position(pos_vv_dict["id"])

    print("✅ Тестові дані успішно очищено.")
    print("=== ALL TESTS PASSED! ===")


if __name__ == "__main__":
    asyncio.run(run_tests())
