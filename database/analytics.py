import aiosqlite
from . import DB_PATH
from datetime import datetime, timedelta
import pytz
from bot.config import TIMEZONE, DAYS_TOTAL
from typing import Optional
from database.managers import MANAGERS_DB_PATH

async def get_daily_stats():
    """
    Returns statistics for the last 24 hours:
    - New users registered
    - Total completed learning blocks
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # Define 24h window
        # SQLite's datetime('now') is in UTC usually, but our app uses local strings mostly.
        # However, first_seen and completed_at are stored as strings in 'YYYY-MM-DD HH:MM:SS' format.
        # We need to construct the cutoff string in the same timezone used by the app.
        
        now = datetime.now(pytz.timezone(TIMEZONE))
        cutoff = (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        
        # New users
        cursor = await db.execute(
            "SELECT COUNT(*) FROM users WHERE first_seen >= ?", 
            (cutoff,)
        )
        new_users = (await cursor.fetchone())[0]
        
        # Completed blocks (completions in last 24h)
        cursor = await db.execute(
            "SELECT COUNT(*) FROM progress WHERE completed_at >= ? AND completed = 1", 
            (cutoff,)
        )
        completions = (await cursor.fetchone())[0]
        
        # Total active users (active in last 24h)
        cursor = await db.execute(
            "SELECT COUNT(*) FROM users WHERE last_activity >= ?", 
            (cutoff,)
        )
        active_users = (await cursor.fetchone())[0]
        
        return {
            "new_users": new_users,
            "completions": completions,
            "active_users": active_users
        }

async def get_dropout_funnel(active_days: int = 3):
    """
    Calculates the distribution of users by their current learning block.
    Returns data for ALL users and separately for ACTIVE users.
    """
    now = datetime.now(pytz.timezone(TIMEZONE))
    cutoff = (now - timedelta(days=active_days)).strftime("%Y-%m-%d %H:%M:%S")
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Виключаємо HR/Dev (з users.db)
        privileged_ids = set()
        hcur = await db.execute("SELECT user_id FROM hr_users")
        privileged_ids |= {row[0] for row in await hcur.fetchall()}

        # Виключаємо тих, хто вже завершив навчання
        ccur = await db.execute(
            """
            SELECT user_id
            FROM progress
            WHERE completed = 1
            GROUP BY user_id
            HAVING COUNT(day) >= ?
            """,
            (DAYS_TOTAL,),
        )
        completed_ids = {row[0] for row in await ccur.fetchall()}

        ucur = await db.execute(
            "SELECT user_id, current_block, last_activity, status, manager_id FROM users"
        )
        users = await ucur.fetchall()

    # Виключаємо керівників (з managers.db)
    async with aiosqlite.connect(MANAGERS_DB_PATH) as mdb:
        mcur = await mdb.execute("SELECT uid FROM managers")
        privileged_ids |= {row[0] for row in await mcur.fetchall()}

    in_progress = []
    for row in users:
        user = dict(row)
        uid = user["user_id"]
        if uid in privileged_ids:
            continue
        if user.get("status") == "Працівник":
            continue
        if uid in completed_ids:
            continue
        # Меню воронки має відображати саме стажерів у процесі
        in_progress.append(user)

    total_dist: dict[int, int] = {}
    active_dist: dict[int, int] = {}
    active_count = 0
    for user in in_progress:
        day = user.get("current_block") or 1
        total_dist[day] = total_dist.get(day, 0) + 1
        last_activity = user.get("last_activity")
        if last_activity and last_activity >= cutoff:
            active_count += 1
            active_dist[day] = active_dist.get(day, 0) + 1

    return {
        "total_users": len(in_progress),
        "total_distribution": total_dist,
        "active_users": active_count,
        "active_distribution": active_dist,
    }


def _cutoff(range_days: Optional[int]) -> Optional[str]:
    if not range_days:
        return None
    now = datetime.now(pytz.timezone(TIMEZONE))
    return (now - timedelta(days=range_days)).strftime("%Y-%m-%d %H:%M:%S")


async def get_training_added_interns(range_days: Optional[int] = None, city: Optional[str] = None) -> list[dict]:
    cutoff = _cutoff(range_days)
    where = ["event_type = 'added'"]
    params: list = []
    if cutoff:
        where.append("event_at >= ?")
        params.append(cutoff)
    if city:
        where.append("city = ?")
        params.append(city)

    query = f"""
        SELECT user_id, full_name, username, city, role, manager_id, event_at
        FROM training_events
        WHERE {" AND ".join(where)}
        ORDER BY event_at DESC
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(query, tuple(params))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

