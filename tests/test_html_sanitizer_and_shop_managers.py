import unittest
import asyncio
from bot.utils.message_utils import sanitize_telegram_html
from database.shops import (
    _normalize_city_name,
    _get_base_city,
    _is_manager_city_match,
)


class TestHtmlSanitizer(unittest.TestCase):
    def test_sanitize_lists(self):
        html_input = "Оголошення:\n<ul><li>Пункт 1</li><li>Пункт 2</li></ul>"
        cleaned = sanitize_telegram_html(html_input)
        self.assertNotIn("<ul>", cleaned)
        self.assertNotIn("<li>", cleaned)
        self.assertIn("• Пункт 1", cleaned)
        self.assertIn("• Пункт 2", cleaned)

    def test_sanitize_unsupported_tags(self):
        html_input = "<h2>Заголовок</h2><p>Текст <span style='color:red'>червоний</span> і <b>жирний</b>.</p>"
        cleaned = sanitize_telegram_html(html_input)
        self.assertNotIn("<h2>", cleaned)
        self.assertNotIn("<p>", cleaned)
        self.assertNotIn("<span", cleaned)
        self.assertIn("<b>Заголовок</b>", cleaned)
        self.assertIn("<b>жирний</b>", cleaned)

    def test_preserve_supported_tags(self):
        html_input = "<b>Bold</b> <i>Italic</i> <u>Underline</u> <code>Code</code> <a href='https://t.me/bulka'>Link</a>"
        cleaned = sanitize_telegram_html(html_input)
        self.assertIn("<b>Bold</b>", cleaned)
        self.assertIn("<i>Italic</i>", cleaned)
        self.assertIn("<u>Underline</u>", cleaned)
        self.assertIn("<code>Code</code>", cleaned)
        self.assertIn('<a href="https://t.me/bulka">Link</a>', cleaned)

    def test_auto_close_tags(self):
        html_input = "<b>Bold text <i>italic without closing"
        cleaned = sanitize_telegram_html(html_input)
        self.assertTrue(cleaned.endswith("</i></b>"))

    def test_orphan_closing_tags(self):
        html_input = "Hello </i></b> World"
        cleaned = sanitize_telegram_html(html_input)
        self.assertEqual(cleaned, "Hello World")

    def test_raw_angles_and_ampersands(self):
        html_input = "Знижка < 50% & акція > 100 грн &amp; <b>супер</b>"
        cleaned = sanitize_telegram_html(html_input)
        self.assertIn("&lt;", cleaned)
        self.assertIn("&amp;", cleaned)
        self.assertIn("<b>супер</b>", cleaned)


class TestShopManagerMatching(unittest.TestCase):
    def test_workshop_city_matching(self):
        # ВЦ Хмельницький matches Хмельницький
        self.assertTrue(_is_manager_city_match("ВЦ Хмельницький", "Хмельницький"))
        self.assertTrue(_is_manager_city_match("Хмельницький", "ВЦ Хмельницький"))

    def test_apostrophe_variants(self):
        self.assertTrue(_is_manager_city_match("Кам'янець-Подільський", "Камʼянець-Подільський"))
        self.assertTrue(_is_manager_city_match("ВЦ Кам'янець-Подільський", "Кам’янець-Подільський"))

    def test_different_cities_do_not_match(self):
        self.assertFalse(_is_manager_city_match("Хмельницький", "Шепетівка"))
        self.assertFalse(_is_manager_city_match("ВЦ Хмельницький", "Кам'янець-Подільський"))

    def test_unassigned_manager_matches_any_city(self):
        self.assertTrue(_is_manager_city_match("Хмельницький", None))
        self.assertTrue(_is_manager_city_match("ВЦ Хмельницький", ""))


if __name__ == "__main__":
    unittest.main()
