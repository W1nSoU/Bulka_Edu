import aiosqlite
from . import DB_PATH
from datetime import datetime, timedelta
import pytz
from bot.config import TIMEZONE, DAYS_TOTAL
from typing import Optional
from database.managers import MANAGERS_DB_PATH

async def get_daily_stats():
    """
    Returns accurate statistics for the last 24 hours:
    - New interns registered
    - Total completed learning blocks/tests
    - Active interns vs active workers
    - Promoted to workers
    - Dropped/rejected
    """
    from database.users import MANAGEMENT_ROLES
    now = datetime.now(pytz.timezone(TIMEZONE))
    cutoff = (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    
    # Privileged users
    privileged_ids = set()
    async with aiosqlite.connect(DB_PATH) as db:
        hcur = await db.execute("SELECT user_id FROM hr_users")
        privileged_ids |= {row[0] for row in await hcur.fetchall()}
    async with aiosqlite.connect(MANAGERS_DB_PATH) as mdb:
        mcur = await mdb.execute("SELECT uid FROM managers")
        privileged_ids |= {row[0] for row in await mcur.fetchall()}

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # All users
        cur = await db.execute("SELECT user_id, status, role, first_seen, last_activity FROM users")
        all_users = await cur.fetchall()

        new_interns = 0
        active_interns = 0
        active_workers = 0

        for r in all_users:
            u = dict(r)
            uid = u["user_id"]
            if uid in privileged_ids or u.get("role") in MANAGEMENT_ROLES:
                continue
            is_worker = u.get("status") == "Працівник"
            first_seen = u.get("first_seen")
            last_act = u.get("last_activity")

            if not is_worker:
                if first_seen and first_seen >= cutoff:
                    new_interns += 1
                if last_act and last_act >= cutoff:
                    active_interns += 1
            else:
                if last_act and last_act >= cutoff:
                    active_workers += 1

        # Completions in last 24h
        cur = await db.execute(
            "SELECT user_id FROM progress WHERE completed_at >= ? AND completed = 1", 
            (cutoff,)
        )
        comp_rows = await cur.fetchall()
        completions = sum(1 for r in comp_rows if r[0] not in privileged_ids)

        # Promoted to workers in last 24h
        cur = await db.execute(
            "SELECT COUNT(*) FROM training_events WHERE event_type = 'promoted' AND event_at >= ?",
            (cutoff,)
        )
        promoted = (await cur.fetchone())[0]

        # Dropped/rejected in last 24h
        cur = await db.execute(
            "SELECT COUNT(*) FROM training_events WHERE event_type IN ('left_deleted', 'rejected', 'fired') AND event_at >= ?",
            (cutoff,)
        )
        dropped = (await cur.fetchone())[0]

        return {
            "new_users": new_interns,
            "completions": completions,
            "active_users": active_interns,
            "active_workers": active_workers,
            "promoted": promoted,
            "dropped": dropped,
        }

async def get_dropout_funnel(active_days: int = 3):
    """
    Calculates the distribution of users by their current learning block.
    Returns data for ALL users and separately for ACTIVE users.
    """
    from database.positions import get_days_count_for_role
    from database.users import MANAGEMENT_ROLES
    now = datetime.now(pytz.timezone(TIMEZONE))
    cutoff = (now - timedelta(days=active_days)).strftime("%Y-%m-%d %H:%M:%S")
    
    privileged_ids = set()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Виключаємо HR/Dev (з users.db)
        hcur = await db.execute("SELECT user_id FROM hr_users")
        privileged_ids |= {row[0] for row in await hcur.fetchall()}

    # Виключаємо керівників (з managers.db)
    async with aiosqlite.connect(MANAGERS_DB_PATH) as mdb:
        mcur = await mdb.execute("SELECT uid FROM managers")
        privileged_ids |= {row[0] for row in await mcur.fetchall()}

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Збираємо кількість пройдених днів для кожного
        pcur = await db.execute("SELECT user_id, COUNT(day) FROM progress WHERE completed = 1 GROUP BY user_id")
        completed_map = {row[0]: row[1] for row in await pcur.fetchall()}

        ucur = await db.execute(
            "SELECT user_id, current_block, role, last_activity, status, manager_id FROM users"
        )
        users = await ucur.fetchall()

    in_progress = []
    for row in users:
        user = dict(row)
        uid = user["user_id"]
        if uid in privileged_ids:
            continue
        if user.get("status") == "Працівник" or user.get("role") in MANAGEMENT_ROLES:
            continue
        
        role = user.get("role") or ""
        required_days = await get_days_count_for_role(role)
        completed_days = completed_map.get(uid, 0)
        if completed_days >= required_days:
            # Завершив навчання
            continue

        user["completed_days_count"] = completed_days
        in_progress.append(user)

    total_dist: dict[int, int] = {}
    active_dist: dict[int, int] = {}
    active_count = 0
    for user in in_progress:
        # Ефективний поточний день: або поточний блок, або наступний після завершених
        completed_count = user.get("completed_days_count", 0)
        stored_block = user.get("current_block") or 1
        day = max(stored_block, completed_count + 1)
        day = min(day, DAYS_TOTAL)
        
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
    from database.positions import get_days_count_for_role
    from database.users import MANAGEMENT_ROLES
    now = datetime.now(pytz.timezone(TIMEZONE))
    cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    privileged_ids = set()
    async with aiosqlite.connect(DB_PATH) as db:
        hcur = await db.execute("SELECT user_id FROM hr_users")
        privileged_ids |= {row[0] for row in await hcur.fetchall()}
    async with aiosqlite.connect(MANAGERS_DB_PATH) as mdb:
        mcur = await mdb.execute("SELECT uid FROM managers")
        privileged_ids |= {row[0] for row in await mcur.fetchall()}

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
            ORDER BY last_activity ASC
            """,
            (cutoff,),
        )
        rows = await cur.fetchall()
        result = []
        for r in rows:
            row = dict(r)
            uid = row["user_id"]
            if uid in privileged_ids or row.get("role") in MANAGEMENT_ROLES:
                continue
            role = row.get("role") or ""
            required_days = await get_days_count_for_role(role)
            p_cur = await db.execute(
                "SELECT COUNT(day) FROM progress WHERE user_id = ? AND completed = 1",
                (uid,)
            )
            completed_days = (await p_cur.fetchone())[0]
            if completed_days >= required_days:
                continue

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
            SELECT
                te.user_id,
                te.full_name,
                te.username,
                te.city,
                COALESCE(
                    te.shop,
                    (
                        SELECT te2.shop
                        FROM training_events te2
                        WHERE te2.user_id = te.user_id
                          AND te2.shop IS NOT NULL
                          AND te2.shop != ''
                        ORDER BY te2.event_at DESC
                        LIMIT 1
                    )
                ) AS shop,
                te.role,
                te.manager_id,
                te.event_at
            FROM training_events te
            WHERE te.event_type IN ('left_deleted', 'rejected', 'fired')
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
