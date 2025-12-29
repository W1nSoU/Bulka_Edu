import aiosqlite
from database import DB_PATH
from datetime import datetime, timedelta
from database.users import get_all_users, get_user_progress # Import for fetching user progress
from bot.services.learning_progress import DayStatus, get_days_overview # Import for day status
from bot.config import DAYS_TOTAL # Import for total days

async def get_test_error_statistics() -> list[dict]:
    """Retrieves aggregated test error statistics."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT role, day, question_idx, error_count, last_reset_at
            FROM test_errors
            ORDER BY role, day, question_idx
            """
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def reset_test_error_statistics():
    """Resets all test error counts to 0 and updates last_reset_at."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE test_errors
            SET error_count = 0, last_reset_at = CURRENT_TIMESTAMP
            """
        )
        await db.commit()

async def should_perform_quarterly_reset() -> bool:
    """Checks if a quarterly reset is due."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT last_reset_at FROM test_errors ORDER BY last_reset_at DESC LIMIT 1")
        last_reset_row = await cursor.fetchone()

        if not last_reset_row:
            return False 

        last_reset_str = last_reset_row[0]
        last_reset_dt = datetime.fromisoformat(last_reset_str)

        three_months_ago = datetime.now() - timedelta(days=90) 
        
        return last_reset_dt < three_months_ago

async def perform_quarterly_reset_if_due():
    """
    Performs a quarterly reset of test error statistics if due.
    """
    if await should_perform_quarterly_reset():
        await reset_test_error_statistics()

async def get_intern_incomplete_open_test_days() -> list[tuple[int, int]]:
    """
    Знаходить усіх стажерів, які мають відкритий день, але не пройшли тест за цей день.
    Повертає список кортежів (user_id, day_num).
    """
    all_users = await get_all_users()
    incomplete_tests = []

    for user in all_users:
        user_id = user["user_id"]
        days_overview = await get_days_overview(user_id)
        user_progress = await get_user_progress(user_id)

        completed_days_set = {p["day"] for p in user_progress if p["completed"]}

        for day_num, status in days_overview:
            if day_num > DAYS_TOTAL: # Ignore days beyond the total course days
                continue

            # Якщо день відкритий (не закритий) І тест за цей день не пройдено
            if status != DayStatus.CLOSED and day_num not in completed_days_set:
                incomplete_tests.append((user_id, day_num))
    
    return incomplete_tests

async def group_test_failures_by_manager(incomplete_days: list[tuple[int, int]]) -> dict[int, list[tuple[int, int]]]:
    """
    Групує стажерів з незавершеними відкритими тестами за їхнім керівником.
    Повертає словник: {manager_id: [(intern_id, day_num), ...]}
    """
    from database.users import get_user_details # Import inside to avoid circular dependency if needed

    grouped_failures = {} # type: dict[int, list[tuple[int, int]]]

    for intern_id, day_num in incomplete_days:
        intern_details = await get_user_details(intern_id)
        if intern_details and intern_details.get("manager_id"):
            manager_id = intern_details["manager_id"]
            if manager_id not in grouped_failures:
                grouped_failures[manager_id] = []
            grouped_failures[manager_id].append((intern_id, day_num))
    
    return grouped_failures
