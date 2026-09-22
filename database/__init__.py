"""
Пакет для роботи з базою даних.
"""
import os

# Шлях до файлу бази даних (відносно кореня проекту Bulka)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.db")

from .shops import init_shops_db

__all__ = ['DB_PATH', 'init_db', 'init_shops_db']
