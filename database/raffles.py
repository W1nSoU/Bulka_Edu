from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite
import pytz

from bot.config import TIMEZONE
from . import DB_PATH

logger = logging.getLogger(__name__)

RAFFLES_MEDIA_DIR = os.path.join(os.path.dirname(DB_PATH), "raffles_media")


def get_current_kyiv_dt() -> datetime:
    """Повертає поточний datetime у часовому поясі Europe/Kyiv."""
    tz = pytz.timezone(TIMEZONE)
    return datetime.now(tz)


def get_current_kyiv_time_str() -> str:
    """Повертає поточний час у часовому поясі Europe/Kyiv у форматі YYYY-MM-DD HH:MM:SS."""
    return get_current_kyiv_dt().strftime("%Y-%m-%d %H:%M:%S")


def _parse_raffle_row(row: aiosqlite.Row) -> Dict[str, Any]:
    """Перетворює рядок з таблиці raffles у словник з десеріалізованими ролями."""
    d = dict(row)
    try:
        parsed_roles = json.loads(d.get("selected_roles") or "[]")
        d["selected_roles"] = parsed_roles if isinstance(parsed_roles, list) else []
    except Exception:
        d["selected_roles"] = []
    d["send_announcement"] = bool(d.get("send_announcement"))
    d["media_cleaned"] = bool(d.get("media_cleaned"))
    return d


async def init_raffles_db(db_path: str = DB_PATH) -> None:
    """Ініціалізує таблиці розіграшів та заявок учасників у базі даних."""
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    os.makedirs(RAFFLES_MEDIA_DIR, exist_ok=True)

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS raffles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                text TEXT NOT NULL,
                media_type TEXT,
                photo_file_id TEXT,
                video_file_id TEXT,
                participation_type TEXT NOT NULL,
                text_format TEXT,
                selected_roles TEXT NOT NULL,
                selected_city TEXT DEFAULT 'all',
                deadline TIMESTAMP NOT NULL,
                send_announcement INTEGER DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                media_cleaned INTEGER DEFAULT 0,
                created_at TIMESTAMP NOT NULL,
                completed_at TIMESTAMP,
                created_by INTEGER NOT NULL
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS raffle_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raffle_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                user_name TEXT,
                user_full_name TEXT,
                shop_name TEXT,
                user_city TEXT,
                user_role TEXT,
                submission_text TEXT,
                media_type TEXT,
                file_id TEXT,
                local_file_path TEXT,
                file_size INTEGER DEFAULT 0,
                created_at TIMESTAMP NOT NULL,
                FOREIGN KEY (raffle_id) REFERENCES raffles(id) ON DELETE CASCADE,
                UNIQUE(raffle_id, user_id)
            )
            """
        )

        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_raffle_submissions_raffle_id ON raffle_submissions(raffle_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_raffles_status_deadline ON raffles(status, deadline)"
        )
        await db.commit()

    logger.info("Raffles database initialized successfully.")


async def check_and_complete_expired_raffles(db_path: str = DB_PATH) -> int:
    """
    Переводить усі активні розіграші, у яких настав дедлайн, у статус 'completed'.
    Повертає кількість завершених розіграшів.
    """
    now_str = get_current_kyiv_time_str()
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            UPDATE raffles
            SET status = 'completed',
                completed_at = COALESCE(completed_at, ?)
            WHERE status = 'active' AND deadline <= ?
            """,
            (now_str, now_str),
        )
        await db.commit()
        return cursor.rowcount


