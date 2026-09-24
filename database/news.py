from __future__ import annotations
import aiosqlite
import logging
import re
from typing import Optional, List, Dict, Any, Tuple
import json
from datetime import datetime, timedelta
import pytz
from bot.config import TIMEZONE
from . import DB_PATH

logger = logging.getLogger(__name__)

NEWS_REACTIONS = ["👎", "🤔", "❤️", "🔥"]


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
    """Ініціалізує таблиці для новин, категорій, доставок та реакцій у базі даних."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS news_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP,
            created_by INTEGER NOT NULL
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            photo_file_id TEXT,
            selected_roles TEXT,
            selected_city TEXT,
            total_recipients INTEGER DEFAULT 0,
            sent_count INTEGER DEFAULT 0,
            failed_count INTEGER DEFAULT 0,
            total_waves INTEGER DEFAULT 0,
            status TEXT DEFAULT 'in_progress',
            created_at TIMESTAMP,
            created_by INTEGER
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS news_deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            news_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            error_reason TEXT,
            raw_error TEXT,
            delivered_at TIMESTAMP,
            message_id INTEGER,
            FOREIGN KEY(news_id) REFERENCES news(id) ON DELETE CASCADE
        )
        """)
        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_news_deliveries_news_id ON news_deliveries(news_id)
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS news_reactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            news_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            reaction TEXT NOT NULL,
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            UNIQUE(news_id, user_id),
            FOREIGN KEY(news_id) REFERENCES news(id) ON DELETE CASCADE
        )
        """)
        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_news_reactions_news_id ON news_reactions(news_id)
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


async def create_news(
    text: str,
    photo_file_id: Optional[str] = None,
    selected_roles: Optional[List[str]] = None,
    selected_city: str = "all",
    total_recipients: int = 0,
    total_waves: int = 0,
    created_by: int = 0,
    db_path: str = DB_PATH
) -> int:
    """Створює запис про нову публікацію в таблиці news та повертає її ID."""
    roles_json = json.dumps(selected_roles or [], ensure_ascii=False)
    now_str = get_current_kyiv_time_str()

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO news (
                text, photo_file_id, selected_roles, selected_city,
                total_recipients, total_waves, status, created_at, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, 'in_progress', ?, ?)
            """,
            (text, photo_file_id, roles_json, selected_city, total_recipients, total_waves, now_str, created_by)
        )
        news_id = cursor.lastrowid
        await db.commit()
    return news_id


async def update_news_stats(
    news_id: int,
    sent_count: int,
    failed_count: int,
    status: str = "completed",
    db_path: str = DB_PATH
) -> None:
    """Оновлює статистику відправки публікації."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            UPDATE news
            SET sent_count = ?, failed_count = ?, status = ?
            WHERE id = ?
            """,
            (sent_count, failed_count, status, news_id)
        )
        await db.commit()


async def record_delivery(
    news_id: int,
    user_id: int,
    status: str,
    error_reason: Optional[str] = None,
    raw_error: Optional[str] = None,
    message_id: Optional[int] = None,
    db_path: str = DB_PATH
) -> None:
    """Записує факт доставки чи помилки одному користувачу."""
    now_str = get_current_kyiv_time_str()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO news_deliveries (
                news_id, user_id, status, error_reason, raw_error, delivered_at, message_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (news_id, user_id, status, error_reason, raw_error, now_str, message_id)
        )
        await db.commit()


