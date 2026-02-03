from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Literal, Optional, Sequence, Tuple

import aiosqlite
import pytz

from bot.config import DAYS_TOTAL, TIMEZONE
from database import DB_PATH
from database.users import update_progress


class DayStatus(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    COMPLETED = "completed"


async def _ensure_progress_row(user_id: int, day: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO progress (user_id, day, completed, completed_at, manual_open)
            VALUES (?, ?, 0, NULL, 0)
            """,
            (user_id, day),
        )
        await db.commit()


async def _fetch_progress_rows(user_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT day, completed, manual_open FROM progress WHERE user_id = ?",
            (user_id,),
        )
        rows = await cursor.fetchall()
    return {row["day"]: dict(row) for row in rows}


def _status_from_row(
    day: int,
    row: Optional[dict],
    prev_completed: bool,
) -> DayStatus:
    if row and row.get("completed"):
        return DayStatus.COMPLETED
    if day == 1:
        return DayStatus.OPEN
    if row and row.get("manual_open"):
        return DayStatus.OPEN
    return DayStatus.CLOSED


async def get_day_status(user_id: int, day: int) -> DayStatus:
    overview = await get_days_overview(user_id)
    for item_day, status in overview:
        if item_day == day:
            return status
    return DayStatus.CLOSED


async def get_days_overview(user_id: int) -> List[Tuple[int, DayStatus]]:
    rows = await _fetch_progress_rows(user_id)
    overview: List[Tuple[int, DayStatus]] = []
    prev_completed = True
    for day in range(1, DAYS_TOTAL + 1):
        row = rows.get(day)
        status = _status_from_row(day, row, prev_completed)
        overview.append((day, status))
        prev_completed = bool(row and row.get("completed"))
    return overview


async def _set_manual_open(user_id: int, day: int, opened_by: str) -> None:
    await _ensure_progress_row(user_id, day)
    now = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE progress
            SET manual_open = 1,
                manual_opened_by = ?
            WHERE user_id = ? AND day = ?
            """,
            (opened_by, user_id, day),
        )
        await db.commit()
    _sync_state_manual(user_id, day, True)


async def open_day_auto(user_id: int, day: int) -> None:
    await _set_manual_open(user_id, day, "auto")


async def open_day_manual(
    user_id: int,
    day: int,
    opened_by: Literal["dev", "manager", "hr"],
) -> None:
    await _set_manual_open(user_id, day, opened_by)


async def close_day(user_id: int, day: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE progress
            SET manual_open = 0,
                manual_opened_by = NULL
            WHERE user_id = ? AND day = ?
            """,
            (user_id, day),
        )
        await db.commit()
    _sync_state_manual(user_id, day, False)


async def mark_day_completed(user_id: int, day: int) -> None:
    completed_at = await update_progress(user_id, day, completed=True)
    await close_day(user_id, day)
    _sync_state_completion(user_id, day, True, completed_at)


async def mark_day_incomplete(user_id: int, day: int) -> None:
    await update_progress(user_id, day, completed=False)
    _sync_state_completion(user_id, day, False, None)


async def reset_day(user_id: int, day: int) -> None:
    await mark_day_incomplete(user_id, day)
    await close_day(user_id, day)


def _sync_state_manual(user_id: int, day: int, is_open: bool) -> None:
    try:
        from bot.state import initialize_user_progress, user_progress
    except ImportError:
        return

    initialize_user_progress(user_id)
    entry = user_progress.setdefault(user_id, {}).setdefault(f"day_{day}", {})
    if is_open:
        entry["manual_open"] = True
    else:
        entry.pop("manual_open", None)


def _sync_state_completion(
    user_id: int,
    day: int,
    completed: bool,
    completed_at: Optional[datetime],
) -> None:
    try:
        from bot.state import initialize_user_progress, user_progress
    except ImportError:
        return

    initialize_user_progress(user_id)
    entry = user_progress.setdefault(user_id, {}).setdefault(f"day_{day}", {})
    entry["completed"] = completed
    if completed and completed_at:
        entry["completed_at"] = completed_at
    elif not completed:
        entry.pop("completed_at", None)


__all__ = [
    "DayStatus",
    "get_day_status",
    "get_days_overview",
    "open_day_auto",
    "open_day_manual",
    "mark_day_completed",
    "mark_day_incomplete",
    "close_day",
    "reset_day",
]
