import sys
import os
import asyncio

# Добавляем родительскую директорию в sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.mentors import add_mentor, init_mentors_db
from database import DB_PATH  # Импортируем путь к базе данных

async def main():
    print(f"Використовується база даних: {DB_PATH}")
    await init_mentors_db()  # Инициализируем базу данных менторов
    try:
        mentor_uid = 1001226587
        mentor_position = "Керівник відділу кадрів"
        
        await add_mentor(mentor_uid, mentor_position)
        print(f"Ментор успішно доданий: {mentor_uid}, {mentor_position}")
    except ValueError as e:
        print(f"Помилка: {str(e)}")
    except Exception as e:
        print(f"Виникла непередбачена помилка: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())
