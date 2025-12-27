import json
import random
from typing import List, Dict, Optional, Tuple
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database.materials import get_test_by_role_and_day

async def get_test_data(role: str, day: int) -> Optional[List[Dict]]:
    """Retrieves and parses test data from DB."""
    test_material = await get_test_by_role_and_day(role, day)
    if not test_material or not test_material.get("content"):
        return None
    try:
        return json.loads(test_material["content"])
    except json.JSONDecodeError:
        return None

def build_test_keyboard(question_idx: int, options: List[str], day: int) -> InlineKeyboardMarkup:
    """Builds keyboard for a test question."""
    buttons = []
    for i, option in enumerate(options):
        # callback_data format: test_ans:{day}:{question_idx}:{answer_idx}
        buttons.append([InlineKeyboardButton(
            text=option, 
            callback_data=f"test_ans:{day}:{question_idx}:{i}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def render_test_question(questions: List[Dict], question_idx: int, day: int) -> Tuple[str, InlineKeyboardMarkup]:
    """Renders the text and keyboard for a specific question."""
    q = questions[question_idx]
    total = len(questions)
    
    text = (
        f"📝 <b>Тестування: День {day}</b>\n"
        f"Питання {question_idx + 1} з {total}\n\n"
        f"<b>{q['question']}</b>"
    )
    
    kb = build_test_keyboard(question_idx, q['options'], day)
    return text, kb
