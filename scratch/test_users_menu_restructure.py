import asyncio
import os
import aiosqlite
from unittest.mock import AsyncMock, MagicMock, patch

from bot.menus.developer import (
    _users_menu_keyboard,
    _users_staff_keyboard,
    _users_filters_keyboard,
    _admin_other_keyboard,
    _service_functions_keyboard,
    _decode_back_callback,
    developer_process_user_search,
)
from database import DB_PATH
from database.positions import get_position_direction
from database.users import (
    get_users_by_shop,
    get_users_by_manager,
    count_users_by_shop,
    count_users_by_manager,
    register_user,
    get_user_details,
)
from bot.services.developer_actions import get_user_days_report


async def run_tests():
    print("🚀 Running Users Menu Restructure & Filters Tests...\n")

    # 1. Test Keyboards
    print("1. Testing Keyboards...")
    users_kb = _users_menu_keyboard(is_admin=True, is_territorial=False)
    users_callbacks = [btn.callback_data for row in users_kb.inline_keyboard for btn in row]
    assert "dev_users_staff" in users_callbacks, "dev_users_staff missing"
    assert "dev_users_filters" in users_callbacks, "dev_users_filters missing"
    assert "dev_users_search" in users_callbacks, "dev_users_search missing"
    assert "dev_main_team" in users_callbacks, "dev_main_team missing"
    assert "dev_users_delete" not in users_callbacks, "Standalone delete should not be in users menu"
    assert "dev_users_bulk_promote" not in users_callbacks, "Bulk promote should not be in users menu"
    print("  ✅ _users_menu_keyboard matches requested layout!")

    # 2. Test Staff Keyboard
    print("2. Testing Staff Keyboard...")
    staff_kb = _users_staff_keyboard(is_admin=True, is_territorial=False)
    staff_callbacks = [btn.callback_data for row in staff_kb.inline_keyboard for btn in row]
    assert "dev_users_interns" in staff_callbacks
    assert "dev_users_workers" in staff_callbacks
    assert "dev_users_list" in staff_callbacks
    assert "dev_users_add" in staff_callbacks
    assert "dev_users_menu" in staff_callbacks
    print("  ✅ _users_staff_keyboard contains Interns, Workers, All, Add, and Back!")

    # 3. Test Filters Keyboard
    print("3. Testing Filters Keyboard...")
    filters_kb = _users_filters_keyboard(is_admin=True, is_territorial=False)
    filters_callbacks = [btn.callback_data for row in filters_kb.inline_keyboard for btn in row]
    assert "dev_users_by_city" in filters_callbacks
    assert "dev_users_by_shop" in filters_callbacks
    assert "dev_users_by_manager" in filters_callbacks
    assert "dev_users_active" in filters_callbacks
    assert "dev_users_inactive" in filters_callbacks
    assert "dev_users_menu" in filters_callbacks
    print("  ✅ _users_filters_keyboard contains By City, By Shop, By Manager, Active, Inactive, and Back!")

    # 4. Test Service Functions Keyboard in Other
    print("4. Testing Other Category and Service Functions Menu...")
    other_kb = _admin_other_keyboard()
    other_callbacks = [btn.callback_data for row in other_kb.inline_keyboard for btn in row]
    assert "dev_service_functions_menu" in other_callbacks

    service_kb = _service_functions_keyboard()
    service_callbacks = [btn.callback_data for row in service_kb.inline_keyboard for btn in row]
    assert "dev_users_bulk_promote" in service_callbacks
    assert "dev_main_other" in service_callbacks
    print("  ✅ Service functions menu properly houses dev_users_bulk_promote and returns to dev_main_other!")

    # 5. Test Database Query Helpers (Shop & Manager & Direction)
    print("5. Testing Database Query Helpers...")
    vv_dir = await get_position_direction("Пекар")
    assert vv_dir == "ВВ", f"Expected ВВ for Пекар, got {vv_dir}"
    tz_dir = await get_position_direction("Старший продавець")
    assert tz_dir == "ТЗ", f"Expected ТЗ for Старший продавець, got {tz_dir}"
    print("  ✅ get_position_direction correctly classifies roles as ВВ or ТЗ!")

    test_user_id = 9999901
    test_manager_id = 8888801
    test_city = "Хмельницький"
    test_shop = "B-19 вул. Героїв Маріуполя, 62"

    await register_user(
        user_id=test_user_id,
        username="test_trainee",
        full_name="Олексій Тестовий",
    )
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET city = ?, role = ?, shop = ?, manager_id = ? WHERE user_id = ?",
            (test_city, "Старший продавець", test_shop, test_manager_id, test_user_id)
        )
        await db.commit()

    shop_users = await get_users_by_shop(test_city, test_shop)
    assert any(u["user_id"] == test_user_id for u in shop_users)
    shop_count = await count_users_by_shop(test_city, test_shop)
    assert shop_count >= 1

    mgr_users = await get_users_by_manager(test_manager_id)
    assert any(u["user_id"] == test_user_id for u in mgr_users)
    mgr_count = await count_users_by_manager(test_manager_id)
    assert mgr_count >= 1
    print("  ✅ get_users_by_shop, count_users_by_shop, get_users_by_manager, count_users_by_manager pass!")

    # 6. Test Back Callback Decoder
    print("6. Testing _decode_back_callback...")
    assert _decode_back_callback("sh_0_2") == "dev_u_shop:0:2"
    assert _decode_back_callback("mg_777") == "dev_u_mgr:777"
    assert _decode_back_callback("srch") == "dev_users_search"
    assert _decode_back_callback("staff") == "dev_users_staff"
    assert _decode_back_callback("filters") == "dev_users_filters"
    assert _decode_back_callback("menu") == "dev_users_menu"
    print("  ✅ _decode_back_callback decodes all return codes properly!")

    # 7. Test User Card Format (get_user_days_report)
    print("7. Testing User Card Format...")
    report = await get_user_days_report(test_user_id)
    assert "👤 <b>Олексій Тестовий</b> (@test_trainee)" in report
    assert "🏢 <b>Посада:</b> Старший продавець | ТЗ" in report
    assert f"🏙 <b>Місто:</b> {test_city}" in report
    assert f"🏪 <b>Магазин:</b> {test_shop}" in report
    assert "👨‍🏫 <b>Керівник:</b>" in report
    assert "📊 <b>Прогрес:</b>" in report
    assert "⏱️ <b>Остання активність:</b>" in report
    assert "📅 <b>Статус днів</b>" in report
    assert "День 1" in report
    print("  ✅ get_user_days_report produces exactly the required profile card structure!")

    # 8. Test Search user handler single result resolution
    print("8. Testing Search single user direct card resolution...")
    mock_message = MagicMock()
    mock_message.text = "9999901"
    mock_message.from_user.id = 123456
    mock_message.answer = AsyncMock()
    mock_message.answer_photo = AsyncMock()
    mock_state = MagicMock()
    mock_state.clear = AsyncMock()
    mock_state.set_state = AsyncMock()

    with patch("bot.menus.developer._check_access", return_value=(True, True, False)):
        await developer_process_user_search(mock_message, mock_state)
        assert mock_message.answer_photo.called
        args, kwargs = mock_message.answer_photo.call_args
        caption = kwargs.get("caption") or (args[1] if len(args) > 1 else "")
        assert "Олексій Тестовий" in caption
        assert "📅 <b>Статус днів</b>" in caption
        reply_markup = kwargs.get("reply_markup")
        card_callbacks = [btn.callback_data for row in reply_markup.inline_keyboard for btn in row]
        assert any(c.startswith(f"dev_days_manage:{test_user_id}") for c in card_callbacks)
        assert any(c.startswith(f"dev_user_modify:{test_user_id}") for c in card_callbacks)
        assert any(c.startswith(f"dev_user_delete_confirm:{test_user_id}") for c in card_callbacks)
        assert "dev_u_cback:srch" in card_callbacks
    print("  ✅ Search directly resolves single user to photo card with action buttons and dev_u_cback:srch!")

    # 9. Test _developer_show_users_list has NO inline user buttons
    print("9. Testing _developer_show_users_list does NOT have inline user buttons...")
    from bot.menus.developer import _developer_show_users_list
    mock_cb = MagicMock()
    mock_cb.from_user.id = 123456
    mock_cb.message = MagicMock()
    mock_cb.message.photo = None
    mock_cb.message.edit_text = AsyncMock()
    mock_cb.message.answer = AsyncMock()
    mock_cb.answer = AsyncMock()

    sample_users = [
        {"user_id": 111, "full_name": "Іван Тест", "role": "Стажер", "shop": "B-1", "city": "Київ"},
        {"user_id": 222, "full_name": "Петро Тест", "role": "Працівник", "shop": "B-2", "city": "Київ"},
    ]
    await _developer_show_users_list(mock_cb, sample_users, "👥 <b>Всі користувачі</b>", "all", 0)
    assert mock_cb.message.edit_text.called or mock_cb.message.answer.called
    call_args = mock_cb.message.edit_text.call_args or mock_cb.message.answer.call_args
    list_markup = call_args[1].get("reply_markup") or call_args[0][1]
    list_callbacks = [btn.callback_data for row in list_markup.inline_keyboard for btn in row]
    # Ensure NO dev_u_card callbacks in the general list!
    assert not any(c.startswith("dev_u_card:") for c in list_callbacks), "Found dev_u_card in user list! Should not be there."
    assert "dev_users_staff" in list_callbacks
    print("  ✅ _developer_show_users_list is clean text with pagination only, NO user inline buttons!")

    # 10. Test developer_user_card_back_handler strictly deletes card photo message
    print("10. Testing developer_user_card_back_handler strictly deletes card photo message...")
    from bot.menus.developer import developer_user_card_back_handler
    mock_card_cb = MagicMock()
    mock_card_cb.from_user.id = 123456
    mock_card_cb.data = "dev_u_cback:srch"
    mock_card_cb.message = MagicMock()
    mock_card_cb.message.photo = [MagicMock()]
    mock_card_cb.message.delete = AsyncMock()
    mock_card_cb.message.answer = AsyncMock()
    mock_card_cb.answer = AsyncMock()

    with patch("bot.menus.developer._check_access", return_value=(True, True, False)):
        await developer_user_card_back_handler(mock_card_cb, mock_state)
        # Verify photo message delete was called!
        assert mock_card_cb.message.delete.called, "Card message delete was not called!"
        assert mock_card_cb.message.photo is None, "message.photo was not reset to None!"
        # Verify it answered with text search prompt
        assert mock_card_cb.message.answer.called, "Search prompt was not answered!"
        args, kwargs = mock_card_cb.message.answer.call_args
        prompt_text = args[0] if args else kwargs.get("text", "")
        assert "Пошук користувача" in prompt_text
    print("  ✅ developer_user_card_back_handler deleted the card photo message and sent clean search prompt!")

    from database.users import delete_user
    await delete_user(test_user_id)

    print("\n🎉 ALL 10 USERS MENU RESTRUCTURING & ADVANCED FILTERS TESTS PASSED 100%!")


if __name__ == "__main__":
    asyncio.run(run_tests())
