"""
Global dictionaries and helpers for Bulka roles/cities/content types.
"""

AVAILABLE_ROLES = [
    "Старший продавець",
    "Продавець-консультант (каса)",
    "Продавець відділу гастрономії",
    "Продавець відділу кулінарії",
    "Продавець (сер. зміна)",
    "Продавець-приймальник",
    "Підсобний робітник",
]

AVAILABLE_CITIES = [
    "Хмельницький",
    "Камʼянець-Подільський",
    "Деражня",
]

CONTENT_TYPES = ["video", "comic", "info", "text"]


def is_valid_role(role: str | None) -> bool:
    """Return True if the role exists in the directory."""
    return bool(role) and role in AVAILABLE_ROLES


def is_valid_city(city: str | None) -> bool:
    """Return True if the city exists in the directory."""
    return bool(city) and city in AVAILABLE_CITIES


__all__ = [
    "AVAILABLE_ROLES",
    "AVAILABLE_CITIES",
    "CONTENT_TYPES",
    "is_valid_role",
    "is_valid_city",
]