async def get_active_raffle(db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """
    Повертає поточний активний розіграш (якщо є та дедлайн не минув)
    разом із кількістю учасників submissions_count.
    """
    await check_and_complete_expired_raffles(db_path=db_path)
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT r.*,
                   (SELECT COUNT(*) FROM raffle_submissions s WHERE s.raffle_id = r.id) AS submissions_count
            FROM raffles r
            WHERE r.status = 'active'
            ORDER BY r.id DESC
            LIMIT 1
            """
        )
        row = await cursor.fetchone()
        return _parse_raffle_row(row) if row else None


async def is_user_eligible_for_active_raffle(
    user_id: int,
    db_path: str = DB_PATH,
) -> Optional[Dict[str, Any]]:
    """
    Перевіряє, чи є активний розіграш і чи належить користувач до цільових ролей та міста.
    Якщо так - повертає словник активного розіграшу, інакше None.
    """
    raffle = await get_active_raffle(db_path=db_path)
    if not raffle:
        return None

    from database.news import get_matching_news_recipients

    roles = raffle.get("selected_roles") or []
    city = raffle.get("selected_city") or "all"
    eligible_uids = await get_matching_news_recipients(roles, city, db_path=db_path)
    if user_id in eligible_uids:
        return raffle
    return None


async def create_raffle(
    title: str,
    text: str,
    participation_type: str,
    selected_roles: List[str],
    deadline: str,
    created_by: int,
    text_format: Optional[str] = None,
    selected_city: str = "all",
    media_type: Optional[str] = None,
    photo_file_id: Optional[str] = None,
    video_file_id: Optional[str] = None,
    send_announcement: bool = False,
    db_path: str = DB_PATH,
) -> int:
    """
    Створює новий активний розіграш, якщо немає іншого активного.
    Повертає ID створеного розіграшу.
    """
    active = await get_active_raffle(db_path=db_path)
    if active:
        raise ValueError("Вже існує активний розіграш. Завершіть його перед створенням нового.")

    if not media_type:
        if video_file_id:
            media_type = "video"
        elif photo_file_id:
            media_type = "photo"

    now_str = get_current_kyiv_time_str()
    roles_json = json.dumps(selected_roles or [], ensure_ascii=False)

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO raffles (
                title, text, media_type, photo_file_id, video_file_id,
                participation_type, text_format, selected_roles, selected_city,
                deadline, send_announcement, status, media_cleaned, created_at, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 0, ?, ?)
            """,
            (
                title.strip() or "Розіграш BULKA",
                text,
                media_type,
                photo_file_id,
                video_file_id,
                participation_type,
                text_format,
                roles_json,
                selected_city or "all",
                deadline,
                1 if send_announcement else 0,
                now_str,
                created_by,
            ),
        )
        raffle_id = cursor.lastrowid
        await db.commit()
        return raffle_id


async def get_raffle_by_id(raffle_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Повертає розіграш за ID разом із кількістю учасників."""
    await check_and_complete_expired_raffles(db_path=db_path)
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT r.*,
                   (SELECT COUNT(*) FROM raffle_submissions s WHERE s.raffle_id = r.id) AS submissions_count
            FROM raffles r
            WHERE r.id = ?
            """,
            (raffle_id,),
        )
        row = await cursor.fetchone()
        return _parse_raffle_row(row) if row else None


async def complete_raffle(raffle_id: int, db_path: str = DB_PATH) -> bool:
    """Достроково або планово завершує розіграш."""
    now_str = get_current_kyiv_time_str()
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            UPDATE raffles
            SET status = 'completed',
                completed_at = COALESCE(completed_at, ?)
            WHERE id = ? AND status = 'active'
            """,
            (now_str, raffle_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_latest_raffle(db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Повертає останній розіграш (активний або завершений в межах останніх 60 днів)."""
    await check_and_complete_expired_raffles(db_path=db_path)
    cutoff = (get_current_kyiv_dt() - timedelta(days=60)).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT r.*,
                   (SELECT COUNT(*) FROM raffle_submissions s WHERE s.raffle_id = r.id) AS submissions_count
            FROM raffles r
            WHERE r.status = 'active'
               OR COALESCE(r.completed_at, r.deadline, r.created_at) >= ?
            ORDER BY r.id DESC
            LIMIT 1
            """,
            (cutoff,),
        )
        row = await cursor.fetchone()
        return _parse_raffle_row(row) if row else None


async def get_raffle_history_last_60_days(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """
    Повертає список розіграшів за останні 60 днів (активні та завершені не пізніше 60 днів тому),
    відсортованих від найновішого до старішого.
    """
    await check_and_complete_expired_raffles(db_path=db_path)
    cutoff = (get_current_kyiv_dt() - timedelta(days=60)).strftime("%Y-%m-%d %H:%M:%S")

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT r.*,
                   (SELECT COUNT(*) FROM raffle_submissions s WHERE s.raffle_id = r.id) AS submissions_count
            FROM raffles r
            WHERE r.status = 'active'
               OR COALESCE(r.completed_at, r.deadline, r.created_at) >= ?
            ORDER BY r.id DESC
            """,
            (cutoff,),
        )
        rows = await cursor.fetchall()
        return [_parse_raffle_row(r) for r in rows]


