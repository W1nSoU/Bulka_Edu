from __future__ import annotations
import aiosqlite
import logging
import re
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
import pytz
from bot.config import TIMEZONE
from . import DB_PATH

logger = logging.getLogger(__name__)


def get_current_kyiv_time_str() -> str:
    """Повертає поточний час у часовому поясі Europe/Kyiv у форматі YYYY-MM-DD HH:MM:SS."""
    tz = pytz.timezone(TIMEZONE)
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")


def normalize_hashtag(raw_name: str) -> str:
    """
    Нормалізує текст категорії до валідного хештегу:
    - Прибирає зайві пробіли.
    - Замінює внутрішні пробіли та дефіси на підкреслення.
    - Видаляє неприпустимі спецсимволи.
    - Гарантує знак '#' на початку.
    """
    cleaned = raw_name.strip()
    if cleaned.startswith("#"):
        cleaned = cleaned[1:].strip()

    # Замінюємо пробіли та дефіси на підкреслення
    cleaned = re.sub(r"[\s\-]+", "_", cleaned)
    # Залишаємо лише літери (включаючи українські), цифри та підкреслення
    cleaned = re.sub(r"[^\w_а-яА-ЯіїєґІЇЄҐ]", "", cleaned)

    return f"#{cleaned}" if cleaned else ""


async def init_news_db(db_path: str = DB_PATH) -> None:
    """Ініціалізує таблиці для новин та категорій у базі даних."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS news_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP,
            created_by INTEGER NOT NULL
        )
        """)
        await db.commit()
    logger.info("News database initialized successfully.")


async def get_all_news_categories(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Повертає список усіх категорій новин, відсортованих за ID."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM news_categories ORDER BY id ASC")
        rows = await cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["hashtag"] = d["name"].lstrip("#")
            result.append(d)
        return result


async def get_news_category_by_id(category_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Отримує категорію за її ID."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM news_categories WHERE id = ?", (category_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        d["hashtag"] = d["name"].lstrip("#")
        return d


async def add_news_category(
    name: str,
    created_by: int,
    db_path: str = DB_PATH
) -> Tuple[bool, str, Optional[int]]:
    """
    Додає нову категорію-хештег.
    Повертає (success, message, new_id).
    """
    tag = normalize_hashtag(name)
    if not tag or len(tag) < 2:
        return False, "Некоректна назва категорії. Використовуйте літери або цифри.", None

    if len(tag) > 50:
        return False, "Назва категорії занадто довга (максимум 50 символів).", None

    now_str = get_current_kyiv_time_str()

    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO news_categories (name, created_at, created_by)
                VALUES (?, ?, ?)
                """,
                (tag, now_str, created_by)
            )
            cat_id = cursor.lastrowid
            await db.commit()
            return True, f"Категорію <b>{tag}</b> успішно додано!", cat_id
    except aiosqlite.IntegrityError:
        return False, f"Категорія <b>{tag}</b> вже існує в системі.", None
    except Exception as e:
        logger.exception(f"Error adding news category: {e}")
        return False, f"Помилка при збереженні категорії: {e}", None


async def delete_news_category(category_id: int, db_path: str = DB_PATH) -> bool:
    """Видаляє категорію новин за ID."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("DELETE FROM news_categories WHERE id = ?", (category_id,))
        await db.commit()
        return cursor.rowcount > 0


async def get_matching_news_recipients(
    roles: List[str],
    target_city: str = "all",
    db_path: str = DB_PATH
) -> List[int]:
    """
    Повертає список унікальних telegram user_id для розсилки новини.
    Виключає звільнених (status == 'fired' у managers.db) та неактивних користувачів.
    """
    from database.surveys import get_matching_survey_recipients
    from database.managers import MANAGERS_DB_PATH

    recipients = await get_matching_survey_recipients(roles, target_city, db_path=db_path)
    
    # Додаткова перевірка звільнених менеджерів/керівників у managers.db
    try:
        async with aiosqlite.connect(MANAGERS_DB_PATH) as m_db:
            cur = await m_db.execute("SELECT uid FROM managers WHERE status = 'fired'")
            fired_uids = {r[0] for r in await cur.fetchall() if r[0]}
            if fired_uids:
                recipients = [uid for uid in recipients if uid not in fired_uids]
    except Exception:
        pass

    return recipients

