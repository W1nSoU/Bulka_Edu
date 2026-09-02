import asyncio
import os
from unittest.mock import AsyncMock, MagicMock

# Set up test environment
os.environ["BOT_TOKEN"] = "test_token"

from database.schema import init_db
from database.managers import (
    init_managers_db,
    add_manager,
    get_manager_by_uid,
    is_manager_user,
    is_manager_trainee,
    promote_manager_trainee,
    get_manager_trainees_by_territorial,
    get_all_kerivnyky,
    delete_manager_by_uid,
)
from database.users import register_user, set_intern_extra, get_user_details, delete_user
from bot.keyboards import manager_menu_keyboard
from bot.services.reminders import notify_territorial_manager_training_completed
from bot.menus.developer import developer_promote_manager_handler, developer_keep_manager_trainee_handler

async def run_tests():
    print("🚀 Starting Manager Training & Trainee Manager (Пункт 6) automated tests...")
    await init_db()
    await init_managers_db()

    test_territorial_uid = 777111000
    test_trainee_mgr_uid = 777222111
    test_trainee_name = "Тарас Керівниченко"
    test_trainee_username = "taras_mgr"
    test_city = "Хмельницький"
    test_shops = "B-19 вул. Героїв Маріуполя, 62"

    # Clean up before testing
    await delete_manager_by_uid(test_trainee_mgr_uid)
    await delete_user(test_trainee_mgr_uid)

    # 1. Test creation of 'Керівник Стажер'
    print("\n1. Testing 'Керівник Стажер' Creation & Registration...")
    await register_user(test_trainee_mgr_uid, username=test_trainee_username, full_name=test_trainee_name)
    await set_intern_extra(test_trainee_mgr_uid, test_territorial_uid, "Керівник", test_city, shop=test_shops)
    await add_manager(
        uid=test_trainee_mgr_uid,
        username=test_trainee_username,
        full_name=test_trainee_name,
        process="Керівник Стажер",
        shops=test_shops,
        city=test_city,
        responsible_uid=test_territorial_uid
    )

    user_info = await get_user_details(test_trainee_mgr_uid)
    assert user_info is not None, "User record not found in users table"
    assert user_info["role"] == "Керівник", f"Expected role 'Керівник', got {user_info['role']}"
    assert user_info.get("status") is None or user_info.get("status") != "Працівник", f"Expected trainee status, got {user_info.get('status')}"

    mgr_info = await get_manager_by_uid(test_trainee_mgr_uid)
    assert mgr_info is not None, "Manager record not found in managers table"
    assert mgr_info["process"] == "Керівник Стажер", f"Expected process 'Керівник Стажер', got {mgr_info['process']}"
    assert mgr_info["responsible_uid"] == test_territorial_uid, "Responsible UID mismatch"
    print("✅ Trainee manager created in DB successfully!")

    # 2. Test Role Queries
    print("\n2. Testing Role Functions (is_manager_user & is_manager_trainee)...")
    is_mgr = await is_manager_user(test_trainee_mgr_uid)
    assert is_mgr is True, "is_manager_user must return True for 'Керівник Стажер'"
    
    is_trainee = await is_manager_trainee(test_trainee_mgr_uid)
    assert is_trainee is True, "is_manager_trainee must return True for 'Керівник Стажер'"

    all_kerivnyky = await get_all_kerivnyky()
    assert any(m["uid"] == test_trainee_mgr_uid for m in all_kerivnyky), "get_all_kerivnyky must include trainee managers"

    trainees_list = await get_manager_trainees_by_territorial(test_territorial_uid)
    assert any(m["uid"] == test_trainee_mgr_uid for m in trainees_list), "get_manager_trainees_by_territorial must list the trainee manager"
    print("✅ Role queries verified!")

    # 3. Test manager_menu_keyboard()
    print("\n3. Testing Manager Menu Keyboard (Top [ 📚 Навчання ] button)...")
    mgr_kb = manager_menu_keyboard()
    first_row = mgr_kb.inline_keyboard[0]
    assert len(first_row) >= 1, "First row is empty"
    first_btn = first_row[0]
    assert first_btn.text == "📚 Навчання", f"Expected first button '📚 Навчання', got '{first_btn.text}'"
    assert first_btn.callback_data == "continue_learning", f"Expected callback 'continue_learning', got '{first_btn.callback_data}'"
    print("✅ Manager menu keyboard verified!")

    # 4. Test Notification to Territorial
    print("\n4. Testing Notification to Territorial on Training Completion...")
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    
    notified = await notify_territorial_manager_training_completed(mock_bot, test_trainee_mgr_uid)
    assert notified is True, "notify_territorial_manager_training_completed returned False"
    mock_bot.send_message.assert_called_once()
    call_args = mock_bot.send_message.call_args
    assert call_args[0][0] == test_territorial_uid, f"Sent to wrong territorial UID: {call_args[0][0]}"
    assert f"dev_promote_mgr:{test_trainee_mgr_uid}" in str(call_args[1]["reply_markup"]), "Missing promote callback in keyboard"
    print("✅ Territorial notification verified!")

    # 5. Test Territorial Promotion Handler
    print("\n5. Testing Promotion Flow & DB Status Update...")
    mock_cb = MagicMock()
    mock_cb.from_user.id = test_territorial_uid
    mock_cb.data = f"dev_promote_mgr:{test_trainee_mgr_uid}"
    mock_cb.answer = AsyncMock()
    mock_cb.message = MagicMock()
    mock_cb.message.photo = None
    mock_cb.message.edit_text = AsyncMock()
    mock_cb.bot.send_message = AsyncMock()

    # Make territorial recognized as privileged/territorial
    await add_manager(
        uid=test_territorial_uid,
        username="territorial_boss",
        full_name="Іван Територіальний",
        process="Територіал",
        city=test_city
    )

    await developer_promote_manager_handler(mock_cb)

    # Check updated status
    mgr_after = await get_manager_by_uid(test_trainee_mgr_uid)
    assert mgr_after["process"] == "Керівник", f"Expected process 'Керівник', got {mgr_after['process']}"

    user_after = await get_user_details(test_trainee_mgr_uid)
    assert user_after["status"] == "Працівник", f"Expected user status 'Працівник', got {user_after.get('status')}"

    is_trainee_after = await is_manager_trainee(test_trainee_mgr_uid)
    assert is_trainee_after is False, "is_manager_trainee must be False after promotion"

    mock_cb.bot.send_message.assert_called_once()
    congrats_call = mock_cb.bot.send_message.call_args
    assert congrats_call[0][0] == test_trainee_mgr_uid, "Congrats sent to wrong user"
    assert "присвоєно статус" in congrats_call[0][1], "Congrats message content mismatch"
    print("✅ Promotion flow and status transition verified!")

    # 6. Cleanup
    print("\n6. Cleaning up test data...")
    await delete_manager_by_uid(test_trainee_mgr_uid)
    await delete_manager_by_uid(test_territorial_uid)
    print("✅ Cleaned up!")

    print("\n🎉 ALL TESTS PASSED SUCCESSFULLY! Manager Training & Trainee Manager role works 100% as specified.")

if __name__ == "__main__":
    asyncio.run(run_tests())
