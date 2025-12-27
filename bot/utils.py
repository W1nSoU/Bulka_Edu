from datetime import datetime
import pytz
from bot.config import TIMEZONE

def format_datetime(dt: datetime) -> str:
    """Форматує datetime в строку для зручного виводу"""
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def get_current_time() -> datetime:
    """Отримує поточний час у вказаній часовій зоні"""
    return datetime.now(pytz.timezone(TIMEZONE))

def calculate_completion_percentage(completed: int, total: int) -> int:
    """
    Розраховує відсоток завершення.
    Args:
        completed (int): Кількість завершених елементів.
        total (int): Загальна кількість елементів.
    Returns:
        int: Відсоток завершення (округлений до цілого).
    """
    if total == 0:
        return 0
    return int((completed / total) * 100)

def validate_answer(user_answer: str, correct_answer: str) -> bool:
    """
    Перевіряє, чи правильна відповідь користувача.
    Args:
        user_answer (str): Введена відповідь користувача.
        correct_answer (str): Очікувана правильна відповідь.
    Returns:
        bool: True, якщо відповідь правильна, інакше False.
    """
    return user_answer.strip().lower() == correct_answer.strip().lower()
