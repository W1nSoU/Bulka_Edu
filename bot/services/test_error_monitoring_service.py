import aiosqlite
from database import DB_PATH
from datetime import datetime, timedelta

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
            # If no errors ever recorded, no reset is due.
            # Or, if we want to ensure a reset happens at the start, we could return True here.
            # For simplicity, assume if no errors, no reset needed.
            return False 

        last_reset_str = last_reset_row[0]
        last_reset_dt = datetime.fromisoformat(last_reset_str)

        # Calculate three months from the last reset date
        # This is a simplification; a more robust solution would handle month lengths
        # and leap years precisely. For quarterly, 90 days is a reasonable approximation.
        three_months_ago = datetime.now() - timedelta(days=90) 
        
        return last_reset_dt < three_months_ago

async def perform_quarterly_reset_if_due():
    """Performs a quarterly reset of test error statistics if due."""
    if await should_perform_quarterly_reset():
        await reset_test_error_statistics()
        print("Test error statistics reset due to quarterly schedule.")
    else:
        print("Quarterly test error reset not yet due.")
