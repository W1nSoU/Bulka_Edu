import os
import asyncio
from bot.menus.developer import (
    _admin_cho_keyboard,
    _admin_study_keyboard,
    _admin_analyt_keyboard,
    _admin_team_keyboard,
    _admin_other_keyboard,
    _materials_menu_keyboard,
    _territorials_menu_keyboard,
    _users_menu_keyboard,
    _build_dev_team_view,
    _positions_keyboard,
    _cities_keyboard
)
from database.managers import init_managers_db


async def run_tests():
    print("🚀 Starting Admin Panel Restructuring & Renaming (Пункт 9) tests...")
    await init_managers_db()

    # 1. Test image files existence
    print("\n1. Verifying admin header photos in img/admin/...")
    required_images = [
        "img/admin/admin_cho.jpg",
        "img/admin/admin_study.jpg",
        "img/admin/admin_analyt.jpg",
        "img/admin/admin_spus.jpg",
        "img/admin/admin_tools.jpg"
    ]
    for img_path in required_images:
        assert os.path.exists(img_path), f"Missing required admin image: {img_path}"
        assert os.path.getsize(img_path) > 0, f"Image {img_path} is empty"
    print("✅ All 5 admin photo headers exist and are valid files.")

    # 2. Test Category Choice Keyboard (admin_cho)
    print("\n2. Verifying _admin_cho_keyboard categories...")
    cho_kb = _admin_cho_keyboard(is_main_dev=True, is_admin=True, is_territorial=False)
    cho_callbacks = [btn.callback_data for row in cho_kb.inline_keyboard for btn in row]
    
    assert "dev_main_study" in cho_callbacks, "Missing study category"
    assert "dev_main_analyt" in cho_callbacks, "Missing analytics category"
    assert "dev_main_team" in cho_callbacks, "Missing team category"
    assert "dev_main_other" in cho_callbacks, "Missing other category"
    assert "main_menu" in cho_callbacks, "Missing main_menu button"
    print("✅ _admin_cho_keyboard contains all 4 categories and main_menu!")

    # 3. Test Study Category Keyboard (admin_study)
    print("\n3. Verifying _admin_study_keyboard...")
    study_kb = _admin_study_keyboard()
    study_callbacks = [btn.callback_data for row in study_kb.inline_keyboard for btn in row]
    assert "dev_materials_menu" in study_callbacks
    assert "dev_videos_menu" in study_callbacks
    assert "dev_tests_menu" in study_callbacks
    assert "dev_photos_menu" in study_callbacks
    assert "dev_syllabus_menu" in study_callbacks
    assert "remind_topic_global" in study_callbacks
    assert "developer_menu" in study_callbacks
    print("✅ _admin_study_keyboard contains all study tools & back to developer_menu!")

    # 4. Test Analytics Category Keyboard (admin_analyt)
    print("\n4. Verifying _admin_analyt_keyboard...")
    analyt_kb = _admin_analyt_keyboard(is_observer=False)
    analyt_callbacks = [btn.callback_data for row in analyt_kb.inline_keyboard for btn in row]
    assert "dev_analytics_menu" in analyt_callbacks
    assert "show_test_errors" in analyt_callbacks
    assert "dev_an_ack_menu" in analyt_callbacks
    assert "dev_reminder_history" in analyt_callbacks
    assert "dev_xlsx_menu" in analyt_callbacks
    assert "developer_menu" in analyt_callbacks
    print("✅ _admin_analyt_keyboard contains analytics, test errors, ack, history, xlsx & back to developer_menu!")

    # 5. Test Team Category Keyboard (admin_spus)
    print("\n5. Verifying _admin_team_keyboard...")
    team_kb = _admin_team_keyboard(is_admin=True, is_territorial=False)
    team_callbacks = [btn.callback_data for row in team_kb.inline_keyboard for btn in row]
    assert "dev_users_menu" in team_callbacks
    assert "dev_manage_managers" in team_callbacks
    assert "dev_team_menu" in team_callbacks
    assert "dev_territorials_menu" in team_callbacks
    assert "dev_observers_menu" in team_callbacks
    assert "developer_menu" in team_callbacks
    
    # Check button text for Admin Team
    admin_team_btn = [btn for row in team_kb.inline_keyboard for btn in row if btn.callback_data == "dev_team_menu"][0]
    assert "Команда Адміністраторів" in admin_team_btn.text, f"Expected 'Команда Адміністраторів', got '{admin_team_btn.text}'"
    print("✅ _admin_team_keyboard contains users, managers, admins, territorials, observers & correct button text!")

    # 6. Test Other Category Keyboard (admin_tools)
    print("\n6. Verifying _admin_other_keyboard...")
    other_kb = _admin_other_keyboard()
    other_callbacks = [btn.callback_data for row in other_kb.inline_keyboard for btn in row]
    assert "dev_positions_menu" in other_callbacks
    assert "dev_cities_menu" in other_callbacks
    assert "dev_tokens_menu" in other_callbacks
    assert "dev_health_status" in other_callbacks
    assert "developer_menu" in other_callbacks
    print("✅ _admin_other_keyboard contains positions, cities, tokens, health & back to developer_menu!")

    # 7. Test Submenu Back Navigation
    print("\n7. Verifying Submenu Back Navigation...")
    # Materials menu returns to dev_main_study
    mat_kb = _materials_menu_keyboard()
    assert any(btn.callback_data == "dev_main_study" for row in mat_kb.inline_keyboard for btn in row)
    
    # Territorials menu returns to dev_main_team
    terr_kb = _territorials_menu_keyboard()
    assert any(btn.callback_data == "dev_main_team" for row in terr_kb.inline_keyboard for btn in row)

    # Users menu returns to dev_main_team
    users_kb = _users_menu_keyboard(is_admin=True, is_territorial=False)
    assert any(btn.callback_data == "dev_main_team" for row in users_kb.inline_keyboard for btn in row)

    # Positions menu returns to dev_main_other
    pos_kb = _positions_keyboard([])
    assert any(btn.callback_data == "dev_main_other" for row in pos_kb.inline_keyboard for btn in row)

    # Cities menu returns to dev_main_other
    city_kb = _cities_keyboard([])
    assert any(btn.callback_data == "dev_main_other" for row in city_kb.inline_keyboard for btn in row)

    # Dev Team view returns to dev_main_team
    _, dev_team_kb = await _build_dev_team_view()
    assert any(btn.callback_data == "dev_main_team" for row in dev_team_kb.inline_keyboard for btn in row)

    print("✅ All submenus cleanly navigate back to their respective parent categories!")

    print("\n🎉 ALL POINT 9 ADMIN PANEL RESTRUCTURING TESTS PASSED 100%!")


if __name__ == "__main__":
    asyncio.run(run_tests())
