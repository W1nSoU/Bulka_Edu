from __future__ import annotations
import asyncio
import json
import logging
from typing import Optional, List, Dict, Any, Tuple
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database.material_notifications import (
    get_pending_wave_recipients,
    mark_recipient_sent,
    mark_recipient_failed,
    get_event_by_id,
    get_max_wave_for_event,
)

logger = logging.getLogger(__name__)


def build_material_notification_keyboard(
    event_id: int,
    recipient_id: int,
    current_page: int,
    total_pages: int,
    is_acknowledged: bool = False
) -> InlineKeyboardMarkup:
    """
    Будує клавіатуру для сповіщення про зміну матеріалів.
    - Якщо total_pages > 1: рядок навігації ⬅️ / ➡️.
    - На останній сторінці (current_page == total_pages - 1) або якщо всього 1 сторінка:
      кнопка [ 🔘 Зі змінами ознайомлений/а ] (або [ ✅ Ви ознайомлені зі змінами ]).
    """
    kb_rows = []

    # Рядок пагінації
    if total_pages > 1:
        nav_row = []
        if current_page > 0:
            nav_row.append(InlineKeyboardButton(
                text="⬅️",
                callback_data=f"mat_ch_pag:{event_id}:{recipient_id}:{current_page - 1}"
            ))
        nav_row.append(InlineKeyboardButton(
            text=f"📄 {current_page + 1}/{total_pages}",
            callback_data="ignore"
        ))
        if current_page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(
                text="➡️",
                callback_data=f"mat_ch_pag:{event_id}:{recipient_id}:{current_page + 1}"
            ))
        kb_rows.append(nav_row)

    # Кнопка ознайомлення (відображається на останній сторінці або якщо 1 сторінка)
    if current_page == total_pages - 1 or total_pages <= 1:
        if is_acknowledged:
            kb_rows.append([InlineKeyboardButton(
                text="✅ Ви ознайомлені зі змінами",
                callback_data="ignore"
            )])
        else:
            kb_rows.append([InlineKeyboardButton(
                text="🔘 Зі змінами ознайомлений/а",
                callback_data=f"mat_ch_ack:{event_id}:{recipient_id}"
            )])

    return InlineKeyboardMarkup(inline_keyboard=kb_rows)


def format_material_notification_text(
    role: str,
    day: int,
    page_content: str,
    current_page: int,
    total_pages: int
) -> str:
    """Форматує текст повідомлення сповіщення для користувача."""
    header = (
        f"📢 <b>Оновлення навчальних матеріалів</b>\n"
        f"📚 Посада: <b>{role}</b> | 📅 День: <b>{day}</b>\n"
        f"───────────────────\n\n"
    )
    return header + page_content


async def send_wave_batch(bot: Bot, recipients: List[Dict[str, Any]]) -> Tuple[int, int]:
    """
    Надсилає повідомлення поточної хвилі списку отримувачів.
    Повертає (кількість успішно надісланих, кількість помилок).
    """
    sent_count = 0
    failed_count = 0

    for rec in recipients:
        user_id = rec['user_id']
        rec_id = rec['id']
        event_id = rec['event_id']
        role = rec.get('role', '')
        day = rec.get('day', 1)
        pages_raw = rec.get('pages_json', '[]')
        
        try:
            pages = json.loads(pages_raw)
            if not isinstance(pages, list) or not pages:
                pages = [rec.get('description', 'Оновлено матеріали')]
        except Exception:
            pages = [rec.get('description', 'Оновлено матеріали')]

        total_pages = len(pages)
        first_page_text = format_material_notification_text(role, day, pages[0], 0, total_pages)
        kb = build_material_notification_keyboard(event_id, rec_id, 0, total_pages, is_acknowledged=False)

        try:
            msg = await bot.send_message(
                chat_id=user_id,
                text=first_page_text,
                reply_markup=kb,
                parse_mode="HTML"
            )
            await mark_recipient_sent(rec_id, message_id=msg.message_id)
            sent_count += 1
        except Exception as e:
            logger.warning(f"Failed to send material notification to user {user_id}: {e}")
            await mark_recipient_failed(rec_id)
            failed_count += 1

        # Безпечна мікропауза для уникнення Telegram Flood Limit
        await asyncio.sleep(0.08)

    return sent_count, failed_count


async def dispatch_event_waves(bot: Bot, event_id: int):
    """
    Фонова задача для послідовного надсилання всіх хвиль для конкретної події
    з інтервалом в 1 годину (3600 секунд) між хвилями.
    """
    max_waves = await get_max_wave_for_event(event_id)
    
    for wave in range(1, max_waves + 1):
        pending_recipients = await get_pending_wave_recipients(wave_number=wave, event_id=event_id)
        if pending_recipients:
            logger.info(f"Dispatching wave {wave}/{max_waves} for event {event_id} ({len(pending_recipients)} users)...")
            sent, failed = await send_wave_batch(bot, pending_recipients)
            logger.info(f"Wave {wave} finished: {sent} sent, {failed} failed.")

        # Якщо це не остання хвиля, чекаємо 1 годину перед наступною
        if wave < max_waves:
            await asyncio.sleep(3600)


def start_event_wave_broadcast(bot: Bot, event_id: int):
    """Запускає асинхронну розсилку хвиль у фоновому режимі."""
    asyncio.create_task(dispatch_event_waves(bot, event_id))
