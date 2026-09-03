import logging
from typing import Optional
from aiogram import Bot
import aiosqlite

from database import DB_PATH
from database.managers import get_manager_by_uid, is_territorial_user, MANAGERS_DB_PATH
from database.users import get_user_details
from database.hr import is_developer_user

logger = logging.getLogger(__name__)


async def get_manager_display_title(bot: Optional[Bot], manager_id: Optional[int]) -> str:
    """
    Повертає відформатований рядок із реальним ПІБ керівника та статусом:
    - Якщо призначено керівника: "ПІБ"
    - Якщо призначено територіала: "ПІБ (Територіал)"
    - Якщо призначено адміністратора: "ПІБ (Адміністратор)"
    - Якщо не призначено: "Не призначено"
    """
    if not manager_id:
        return "Не призначено"

    manager_info = await get_manager_by_uid(manager_id)
    user_info = await get_user_details(manager_id)

    full_name = None
    username = None
    process = None

    if manager_info:
        full_name = manager_info.get("full_name")
        username = manager_info.get("username")
        process = manager_info.get("process")

    if (not full_name or not full_name.strip()) and user_info:
        full_name = user_info.get("full_name")
        if not username:
            username = user_info.get("username")

    # Якщо full_name пустий або дефолтний, пробуємо отримати з Telegram API
    if (not full_name or not full_name.strip() or full_name == "Без імені") and bot:
        try:
            chat = await bot.get_chat(manager_id)
            if chat:
                if not username and chat.username:
                    username = chat.username
                t_fullname = f"{chat.first_name or ''} {chat.last_name or ''}".strip()
                if t_fullname:
                    full_name = t_fullname
                    # Зберігаємо оновлені дані в базах
                    try:
                        async with aiosqlite.connect(MANAGERS_DB_PATH) as m_db:
                            await m_db.execute(
                                "UPDATE managers SET full_name = ?, username = ? WHERE uid = ?",
                                (full_name, username or "", manager_id)
                            )
                            await m_db.commit()
                        async with aiosqlite.connect(DB_PATH) as u_db:
                            await u_db.execute(
                                "UPDATE users SET full_name = ?, username = ? WHERE user_id = ?",
                                (full_name, username or "", manager_id)
                            )
                            await u_db.commit()
                    except Exception as db_exc:
                        logger.debug(f"Failed to cache manager profile: {db_exc}")
        except Exception as exc:
            logger.debug(f"Could not fetch Telegram chat for manager {manager_id}: {exc}")

    # Визначаємо фінальне ім'я (ПІБ або fallback)
    resolved_name = None
    if full_name and full_name.strip():
        resolved_name = full_name.strip()
    elif username and username.strip():
        resolved_name = f"@{username.strip().lstrip('@')}"
    else:
        resolved_name = f"ID: {manager_id}"

    # 1. Якщо це територіал
    is_terr = (process == "Територіал") or await is_territorial_user(manager_id)
    if is_terr:
        return f"{resolved_name} (Територіал)"

    # 2. Якщо це адміністратор / developer (коли немає територіала і керівника)
    is_admin = await is_developer_user(manager_id)
    if is_admin:
        return f"{resolved_name} (Адміністратор)"

    # 3. Звичайний керівник (або керівник-стажер)
    return resolved_name
