import asyncio
import aiosqlite
from unittest.mock import AsyncMock, MagicMock
from aiogram.types import CallbackQuery, Message, User, Chat, InlineKeyboardMarkup

from database import DB_PATH
from database.managers import (
    MANAGERS_DB_PATH,
    add_manager,
    delete_manager_by_uid,
    get_manager_by_uid,
    is_user_without_store_manager,
)
from database.positions import get_position_by_name
from bot.services.positions import update_position_days
from database.users import register_user, delete_user, get_user_details
from bot.menus.manager import (
    manager_process_add_shop_callback,
    manager_fire_prompt_handler,
    manager_fire_confirm_handler,
    _show_intern_details,
)
from bot.menus.developer import (
    _admin_cho_keyboard,
    _admin_study_keyboard,
    _build_managers_team_view,
    _build_manager_card,
    _users_staff_keyboard,
    _decode_back_callback,
    dev_pos_edit_days_start,
    dev_pos_edit_days_process,
    developer_list_interns_no_manager,
    developer_list_workers_no_manager,
    developer_user_profile_back,
)


async def test_all():
    print("🚀 Starting comprehensive test suite for Manager Training, Control and Security...\n")

    # =========================================================================
    # Test 1: Manager Intern Token Creation Role Exclusion
    # =========================================================================
    print("--- Test 1: Role Exclusion for Manager Intern Creation ---")
    mock_cb = MagicMock(spec=CallbackQuery)
    mock_cb.data = "mgr_add_shop:0"
    mock_cb.from_user = User(id=777001, is_bot=False, first_name="Manager")
    mock_cb.message = MagicMock(spec=Message)
    mock_cb.message.photo = [MagicMock(file_id="abc")]
    mock_cb.message.caption = "some_caption"
    mock_cb.message.edit_caption = AsyncMock()
    mock_cb.message.edit_media = AsyncMock()
    mock_cb.message.answer_photo = AsyncMock()
    mock_cb.answer = AsyncMock()

    mock_state = MagicMock()
    mock_state.get_data = AsyncMock(return_value={"add_city": "Хмельницький"})
    mock_state.update_data = AsyncMock()
    mock_state.set_state = AsyncMock()

    await manager_process_add_shop_callback(mock_cb, mock_state)
    call_args = None
    if mock_cb.message.edit_caption.called:
        call_args = mock_cb.message.edit_caption.call_args
    elif mock_cb.message.edit_media.called:
        call_args = mock_cb.message.edit_media.call_args
    elif mock_cb.message.answer_photo.called:
        call_args = mock_cb.message.answer_photo.call_args
    assert call_args is not None, "A message update should have been called"
    reply_markup = call_args.kwargs.get("reply_markup")
    assert reply_markup is not None, "Reply markup must exist"

    presented_roles = [
        btn.text for row in reply_markup.inline_keyboard for btn in row if btn.callback_data.startswith("add_role:")
    ]
    assert "Керівник" not in presented_roles, "Role 'Керівник' must not be offered to managers!"
    assert "Керівник Стажер" not in presented_roles, "Role 'Керівник Стажер' must not be offered to managers!"
    print(f"✅ Excluded roles checked. Offered roles: {presented_roles}")

    # =========================================================================
    # Test 2: Fire Intern Button & Confirmation
    # =========================================================================
    print("\n--- Test 2: Fire Intern Button & Confirmation in Manager Panel ---")
    test_intern_uid = 888101
    test_manager_uid = 777001
    await add_manager(test_manager_uid, "Керівник", full_name="Тестовий Керівник", city="Хмельницький", shops=["B-10"])
    await register_user(test_intern_uid, "test_intern", "Тестовий Стажер")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET manager_id = ?, city = 'Хмельницький', shop = 'B-10' WHERE user_id = ?",
            (test_manager_uid, test_intern_uid)
        )
        await db.commit()

    # Check that _show_intern_details shows the fire button
    mock_view_cb = MagicMock(spec=CallbackQuery)
    mock_view_cb.message = MagicMock(spec=Message)
    mock_view_cb.message.answer = AsyncMock()
    mock_view_cb.message.answer_photo = AsyncMock()
    mock_view_cb.answer = AsyncMock()
    mock_view_cb.bot = MagicMock()
    mock_view_cb.bot.get_chat = AsyncMock(side_effect=Exception("No tg"))
    mock_view_cb.bot.get_user_profile_photos = AsyncMock(return_value=MagicMock(total_count=0))

    await _show_intern_details(mock_view_cb, test_intern_uid)
    sent_kb = None
    if mock_view_cb.message.answer.called:
        sent_kb = mock_view_cb.message.answer.call_args.kwargs.get("reply_markup")
    elif mock_view_cb.message.answer_photo.called:
        sent_kb = mock_view_cb.message.answer_photo.call_args.kwargs.get("reply_markup")

    assert sent_kb is not None, "Intern card must have reply markup"
    fire_btns = [
        btn for row in sent_kb.inline_keyboard for btn in row if btn.callback_data.startswith(f"mgr_fire_prompt:{test_intern_uid}")
    ]
    assert len(fire_btns) == 1, "Should have exactly 1 'Звільнити' button"
    print("✅ 'Звільнити' button found on intern card.")

    # Test prompt handler
    mock_prompt_cb = MagicMock(spec=CallbackQuery)
    mock_prompt_cb.data = f"mgr_fire_prompt:{test_intern_uid}:mgr_my_team"
    mock_prompt_cb.from_user = User(id=test_manager_uid, is_bot=False, first_name="Manager")
    mock_prompt_cb.message = MagicMock(spec=Message)
    mock_prompt_cb.message.photo = [MagicMock(file_id="xyz")]
    mock_prompt_cb.message.edit_text = AsyncMock()
    mock_prompt_cb.message.edit_caption = AsyncMock()
    mock_prompt_cb.message.edit_media = AsyncMock()
    mock_prompt_cb.message.answer = AsyncMock()
    mock_prompt_cb.message.answer_photo = AsyncMock()
    mock_prompt_cb.message.delete = AsyncMock()
    mock_prompt_cb.answer = AsyncMock()

    await manager_fire_prompt_handler(mock_prompt_cb)
    prompt_kb = None
    if mock_prompt_cb.message.edit_caption.called:
        prompt_kb = mock_prompt_cb.message.edit_caption.call_args.kwargs.get("reply_markup")
    elif mock_prompt_cb.message.edit_media.called:
        prompt_kb = mock_prompt_cb.message.edit_media.call_args.kwargs.get("reply_markup")
    elif mock_prompt_cb.message.edit_text.called:
        prompt_kb = mock_prompt_cb.message.edit_text.call_args.kwargs.get("reply_markup")
    elif mock_prompt_cb.message.answer.called:
        prompt_kb = mock_prompt_cb.message.answer.call_args.kwargs.get("reply_markup")
    elif mock_prompt_cb.message.answer_photo.called:
        prompt_kb = mock_prompt_cb.message.answer_photo.call_args.kwargs.get("reply_markup")
    assert prompt_kb is not None
    confirm_btns = [
        btn for row in prompt_kb.inline_keyboard for btn in row if btn.callback_data.startswith(f"mgr_fire_confirm:{test_intern_uid}")
    ]
    assert len(confirm_btns) == 1, "Must contain confirm fire button"
    print("✅ Fire confirmation prompt displayed correctly.")

    # Test confirm handler
    mock_confirm_cb = MagicMock(spec=CallbackQuery)
    mock_confirm_cb.data = f"mgr_fire_confirm:{test_intern_uid}:mgr_my_team"
    mock_confirm_cb.from_user = User(id=test_manager_uid, is_bot=False, first_name="Manager")
    mock_confirm_cb.message = MagicMock(spec=Message)
    mock_confirm_cb.message.photo = [MagicMock(file_id="xyz")]
    mock_confirm_cb.message.edit_text = AsyncMock()
    mock_confirm_cb.message.edit_caption = AsyncMock()
    mock_confirm_cb.message.edit_media = AsyncMock()
    mock_confirm_cb.message.answer = AsyncMock()
    mock_confirm_cb.message.answer_photo = AsyncMock()
    mock_confirm_cb.message.delete = AsyncMock()
    mock_confirm_cb.answer = AsyncMock()

    await manager_fire_confirm_handler(mock_confirm_cb)
    deleted_check = await get_user_details(test_intern_uid)
    assert deleted_check is None, "Intern should be deleted from users table"
    await delete_manager_by_uid(test_manager_uid)
    print("✅ Intern successfully fired and deleted.")

    # =========================================================================
    # Test 3: Restrict Role «Керівник» Days Edit to Admin Only
    # =========================================================================
    print("\n--- Test 3: Restricting 'Керівник' Training Days Edit ---")
    pos = await get_position_by_name("Керівник")
    assert pos is not None, "Position 'Керівник' must exist"
    pos_id = pos["id"]

    # Non-admin attempt via dev_pos_edit_days_start
    mock_non_admin_cb = MagicMock(spec=CallbackQuery)
    mock_non_admin_cb.data = f"dev_pos_edit_days:{pos_id}"
    mock_non_admin_cb.from_user = User(id=1234567, is_bot=False, first_name="NonAdmin")
    mock_non_admin_cb.message = MagicMock(spec=Message)
    mock_non_admin_cb.answer = AsyncMock()

    await dev_pos_edit_days_start(mock_non_admin_cb, mock_state)
    mock_non_admin_cb.answer.assert_called_with(
        "⛔️ Змінювати кількість днів для посади «Керівник» може лише адміністратор!", show_alert=True
    )
    print("✅ Non-admin start attempt rejected.")

    # Non-admin attempt via dev_pos_edit_days_process
    mock_non_admin_msg = MagicMock(spec=Message)
    mock_non_admin_msg.text = "10"
    mock_non_admin_msg.from_user = User(id=1234567, is_bot=False, first_name="NonAdmin")
    mock_non_admin_msg.answer = AsyncMock()

    mock_state_proc = MagicMock()
    mock_state_proc.get_data = AsyncMock(return_value={"edit_pos_id": pos_id})
    mock_state_proc.clear = AsyncMock()

    await dev_pos_edit_days_process(mock_non_admin_msg, mock_state_proc)
    mock_non_admin_msg.answer.assert_called_with(
        "⛔️ Змінювати кількість днів для посади «Керівник» може лише адміністратор!"
    )
    print("✅ Non-admin process attempt rejected.")

    # =========================================================================
    # Test 4: Territorial Panel Materials & Read-Only Study Keyboard
    # =========================================================================
    print("\n--- Test 4: Territorial Study Keyboard Read-Only ---")
    terr_cho_kb = _admin_cho_keyboard(is_main_dev=False, is_admin=False, is_territorial=True)
    study_btns = [
        btn for row in terr_cho_kb.inline_keyboard for btn in row if btn.callback_data == "dev_main_study"
    ]
    assert len(study_btns) == 1, "Territorial must see '📚 Навчальні матеріали'"

    study_kb = _admin_study_keyboard(is_observer=False, is_territorial=True)
    edit_content_btns = [
        btn for row in study_kb.inline_keyboard for btn in row if btn.callback_data == "dev_syllabus_menu"
    ]
    assert len(edit_content_btns) == 0, "Territorial must not see '📚 Змінити змісти' button"
    print("✅ Territorial study keyboard is strictly read-only.")

    # =========================================================================
    # Test 5: Trainee Manager Badges & Days Manage Button
    # =========================================================================
    print("\n--- Test 5: Trainee Manager Badges & Days Manage Button ---")
    trainee_mgr_uid = 999111
    await add_manager(
        trainee_mgr_uid,
        "Керівник Стажер",
        full_name="Олексій Стажер",
        city="Хмельницький",
        shops=["B-10"]
    )
    await register_user(trainee_mgr_uid, "alex_trainee", "Олексій Стажер")

    # Team list view
    team_text, team_kb = await _build_managers_team_view(is_admin=True, is_territorial=False, user_id=123)
    trainee_btns = [
        btn for row in team_kb.inline_keyboard for btn in row if btn.callback_data == f"dev_mgr_view:{trainee_mgr_uid}"
    ]
    assert len(trainee_btns) == 1, "Trainee manager must be in managers list"
    assert "🎓 Стажер" in trainee_btns[0].text, f"Trainee manager must have badge: {trainee_btns[0].text}"
    print(f"✅ Trainee manager badge verified: '{trainee_btns[0].text}'")

    # Manager card view
    card_data = await _build_manager_card(trainee_mgr_uid, is_admin=True, is_territorial=False)
    assert card_data is not None
    card_text, card_kb = card_data
    assert "🎓 <b>Навчання:</b> Керівник Стажер" in card_text, "Card must include training section"
    days_btns = [
        btn for row in card_kb.inline_keyboard for btn in row if btn.callback_data == f"dev_days_manage:{trainee_mgr_uid}:mgr_team"
    ]
    assert len(days_btns) == 1, "Card must include '📅 Навчальні дні' button with mgr_team return code"
    print("✅ Trainee manager card includes learning progress and days button.")

    # Return code decoding
    assert _decode_back_callback("mgr_team") == "dev_manage_managers"
    assert _decode_back_callback(f"mgr_team_{trainee_mgr_uid}") == f"dev_mgr_view:{trainee_mgr_uid}"
    print("✅ Back callback decoding for mgr_team verified.")

    # =========================================================================
    # Test 6: Users Without Manager
    # =========================================================================
    print("\n--- Test 6: Users Without Manager Detection & Staff Keyboard ---")
    staff_kb = _users_staff_keyboard(is_admin=True, is_territorial=False)
    staff_callbacks = [
        btn.callback_data for row in staff_kb.inline_keyboard for btn in row
    ]
    assert "dev_users_interns_no_mgr" in staff_callbacks, "Staff menu must have dev_users_interns_no_mgr"
    assert "dev_users_workers_no_mgr" in staff_callbacks, "Staff menu must have dev_users_workers_no_mgr"
    print("✅ Buttons for users without manager present in staff keyboard.")

    # Test helper is_user_without_store_manager
    u_no_mgr = {"user_id": 9901, "manager_id": None, "city": "Хмельницький", "shop": "B-99"}
    assert await is_user_without_store_manager(u_no_mgr) is True, "User with manager_id=None must be flagged as without manager"

    # User assigned to an active manager
    u_with_mgr = {"user_id": 9902, "manager_id": trainee_mgr_uid, "city": "Хмельницький", "shop": "B-10"}
    assert await is_user_without_store_manager(u_with_mgr) is False, "User with active manager must not be flagged"

    print("✅ is_user_without_store_manager accurately detects users without active manager.")

    # Clean up test manager
    await delete_manager_by_uid(trainee_mgr_uid)
    await delete_user(trainee_mgr_uid)

    print("\n🎉 ALL TESTS PASSED SUCCESSFULLY! 🚀\n")


if __name__ == "__main__":
    asyncio.run(test_all())