async def record_deliveries_batch(
    deliveries: List[Dict[str, Any]],
    db_path: str = DB_PATH
) -> None:
    """Пакетно записує результати доставки у news_deliveries."""
    if not deliveries:
        return
    now_str = get_current_kyiv_time_str()
    params = [
        (
            d["news_id"],
            d["user_id"],
            d["status"],
            d.get("error_reason"),
            d.get("raw_error"),
            d.get("delivered_at") or now_str,
            d.get("message_id")
        )
        for d in deliveries
    ]
    async with aiosqlite.connect(db_path) as db:
        await db.executemany(
            """
            INSERT INTO news_deliveries (
                news_id, user_id, status, error_reason, raw_error, delivered_at, message_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            params
        )
        await db.commit()


async def get_news_by_id(news_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Повертає новину за ID з десеріалізованими ролями."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM news WHERE id = ?", (news_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["selected_roles"] = json.loads(d.get("selected_roles") or "[]")
        except Exception:
            d["selected_roles"] = []
        return d


async def get_news_history_last_6_months(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """
    Повертає список новин, опублікованих за останні 6 місяців (180 днів),
    відсортованих від найновіших до старіших.
    """
    tz = pytz.timezone(TIMEZONE)
    cutoff = (datetime.now(tz) - timedelta(days=180)).strftime("%Y-%m-%d %H:%M:%S")

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM news WHERE created_at >= ? ORDER BY id DESC",
            (cutoff,)
        )
        rows = await cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["selected_roles"] = json.loads(d.get("selected_roles") or "[]")
            except Exception:
                d["selected_roles"] = []
            result.append(d)
        return result


async def upsert_news_reaction(
    news_id: int,
    user_id: int,
    reaction: str,
    db_path: str = DB_PATH
) -> bool:
    """
    Додає або оновлює реакцію користувача на новину.
    Повертає True у разі успіху.
    """
    now_str = get_current_kyiv_time_str()
    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                """
                INSERT INTO news_reactions (news_id, user_id, reaction, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(news_id, user_id) DO UPDATE SET
                    reaction = excluded.reaction,
                    updated_at = excluded.updated_at
                """,
                (news_id, user_id, reaction, now_str, now_str)
            )
            await db.commit()
            return True
    except Exception as e:
        logger.exception(f"Error upserting news reaction: {e}")
        return False


async def get_user_news_reaction(
    news_id: int,
    user_id: int,
    db_path: str = DB_PATH
) -> Optional[str]:
    """Повертає поточну реакцію користувача на новину (якщо є)."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT reaction FROM news_reactions WHERE news_id = ? AND user_id = ?",
            (news_id, user_id)
        )
        row = await cursor.fetchone()
        return row[0] if row else None


async def get_news_reactions_summary(
    news_id: int,
    db_path: str = DB_PATH
) -> Dict[str, Any]:
    """
    Повертає статистику реакцій для новини:
    {
        "total": int,
        "breakdown": {"👎": int, "🤔": int, "❤️": int, "🔥": int}
    }
    """
    breakdown = {r: 0 for r in NEWS_REACTIONS}
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT reaction, COUNT(*) FROM news_reactions WHERE news_id = ? GROUP BY reaction",
            (news_id,)
        )
        rows = await cursor.fetchall()
        for r, cnt in rows:
            if r in breakdown:
                breakdown[r] = cnt
            else:
                breakdown[r] = cnt

    total = sum(breakdown.values())
    return {"total": total, "breakdown": breakdown}


async def get_news_failed_deliveries_detailed(
    news_id: int,
    db_path: str = DB_PATH
) -> List[Dict[str, Any]]:
    """
    Повертає список недоставлених повідомлень для новини,
    збагачений даними про користувача (ПІБ, посада, місто, магазин) з таблиці users.
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT 
                d.id,
                d.news_id,
                d.user_id,
                d.status,
                d.error_reason,
                d.raw_error,
                d.delivered_at,
                u.full_name,
                u.role,
                u.city,
                u.shop,
                u.username
            FROM news_deliveries d
            LEFT JOIN users u ON d.user_id = u.user_id
            WHERE d.news_id = ? AND d.status = 'failed'
            ORDER BY d.id ASC
            """,
            (news_id,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_news_reactions_detailed(
    news_id: int,
    db_path: str = DB_PATH
) -> List[Dict[str, Any]]:
    """
    Повертає список залишених реакцій на новину,
    збагачений даними про користувача з таблиці users.
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT 
                r.id,
                r.news_id,
                r.user_id,
                r.reaction,
                r.created_at,
                r.updated_at,
                u.full_name,
                u.role,
                u.city,
                u.shop,
                u.username
            FROM news_reactions r
            LEFT JOIN users u ON r.user_id = u.user_id
            WHERE r.news_id = ?
            ORDER BY r.id ASC
            """,
            (news_id,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


