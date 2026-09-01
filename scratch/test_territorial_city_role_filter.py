import asyncio
import aiosqlite
from database import DB_PATH
from database.managers import MANAGERS_DB_PATH, add_manager, delete_manager_by_uid, get_manager_by_uid
from database.positions import add_position, update_position_type, get_position_by_name
from bot.menus.developer import _filter_users_for_territorial


async def test_territorial_filtering():
    print("🚀 Starting Territorial City + Role Type (ТЗ/ВВ) Filter Tests...\n")
    
    # 1. Setup Test Positions
    print("1. Creating test positions...")
    try:
        await add_position("Тест-Касир-ТЗ", days_count=5, territorial_type="ТЗ")
    except ValueError:
        pass
        
    try:
        await add_position("Тест-Пекар-ВВ", days_count=5, territorial_type="ВВ")
    except ValueError:
        pass
        
    pos_tz = await get_position_by_name("Тест-Касир-ТЗ")
    pos_vv = await get_position_by_name("Тест-Пекар-ВВ")
    assert pos_tz["territorial_type"] == "ТЗ", "Position ТЗ mismatch"
    assert pos_vv["territorial_type"] == "ВВ", "Position ВВ mismatch"
    print("✅ Test positions created with correct territorial_type (ТЗ and ВВ).")

    # 2. Setup Test Territorials (Same city: 'Хмельницький', different types: ТЗ & ВВ)
    print("\n2. Creating two Territorials for 'Хмельницький' (ТЗ and ВВ)...")
    terr_tz_uid = 999901
    terr_vv_uid = 999902
    
    await add_manager(terr_tz_uid, "Територіал", full_name="Територіал ТЗ Хмельницький", city="Хмельницький", territorial_type="ТЗ")
    await add_manager(terr_vv_uid, "Територіал", full_name="Територіал ВВ Хмельницький", city="Хмельницький", territorial_type="ВВ")
    
    mgr_tz = await get_manager_by_uid(terr_tz_uid)
    mgr_vv = await get_manager_by_uid(terr_vv_uid)
    
    assert mgr_tz["city"] == "Хмельницький" and mgr_tz["territorial_type"] == "ТЗ"
    assert mgr_vv["city"] == "Хмельницький" and mgr_vv["territorial_type"] == "ВВ"
    print("✅ Both Territorials successfully created in the same city with distinct types.")

    # 3. Test User List Filtering
    print("\n3. Testing dynamic user filtering for each Territorial...")
    users = [
        {"user_id": 101, "full_name": "Іван Касир (Хмельницький)", "city": "Хмельницький", "role": "Тест-Касир-ТЗ"},
        {"user_id": 102, "full_name": "Марія Пекар (Хмельницький)", "city": "Хмельницький", "role": "Тест-Пекар-ВВ"},
        {"user_id": 103, "full_name": "Олена Касир (Кам'янець)", "city": "Кам'янець-Подільський", "role": "Тест-Касир-ТЗ"},
        {"user_id": 104, "full_name": "Петро Пекар (Кам'янець)", "city": "Кам'янець-Подільський", "role": "Тест-Пекар-ВВ"},
    ]
    
    # Filter for Territorial ТЗ (Хмельницький)
    filtered_tz = await _filter_users_for_territorial(terr_tz_uid, users)
    assert len(filtered_tz) == 1, f"Expected 1 user for Territorial ТЗ, got {len(filtered_tz)}"
    assert filtered_tz[0]["user_id"] == 101, "Territorial ТЗ should only see Ivan (User 101)"
    print("✅ Territorial ТЗ sees only Хмельницький ТЗ workers (User 101).")

    # Filter for Territorial ВВ (Хмельницький)
    filtered_vv = await _filter_users_for_territorial(terr_vv_uid, users)
    assert len(filtered_vv) == 1, f"Expected 1 user for Territorial ВВ, got {len(filtered_vv)}"
    assert filtered_vv[0]["user_id"] == 102, "Territorial ВВ should only see Maria (User 102)"
    print("✅ Territorial ВВ sees only Хмельницький ВВ workers (User 102).")

    # 4. Test Dynamic Position Type Toggle
    print("\n4. Testing position type toggle (e.g. changing Тест-Касир-ТЗ to ВВ)...")
    await update_position_type(pos_tz["id"], "ВВ")
    
    # After changing role type to ВВ, Ivan should now be visible to Territorial ВВ!
    filtered_vv_after = await _filter_users_for_territorial(terr_vv_uid, users)
    assert len(filtered_vv_after) == 2, f"Expected 2 users for Territorial ВВ after toggle, got {len(filtered_vv_after)}"
    u_ids = {u["user_id"] for u in filtered_vv_after}
    assert u_ids == {101, 102}, "Territorial ВВ should now see both Ivan and Maria"
    
    filtered_tz_after = await _filter_users_for_territorial(terr_tz_uid, users)
    assert len(filtered_tz_after) == 0, "Territorial ТЗ should now see 0 users"
    print("✅ Dynamic position toggle immediately re-routed workers without manual database edits!")

    # 5. Cleanup
    print("\n5. Cleaning up test data...")
    await delete_manager_by_uid(terr_tz_uid)
    await delete_manager_by_uid(terr_vv_uid)
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM positions WHERE name IN ('Тест-Касир-ТЗ', 'Тест-Пекар-ВВ')")
        await db.commit()
    print("✅ Cleaned up.")

    print("\n🎉 ALL TERRITORIAL FILTERING TESTS PASSED 100%!")


if __name__ == "__main__":
    asyncio.run(test_territorial_filtering())
