import asyncio
from bot.keyboards import learning_menu_keyboard
from bot.services.learning_progress import DayStatus
from bot.menus.developer import _build_dev_days_picker_keyboard


def test_learning_menu_keyboard_pagination():
    print("Testing learning_menu_keyboard pagination...")

    # Case 1: 5 days (<= 6) -> No pagination row
    days_5 = [(d, DayStatus.COMPLETED if d == 1 else DayStatus.OPEN if d == 2 else DayStatus.CLOSED) for d in range(1, 6)]
    kb_5 = learning_menu_keyboard(days_5, syllabus_enabled=True, total_days=5, page=0)
    
    # Check that day buttons are 5
    day_btns_5 = [row[0] for row in kb_5.inline_keyboard if any(row[0].callback_data.startswith(p) for p in ["day_", "locked_"])]
    assert len(day_btns_5) == 5, f"Expected 5 day buttons, got {len(day_btns_5)}"
    
    # Check no navigation row exists
    nav_rows_5 = [row for row in kb_5.inline_keyboard if any(btn.callback_data == "ignore" or btn.callback_data.startswith("learning_days_page:") for btn in row)]
    assert len(nav_rows_5) == 0, f"Expected 0 nav rows for 5 days, got {len(nav_rows_5)}"
    print("✓ 5 days keyboard: 1 page, no nav row.")

    # Case 2: 8 days (> 6) -> 2 pages
    days_8 = [(d, DayStatus.OPEN) for d in range(1, 9)]
    
    # Page 0 (Days 1..6)
    kb_8_p0 = learning_menu_keyboard(days_8, syllabus_enabled=True, total_days=8, page=0)
    day_btns_8_p0 = [row[0] for row in kb_8_p0.inline_keyboard if any(row[0].callback_data.startswith(p) for p in ["day_", "locked_"])]
    assert len(day_btns_8_p0) == 6, f"Expected 6 day buttons on page 0, got {len(day_btns_8_p0)}"
    assert day_btns_8_p0[0].callback_data == "day_1"
    assert day_btns_8_p0[-1].callback_data == "day_6"
    
    nav_rows_8_p0 = [row for row in kb_8_p0.inline_keyboard if any(btn.callback_data == "ignore" for btn in row)]
    assert len(nav_rows_8_p0) == 1, "Expected 1 nav row on page 0"
    nav_p0 = nav_rows_8_p0[0]
    assert len(nav_p0) == 2, f"Expected 2 buttons in nav row on first page (page_indicator, next), got {len(nav_p0)}"
    assert nav_p0[0].text == "📄 1/2"
    assert nav_p0[1].callback_data == "learning_days_page:1"
    
    # Page 1 (Days 7..8)
    kb_8_p1 = learning_menu_keyboard(days_8, syllabus_enabled=True, total_days=8, page=1)
    day_btns_8_p1 = [row[0] for row in kb_8_p1.inline_keyboard if any(row[0].callback_data.startswith(p) for p in ["day_", "locked_"])]
    assert len(day_btns_8_p1) == 2, f"Expected 2 day buttons on page 1, got {len(day_btns_8_p1)}"
    assert day_btns_8_p1[0].callback_data == "day_7"
    assert day_btns_8_p1[1].callback_data == "day_8"
    
    nav_rows_8_p1 = [row for row in kb_8_p1.inline_keyboard if any(btn.callback_data == "ignore" for btn in row)]
    assert len(nav_rows_8_p1) == 1
    nav_p1 = nav_rows_8_p1[0]
    assert len(nav_p1) == 2, f"Expected 2 buttons in nav row on last page (prev, page_indicator), got {len(nav_p1)}"
    assert nav_p1[0].callback_data == "learning_days_page:0"
    assert nav_p1[1].text == "📄 2/2"
    print("✓ 8 days keyboard: 2 pages, correct days per page and navigation buttons.")

    # Case 3: 15 days -> 3 pages
    days_15 = [(d, DayStatus.OPEN) for d in range(1, 16)]
    kb_15_p1 = learning_menu_keyboard(days_15, syllabus_enabled=True, total_days=15, page=1)
    day_btns_15_p1 = [row[0] for row in kb_15_p1.inline_keyboard if any(row[0].callback_data.startswith(p) for p in ["day_", "locked_"])]
    assert len(day_btns_15_p1) == 6
    assert day_btns_15_p1[0].callback_data == "day_7"
    assert day_btns_15_p1[-1].callback_data == "day_12"
    
    nav_p1 = [row for row in kb_15_p1.inline_keyboard if any(btn.callback_data == "ignore" for btn in row)][0]
    assert len(nav_p1) == 3, f"Expected 3 buttons in middle page nav row (prev, indicator, next), got {len(nav_p1)}"
    assert nav_p1[0].callback_data == "learning_days_page:0"
    assert nav_p1[1].text == "📄 2/3"
    assert nav_p1[2].callback_data == "learning_days_page:2"
    print("✓ 15 days keyboard: 3 pages, middle page has prev, indicator, next.")


async def test_dev_days_picker_pagination():
    print("\nTesting _build_dev_days_picker_keyboard...")
    
    # We test with a role or mock
    from database.positions import get_days_count_for_role, add_position
    
    # Add a mock 8-day position for testing if needed
    try:
        await add_position("Тестова Посада 8 Днів", 8, False)
    except Exception:
        pass
    
    kb_p0 = await _build_dev_days_picker_keyboard("Тестова Посада 8 Днів", "dev_mat_day", "dev_materials_menu", page=0)
    day_btns_p0 = [row[0] for row in kb_p0.inline_keyboard if row[0].callback_data.startswith("dev_mat_day|")]
    assert len(day_btns_p0) == 6, f"Expected 6 dev day buttons on page 0, got {len(day_btns_p0)}"
    assert day_btns_p0[0].callback_data == "dev_mat_day|1"
    assert day_btns_p0[-1].callback_data == "dev_mat_day|6"
    
    nav_row_p0 = [row for row in kb_p0.inline_keyboard if any(btn.callback_data == "ignore" for btn in row)][0]
    assert nav_row_p0[0].text == "📄 1/2"
    assert nav_row_p0[1].callback_data == "dev_mat_day_pg|1"
    
    kb_p1 = await _build_dev_days_picker_keyboard("Тестова Посада 8 Днів", "dev_mat_day", "dev_materials_menu", page=1)
    day_btns_p1 = [row[0] for row in kb_p1.inline_keyboard if row[0].callback_data.startswith("dev_mat_day|")]
    assert len(day_btns_p1) == 2, f"Expected 2 dev day buttons on page 1, got {len(day_btns_p1)}"
    assert day_btns_p1[0].callback_data == "dev_mat_day|7"
    assert day_btns_p1[1].callback_data == "dev_mat_day|8"
    
    nav_row_p1 = [row for row in kb_p1.inline_keyboard if any(btn.callback_data == "ignore" for btn in row)][0]
    assert nav_row_p1[0].callback_data == "dev_mat_day_pg|0"
    assert nav_row_p1[1].text == "📄 2/2"
    print("✓ Dev days picker keyboard: 2 pages, correct days per page and navigation callbacks.")


    # Cleanup
    from database.positions import delete_position, get_position_by_name
    p = await get_position_by_name("Тестова Посада 8 Днів")
    if p:
        await delete_position(p["id"])


async def main():
    test_learning_menu_keyboard_pagination()
    await test_dev_days_picker_pagination()
    print("\n🎉 ALL DAY PAGINATION TESTS PASSED 100%!")


if __name__ == "__main__":
    asyncio.run(main())
