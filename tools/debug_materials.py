import asyncio
import sys
import os
import aiosqlite

# Add the project root to sys.path
sys.path.append(os.getcwd())
from database import DB_PATH

async def main():
    print(f"--- Checking database at: {DB_PATH} ---")
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        keyword = "алкоголь"
        like_pattern = f"%{keyword.lower()}%"
        
        print(f"\n--- Searching for materials with keyword '{keyword}' ---")
        
        cursor = await db.execute(
            "SELECT id, role, day, content_type, title, substr(content, 1, 150) as content_preview FROM materials WHERE lower(content) LIKE ? OR lower(title) LIKE ?",
            (like_pattern, like_pattern)
        )
        
        rows = await cursor.fetchall()
        
        if not rows:
            print("\n!!! NO MATERIALS FOUND containing the keyword. !!!")
        else:
            print(f"\nFound {len(rows)} matching material(s):")
            for row in rows:
                print("-" * 20)
                for key in row.keys():
                    print(f"{key}: {row[key]}")

if __name__ == "__main__":
    asyncio.run(main())

