from __future__ import annotations
import asyncio
import html
import logging
import random
from typing import Optional, List, Tuple, Dict, Any
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
import time

from database.news import (
    NEWS_REACTIONS,
    record_deliveries_batch,
    update_news_stats,
    get_news_by_id,
    get_news_reactions_summary,
    format_news_reactions_line,
    update_text_with_reactions_line,
    get_delivered_news_messages,
    get_news_failed_deliveries_detailed
)
from bot.utils.message_utils import sanitize_telegram_html

logger = logging.getLogger(__name__)


def classify_telegram_error(error_str: str) -> str:
    """
    Класифікує помилку Telegram API у зрозумілий та охайний статус для звіту.
    """
    err_lower = error_str.lower()
    if "blocked by the user" in err_lower:
        return "⛔️ Бот заблокований користувачем"
    if "user is deactivated" in err_lower:
        return "👤 Акаунт деактивовано / видалено"
    if "chat not found" in err_lower:
        return "❓ Чат не знайдено"
    if "retry after" in err_lower or "flood" in err_lower:
        return "⏳ Ліміт запитів Telegram (Flood limit)"
    return f"⚠️ {error_str[:80]}"


def get_news_reaction_keyboard(news_id: int, current_reaction: Optional[str] = None) -> InlineKeyboardMarkup:
    """
    Формує інлайн-клавіатуру з 4 реакціями для новини.
    Якщо користувач уже обрав реакцію, додає позначку ✅ біля неї.
    """
    buttons = []
    for r in NEWS_REACTIONS:
        text = f"{r} ✅" if current_reaction == r else r
        buttons.append(InlineKeyboardButton(text=text, callback_data=f"news_react:{news_id}:{r}"))
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


