from __future__ import annotations
import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple, Optional
import pytz
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.config import TIMEZONE
from database.surveys import (
    get_survey_by_id,
    get_max_wave_for_survey,
    get_pending_wave_recipients,
    mark_survey_recipient_sent,
    mark_survey_recipient_failed,
    update_survey_status,
    get_due_survey_reminders,
    record_survey_reminder_sent
)

logger = logging.getLogger(__name__)


def calculate_next_survey_reminder_time(base_dt: Optional[datetime] = None) -> datetime:
    """
    Розраховує час наступного нагадування:
    - Випадковий інтервал 3-7 годин (180 - 420 хвилин).
    - Вікно відправки: 09:00 - 19:00 за київським часом.
    - Якщо час потрапляє після 19:00 — переноситься на 10:30 наступного ранку.
    - Якщо час до 09:00 — переноситься на 10:30 цього ж ранку.
    """
    tz = pytz.timezone(TIMEZONE)
    if not base_dt:
        now_tz = datetime.now(tz)
    else:
        now_tz = base_dt.astimezone(tz) if base_dt.tzinfo else tz.localize(base_dt)

    random_minutes = random.randint(180, 420)
    target_dt = now_tz + timedelta(minutes=random_minutes)

    # Якщо час пізніше 19:00
    if target_dt.hour >= 19:
        # Переносимо на наступний день о 10:30 (із випадковим зміщенням +/- 15 хв для природності)
        next_day = target_dt.date() + timedelta(days=1)
        target_dt = tz.localize(datetime(next_day.year, next_day.month, next_day.day, 10, 30))
    elif target_dt.hour < 9:
        # Переносимо на 10:30 цього ж дня
        target_dt = tz.localize(datetime(target_dt.year, target_dt.month, target_dt.day, 10, 30))

    return target_dt