async def clear_training_added_interns(range_days: Optional[int] = None, city: Optional[str] = None) -> int:
    """Очищає події доданих стажерів у межах фільтра. Повертає кількість видалених рядків."""
    cutoff = _cutoff(range_days)
    where = ["event_type = 'added'"]
    params: list = []
    if cutoff:
        where.append("event_at >= ?")
        params.append(cutoff)
    if city:
        where.append("city = ?")
        params.append(city)

    query = f"DELETE FROM training_events WHERE {' AND '.join(where)}"
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(query, tuple(params))
        await db.commit()
        return cur.rowcount or 0


async def get_training_added_cities() -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT DISTINCT city FROM training_events WHERE event_type = 'added' AND city IS NOT NULL AND city != '' ORDER BY city ASC"
        )
        return [r[0] for r in await cur.fetchall()]


async def get_training_left_inactive(days: int = 3) -> list[dict]:
    now = datetime.now(pytz.timezone(TIMEZONE))
    cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT user_id, full_name, username, city, shop, role, manager_id, last_activity
            FROM users
            WHERE manager_id IS NOT NULL
              AND (status IS NULL OR status != 'Працівник')
              AND last_activity IS NOT NULL
              AND last_activity < ?
              AND user_id NOT IN (
                  SELECT user_id
                  FROM progress
                  WHERE completed = 1
                  GROUP BY user_id
                  HAVING COUNT(day) >= ?
              )
            ORDER BY last_activity ASC
            """,
            (cutoff, DAYS_TOTAL),
        )
        rows = await cur.fetchall()
        result = []
        for r in rows:
            row = dict(r)
            try:
                last_activity = datetime.fromisoformat(row["last_activity"])
                row["inactive_since"] = (last_activity + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                row["inactive_since"] = row.get("last_activity")
            row["deleted"] = 0
            row["deleted_at"] = None
            result.append(row)

        deleted_cur = await db.execute(
            """
            SELECT user_id, full_name, username, city, shop, role, manager_id, event_at
            FROM training_events
            WHERE event_type = 'left_deleted'
            ORDER BY event_at DESC
            """
        )
        deleted_rows = await deleted_cur.fetchall()
        for r in deleted_rows:
            row = dict(r)
            row["deleted"] = 1
            row["deleted_at"] = row.get("event_at")
            try:
                deleted_at = datetime.fromisoformat(row["event_at"])
                row["inactive_since"] = (deleted_at - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                row["inactive_since"] = row.get("event_at")
            result.append(row)

        result.sort(key=lambda item: item.get("deleted_at") or item.get("inactive_since") or "", reverse=True)
        return result


async def get_training_promoted(range_days: Optional[int] = None) -> list[dict]:
    cutoff = _cutoff(range_days)
    where = ["event_type = 'promoted'"]
    params: list = []
    if cutoff:
        where.append("event_at >= ?")
        params.append(cutoff)

    query = f"""
        SELECT user_id, full_name, username, city, role, manager_id, event_at
        FROM training_events
        WHERE {" AND ".join(where)}
        ORDER BY event_at DESC
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(query, tuple(params))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_training_rejected(range_days: Optional[int] = None) -> list[dict]:
    cutoff = _cutoff(range_days)
    where = ["event_type = 'rejected'"]
    params: list = []
    if cutoff:
        where.append("event_at >= ?")
        params.append(cutoff)

    query = f"""
        SELECT user_id, full_name, username, city, role, manager_id, event_at
        FROM training_events
        WHERE {" AND ".join(where)}
        ORDER BY event_at DESC
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(query, tuple(params))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
