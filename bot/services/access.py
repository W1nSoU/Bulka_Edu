"""Helpers for checking user roles and permissions."""

from typing import Optional
from database.hr import is_hr_user, is_developer_user
from database.managers import get_manager_by_uid, is_manager_user, is_territorial_user, is_observer_user # Ensure all manager checks are imported
from database.users import get_user_details
from bot.config import MAIN_DEVELOPER_ID
from bot.services.logger import get_logger

logger = get_logger()


async def is_privileged_user(user_id: int) -> bool:
    """
    Returns True for anyone who should bypass invite checks:
    managers, HR, developers, or the main developer account.
    """
    if user_id == MAIN_DEVELOPER_ID:
        return True

    manager_info = await get_manager_by_uid(user_id)
    if manager_info:
        return True

    if await is_hr_user(user_id):
        return True

    if await is_developer_user(user_id):
        return True

    return False

async def get_display_role(user_id: int) -> str:
    """
    Повертає стандартизовану роль користувача для відображення.
    Можливі значення: 'Адміністратор', 'Керівник', 'Наглядач', 'Територіал', 'Стажер'.
    """
    if user_id == MAIN_DEVELOPER_ID:
        return "Адміністратор"

    if await is_developer_user(user_id):
        return "Адміністратор"

    # is_manager_user перевіряє process IN ('Керівник', 'Керівник Стажер')
    if await is_manager_user(user_id):
        return "Керівник"

    if await is_territorial_user(user_id):
        return "Територіал"

    if await is_observer_user(user_id):
        return "Наглядач"

    # Не є жодним із привілейованих — стажер
    return "Стажер"


async def validate_user_id(raw_value: str, *, context: str = "") -> Optional[int]:
    """
    Централізована валідація user_id з callback data.
    
    Args:
        raw_value: Рядок для парсингу (напр. "123456")
        context: Опис контексту для логів (напр. "remind_topic_for_intern")
    
    Returns:
        int user_id якщо валідний, None якщо ні
    """
    # 1. Перевірка на int
    try:
        user_id = int(raw_value.strip())
    except (ValueError, AttributeError):
        logger.warning(f"[{context}] Invalid user_id format: {raw_value!r}")
        return None
    
    # 2. Перевірка на позитивне число
    if user_id <= 0:
        logger.warning(f"[{context}] Invalid user_id value: {user_id}")
        return None
    
    # 3. Перевірка існування в БД
    user_details = await get_user_details(user_id)
    if not user_details:
        logger.warning(f"[{context}] User not found in DB: {user_id}")
        return None
    
    return user_id


async def validate_intern_id(raw_value: str, *, context: str = "") -> Optional[int]:
    """
    Валідація intern_id з додатковою перевіркою що це не privileged user.
    
    Args:
        raw_value: Рядок для парсингу
        context: Опис контексту для логів
    
    Returns:
        int user_id якщо це стажер, None якщо ні
    """
    user_id = await validate_user_id(raw_value, context=context)
    if user_id is None:
        return None
    
    # Перевірка що це не dev/hr/manager
    if await is_privileged_user(user_id):
        logger.info(f"[{context}] Skipping privileged user: {user_id}")
        return None
    
    return user_id


def parse_callback_id(callback_data: str, prefix: str) -> Optional[str]:
    """
    Парсить ID з callback_data формату "prefix:id" або "prefix|id".
    
    Args:
        callback_data: Повний callback data
        prefix: Очікуваний префікс (напр. "remind_topic_for_intern")
    
    Returns:
        Частина після розділювача або None
    """
    if not callback_data:
        return None
    
    # Підтримуємо обидва формати: ":" та "|"
    for sep in (":", "|"):
        if callback_data.startswith(f"{prefix}{sep}"):
            parts = callback_data.split(sep, 1)
            if len(parts) == 2:
                return parts[1]
    
    return None


__all__ = [
    "is_privileged_user",
    "validate_user_id",
    "validate_intern_id",
    "parse_callback_id",
    "get_display_role", # Add to all
]
