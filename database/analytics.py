import aiosqlite
from . import DB_PATH
from datetime import datetime, timedelta
import pytz
from bot.config import TIMEZONE, DAYS_TOTAL
from typing import Optional

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
        # 1. Загальна статистика (всі користувачі)
        cursor = await db.execute(
            "SELECT current_block, COUNT(*) FROM users GROUP BY current_block"
        )
        total_dist = {row[0]: row[1] for row in await cursor.fetchall()}
        
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        total_count = (await cursor.fetchone())[0]
        
        # 2. Активна статистика (тільки ті, хто заходив останні 3 дні)
        cursor = await db.execute(
            "SELECT current_block, COUNT(*) FROM users WHERE last_activity >= ? GROUP BY current_block",
            (cutoff,)
        )
        active_dist = {row[0]: row[1] for row in await cursor.fetchall()}
        
        cursor = await db.execute("SELECT COUNT(*) FROM users WHERE last_activity >= ?", (cutoff,))
        active_count = (await cursor.fetchone())[0]
        
        return {
            "total_users": total_count,
            "total_distribution": total_dist,
            "active_users": active_count,
            "active_distribution": active_dist
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
            SELECT user_id, full_name, username, city, role, manager_id, last_activity
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
            SELECT user_id, full_name, username, city, role, manager_id, event_at
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
