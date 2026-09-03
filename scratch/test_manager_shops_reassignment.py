import asyncio
import aiosqlite
import json
from unittest.mock import AsyncMock, MagicMock, patch

from database.schema import init_db
from database.managers import (
    init_managers_db,
    add_manager,
    get_manager_by_uid,
    delete_manager_by_uid,
    get_appropriate_territorial_for_user,
    get_manager_by_shop,
    reassign_removed_shops_users_to_territorial,
    count_unassigned_or_territorial_users_in_shops,
    transfer_shop_users_to_manager,
    update_manager_shops,
    DB_PATH
)
from database.users import register_user, set_intern_extra, get_user_details, delete_user
from database.positions import get_position_direction


async def run_tests():
    print("🚀 Starting Manager Shops Reassignment & Territorial Binding Tests...\n")
    await init_db()
    await init_managers_db()

    test_city = "ТестовеМісто"
    shop_a = "Магазин А"
    shop_b = "Магазин Б"
    shop_c = "Магазин В"
    shop_d = "Магазин Г"

    for uid in (888001, 888002, 888003, 888004, 888005, 888006, 888007):
        await delete_user(uid)

    # Setup test territorials:
    # 1. Territorial ТЗ
    t_tz_uid = 999001
    await delete_manager_by_uid(t_tz_uid)
    await add_manager(
        uid=t_tz_uid,
        process="Територіал",
        full_name="Територіал ТЗ",
        username="terr_tz",
        city=test_city,
        territorial_type="ТЗ"
    )

    # 2. Territorial ВВ
    t_vv_uid = 999002
    await delete_manager_by_uid(t_vv_uid)
    await add_manager(
        uid=t_vv_uid,
        process="Територіал",
        full_name="Територіал ВВ",
        username="terr_vv",
        city=test_city,
        territorial_type="ВВ"
    )

    # Setup test store manager
    mgr_uid = 999003
    await delete_manager_by_uid(mgr_uid)
    await add_manager(
        uid=mgr_uid,
        process="Керівник",
        full_name="Керівник Магазинів",
        username="mgr_test",
        city=test_city,
        shops=[shop_a, shop_b, shop_c]
    )

    print("1. Testing get_appropriate_territorial_for_user...")
    # Пекар is ВВ
    vv_target = await get_appropriate_territorial_for_user(test_city, "Пекар")
    assert vv_target == t_vv_uid, f"Expected {t_vv_uid}, got {vv_target}"

    # Старший продавець is ТЗ
    tz_target = await get_appropriate_territorial_for_user(test_city, "Старший продавець")
    assert tz_target == t_tz_uid, f"Expected {t_tz_uid}, got {tz_target}"

    # City with no territorials
    none_target = await get_appropriate_territorial_for_user("МістоБезТериторіалів", "Пекар")
    assert none_target is None, f"Expected None, got {none_target}"
    print("  ✅ get_appropriate_territorial_for_user correctly routes by ТЗ/ВВ!")

    print("2. Testing get_manager_by_shop...")
    m_found = await get_manager_by_shop(test_city, shop_a)
    assert m_found and m_found["uid"] == mgr_uid, "Did not find manager for shop_a!"
    m_not_found = await get_manager_by_shop(test_city, shop_d)
    assert m_not_found is None, "Should not find manager for unassigned shop_d!"
    print("  ✅ get_manager_by_shop accurately identifies active store managers!")

    print("3. Testing dev_mgr_change_shops_start non-destructive initialization...")
    from bot.menus.developer import dev_mgr_change_shops_start
    mock_cb = MagicMock()
    mock_cb.data = f"dev_mgr_ch_shops:{mgr_uid}"
    mock_cb.from_user.id = 123456
    mock_cb.message = MagicMock()
    mock_cb.message.edit_text = AsyncMock()
    mock_cb.message.answer = AsyncMock()
    mock_cb.answer = AsyncMock()
    mock_state = MagicMock()
    mock_state.update_data = AsyncMock()
    mock_state.set_state = AsyncMock()

    with patch("bot.menus.developer._check_access", return_value=(True, True, False)):
        await dev_mgr_change_shops_start(mock_cb, mock_state)
        # Verify state was initialized with manager's current shops
        assert mock_state.update_data.called
        data_call_kwargs = mock_state.update_data.call_args[1]
        assert data_call_kwargs["original_shops"] == [shop_a, shop_b, shop_c]
        assert data_call_kwargs["selected_shops"] == [shop_a, shop_b, shop_c]
    print("  ✅ dev_mgr_change_shops_start pre-populates state and checkboxes non-destructively!")

    print("4. Testing differential reassignment of removed shop to Territorial...")
    # Create test users:
    # User 1: Intern in Shop A (Пекар -> ВВ) under mgr_uid
    u1 = 888001
    await delete_user(u1)
    await register_user(u1, full_name="Стажер А ВВ", username="u1")
    await set_intern_extra(u1, mgr_uid, "Пекар", test_city, shop=shop_a)

    # User 2: Worker in Shop C (Продавець -> ТЗ) under mgr_uid
    u2 = 888002
    await delete_user(u2)
    await register_user(u2, full_name="Працівник С ТЗ", username="u2")
    await set_intern_extra(u2, mgr_uid, "Продавець", test_city, shop=shop_c)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET status = 'Працівник' WHERE user_id = ?", (u2,))
        await db.commit()

    # User 3: Intern in Shop C (ВВ Кондитер -> ВВ) under mgr_uid
    u3 = 888003
    await delete_user(u3)
    await register_user(u3, full_name="Стажер С ВВ", username="u3")
    await set_intern_extra(u3, mgr_uid, "ВВ Кондитер", test_city, shop=shop_c)

    # Now remove shop_c
    reassigned = await reassign_removed_shops_users_to_territorial(test_city, [shop_c], mgr_uid)
    await update_manager_shops(mgr_uid, test_city, [shop_a, shop_b])
    assert reassigned == 2, f"Expected 2 reassigned users, got {reassigned}"

    # Verify User 1 is STILL with mgr_uid
    u1_db = await get_user_details(u1)
    assert u1_db["manager_id"] == mgr_uid, "User 1 should not have been moved!"

    # Verify User 2 (Продавець ТЗ) was moved to Territorial ТЗ
    u2_db = await get_user_details(u2)
    assert u2_db["manager_id"] == t_tz_uid, f"User 2 should be with Territorial ТЗ ({t_tz_uid}), got {u2_db['manager_id']}"

    # Verify User 3 (Формувальник ВВ) was moved to Territorial ВВ
    u3_db = await get_user_details(u3)
    assert u3_db["manager_id"] == t_vv_uid, f"User 3 should be with Territorial ВВ ({t_vv_uid}), got {u3_db['manager_id']}"
    print("  ✅ reassign_removed_shops_users_to_territorial correctly moves only removed shop users to matching ТЗ/ВВ territorials!")

    print("5. Testing adding new shop and transferring both interns and workers...")
    # Add User 4 (Intern in Shop D, under Territorial ТЗ)
    u4 = 888004
    await delete_user(u4)
    await register_user(u4, full_name="Стажер Д", username="u4")
    await set_intern_extra(u4, t_tz_uid, "Продавець", test_city, shop=shop_d)

    # Add User 5 (Worker in Shop D, under Territorial ВВ)
    u5 = 888005
    await delete_user(u5)
    await register_user(u5, full_name="Працівник Д", username="u5")
    await set_intern_extra(u5, t_vv_uid, "Пекар", test_city, shop=shop_d)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET status = 'Працівник' WHERE user_id = ?", (u5,))
        await db.commit()

    # Count users in shop_d
    interns_c, workers_c = await count_unassigned_or_territorial_users_in_shops(test_city, [shop_d], exclude_manager_uid=mgr_uid)
    assert interns_c == 1, f"Expected 1 intern, got {interns_c}"
    assert workers_c == 1, f"Expected 1 worker, got {workers_c}"

    # Transfer both to mgr_uid
    transferred = await transfer_shop_users_to_manager(test_city, [shop_d], mgr_uid)
    assert transferred == 2, f"Expected 2 transferred, got {transferred}"

    u4_db = await get_user_details(u4)
    u5_db = await get_user_details(u5)
    assert u4_db["manager_id"] == mgr_uid, "User 4 should be transferred to mgr_uid!"
    assert u5_db["manager_id"] == mgr_uid, "User 5 should be transferred to mgr_uid!"
    print("  ✅ count and transfer functions correctly handle both interns and workers in added shops!")

    print("6. Testing dynamic manager assignment during registration...")
    from bot.handlers import process_registration_full_name

    # Scenario A: New user registers in shop_a (which has manager mgr_uid)
    mock_reg_msg = MagicMock()
    reg_u_id = 888006
    await delete_user(reg_u_id)
    mock_reg_msg.from_user.id = reg_u_id
    mock_reg_msg.from_user.username = "reg_test_1"
    mock_reg_msg.text = "Іван Тестовий"
    mock_reg_msg.answer = AsyncMock()
    mock_reg_msg.answer_photo = AsyncMock()
    mock_reg_msg.bot = MagicMock()
    mock_reg_msg.bot.send_message = AsyncMock()

    mock_reg_state = MagicMock()
    mock_reg_state.get_data = AsyncMock(return_value={
        "reg_role": "Продавець",
        "reg_city": test_city,
        "reg_shop": shop_a,
        "reg_manager_id": None, # Created without explicit manager
        "reg_token": None
    })
    mock_reg_state.clear = AsyncMock()

    await process_registration_full_name(mock_reg_msg, mock_reg_state)
    reg_u1_db = await get_user_details(reg_u_id)
    assert reg_u1_db["manager_id"] == mgr_uid, f"Expected {mgr_uid}, got {reg_u1_db['manager_id']}"

    # Scenario B: New user registers in shop without a manager (shop_c had its manager removed!)
    # Role = Пекар -> Should be assigned to Territorial ВВ (t_vv_uid)
    reg_u2_id = 888007
    await delete_user(reg_u2_id)
    mock_reg_msg.from_user.id = reg_u2_id
    mock_reg_msg.from_user.username = "reg_test_2"
    mock_reg_msg.text = "Оксана Тестова"

    mock_reg_state.get_data = AsyncMock(return_value={
        "reg_role": "Пекар",
        "reg_city": test_city,
        "reg_shop": shop_c, # shop_c is unmanaged
        "reg_manager_id": None,
        "reg_token": None
    })

    await process_registration_full_name(mock_reg_msg, mock_reg_state)
    reg_u2_db = await get_user_details(reg_u2_id)
    assert reg_u2_db["manager_id"] == t_vv_uid, f"Expected {t_vv_uid} (Territorial ВВ), got {reg_u2_db['manager_id']}"
    print("  ✅ Registration dynamically attaches to store manager or matches appropriate Territorial!")

    # Cleanup
    for uid in (u1, u2, u3, u4, u5, reg_u_id, reg_u2_id):
        await delete_user(uid)
    for m_id in (t_tz_uid, t_vv_uid, mgr_uid):
        await delete_manager_by_uid(m_id)

    print("\n🎉 ALL MANAGER SHOPS REASSIGNMENT & TERRITORIAL TESTS PASSED 100%!")


if __name__ == "__main__":
    asyncio.run(run_tests())
