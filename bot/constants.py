"""
Global dictionaries and helpers for Bulka roles/cities/content types.
"""

from typing import Optional

AVAILABLE_ROLES = [
    "Старший продавець",
    "Продавець-консультант (каса)",
    "Продавець відділу гастрономії",
    "Продавець відділу кулінарії",
    "Продавець (сер. зміна)",
    "Продавець-приймальник",
]

AVAILABLE_CITIES = [
    "Хмельницький",
    "Камʼянець-Подільський",
]

AVAILABLE_SHOPS = {
    "Хмельницький": [
        "B-19 вул. Героїв Маріуполя, 62",
        "B-17 проспект Миру, 69",
        "B-4 Деражня",
        "B-24 вул. Камянецька, 52/2",
        "B-29 вул. Шевченка, 39",
        "B-8 вул. Тернопільська, 30/2а",
        "B-1 вул. Степана Бандери, 17",
        "B-20 проспект Миру, 62а",
        "B-12 вул. Олександра Кушнірука, 6/1",
        "B-18 вул. Тернопільська, 20/1",
        "B-23 вул. Залізняка, 8/3",
        "B-26 вул. Водопровідна, 75/2",
        "BAD CAT вул. Зарічанська, 16",
        "B-32 вул. Трудова, 40",
    ],
    "Камʼянець-Подільський": [
        "B-31 вул. Юрія Руфа, 5",
        "B-30 вул. Є. Коновальця, 5а (SAKURA)",
        "B-25 вул. Ярослава Мудрого, 134",
        "B-22 вул. Миру, 4",
        "B-21 вул. Любомира Гузара, 5",
        "B-16 вул. Степана Бандери, 65",
        "B-15 вул. Князів Коріатовичів, 25",
        "B-9 вул. Героїв ЗСУ, 8",
        "B-6 вул. Героїв Небесної Сотні, 4",
        "B-5 вул. Шевченка, 4",
        "B-2 вул. Панівецька, 5",
    ]
}

CONTENT_TYPES = ["comic", "info", "text"]


def is_valid_role(role: Optional[str]) -> bool:
    """Return True if the role exists in the directory."""
    return bool(role) and role in AVAILABLE_ROLES


def is_valid_city(city: Optional[str]) -> bool:
    """Return True if the city exists in the directory."""
    return bool(city) and city in AVAILABLE_CITIES


__all__ = [
    "AVAILABLE_ROLES",
    "AVAILABLE_CITIES",
    "AVAILABLE_SHOPS",
    "CONTENT_TYPES",
    "is_valid_role",
    "is_valid_city",
]