async def send_news_batch(
    bot: Bot,
    recipient_uids: List[int],
    text: str,
    photo_file_id: Optional[str] = None,
    news_id: Optional[int] = None,
    video_file_id: Optional[str] = None,
    media_type: Optional[str] = None
) -> Tuple[int, int]:
    """
    Надсилає новину одній пачці (хвилі) користувачів (до 50 осіб)
    з мікропаузою 0.08с між відправками для захисту від Telegram Flood limits.
    Фіксує результат кожної доставки в базі даних.
    """
    sent_count = 0
    failed_count = 0
    deliveries = []

    clean_text = sanitize_telegram_html(text)
    if news_id:
        initial_line = format_news_reactions_line({})
        clean_text = update_text_with_reactions_line(clean_text, initial_line)
    reply_markup = get_news_reaction_keyboard(news_id) if news_id else None

    effective_media_type = media_type
    if not effective_media_type:
        if video_file_id:
            effective_media_type = "video"
        elif photo_file_id:
            effective_media_type = "photo"

    for user_id in recipient_uids:
        try:
            # 1. Відправка медіа (за наявності) з захистом від падіння
            if effective_media_type == "video" and video_file_id:
                try:
                    await bot.send_video(chat_id=user_id, video=video_file_id)
                except Exception as me:
                    logger.warning(f"[News Broadcaster] Video send warning for user {user_id}: {me}")
            elif effective_media_type == "photo" and photo_file_id:
                try:
                    await bot.send_photo(chat_id=user_id, photo=photo_file_id)
                except Exception as me:
                    logger.warning(f"[News Broadcaster] Photo send warning for user {user_id}: {me}")

            # 2. Відправка тексту новини з автоматичним fallback при збоях HTML
            try:
                sent_msg = await bot.send_message(
                    chat_id=user_id,
                    text=clean_text,
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
            except TelegramBadRequest as tbe:
                err_msg = str(tbe).lower()
                if "can't parse entities" in err_msg or "tag" in err_msg or "entity" in err_msg:
                    logger.warning(f"[News Broadcaster] HTML parse error for user {user_id}, falling back to plain text: {tbe}")
                    sent_msg = await bot.send_message(
                        chat_id=user_id,
                        text=clean_text,
                        reply_markup=reply_markup,
                        parse_mode=None
                    )
                else:
                    raise

            sent_count += 1
            if news_id:
                deliveries.append({
                    "news_id": news_id,
                    "user_id": user_id,
                    "status": "delivered",
                    "error_reason": None,
                    "raw_error": None,
                    "message_id": getattr(sent_msg, "message_id", None)
                })
        except Exception as e:
            logger.warning(f"[News Broadcaster] Failed to send news to user {user_id}: {e}")
            failed_count += 1
            if news_id:
                reason = classify_telegram_error(str(e))
                deliveries.append({
                    "news_id": news_id,
                    "user_id": user_id,
                    "status": "failed",
                    "error_reason": reason,
                    "raw_error": str(e),
                    "message_id": None
                })

        # Мікропауза 0.08с
        await asyncio.sleep(0.08)

    if news_id and deliveries:
        try:
            await record_deliveries_batch(deliveries)
        except Exception as e:
            logger.exception(f"[News Broadcaster] Failed to record deliveries batch: {e}")

    return sent_count, failed_count


async def dispatch_news_waves(
    bot: Bot,
    recipient_uids: List[int],
    text: str,
    photo_file_id: Optional[str] = None,
    admin_chat_id: Optional[int] = None,
    news_id: Optional[int] = None,
    min_wave_delay: int = 300,
    max_wave_delay: int = 600,
    video_file_id: Optional[str] = None,
    media_type: Optional[str] = None
) -> Tuple[int, int]:
    """
    Фонова задача хвильової розсилки новини:
    - Розбиває отримувачів на хвилі по 50 осіб.
    - Мікропауза 0.08с між користувачами.
    - Робить паузу 5-10 хвилин (300-600с) між хвилями.
    - Інформує адміна про хід розсилки.
    - Оновлює підсумковий статус у базі даних.
    """
    if not recipient_uids:
        logger.warning("[News Broadcaster] No recipients provided for news broadcast.")
        if news_id:
            await update_news_stats(news_id, 0, 0, status="completed")
        return 0, 0

    wave_size = 50
    waves = [recipient_uids[i:i + wave_size] for i in range(0, len(recipient_uids), wave_size)]
    total_waves = len(waves)
    total_recipients = len(recipient_uids)

    logger.info(f"[News Broadcaster] Starting news broadcast (news_id={news_id}) to {total_recipients} users in {total_waves} waves.")

    total_sent = 0
    total_failed = 0

    for wave_idx, wave_uids in enumerate(waves, start=1):
        logger.info(f"[News Broadcaster] Dispatching wave {wave_idx}/{total_waves} ({len(wave_uids)} users)...")
        sent, failed = await send_news_batch(
            bot,
            wave_uids,
            text,
            photo_file_id,
            news_id=news_id,
            video_file_id=video_file_id,
            media_type=media_type
        )
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

    logger.info(f"[News Broadcaster] Completed news broadcast (news_id={news_id}): {total_sent} sent, {total_failed} failed of {total_recipients} total.")

    if news_id:
        try:
            await update_news_stats(news_id, total_sent, total_failed, status="completed")
        except Exception as e:
            logger.exception(f"[News Broadcaster] Failed to update news stats for news_id={news_id}: {e}")

    if admin_chat_id:
        try:
            report_lines = [
                "🏁 <b>Розсилку новини повністю завершено!</b>",
                "───────────────────",
                f"📬 Всього отримувачів: <b>{total_recipients}</b>",
                f"✅ Успішно доставлено: <b>{total_sent}</b>",
                f"❌ Не вдалося доставити: <b>{total_failed}</b>",
                f"🌊 Всього хвиль: <b>{total_waves}</b>"
            ]

            if total_failed > 0 and news_id:
                try:
                    failed_details = await get_news_failed_deliveries_detailed(news_id)
                    if failed_details:
                        report_lines.append("\n⚠️ <b>Не отримали повідомлення:</b>")
                        display_items = failed_details[:15]
                        for fd in display_items:
                            uid = fd.get("user_id")
                            name = fd.get("full_name") or (f"@{fd['username']}" if fd.get("username") else f"ID {uid}")
                            name_clean = html.escape(str(name))
                            
                            meta_parts = []
                            if fd.get("role"):
                                meta_parts.append(str(fd["role"]))
                            if fd.get("shop"):
                                meta_parts.append(str(fd["shop"]))
                            meta_str = f" | {', '.join(meta_parts)}" if meta_parts else ""
                            
                            reason = fd.get("error_reason") or "Помилка доставки"
                            report_lines.append(f"• <b>{name_clean}</b> (<code>{uid}</code>{html.escape(meta_str)}) — {html.escape(str(reason))}")
                        
                        if len(failed_details) > 15:
                            remaining = len(failed_details) - 15
                            report_lines.append(f"<i>...та ще {remaining} осіб</i>")
                except Exception as fe:
                    logger.warning(f"[News Broadcaster] Could not attach failed details to report: {fe}")

            await bot.send_message(
                chat_id=admin_chat_id,
                text="\n".join(report_lines),
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
    admin_chat_id: Optional[int] = None,
    news_id: Optional[int] = None,
    min_wave_delay: int = 300,
    max_wave_delay: int = 600,
    video_file_id: Optional[str] = None,
    media_type: Optional[str] = None
) -> asyncio.Task:
    """Запускає фонову похвильову розсилку новини."""
    return asyncio.create_task(
        dispatch_news_waves(
            bot=bot,
            recipient_uids=recipient_uids,
            text=text,
            photo_file_id=photo_file_id,
            admin_chat_id=admin_chat_id,
            news_id=news_id,
            min_wave_delay=min_wave_delay,
            max_wave_delay=max_wave_delay,
            video_file_id=video_file_id,
            media_type=media_type
        )
    )


class NewsReactionSyncQueue:
    """
    Фоновий менеджер черги синхронізації лічильників реакцій новин для всіх отримувачів.
    Використовує дебаунс (за замовчуванням 15 сек, макс 30 сек) та безпечно оновлює
    повідомлення отримувачів пакетами, не перевищуючи ліміти Telegram.
    """

    def __init__(self, debounce_seconds: float = 15.0, max_wait_seconds: float = 30.0, db_path: Optional[str] = None):
        self.debounce_seconds = debounce_seconds
        self.max_wait_seconds = max_wait_seconds
        self.db_path = db_path
        self._pending: Dict[int, Dict[str, Any]] = {}

    def schedule_sync(self, bot: Bot, news_id: int, trigger_user_id: Optional[int] = None) -> None:
        """Планує відкладену синхронізацію після кліку реакції."""
        now = time.time()
        info = self._pending.get(news_id)
        if not info:
            info = {
                "first_triggered": now,
                "last_triggered": now,
                "exclude_uids": set(),
                "timer_task": None,
            }
            self._pending[news_id] = info
        else:
            info["last_triggered"] = now

        if trigger_user_id:
            info["exclude_uids"].add(trigger_user_id)

        # Скасовуємо попередній таймер дебаунсу, якщо він активний
        prev_task = info.get("timer_task")
        if prev_task and not prev_task.done():
            prev_task.cancel()

        # Розраховуємо дебаунс з урахуванням граничного max_wait_seconds
        elapsed = now - info["first_triggered"]
        remaining_max = max(0.0, self.max_wait_seconds - elapsed)
        delay = min(self.debounce_seconds, remaining_max)

        info["timer_task"] = asyncio.create_task(self._delayed_sync(bot, news_id, delay))

    async def _delayed_sync(self, bot: Bot, news_id: int, delay: float) -> None:
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            await self._execute_sync(bot, news_id)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception(f"[NewsReactionSyncQueue] Unexpected error during sync for news {news_id}: {e}")

    async def _execute_sync(self, bot: Bot, news_id: int) -> None:
        info = self._pending.pop(news_id, None)
        exclude_uids = info.get("exclude_uids", set()) if info else set()

        import database.news as news_db_module
        effective_db_path = self.db_path or news_db_module.DB_PATH

        news_row = await get_news_by_id(news_id, db_path=effective_db_path)
        if not news_row:
            return

        summary = await get_news_reactions_summary(news_id, db_path=effective_db_path)
        new_reactions_line = format_news_reactions_line(summary.get("breakdown", {}))

        clean_base_text = sanitize_telegram_html(news_row.get("text", ""))
        full_updated_text = update_text_with_reactions_line(clean_base_text, new_reactions_line)

        messages = await get_delivered_news_messages(news_id, db_path=effective_db_path)
        if not messages:
            return

        # Завантажуємо реакції користувачів для збереження їхніх індивідуальних позначок ✅
        import aiosqlite
        user_reactions = {}
        try:
            async with aiosqlite.connect(effective_db_path) as db:
                cursor = await db.execute("SELECT user_id, reaction FROM news_reactions WHERE news_id = ?", (news_id,))
                rows = await cursor.fetchall()
                user_reactions = {r[0]: r[1] for r in rows}
        except Exception as e:
            logger.warning(f"[NewsReactionSyncQueue] Could not load user reactions for news {news_id}: {e}")

        logger.info(
            f"[NewsReactionSyncQueue] Syncing live reactions for news {news_id} to {len(messages)} recipients: '{new_reactions_line}'"
        )

        for item in messages:
            uid = item.get("user_id")
            mid = item.get("message_id")
            if not uid or not mid:
                continue

            # Користувача, який щойно голосував, пропускаємо (його повідомлення вже оновлено миттєво)
            if uid in exclude_uids:
                continue

            user_reaction = user_reactions.get(uid)
            kb = get_news_reaction_keyboard(news_id, current_reaction=user_reaction)

            try:
                try:
                    await bot.edit_message_text(
                        chat_id=uid,
                        message_id=mid,
                        text=full_updated_text,
                        reply_markup=kb,
                        parse_mode="HTML"
                    )
                except TelegramBadRequest as tbe:
                    err_lower = str(tbe).lower()
                    if "message is not modified" in err_lower:
                        pass
                    elif "no text in the message to edit" in err_lower or "there is no text" in err_lower:
                        # Спроба редагувати caption, якщо повідомлення було з фото/відео
                        await bot.edit_message_caption(
                            chat_id=uid,
                            message_id=mid,
                            caption=full_updated_text,
                            reply_markup=kb,
                            parse_mode="HTML"
                        )
                    elif any(term in err_lower for term in ["message to edit not found", "chat not found", "bot was blocked", "user is deactivated"]):
                        pass
                    else:
                        logger.debug(f"[NewsReactionSyncQueue] Edit error for uid={uid}: {tbe}")
            except TelegramRetryAfter as tra:
                logger.warning(f"[NewsReactionSyncQueue] Flood wait {tra.retry_after}s for news {news_id}")
                await asyncio.sleep(tra.retry_after)
            except Exception as e:
                err_lower = str(e).lower()
                if not any(term in err_lower for term in ["blocked", "deactivated", "not found", "not modified"]):
                    logger.debug(f"[NewsReactionSyncQueue] Failed to edit for uid={uid}: {e}")

            # Захисна мікропауза 0.05с між викликами
            await asyncio.sleep(0.05)


news_reaction_sync_queue = NewsReactionSyncQueue()
