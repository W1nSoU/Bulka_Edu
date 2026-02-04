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