async def get_user_raffle_submission(
    raffle_id: int,
    user_id: int,
    db_path: str = DB_PATH,
) -> Optional[Dict[str, Any]]:
    """Повертає заявку користувача в конкретному розіграші (якщо є)."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM raffle_submissions WHERE raffle_id = ? AND user_id = ?",
            (raffle_id, user_id),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def _resolve_user_profile(
    db: aiosqlite.Connection,
    user_id: int,
    fallback_username: Optional[str] = None,
    fallback_full_name: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    """Витягує ПІБ, магазин, місто, роль та username з users (та managers за потреби)."""
    db.row_factory = aiosqlite.Row
    cur = await db.execute(
        "SELECT username, full_name, shop, city, role, status FROM users WHERE user_id = ?",
        (user_id,),
    )
    u_row = await cur.fetchone()

    username = (u_row["username"] if u_row else None) or fallback_username
    full_name = (u_row["full_name"] if u_row else None) or fallback_full_name
    shop = u_row["shop"] if u_row else None
    city = u_row["city"] if u_row else None
    role = u_row["role"] if u_row else None

    if not full_name or not role or not shop or not city:
        try:
            from database.managers import get_manager_by_uid

            mgr = await get_manager_by_uid(user_id)
            if mgr:
                full_name = full_name or mgr.get("full_name")
                username = username or mgr.get("username")
                role = role or mgr.get("process")
                city = city or mgr.get("city")
                shops = mgr.get("shops") or []
                if not shop and shops:
                    shop = ", ".join(str(s) for s in shops if s)
        except Exception:
            pass

    return {
        "username": username,
        "full_name": full_name or f"Користувач {user_id}",
        "shop": shop or "-",
        "city": city or "-",
        "role": role or "Працівник",
    }


async def add_raffle_submission(
    raffle_id: int,
    user_id: int,
    submission_text: Optional[str] = None,
    media_type: Optional[str] = None,
    file_id: Optional[str] = None,
    local_file_path: Optional[str] = None,
    file_size: int = 0,
    fallback_username: Optional[str] = None,
    fallback_full_name: Optional[str] = None,
    db_path: str = DB_PATH,
) -> Tuple[bool, str, Optional[int]]:
    """
    Фіксує одноразову участь користувача в активному розіграші.
    Повертає (success, message, submission_id).
    """
    raffle = await get_raffle_by_id(raffle_id, db_path=db_path)
    if not raffle:
        return False, "Розіграш не знайдено.", None
    if raffle.get("status") != "active":
        return False, "Термін дії цього розіграшу вже завершено.", None

    now_str = get_current_kyiv_time_str()
    async with aiosqlite.connect(db_path) as db:
        profile = await _resolve_user_profile(
            db,
            user_id,
            fallback_username=fallback_username,
            fallback_full_name=fallback_full_name,
        )
        try:
            cursor = await db.execute(
                """
                INSERT INTO raffle_submissions (
                    raffle_id, user_id, user_name, user_full_name, shop_name,
                    user_city, user_role, submission_text, media_type,
                    file_id, local_file_path, file_size, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    raffle_id,
                    user_id,
                    profile["username"],
                    profile["full_name"],
                    profile["shop"],
                    profile["city"],
                    profile["role"],
                    submission_text,
                    media_type,
                    file_id,
                    local_file_path,
                    file_size or 0,
                    now_str,
                ),
            )
            sub_id = cursor.lastrowid
            await db.commit()
            return True, "Участь успішно підтверджено!", sub_id
        except aiosqlite.IntegrityError:
            return False, "Ви вже берете участь в акції!", None


