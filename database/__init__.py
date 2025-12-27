"""
Пакет для роботи з базою даних.
"""
import os

# Шлях до файлу бази даних (відносно кореня проекту Bulka)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.db")

__all__ = ['DB_PATH']
__all__ = ['init_db', 'DB_PATH']
