import asyncio
import os
import sqlite3
from unittest.mock import AsyncMock, MagicMock

# Set up test environment
os.environ["BOT_TOKEN"] = "test_token"

from database.tokens import generate_token, use_token, get_token_data
from database.managers import (
    add_observer,
    get_all_observers,
    get_observer_by_uid,
    is_observer_user,
    delete_observer_by_uid,
    is_territorial_user
)
from database.hr import is_privileged_user, is_developer_user
from database.users import delete_user
from bot.menus.developer import (
    _check_access,
    _ensure_developer,
    _admin_cho_keyboard,
    _admin_analyt_keyboard,
    _admin_team_keyboard,
    _users_menu_keyboard,
    _build_manager_card,
    _build_observers_menu_view
)
from bot.keyboards import main_menu_keyboard

async def run_tests():
    print("🚀 Starting Observer Role (Наглядач) automated tests...")
    
    test_admin_uid = 999999111
    test_obs_uid = 888888222
    test_obs_username = "test_obs_user"
    test_obs_name = "Олександр Наглядаченко"

    # 1. Test token generation and validation for observer
    print("\n1. Testing Token Generation for Role 'Наглядач'...")
    token = await generate_token(manager_id=test_admin_uid, role="Наглядач", expires_in_hours=24)
    assert token is not None, "Token generation failed"
    token_info = await get_token_data(token)
    assert token_info is not None, "Token info not found"
    assert token_info["role"] == "Наглядач", f"Expected role 'Наглядач', got {token_info['role']}"
    assert token_info["manager_id"] == test_admin_uid, "Creator mismatch"
    print("✅ Token generated and verified successfully!")

    # 2. Test token consumption
    print("\n2. Testing Token Consumption...")
    success = await use_token(token, test_obs_uid)
    assert success is True, "Token consumption failed"
    # Consuming again should fail
    fail_consume = await use_token(token, test_obs_uid)
    assert fail_consume is False, "Double consumption should fail"
    print("✅ Token consumed successfully and single-use enforced!")

    # 3. Test adding observer in managers table
    print("\n3. Testing Observer Record Creation in DB...")
    # Clean up before inserting if exists
    await delete_observer_by_uid(test_obs_uid)
    
    await add_observer(
        uid=test_obs_uid,
        full_name=test_obs_name,
        username=test_obs_username,
        responsible_uid=test_admin_uid
    )
    
    # 4. Verify role detection functions
    print("\n4. Testing Role Detection Functions...")
    is_obs = await is_observer_user(test_obs_uid)
    assert is_obs is True, "is_observer_user returned False"
    
    is_dev = await is_developer_user(test_obs_uid)
    assert is_dev is False, "Observer should not be a full Developer"
    
    is_terr = await is_territorial_user(test_obs_uid)
    assert is_terr is False, "Observer should not be a Territorial"
    
    is_priv = await is_privileged_user(test_obs_uid)
    assert is_priv is True, "Observer must be recognized as a privileged user"
    print("✅ Role detection functions verified!")

    # 5. Verify query helpers
    print("\n5. Testing DB Helper Queries...")
    obs_record = await get_observer_by_uid(test_obs_uid)
    assert obs_record is not None, "get_observer_by_uid returned None"
    assert obs_record["full_name"] == test_obs_name, f"Expected {test_obs_name}, got {obs_record['full_name']}"
    assert obs_record["process"] == "Наглядач", "Expected process='Наглядач'"
    
    all_obs = await get_all_observers()
    found = any(o["uid"] == test_obs_uid for o in all_obs)
    assert found is True, "get_all_observers did not contain test observer"
    print("✅ Query helpers verified!")

    # 6. Test Keyboards UI Restrictions
    print("\n6. Testing Keyboards UI Restrictions for Observer...")
    # Main menu keyboard
    mm_kb = main_menu_keyboard(is_observer=True)
    all_btn_texts = [btn.text for row in mm_kb.inline_keyboard for btn in row]
    assert "🚀 Почати роботу" in all_btn_texts, "Observer main menu missing '🚀 Почати роботу'"
    assert "👤 Профіль" in all_btn_texts, "Observer main menu missing '👤 Профіль'"
    assert "🛠 Панель Розробника" not in all_btn_texts, "Observer should not have dev panel button"
    print(" - Main menu keyboard: OK")

    # CHO (Admin/Observer dashboard) keyboard
    cho_kb = _admin_cho_keyboard(is_main_dev=False, is_admin=False, is_territorial=False, is_observer=True)
    cho_callbacks = [btn.callback_data for row in cho_kb.inline_keyboard for btn in row]
    assert "dev_main_study" in cho_callbacks, "Observer should have access to study materials"
    assert "dev_main_analyt" in cho_callbacks, "Observer should have access to analytics"
    assert "dev_main_team" in cho_callbacks, "Observer should have access to team"
    assert "dev_main_other" not in cho_callbacks, "Observer must NOT have access to 'Інше' (positions, cities, tokens, health)"
    print(" - Admin CHO keyboard: OK")

    # Analytics keyboard
    analyt_kb = _admin_analyt_keyboard(is_observer=True)
    analyt_callbacks = [btn.callback_data for row in analyt_kb.inline_keyboard for btn in row]
    assert "dev_analytics_menu" in analyt_callbacks, "Analytics menu missing"
    assert "show_test_errors" in analyt_callbacks, "Test errors missing"
    assert "dev_reminder_history" in analyt_callbacks, "Reminder history missing"
    assert "dev_xlsx_menu" not in analyt_callbacks, "Observer must NOT have access to '📊 XLSX звіт'"
    print(" - Analytics keyboard: OK")

    # Users keyboard
    users_kb = _users_menu_keyboard(is_admin=False, is_territorial=False, is_observer=True)
    users_callbacks = [btn.callback_data for row in users_kb.inline_keyboard for btn in row]
    assert "dev_users_staff" in users_callbacks, "Users staff menu missing"
    assert "dev_users_filters" in users_callbacks, "Users filters missing"
    assert "dev_users_search" in users_callbacks, "Users search missing"
    assert "dev_users_delete" not in users_callbacks, "Observer must NOT have delete user button"
    assert "dev_users_bulk_promote" not in users_callbacks, "Observer must NOT have bulk promote button"

    from bot.menus.developer import _users_staff_keyboard, _users_filters_keyboard
    staff_kb = _users_staff_keyboard(is_admin=False, is_territorial=False, is_observer=True)
    staff_callbacks = [btn.callback_data for row in staff_kb.inline_keyboard for btn in row]
    assert "dev_users_list" in staff_callbacks, "Users list missing in staff menu"
    assert "dev_users_add" not in staff_callbacks, "Observer must NOT have add user button"

    filters_kb = _users_filters_keyboard(is_admin=False, is_territorial=False, is_observer=True)
    filters_callbacks = [btn.callback_data for row in filters_kb.inline_keyboard for btn in row]
    assert "dev_users_by_city" in filters_callbacks, "Users by city missing in filters menu"
    print(" - Users keyboard & submenus: OK")

    # Manager card keyboard for observer
    # Mock manager in managers table if needed
    card_data = await _build_manager_card(test_obs_uid, is_admin=False, is_territorial=False, is_observer=True)
    if card_data:
        _, card_kb = card_data
        card_callbacks = [btn.callback_data for row in card_kb.inline_keyboard for btn in row]
        assert not any("dev_mgr_edit_menu" in cb for cb in card_callbacks), "Observer must NOT have edit manager button"
        assert not any("dev_mgr_reassign_menu" in cb for cb in card_callbacks), "Observer must NOT have reassign manager button"
        print(" - Manager card keyboard: OK")

    # 7. Test Access Guard Handlers
    print("\n7. Testing Access Guard Handlers...")
    # Mock callback
    mock_cb = MagicMock()
    mock_cb.from_user.id = test_obs_uid
    mock_cb.answer = AsyncMock()

    has_acc, is_adm, is_terr = await _check_access(mock_cb)
    assert has_acc is True, "_check_access should allow observer"
    assert is_adm is False, "is_admin should be False for observer"
    assert is_terr is False, "is_territorial should be False for observer"

    # _ensure_developer for write/edit operations
    write_allowed = await _ensure_developer(mock_cb, allow_observer=False)
    assert write_allowed is False, "_ensure_developer(allow_observer=False) must block observer"

    # _ensure_developer for read operations
    read_allowed = await _ensure_developer(mock_cb, allow_observer=True)
    assert read_allowed is True, "_ensure_developer(allow_observer=True) must permit observer"
    print("✅ Access guards verified!")

    # 8. Test Observers Management View for Admin
    print("\n8. Testing Admin Observers Menu View...")
    obs_view_text, obs_view_kb = await _build_observers_menu_view(page=0)
    assert "Команда Наглядачів" in obs_view_text, "Observers view title missing"
    assert test_obs_name in obs_view_text or any(test_obs_name in btn.text for row in obs_view_kb.inline_keyboard for btn in row), "Test observer missing in view"
    print("✅ Admin observers view verified!")

    # 9. Test Deletion of Observer
    print("\n9. Testing Deletion of Observer...")
    await delete_observer_by_uid(test_obs_uid)
    await delete_user(test_obs_uid)
    import aiosqlite
    from database.tokens import TOKENS_DB_PATH
    from database.managers import MANAGERS_DB_PATH
    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        await db.execute("DELETE FROM managers WHERE uid = ?", (test_obs_uid,))
        await db.commit()
    async with aiosqlite.connect(TOKENS_DB_PATH) as db:
        await db.execute("DELETE FROM tokens WHERE manager_id = ?", (test_admin_uid,))
        await db.commit()
    is_obs_after_del = await is_observer_user(test_obs_uid)
    assert is_obs_after_del is False, "Observer should no longer exist after deletion"
    print("✅ Deletion and cleanup verified!")

    print("\n🎉 ALL TESTS PASSED SUCCESSFULLY! Role 'Наглядач' works 100% as specified.")

if __name__ == "__main__":
    asyncio.run(run_tests())