def get_survey_invite_keyboard(survey_id: int) -> InlineKeyboardMarkup:
    """Клавіатура для старту опитування."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Пройти опитування", callback_data=f"survey_start:{survey_id}")]
    ])


def format_survey_invite_text(title: str) -> str:
    """Форматує текст початкового запрошення до опитування."""
    return (
        "📋 <b>Нове опитування мережі BULKA</b>\n"
        f"«<b>{title}</b>»\n"
        "───────────────────\n"
        "🔒 <i>Це опитування є повністю анонімним. Ваші щирі відповіді допоможуть нам зробити умови праці та процеси ще зручнішими!</i>\n\n"
        "⏳ <i>Проходження займе не більше 2–3 хвилин.</i>"
    )


def format_survey_reminder_text(title: str, reminder_number: int) -> str:
    """Форматує текст одного з трьох шаблонів нагадування."""
    if reminder_number == 1:
        return (
            "👋 <b>Привіт!</b> 🥐\n\n"
            f"Нагадуємо про опитування «<b>{title}</b>».\n"
            "Твоя думка дуже важлива для всієї команди BULKA! Проходження займе всього пару хвилин. ☕️\n\n"
            "<i>Це опитування повністю анонімне.</i>"
        )
    elif reminder_number == 2:
        return (
            "👋 <b>Привіт знову!</b> 🥐\n\n"
            f"Ми все ще чекаємо на твої відповіді в опитуванні «<b>{title}</b>».\n"
            "Допоможи нам покращити роботу та процеси в магазинах BULKA! ✨\n\n"
            "<i>Це опитування повністю анонімне.</i>"
        )
    else:
        return (
            "⏳ <b>Останнє нагадування!</b> 🥐\n\n"
            f"Опитування «<b>{title}</b>» незабаром завершиться.\n"
            "Поділись своїми думками — це повністю анонімно та дуже допоможе нашій команді!"
        )


async def send_survey_wave_batch(
    bot: Bot,
    survey_id: int,
    recipients: List[Dict[str, Any]],
    survey_title: str
) -> Tuple[int, int]:
    """Надсилає опитування одній хвилі користувачів (до 50 чол.)."""
    sent_count = 0
    failed_count = 0
    text = format_survey_invite_text(survey_title)
    kb = get_survey_invite_keyboard(survey_id)

    for rec in recipients:
        user_id = rec["user_id"]
        rec_id = rec["id"]

        try:
            await bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=kb,
                parse_mode="HTML"
            )
            next_rem = calculate_next_survey_reminder_time()
            await mark_survey_recipient_sent(rec_id, next_rem)
            sent_count += 1
        except Exception as e:
            logger.warning(f"Failed to send survey {survey_id} to user {user_id}: {e}")
            await mark_survey_recipient_failed(rec_id)
            failed_count += 1

        # Безпечна мікропауза для уникнення Telegram Flood Limit
        await asyncio.sleep(0.08)

    return sent_count, failed_count


async def dispatch_survey_waves(bot: Bot, survey_id: int) -> None:
    """
    Фонова задача для послідовного надсилання хвиль опитування
    із випадковою затримкою 5-10 хвилин між хвилями.
    """
    survey = await get_survey_by_id(survey_id)
    if not survey:
        return

    title = survey.get("title", "Опитування BULKA")
    await update_survey_status(survey_id, "broadcasting")

    max_waves = await get_max_wave_for_survey(survey_id)
    logger.info(f"Starting survey {survey_id} wave broadcast: {max_waves} waves total.")

    for wave in range(1, max_waves + 1):
        pending = await get_pending_wave_recipients(survey_id, wave)
        if pending:
            logger.info(f"Dispatching survey {survey_id} wave {wave}/{max_waves} ({len(pending)} users)...")
            sent, failed = await send_survey_wave_batch(bot, survey_id, pending, title)
            logger.info(f"Survey wave {wave} finished: {sent} sent, {failed} failed.")

        # Якщо це не остання хвиля, очікуємо випадково 5-10 хвилин (300 - 600 секунд)
        if wave < max_waves:
            delay_sec = random.randint(300, 600)
            logger.info(f"Waiting {delay_sec} seconds before wave {wave + 1}...")
            await asyncio.sleep(delay_sec)

    await update_survey_status(survey_id, "active")
    logger.info(f"Survey {survey_id} wave broadcast completed successfully. Status set to active.")


async def start_survey_wave_broadcast(first_arg: Any, second_arg: Any) -> asyncio.Task:
    """
    Запускає асинхронну похвильову розсилку опитування у фоновому режимі.
    Підтримує виклик як (survey_id, bot), так і (bot, survey_id).
    """
    if isinstance(first_arg, Bot):
        bot = first_arg
        survey_id = int(second_arg)
    else:
        survey_id = int(first_arg)
        bot = second_arg
    return asyncio.create_task(dispatch_survey_waves(bot, survey_id))


async def survey_reminder_worker(bot: Bot) -> None:
    """
    Фоновий періодичний воркер для перевірки та відправки нагадувань про опитування.
    Перевіряє базу щохвилини.
    """
    logger.info("[Survey Reminder Worker] Started.")
    while True:
        try:
            due_reminders = await get_due_survey_reminders()
            if due_reminders:
                for rec in due_reminders:
                    user_id = rec["user_id"]
                    rec_id = rec["id"]
                    survey_id = rec["survey_id"]
                    survey_title = rec.get("survey_title", "Опитування BULKA")
                    reminders_sent = rec.get("reminders_sent", 0)

                    # Наступний номер нагадування (1, 2 або 3)
                    next_num = reminders_sent + 1
                    text = format_survey_reminder_text(survey_title, next_num)
                    kb = get_survey_invite_keyboard(survey_id)

                    try:
                        await bot.send_message(
                            chat_id=user_id,
                            text=text,
                            reply_markup=kb,
                            parse_mode="HTML"
                        )
                        # Якщо це було 1-ше чи 2-ге нагадування, призначаємо наступне
                        if next_num < 3:
                            next_rem = calculate_next_survey_reminder_time()
                        else:
                            next_rem = None

                        await record_survey_reminder_sent(rec_id, next_rem)
                        logger.info(f"Sent reminder #{next_num} for survey {survey_id} to user {user_id}")
                    except Exception as e:
                        logger.warning(f"Failed to send survey reminder to user {user_id}: {e}")
                        # При невдачі спробуємо знову пізніше
                        next_rem = calculate_next_survey_reminder_time()
                        await record_survey_reminder_sent(rec_id, next_rem)

                    await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            logger.info("[Survey Reminder Worker] Gracefully stopped.")
            break
        except Exception as e:
            logger.error(f"Error in survey_reminder_worker: {e}", exc_info=True)

        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            break
