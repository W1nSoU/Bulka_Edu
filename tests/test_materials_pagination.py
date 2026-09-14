import unittest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from bot.keyboards import get_pagination_keyboard


class TestMaterialsPaginationKeyboard(unittest.TestCase):
    def test_first_page_has_page_controls_and_back_button(self):
        final_btn = InlineKeyboardButton(text="➡️ До тесту", callback_data="day1_test")
        kb = get_pagination_keyboard(
            current_page=0,
            total_pages=7,
            content_identifier="101",
            day=1,
            final_button=final_btn,
        )
        self.assertIsNotNone(kb)
        rows = kb.inline_keyboard
        self.assertEqual(len(rows), 2)
        
        # Row 0: page indicator and next button
        row0 = rows[0]
        self.assertEqual(len(row0), 2)
        self.assertEqual(row0[0].text, "📄 1/7")
        self.assertEqual(row0[0].callback_data, "do_nothing")
        self.assertEqual(row0[1].text, "Далі ➡️")
        self.assertEqual(row0[1].callback_data, "paginate:101:1:1")
        
        # Row 1: persistent back button
        row1 = rows[1]
        self.assertEqual(len(row1), 1)
        self.assertEqual(row1[0].text, "⬅️ Повернутися до вибору")
        self.assertEqual(row1[0].callback_data, "day_1")

    def test_middle_page_has_both_arrows_and_back_button(self):
        kb = get_pagination_keyboard(
            current_page=3,
            total_pages=7,
            content_identifier="101",
            day=2,
        )
        self.assertIsNotNone(kb)
        rows = kb.inline_keyboard
        self.assertEqual(len(rows), 2)
        
        # Row 0: prev, indicator, next
        row0 = rows[0]
        self.assertEqual(len(row0), 3)
        self.assertEqual(row0[0].text, "⬅️ Назад")
        self.assertEqual(row0[0].callback_data, "paginate:101:2:2")
        self.assertEqual(row0[1].text, "📄 4/7")
        self.assertEqual(row0[2].text, "Далі ➡️")
        self.assertEqual(row0[2].callback_data, "paginate:101:2:4")
        
        # Row 1: back button
        row1 = rows[1]
        self.assertEqual(len(row1), 1)
        self.assertEqual(row1[0].text, "⬅️ Повернутися до вибору")
        self.assertEqual(row1[0].callback_data, "day_2")

    def test_last_page_has_final_action_and_back_button(self):
        final_btn = InlineKeyboardButton(text="➡️ До тесту", callback_data="day1_test")
        kb = get_pagination_keyboard(
            current_page=6,
            total_pages=7,
            content_identifier="101",
            day=1,
            final_button=final_btn,
        )
        self.assertIsNotNone(kb)
        rows = kb.inline_keyboard
        self.assertEqual(len(rows), 3)
        
        # Row 0: prev arrow and indicator
        row0 = rows[0]
        self.assertEqual(len(row0), 2)
        self.assertEqual(row0[0].text, "⬅️ Назад")
        self.assertEqual(row0[0].callback_data, "paginate:101:1:5")
        self.assertEqual(row0[1].text, "📄 7/7")
        
        # Row 1: final action button
        row1 = rows[1]
        self.assertEqual(len(row1), 1)
        self.assertEqual(row1[0].text, "➡️ До тесту")
        self.assertEqual(row1[0].callback_data, "day1_test")
        
        # Row 2: persistent back button
        row2 = rows[2]
        self.assertEqual(len(row2), 1)
        self.assertEqual(row2[0].text, "⬅️ Повернутися до вибору")
        self.assertEqual(row2[0].callback_data, "day_1")

    def test_single_page_material(self):
        final_btn = InlineKeyboardButton(text="✅ Завершити день", callback_data="complete_day_3")
        kb = get_pagination_keyboard(
            current_page=0,
            total_pages=1,
            content_identifier="202",
            day=3,
            final_button=final_btn,
        )
        self.assertIsNotNone(kb)
        rows = kb.inline_keyboard
        # No row 0 page controls because total_pages == 1
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0].text, "✅ Завершити день")
        self.assertEqual(rows[0][0].callback_data, "complete_day_3")
        self.assertEqual(rows[1][0].text, "⬅️ Повернутися до вибору")
        self.assertEqual(rows[1][0].callback_data, "day_3")

    def test_syllabus_day_zero_defaults_to_main_menu(self):
        final_btn = InlineKeyboardButton(text="⬅️ В головне меню", callback_data="main_menu")
        kb = get_pagination_keyboard(
            current_page=0,
            total_pages=3,
            content_identifier="syl",
            day=0,
            final_button=final_btn,
        )
        self.assertIsNotNone(kb)
        rows = kb.inline_keyboard
        # Row 0: controls
        self.assertEqual(len(rows[0]), 2)
        # Row 1: only one 'main_menu' button, no duplicate
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][0].text, "⬅️ В головне меню")
        self.assertEqual(rows[1][0].callback_data, "main_menu")

    def test_custom_back_button(self):
        custom_back = InlineKeyboardButton(text="⬅️ До списку відео", callback_data="custom_video_back")
        kb = get_pagination_keyboard(
            current_page=0,
            total_pages=2,
            content_identifier="vid",
            day=5,
            back_button=custom_back,
        )
        self.assertIsNotNone(kb)
        rows = kb.inline_keyboard
        self.assertEqual(rows[1][0].text, "⬅️ До списку відео")
        self.assertEqual(rows[1][0].callback_data, "custom_video_back")


if __name__ == "__main__":
    unittest.main()
