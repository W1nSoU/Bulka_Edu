import sys
import os
import asyncio

# Добавляем родительскую директорию в sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.managers import add_manager, init_managers_db
from database import DB_PATH  # Импортируем путь к базе данных

async def main():
    print(f"Використовується база даних: {DB_PATH}")
    await init_managers_db()  # Инициализируем базу данных керівників
    try:
        manager_uid = 1001226587
        manager_position = "Керівник відділу кадрів"
        
        await add_manager(manager_uid, manager_position)
        print(f"Керівник успішно доданий: {manager_uid}, {manager_position}")
    except ValueError as e:
        print(f"Помилка: {str(e)}")
    except Exception as e:
        print(f"Виникла непередбачена помилка: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())
