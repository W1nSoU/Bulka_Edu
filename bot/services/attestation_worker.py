from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
import pytz
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.config import TIMEZONE
from database.attestation import (
    get_active_wave,
    get_wave_by_id,
    get_wave_participants,
    get_user_latest_attempt
)
from database import DB_PATH
import aiosqlite

logger = logging.getLogger(__name__)


def get_attestation_action_button(text: str = "🚀 Розпочати атестацію", user_id: Optional[int] = None) -> InlineKeyboardButton:
    """
    Повертає нативну інлайн-кнопку бота для запуску тестування.
    """
    return InlineKeyboardButton(text=text, callback_data="att_start_test")


async def launch_attestation_broadcast(bot: Bot, wave_id: int) -> None:
    """
    Фонова задача безпечної похвильової розсилки сповіщень про старт атестації.
    Розбиває на пачки по 40 осіб з мікро-паузами.
    """
    wave = await get_wave_by_id(wave_id)
    if not wave:
        logger.error(f"Хвилю {wave_id} не знайдено для розсилки.")
        return

    participants = await get_wave_participants(wave_id)
    logger.info(f"🚀 Початок розсилки атестації хвилі #{wave_id} для {len(participants)} учасників.")

    title = wave.get("title", "Корпоративна атестація")
    duration = wave.get("duration_minutes", 20)
    passing_pct = wave.get("passing_score_pct", 80)
    deadline = wave.get("deadline_date", "")

    # Форматуємо дату дедлайну
    try:
        dt = datetime.strptime(deadline, "%Y-%m-%d %H:%M:%S")
        deadline_formatted = dt.strftime("%d.%m.%Y о %H:%M")
    except Exception:
        deadline_formatted = deadline

    batch_size = 40
    sent_count = 0
    failed_count = 0

    for i in range(0, len(participants), batch_size):
        batch = participants[i:i + batch_size]
        for p in batch:
            user_id = p["user_id"]
            user_name = p.get("full_name") or "Колего"
            shop_name = p.get("shop_name") or "Твій магазин"

            text = (
                f"🥐 <b>{title} розпочалась!</b>\n\n"
                f"Привіт, <b>{user_name}</b>! Для твого магазину <b>{shop_name}</b> відкрито період корпоративної атестації.\n\n"
                f"⏱ <b>Час на тест:</b> {duration} хвилин (1 спроба)\n"
                f"🎯 <b>Прохідний поріг:</b> {passing_pct}%\n"
                f"📅 <b>Дедлайн:</b> до {deadline_formatted}\n\n"
                f"Натискай кнопку нижче, щоб відкрити застосунок та перевірити свої знання! 👇"
            )

            # Безпечна інлайн-кнопка (HTTPS -> Mini App, HTTP -> browser fallback)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [get_attestation_action_button("🚀 Розпочати атестацію", user_id=user_id)]
            ])

            try:
                await bot.send_message(chat_id=user_id, text=text, parse_mode="HTML", reply_markup=kb)
                sent_count += 1
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        "UPDATE attestation_participants SET notification_sent = 1 WHERE wave_id = ? AND user_id = ?",
                        (wave_id, user_id)
                    )
                    await db.commit()
            except Exception as e:
                failed_count += 1
                logger.warning(f"Не вдалося надіслати запрошення на атестацію користувачу {user_id}: {e}")

            await asyncio.sleep(0.08) # мікро-пауза для захисту від flood limit

        if i + batch_size < len(participants):
            await asyncio.sleep(10) # пауза між пачками

    logger.info(f"✅ Розсилку атестації #{wave_id} завершено. Успішно: {sent_count}, помилок: {failed_count}.")


async def attestation_reminder_worker(bot: Bot) -> None:
    """
    Фоновий періодичний воркер нагадувань про атестацію.
    Працює в денний час (09:00 - 19:00).
    Надсилає до 3 нагадувань: за 72г, 24г та 6г до дедлайну.
    """
    while True:
        try:
            wave = await get_active_wave()
            if wave:
                tz = pytz.timezone(TIMEZONE)
                now = datetime.now(tz)

                # Перевіряємо денний інтервал (09:00 - 19:00)
                if 9 <= now.hour < 19:
                    deadline_str = wave.get("deadline_date")
                    try:
                        deadline_dt = datetime.strptime(deadline_str, "%Y-%m-%d %H:%M:%S")
                        deadline_dt = tz.localize(deadline_dt) if deadline_dt.tzinfo is None else deadline_dt
                        hours_left = (deadline_dt - now).total_seconds() / 3600.0

                        participants = await get_wave_participants(wave["id"])
                        for p in participants:
                            user_id = p["user_id"]
                            # Перевіряємо чи користувач уже склав тест
                            attempt = await get_user_latest_attempt(wave["id"], user_id)
                            if attempt and attempt["status"] == "passed":
                                continue

                            reminders_sent = p.get("reminders_sent", 0)
                            should_remind = False
                            reminder_text = ""

                            if hours_left <= 6 and reminders_sent < 3:
                                should_remind = True
                                reminders_sent_new = 3
                                reminder_text = (
                                    f"🚨 <b>Останнє нагадування! Атестація завершується сьогодні!</b>\n\n"
                                    f"Залишилося менше 6 годин до закриття тестування для магазину <b>{p['shop_name']}</b>.\n"
                                    f"Пройди атестацію зараз, щоб результат твого магазину був максимальним! 🥐"
                                )
                            elif hours_left <= 24 and reminders_sent < 2:
                                should_remind = True
                                reminders_sent_new = 2
                                reminder_text = (
                                    f"⏰ <b>Нагадування: Залишилось менше 24 годин!</b>\n\n"
                                    f"Атестація для магазину <b>{p['shop_name']}</b> закінчується завтра.\n"
                                    f"Не відкладай — виділи 20 хвилин та склади тест у Mini App. 👇"
                                )
                            elif hours_left <= 72 and reminders_sent < 1:
                                should_remind = True
                                reminders_sent_new = 1
                                reminder_text = (
                                    f"🔔 <b>Нагадування про корпоративну атестацію</b>\n\n"
                                    f"До дедлайну атестації залишилось 3 дні. Твій магазин <b>{p['shop_name']}</b> розраховує на твої знання!\n"
                                    f"Таймер тесту: {wave.get('duration_minutes', 20)} хв. Успіхів! 🥐"
                                )

                            if should_remind:
                                kb = InlineKeyboardMarkup(inline_keyboard=[
                                    [get_attestation_action_button("🚀 Пройти атестацію", user_id=user_id)]
                                ])
                                try:
                                    await bot.send_message(chat_id=user_id, text=reminder_text, parse_mode="HTML", reply_markup=kb)
                                    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
                                    async with aiosqlite.connect(DB_PATH) as db:
                                        await db.execute('''
                                        UPDATE attestation_participants 
                                        SET reminders_sent = ?, last_reminder_at = ?
                                        WHERE wave_id = ? AND user_id = ?
                                        ''', (reminders_sent_new, now_str, wave["id"], user_id))
                                        await db.commit()
                                except Exception as e:
                                    logger.warning(f"Помилка відправки нагадування атестації {user_id}: {e}")

                                await asyncio.sleep(0.1)

                    except Exception as e:
                        logger.error(f"Помилка обробки дедлайну атестації у воркері: {e}")

        except Exception as e:
            logger.error(f"Помилка в attestation_reminder_worker: {e}")

        # Перевірка щогодини
        await asyncio.sleep(3600)
