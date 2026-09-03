from datetime import datetime
from typing import Optional, Union
from pathlib import Path
from aiogram import Bot
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardMarkup, InputMediaPhoto

from .avatar import get_user_avatar_input, _send_or_edit_card_photo
from .message_utils import send_long_message, send_message_with_debug, truncate_text
from .paginator import split_text
from .manager import get_manager_display_title

def format_datetime(dt: datetime) -> str:
    """Форматує datetime в строку для зручного виводу"""
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def get_current_time() -> datetime:
    """Отримує поточний час у вказаній часовій зоні"""
    from bot.config import TIMEZONE
    import pytz
    return datetime.now(pytz.timezone(TIMEZONE))

def calculate_completion_percentage(completed: int, total: int) -> int:
    """Розраховує відсоток завершення."""
    if total == 0:
        return 0
    return int((completed / total) * 100)

def validate_answer(user_answer: str, correct_answer: str) -> bool:
    """Перевіряє, чи правильна відповідь користувача."""
    return user_answer.strip().lower() == correct_answer.strip().lower()

__all__ = [
    'get_user_avatar_input',
    '_send_or_edit_card_photo',
    'get_manager_display_title',
    'send_long_message',
    'send_message_with_debug',
    'truncate_text',
    'split_text',
    'format_datetime',
    'get_current_time',
    'calculate_completion_percentage',
    'validate_answer',
]
