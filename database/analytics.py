import aiosqlite
from . import DB_PATH
from datetime import datetime, timedelta
import pytz
from bot.config import TIMEZONE

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

async def get_dropout_funnel():
    """
    Calculates the distribution of users by their current learning block.
    This helps identify where users drop out.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # We assume regular users have roles, or we can just filter out known admins if needed.
        # For now, we take all users.
        
        # Group by current_block
        cursor = await db.execute(
            """
            SELECT current_block, COUNT(*) 
            FROM users 
            GROUP BY current_block 
            ORDER BY current_block
            """
        )
        rows = await cursor.fetchall()
        
        # Get total users count to calculate percentages
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        total_users = (await cursor.fetchone())[0]
        
        # Format: {block_num: count}
        distribution = {row[0]: row[1] for row in rows}
        
        return {
            "total_users": total_users,
            "distribution": distribution
        }
