from __future__ import annotations
import asyncio
import logging
import random
from typing import Optional, List, Tuple
from aiogram import Bot

logger = logging.getLogger(__name__)


async def send_news_batch(
    bot: Bot,
    recipient_uids: List[int],
    text: str,
    photo_file_id: Optional[str] = None
) -> Tuple[int, int]:
    """
    Надсилає новину одній пачці (хвилі) користувачів (до 50 осіб)
    з мікропаузою 0.08с між відправками для захисту від Telegram Flood limits.
    """
    sent_count = 0
    failed_count = 0

    for user_id in recipient_uids:
        try:
            if photo_file_id:
                await bot.send_photo(
                    chat_id=user_id,
                    photo=photo_file_id,
                    caption=text,
                    parse_mode="HTML"
                )
            else:
                await bot.send_message(
                    chat_id=user_id,
                    text=text,
                    parse_mode="HTML"
                )
            sent_count += 1
        except Exception as e:
            logger.warning(f"[News Broadcaster] Failed to send news to user {user_id}: {e}")
            failed_count += 1

        # Мікропауза 0.08с
        await asyncio.sleep(0.08)

    return sent_count, failed_count


async def dispatch_news_waves(
    bot: Bot,
    recipient_uids: List[int],
    text: str,
    photo_file_id: Optional[str] = None,
    admin_chat_id: Optional[int] = None,
    min_wave_delay: int = 300,
    max_wave_delay: int = 600
) -> Tuple[int, int]:
    """
    Фонова задача хвильової розсилки новини:
    - Розбиває отримувачів на хвилі по 50 осіб.
    - Мікропауза 0.08с між користувачами.
    - Робить паузу 5-10 хвилин (300-600с) між хвилями.
    - Інформує адміна про хід розсилки.
    """
    if not recipient_uids:
        logger.warning("[News Broadcaster] No recipients provided for news broadcast.")
        return 0, 0

    wave_size = 50
    waves = [recipient_uids[i:i + wave_size] for i in range(0, len(recipient_uids), wave_size)]
    total_waves = len(waves)
    total_recipients = len(recipient_uids)

    logger.info(f"[News Broadcaster] Starting news broadcast to {total_recipients} users in {total_waves} waves.")

    total_sent = 0
    total_failed = 0

    for wave_idx, wave_uids in enumerate(waves, start=1):
        logger.info(f"[News Broadcaster] Dispatching wave {wave_idx}/{total_waves} ({len(wave_uids)} users)...")
        sent, failed = await send_news_batch(bot, wave_uids, text, photo_file_id)
        total_sent += sent
        total_failed += failed
        logger.info(f"[News Broadcaster] Wave {wave_idx} finished: {sent} sent, {failed} failed.")

        if admin_chat_id:
            try:
                await bot.send_message(
                    chat_id=admin_chat_id,
                    text=(
                        f"🌊 <b>Звіт хвилі #{wave_idx}/{total_waves}</b>\n"
                        f"• Успішно надіслано: <b>{sent}</b>\n"
                        f"• Не вдалося доставити: <b>{failed}</b>"
                    ),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"[News Broadcaster] Could not send wave report to admin {admin_chat_id}: {e}")

        # Якщо це не остання хвиля, очікуємо min_wave_delay - max_wave_delay секунд
        if wave_idx < total_waves:
            if max_wave_delay > 0:
                delay_sec = random.randint(min_wave_delay, max_wave_delay)
                logger.info(f"[News Broadcaster] Waiting {delay_sec} seconds before wave {wave_idx + 1}...")
                await asyncio.sleep(delay_sec)

    logger.info(f"[News Broadcaster] Completed news broadcast: {total_sent} sent, {total_failed} failed of {total_recipients} total.")

    if admin_chat_id:
        try:
            await bot.send_message(
                chat_id=admin_chat_id,
                text=(
                    f"🏁 <b>Розсилку новини повністю завершено!</b>\n"
                    f"───────────────────\n"
                    f"📬 Всього отримувачів: <b>{total_recipients}</b>\n"
                    f"✅ Успішно доставлено: <b>{total_sent}</b>\n"
                    f"❌ Не вдалося доставити: <b>{total_failed}</b>\n"
                    f"🌊 Всього хвиль: <b>{total_waves}</b>"
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"[News Broadcaster] Could not send final report to admin {admin_chat_id}: {e}")

    return total_sent, total_failed


def start_news_wave_broadcast(
    bot: Bot,
    recipient_uids: List[int],
    text: str,
    photo_file_id: Optional[str] = None,
    admin_chat_id: Optional[int] = None
) -> asyncio.Task:
    """Запускає фонову похвильову розсилку новини."""
    return asyncio.create_task(
        dispatch_news_waves(
            bot=bot,
            recipient_uids=recipient_uids,
            text=text,
            photo_file_id=photo_file_id,
            admin_chat_id=admin_chat_id
        )
    )
