"""
Global dictionaries and helpers for Bulka roles/cities/content types.

⚠️  ВАЖЛИВО (Крок 1 реформи):
    Починаючи з цього оновлення, джерело правди для посад — таблиця `positions`
    у базі даних users.db. Список AVAILABLE_ROLES нижче є FALLBACK-резервом
    для зворотної сумісності (стара логіка, cold-start без БД).

    Для читання посад використовуй: database.positions.get_all_positions()
    Для перевірки посади: database.positions.get_position_by_name(name)
"""

from typing import Optional

# FALLBACK: список посад для зворотної сумісності.
# Основне джерело правди — таблиця `positions` у БД.
# Не видаляй цей список — він потрібен для is_valid_role() у синхронному коді.
AVAILABLE_ROLES = [
    "Старший продавець",
    "Керівник",
    "Продавець-консультант (каса)",
    "Продавець відділу гастрономії",
    "Продавець відділу кулінарії",
    "Продавець (сер. зміна)",
    "Продавець-приймальник",
    "ВВ Завідувач виробництва",
    "ВВ Старший зміни",    
    "ВВ Пекар",
    "ВВ Піцейолог",
    "ВВ Кухар",
    "ВВ Кондитер",
    "ВВ Бариста",
    "ВВ Керівник мережі кавʼярень",
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
        "B-33 вул. проспект Грушевського, 50",
    ]
}

CONTENT_TYPES = ["comic", "info", "text"]

TERRITORIAL_TYPES = {
    "ТЗ": "🏪 Торговий зал",
    "ВВ": "🍞 Власне виробництво",
}

POSITION_TYPES = {
    "ТЗ": "🏪 ТЗ",
    "ВВ": "🍞 ВВ",
    "РЦ": "📦 РЦ",
    "ОФІС": "🏢 ОФІС",
}

VALID_POSITION_TYPES = tuple(POSITION_TYPES.keys())


def is_valid_role(role: Optional[str]) -> bool:
    """
    Синхронна перевірка посади — використовує AVAILABLE_ROLES як fallback.
    Для асинхронної перевірки через БД використовуй get_position_by_name().
    """
    return bool(role) and role in AVAILABLE_ROLES


def is_valid_city(city: Optional[str]) -> bool:
    """Return True if the city exists in the directory."""
    return bool(city) and city in AVAILABLE_CITIES


__all__ = [
    "AVAILABLE_ROLES",
    "AVAILABLE_CITIES",
    "AVAILABLE_SHOPS",
    "CONTENT_TYPES",
    "TERRITORIAL_TYPES",
    "POSITION_TYPES",
    "VALID_POSITION_TYPES",
    "is_valid_role",
    "is_valid_city",
]