async def get_raffle_submissions_detailed(
    raffle_id: int,
    db_path: str = DB_PATH,
) -> List[Dict[str, Any]]:
    """Повертає деталізований список усіх учасників розіграшу."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT s.*,
                   COALESCE(NULLIF(s.user_full_name, ''), u.full_name, 'Користувач ' || s.user_id) AS full_name,
                   COALESCE(NULLIF(s.user_role, ''), u.role, '-') AS role,
                   COALESCE(NULLIF(s.user_city, ''), u.city, '-') AS city,
                   COALESCE(NULLIF(s.shop_name, ''), u.shop, '-') AS shop,
                   COALESCE(NULLIF(s.user_name, ''), u.username, '') AS username
            FROM raffle_submissions s
            LEFT JOIN users u ON s.user_id = u.user_id
            WHERE s.raffle_id = ?
            ORDER BY s.id ASC
            """,
            (raffle_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def cleanup_expired_raffle_media(
    days: int = 60,
    db_path: str = DB_PATH,
    media_root: str = RAFFLES_MEDIA_DIR,
) -> int:
    """
    Знаходить завершені розіграші, яким більше `days` днів (60 за замовчуванням),
    видаляє їхні медіафайли з диска та позначає media_cleaned = 1.
    Повертає кількість очищених розіграшів.
    """
    await check_and_complete_expired_raffles(db_path=db_path)
    cutoff = (get_current_kyiv_dt() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    cleaned_count = 0
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            SELECT id
            FROM raffles
            WHERE status = 'completed'
              AND media_cleaned = 0
              AND COALESCE(completed_at, deadline, created_at) < ?
            """,
            (cutoff,),
        )
        rows = await cursor.fetchall()
        expired_ids = [r[0] for r in rows]

        for rid in expired_ids:
            raffle_dir = os.path.join(media_root, str(rid))
            if os.path.exists(raffle_dir):
                try:
                    shutil.rmtree(raffle_dir)
                except Exception as exc:
                    logger.warning(f"Failed to remove raffle media dir {raffle_dir}: {exc}")

            # Також підчищаємо будь-які індивідуальні шляхи, якщо файл був поза стандартною папкою
            cur_files = await db.execute(
                "SELECT local_file_path FROM raffle_submissions WHERE raffle_id = ? AND local_file_path IS NOT NULL",
                (rid,),
            )
            for (fpath,) in await cur_files.fetchall():
                if fpath and os.path.exists(fpath):
                    try:
                        os.remove(fpath)
                    except Exception:
                        pass

            await db.execute(
                "UPDATE raffle_submissions SET local_file_path = NULL WHERE raffle_id = ?",
                (rid,),
            )
            await db.execute(
                "UPDATE raffles SET media_cleaned = 1 WHERE id = ?",
                (rid,),
            )
            cleaned_count += 1

        if cleaned_count > 0:
            await db.commit()

    return cleaned_count


async def delete_raffle(
    raffle_id: int,
    db_path: str = DB_PATH,
    media_root: str = RAFFLES_MEDIA_DIR,
) -> bool:
    """Повністю видаляє розіграш, заявки учасників і всі локальні медіафайли."""
    raffle_dir = os.path.join(media_root, str(raffle_id))
    if os.path.exists(raffle_dir):
        try:
            shutil.rmtree(raffle_dir)
        except Exception as exc:
            logger.warning(f"Failed to delete raffle dir {raffle_dir}: {exc}")

    async with aiosqlite.connect(db_path) as db:
        cur_files = await db.execute(
            "SELECT local_file_path FROM raffle_submissions WHERE raffle_id = ? AND local_file_path IS NOT NULL",
            (raffle_id,),
        )
        for (fpath,) in await cur_files.fetchall():
            if fpath and os.path.exists(fpath):
                try:
                    os.remove(fpath)
                except Exception:
                    pass

        await db.execute("DELETE FROM raffle_submissions WHERE raffle_id = ?", (raffle_id,))
        cursor = await db.execute("DELETE FROM raffles WHERE id = ?", (raffle_id,))
        await db.commit()
        return cursor.rowcount > 0
