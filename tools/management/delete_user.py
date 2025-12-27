import sys
import os
import asyncio

# Добавляем родительскую директорию в sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.users import delete_user, get_user_details
from database import DB_PATH  # Импортируем путь к базе данных

async def main():
    print(f"Використовується база даних: {DB_PATH}")
    user_id = input("Введіть user_id користувача для видалення: ")
    try:
        user_id = int(user_id)
        
        # Проверяем, существует ли пользователь
        user_details = await get_user_details(user_id)
        if not user_details:
            print(f"Користувач з ID {user_id} не знайдений в базі.")
            return
            
        print(f"Знайдено користувача: {user_details.get('full_name', 'Ім`я не вказано')} (@{user_details.get('username', 'без username')})")
        confirm = input(f"Ви впевнені, що хочете видалити цього користувача? (y/n): ")
        
        if confirm.lower() == 'y':
            await delete_user(user_id)
            print(f"Користувач {user_id} успішно видалений з бази.")
        else:
            print("Видалення скасовано.")
            
    except ValueError:
        print("Помилка: user_id повинен бути цілим числом")
    except Exception as e:
        print(f"Виникла непередбачена помилка: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())
