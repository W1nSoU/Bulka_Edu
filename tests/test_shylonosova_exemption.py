import unittest
from unittest.mock import patch, AsyncMock
from database.managers import is_user_without_store_manager


class TestShylonosovaExemption(unittest.IsolatedAsyncioTestCase):
    @patch("database.managers.get_manager_by_uid")
    @patch("database.managers.is_territorial_user")
    @patch("database.managers.get_manager_by_shop")
    async def test_intern_assigned_to_shylonosova(self, mock_get_shop, mock_is_terr, mock_get_mgr):
        # 1. Шилоносова активна і є територіалом
        def get_mgr_side_effect(uid):
            if uid == 999999:
                return {
                    "uid": 999999,
                    "full_name": "Шилоносова Валерія Олексіївна",
                    "process": "Територіал",
                    "status": "active"
                }
            return None

        mock_get_mgr.side_effect = get_mgr_side_effect
        mock_is_terr.return_value = True
        mock_get_shop.return_value = None  # Немає окремого директора магазину

        user = {
            "user_id": 12345,
            "role": "Продавець",
            "manager_id": 999999,
            "city": "Камʼянець-Подільський",
            "shop": "TK-8, КП, вул. Коновальця 5А (TIKO KAVA)"
        }

        # Очікуємо False (має керівника!)
        result = await is_user_without_store_manager(user)
        self.assertFalse(result)

    @patch("database.managers.get_manager_by_uid")
    @patch("database.managers.is_territorial_user")
    @patch("database.managers.get_manager_by_shop")
    async def test_intern_assigned_to_other_territorial(self, mock_get_shop, mock_is_terr, mock_get_mgr):
        # 2. Інший територіал без директора магазину
        def get_mgr_side_effect(uid):
            if uid == 888888:
                return {
                    "uid": 888888,
                    "full_name": "Кушнір Андрій Васильович",
                    "process": "Територіал",
                    "status": "active"
                }
            return None

        mock_get_mgr.side_effect = get_mgr_side_effect
        mock_is_terr.return_value = True
        mock_get_shop.return_value = None

        user = {
            "user_id": 54321,
            "role": "Продавець",
            "manager_id": 888888,
            "city": "Хмельницький",
            "shop": "B-1 вул. Степана Бандери, 17"
        }

        # Очікуємо True (без директора магазину, висить на територіалі)
        result = await is_user_without_store_manager(user)
        self.assertTrue(result)

    @patch("database.managers.get_manager_by_uid")
    async def test_intern_assigned_to_fired_shylonosova(self, mock_get_mgr):
        # 3. Якщо керівник зі статусом fired -> вважається без керівника
        def get_mgr_side_effect(uid):
            if uid == 999999:
                return {
                    "uid": 999999,
                    "full_name": "Шилоносова Валерія Олексіївна",
                    "process": "Територіал",
                    "status": "fired"
                }
            return None

        mock_get_mgr.side_effect = get_mgr_side_effect

        user = {
            "user_id": 12345,
            "role": "Продавець",
            "manager_id": 999999,
            "city": "Камʼянець-Подільський",
            "shop": "TK-8"
        }

        result = await is_user_without_store_manager(user)
        self.assertTrue(result)

    async def test_intern_without_manager_id(self):
        user = {
            "user_id": 12345,
            "role": "Продавець",
            "manager_id": None,
            "city": "Камʼянець-Подільський",
            "shop": "TK-8"
        }
        result = await is_user_without_store_manager(user)
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
