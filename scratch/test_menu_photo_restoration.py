import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup

from bot.handlers import (
    show_student_main_menu,
    show_manager_main_menu,
    show_developer_main_menu,
    show_observer_main_menu,
    _show_photo_menu,
    IMG_DIR,
)
from bot.menus.developer import (
    _show_admin_photo_menu,
    developer_menu_callback,
    dev_main_study_handler,
    dev_main_analyt_handler,
    dev_main_team_handler,
    dev_main_other_handler,
)

async def run_tests():
    print("🚀 Starting Menu Photo Restoration Automated Tests...\n")

    # 1. Verify existence of required images
    print("1. Checking required photo assets in img/ and img/admin/...")
    required_images = [
        "b_start.jpg",
        "k_menu.jpg",
        "admin/admin_cho.jpg",
        "admin/admin_study.jpg",
        "admin/admin_analyt.jpg",
        "admin/admin_spus.jpg",
        "admin/admin_tools.jpg",
    ]
    for img in required_images:
        path = IMG_DIR / img
        assert path.exists(), f"Missing photo asset: {path}"
        assert path.stat().st_size > 0, f"Empty photo asset: {path}"
        print(f"  ✓ {img} exists ({path.stat().st_size // 1024} KB)")
    print("✅ All required photo assets verified!\n")

    # 2. Testing _show_photo_menu with text-only message (transition Text -> Photo)
    print("2. Testing _show_photo_menu from text-only message (transition Text -> Photo)...")
    text_message = MagicMock(spec=Message)
    text_message.photo = None
    text_message.delete = AsyncMock()
    text_message.answer_photo = AsyncMock()
    text_message.edit_media = AsyncMock(side_effect=Exception("No media to edit"))
    text_message.edit_caption = AsyncMock(side_effect=Exception("No caption to edit"))

    kb = InlineKeyboardMarkup(inline_keyboard=[])
    await _show_photo_menu(text_message, "b_start.jpg", "Test Caption", kb, allow_edit=True)

    text_message.delete.assert_awaited_once()
    text_message.answer_photo.assert_awaited_once()
    assert "b_start.jpg" in str(text_message.answer_photo.call_args[1]["photo"].path)
    print("✅ Text -> Photo properly deletes text message and answers with photo!\n")

    # 3. Testing _show_photo_menu with existing photo message (transition Photo -> Photo / Edit)
    print("3. Testing _show_photo_menu with existing photo message (Photo -> Photo / Caption)...")
    photo_message = MagicMock(spec=Message)
    photo_message.photo = [MagicMock()]
    photo_message.delete = AsyncMock()
    photo_message.answer_photo = AsyncMock()
    photo_message.edit_media = AsyncMock()
    photo_message.edit_caption = AsyncMock()

    await _show_photo_menu(photo_message, "b_start.jpg", "Test Caption", kb, allow_edit=True)
    photo_message.edit_media.assert_awaited_once()
    assert photo_message.delete.call_count == 0
    print("✅ Photo -> Photo smoothly edits media without deleting message!\n")

    # 4. Testing show_student_main_menu, show_manager_main_menu, show_developer_main_menu, show_observer_main_menu
    print("4. Testing main menus photo restoration...")
    with patch("bot.handlers.get_progress", return_value=1), \
         patch("bot.handlers.get_available_day", return_value=1), \
         patch("bot.handlers._all_days_accessible", new_callable=AsyncMock, return_value=False), \
         patch("bot.handlers.initialize_user_progress"):
        
        # Student menu from text message
        msg1 = MagicMock(spec=Message)
        msg1.photo = None
        msg1.delete = AsyncMock()
        msg1.answer_photo = AsyncMock()
        await show_student_main_menu(msg1, user_id=123, allow_edit=True)
        msg1.delete.assert_awaited_once()
        msg1.answer_photo.assert_awaited_once()
        assert "b_start.jpg" in str(msg1.answer_photo.call_args[1]["photo"].path)
        print("  ✓ show_student_main_menu restores b_start.jpg")

        # Manager menu from text message
        msg2 = MagicMock(spec=Message)
        msg2.photo = None
        msg2.delete = AsyncMock()
        msg2.answer_photo = AsyncMock()
        await show_manager_main_menu(msg2, allow_edit=True)
        msg2.delete.assert_awaited_once()
        msg2.answer_photo.assert_awaited_once()
        assert "k_menu.jpg" in str(msg2.answer_photo.call_args[1]["photo"].path)
        print("  ✓ show_manager_main_menu restores k_menu.jpg")

        # Developer menu from text message
        msg3 = MagicMock(spec=Message)
        msg3.photo = None
        msg3.delete = AsyncMock()
        msg3.answer_photo = AsyncMock()
        await show_developer_main_menu(msg3, allow_edit=True)
        msg3.delete.assert_awaited_once()
        msg3.answer_photo.assert_awaited_once()
        assert "admin_cho.jpg" in str(msg3.answer_photo.call_args[1]["photo"].path)
        print("  ✓ show_developer_main_menu restores admin_cho.jpg")

        # Observer menu from text message
        msg4 = MagicMock(spec=Message)
        msg4.photo = None
        msg4.delete = AsyncMock()
        msg4.answer_photo = AsyncMock()
        await show_observer_main_menu(msg4, allow_edit=True)
        msg4.delete.assert_awaited_once()
        msg4.answer_photo.assert_awaited_once()
        assert "admin_cho.jpg" in str(msg4.answer_photo.call_args[1]["photo"].path)
        print("  ✓ show_observer_main_menu restores admin_cho.jpg")
    print("✅ All root main menus verified!\n")

    # 5. Testing developer category handlers photo restoration from text callback
    print("5. Testing admin categories photo restoration when returning from text submenus...")
    
    async def create_mock_callback():
        cb = MagicMock(spec=CallbackQuery)
        cb.from_user = MagicMock()
        cb.from_user.id = 999999
        cb.message = MagicMock(spec=Message)
        cb.message.photo = None
        cb.message.delete = AsyncMock()
        cb.message.answer_photo = AsyncMock()
        cb.message.answer = AsyncMock()
        cb.answer = AsyncMock()
        return cb

    with patch("bot.menus.developer._check_access", new_callable=AsyncMock, return_value=(True, True, False)), \
         patch("bot.menus.developer.is_observer_user", new_callable=AsyncMock, return_value=False):
        
        # developer_menu_callback
        cb_root = await create_mock_callback()
        await developer_menu_callback(cb_root)
        cb_root.message.delete.assert_awaited_once()
        cb_root.message.answer_photo.assert_awaited_once()
        assert "admin_cho.jpg" in str(cb_root.message.answer_photo.call_args[1]["photo"].path)
        print("  ✓ developer_menu_callback restores admin_cho.jpg")

        # dev_main_study_handler
        cb_study = await create_mock_callback()
        await dev_main_study_handler(cb_study)
        cb_study.message.delete.assert_awaited_once()
        cb_study.message.answer_photo.assert_awaited_once()
        assert "admin_study.jpg" in str(cb_study.message.answer_photo.call_args[1]["photo"].path)
        print("  ✓ dev_main_study_handler restores admin_study.jpg")

        # dev_main_analyt_handler
        cb_analyt = await create_mock_callback()
        await dev_main_analyt_handler(cb_analyt)
        cb_analyt.message.delete.assert_awaited_once()
        cb_analyt.message.answer_photo.assert_awaited_once()
        assert "admin_analyt.jpg" in str(cb_analyt.message.answer_photo.call_args[1]["photo"].path)
        print("  ✓ dev_main_analyt_handler restores admin_analyt.jpg")

        # dev_main_team_handler
        cb_team = await create_mock_callback()
        await dev_main_team_handler(cb_team)
        cb_team.message.delete.assert_awaited_once()
        cb_team.message.answer_photo.assert_awaited_once()
        assert "admin_spus.jpg" in str(cb_team.message.answer_photo.call_args[1]["photo"].path)
        print("  ✓ dev_main_team_handler restores admin_spus.jpg")

        # dev_main_other_handler
        cb_other = await create_mock_callback()
        await dev_main_other_handler(cb_other)
        cb_other.message.delete.assert_awaited_once()
        cb_other.message.answer_photo.assert_awaited_once()
        assert "admin_tools.jpg" in str(cb_other.message.answer_photo.call_args[1]["photo"].path)
        print("  ✓ dev_main_other_handler restores admin_tools.jpg")

    print("✅ All 4 admin categories and root panel reliably restore photo headers!\n")
    print("🎉 ALL MENU PHOTO RESTORATION TESTS PASSED 100%!")

if __name__ == "__main__":
    asyncio.run(run_tests())
