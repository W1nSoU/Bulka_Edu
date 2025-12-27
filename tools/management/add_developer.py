import asyncio
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.hr import add_developer_user
from bot.config import MAIN_DEVELOPER_ID

async def main():
    if len(sys.argv) != 2:
        print("Usage: python add_developer.py <user_id>")
        return
    
    user_id = int(sys.argv[1])
    await add_developer_user(user_id, MAIN_DEVELOPER_ID)
    print(f"Added user {user_id} as developer")

if __name__ == "__main__":
    asyncio.run(main())