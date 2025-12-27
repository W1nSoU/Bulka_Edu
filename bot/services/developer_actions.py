from datetime import datetime
from typing import List

import pytz

from bot.config import DAYS_TOTAL, TIMEZONE
from database.users import (
    get_user_details,
    update_user_current_block,
)
from database.managers import get_manager_by_uid
from .learning_progress import (
    DayStatus,
    get_days_overview,
    open_day_manual,
    reset_day,
)


async def _ensure_user(user_id: int):
    user = await get_user_details(user_id)
    if not user:
        raise ValueError(f"Користувача з ID {user_id} не знайдено.")
    return user


def parse_day_input(day_input: str, max_day: int = DAYS_TOTAL) -> List[int]:
    day_input = (day_input or "").strip()
    if not day_input:
        return []
    try:
        if "-" in day_input:
            start, end = map(int, day_input.split("-"))
            if start < 1 or end > max_day or start > end:
                return []
            return list(range(start, end + 1))
        day = int(day_input)
        if day < 1 or day > max_day:
            return []
        return [day]
    except ValueError:
        return []


def _format_last_activity(value: str | None) -> str:
    if not value:
        return "Невідомо"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    if dt.tzinfo is None:
        dt = pytz.timezone(TIMEZONE).localize(dt)
    now = datetime.now(pytz.timezone(TIMEZONE))
    delta = now - dt
    if delta.days > 0:
        return f"{dt:%Y-%m-%d %H:%M}"
    hours = delta.seconds // 3600
    minutes = (delta.seconds % 3600) // 60
    if hours:
        return f"{hours} год. тому"
    return f"{minutes} хв. тому"


def _status_icon(status: DayStatus) -> str:
    return {
        DayStatus.COMPLETED: "✅",
        DayStatus.OPEN: "🔓",
        DayStatus.CLOSED: "🔒",
    }[status]


async def get_user_days_report(user_id: int) -> str:
    user = await _ensure_user(user_id)
    
    # Отримуємо ім'я керівника
    manager_name = "Не призначено"
    if manager_id := user.get("manager_id"):
        if manager := await get_manager_by_uid(manager_id):
            manager_name = manager.get("full_name", f"ID:{manager_id}")

    overview = await get_days_overview(user_id)
    completed_days = sum(1 for _, status in overview if status == DayStatus.COMPLETED)
    percent = int(completed_days / DAYS_TOTAL * 100)

    lines = [
        f"👤 <b>{user.get('full_name', 'Без імені')}</b> (@{user.get('username', 'немає')})",
        f"🏢 Посада: <b>{user.get('role', 'Не вказано')}</b>",
        f"🏙 Місто: <b>{user.get('city', 'Не вказано')}</b>",
        f"👨‍🏫 Керівник: <b>{manager_name}</b>",
        f"📊 Прогрес: <b>{completed_days}/{DAYS_TOTAL} ({percent}%)</b>",
        f"⏱️ Остання активність: <b>{_format_last_activity(user.get('last_activity'))}</b>",
        "",
        "📅 <b>Статус днів</b>",
    ]

    for day, status in overview:
        icon = _status_icon(status)
        lines.append(f"{icon} День {day}")
    return "\n".join(lines)


async def open_days_for_user(user_id: int, days: List[int]) -> str:
    await _ensure_user(user_id)
    messages = []
    for day in days:
        await open_day_manual(user_id, day, "dev")
        messages.append(f"✅ День {day} відкрито вручну.")
    if not messages:
        messages.append("ℹ️ Оберіть хоча б один день для відкриття.")
    return "\n".join(messages)


async def close_days_for_user(user_id: int, days: List[int]) -> str:
    await _ensure_user(user_id)
    messages = []
    for day in days:
        await reset_day(user_id, day)
        messages.append(f"🔒 День {day} закрито та прогрес скинуто.")
    if not messages:
        messages.append("ℹ️ Оберіть хоча б один день для закриття.")
    return "\n".join(messages)


async def reset_days_for_user(user_id: int, days: List[int]) -> str:
    await _ensure_user(user_id)
    if isinstance(days, int):
        days = [days]
    if not days:
        return "ℹ️ Не вказано жодного дня для скидання."

    for day in days:
        await reset_day(user_id, day)

    min_day = min(days)
    new_block = max(1, min_day - 1)
    await update_user_current_block(user_id, new_block)
    text_days = ", ".join(str(d) for d in sorted(days))
    return (
        f"🔄 Прогрес днів {text_days} скинуто.\n"
        f"📊 Поточний блок навчання встановлено на <b>День {new_block}</b>."
    )


__all__ = [
    "parse_day_input",
    "get_user_days_report",
    "open_days_for_user",
    "close_days_for_user",
    "reset_days_for_user",
]
