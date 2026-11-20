from __future__ import annotations
import asyncio
import html
import json
import logging
from typing import Optional, List, Dict, Any, Tuple
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
)

from database.material_notifications import (
    WAVE_BATCH_SIZE,
    get_pending_wave_recipients,
    mark_recipient_sent,
    mark_recipient_failed,
    get_max_wave_for_event,
    get_events_with_pending_recipients,
    mark_event_completed_if_done,
)

logger = logging.getLogger(__name__)

WAVE_INTERVAL_SECONDS = 240  # 4 хвилини між хвилями по 40 осіб
PER_MESSAGE_DELAY_SECONDS = 0.08
TELEGRAM_TEXT_SAFE_LIMIT = 3980
TELEGRAM_CAPTION_SAFE_LIMIT = 970

_active_event_ids: set[int] = set()

CHANGE_TYPE_BADGES = {
    "added": "🆕 <b>Додано</b>",
    "modified": "✏️ <b>Змінено</b>",
    "deleted": "❌ <b>Видалено</b>",
}


def normalize_change_page(
    raw_page: Any,
    default_day: int = 1,
    default_change_type: str = "manual",
) -> Dict[str, Any]:
    """
    Приводить сторінку до єдиного формату dict з повною зворотною сумісністю
    зі старими подіями (де сторінки зберігались як прості рядки str).
    """
    if isinstance(raw_page, dict):
        text = raw_page.get("text")
        if text is None:
            text = raw_page.get("content", "")
        text = str(text) if text is not None else ""

        change_type = raw_page.get("change_type")
        if not change_type:
            if (
                raw_page.get("status") == "deleted"
                or raw_page.get("deleted") is True
                or raw_page.get("type") == "deleted"
            ):
                change_type = "deleted"
            else:
                change_type = default_change_type

        day_val = raw_page.get("day", default_day)
        try:
            day_val = int(day_val)
        except (TypeError, ValueError):
            day_val = default_day

        page: Dict[str, Any] = {
            "text": text,
            "change_type": str(change_type),
            "day": day_val,
            "source_type": str(raw_page.get("source_type") or "text"),
        }
        if raw_page.get("photo"):
            page["photo"] = str(raw_page["photo"])
        if raw_page.get("video"):
            page["video"] = str(raw_page["video"])
        if raw_page.get("comment"):
            page["comment"] = str(raw_page["comment"])
        return page

    # Legacy string page
    text_str = str(raw_page) if raw_page is not None else ""
    lowered = text_str.lower()
    inferred_type = default_change_type
    if "❌" in text_str[:15] or "видалено" in lowered[:25] or "[видалено]" in lowered[:25]:
        inferred_type = "deleted"
    return {
        "text": text_str,
        "change_type": inferred_type,
        "day": default_day,
        "source_type": "text",
    }


def normalize_change_pages(
    raw_pages: Any,
    fallback_text: str = "Оновлено навчальні матеріали",
    default_day: int = 1,
    default_change_type: str = "manual",
) -> List[Dict[str, Any]]:
    """Парсить pages_json або list у список нормалізованих сторінок."""
    parsed = raw_pages
    if isinstance(raw_pages, str):
        try:
            parsed = json.loads(raw_pages)
        except Exception:
            parsed = [raw_pages] if raw_pages.strip() else []

    if not isinstance(parsed, list) or not parsed:
        parsed = [fallback_text]

    return [
        normalize_change_page(p, default_day=default_day, default_change_type=default_change_type)
        for p in parsed
    ]


def summarize_change_pages(pages: List[Dict[str, Any]]) -> str:
    """Формує короткий авто-опис змін для списку аналітики та XLSX."""
    added = sum(1 for p in pages if p.get("change_type") == "added")
    modified = sum(1 for p in pages if p.get("change_type") == "modified")
    deleted = sum(1 for p in pages if p.get("change_type") == "deleted")
    parts = []
    if added:
        parts.append(f"+{added} дод.")
    if modified:
        parts.append(f"{modified} зм.")
    if deleted:
        parts.append(f"{deleted} вид.")
    if not parts:
        return f"Авто-оголошення ({len(pages)} стор.)"
    return "Авто: " + ", ".join(parts)


def build_material_notification_keyboard(
    event_id: int,
    recipient_id: int,
    current_page: int,
    total_pages: int,
    is_acknowledged: bool = False,
) -> InlineKeyboardMarkup:
    """
    Будує клавіатуру для сповіщення про зміну матеріалів.
    - Якщо total_pages > 1: рядок навігації ⬅️ / ➡️.
    - На останній сторінці (current_page == total_pages - 1) або якщо всього 1 сторінка:
      кнопка [ 🔘 Зі змінами ознайомлений/а ] (або [ ✅ Ви ознайомлені зі змінами ]).
    """
    kb_rows = []

    if total_pages > 1:
        nav_row = []
        if current_page > 0:
            nav_row.append(
                InlineKeyboardButton(
                    text="⬅️",
                    callback_data=f"mat_ch_pag:{event_id}:{recipient_id}:{current_page - 1}",
                )
            )
        nav_row.append(
            InlineKeyboardButton(
                text=f"📄 {current_page + 1}/{total_pages}",
                callback_data="ignore",
            )
        )
        if current_page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(
                    text="➡️",
                    callback_data=f"mat_ch_pag:{event_id}:{recipient_id}:{current_page + 1}",
                )
            )
        kb_rows.append(nav_row)

    if current_page == total_pages - 1 or total_pages <= 1:
        if is_acknowledged:
            kb_rows.append(
                [
                    InlineKeyboardButton(
                        text="✅ Ви ознайомлені зі змінами",
                        callback_data="ignore",
                    )
                ]
            )
        else:
            kb_rows.append(
                [
                    InlineKeyboardButton(
                        text="🔘 Зі змінами ознайомлений/а",
                        callback_data=f"mat_ch_ack:{event_id}:{recipient_id}",
                    )
                ]
            )

    return InlineKeyboardMarkup(inline_keyboard=kb_rows)


def _strip_deleted_prefix(text: str) -> str:
    clean = text
    for prefix in ["[ВИДАЛЕНО]", "ВИДАЛЕНО:", "❌ ВИДАЛЕНО", "❌ВИДАЛЕНО"]:
        if clean.startswith(prefix):
            clean = clean[len(prefix):].strip()
    return clean


def format_material_notification_text(
    role: str,
    day: int,
    page_content: Any,
    current_page: int,
    total_pages: int,
    *,
    is_media: Optional[bool] = None,
    header_title: str = "📢 <b>Оновлення навчальних матеріалів</b>",
    extra_header_line: Optional[str] = None,
    escape_body: bool = False,
) -> str:
    """
    Форматує текст (або підпис до фото/відео) сторінки сповіщення про зміну матеріалів.
    Гарантує дотримання лімітів Telegram (4096 для тексту / 1024 для caption).
    """
    page = normalize_change_page(page_content, default_day=day)
    page_day = page.get("day", day)
    has_media = bool(page.get("photo") or page.get("video")) if is_media is None else is_media

    lines = [
        header_title,
        f"📚 Посада: <b>{html.escape(str(role))}</b> | 📅 День: <b>{page_day}</b>",
    ]
    if extra_header_line:
        lines.append(extra_header_line)
    lines.append("───────────────────")

    # Коментар адміністратора показуємо на 1-й сторінці (якщо заданий)
    comment = (page.get("comment") or "").strip()
    if current_page == 0 and comment:
        lines.append(f"💬 <b>Коментар:</b> {html.escape(comment)}")
        lines.append("")

    # Бейдж типу зміни для автоматичних сторінок
    change_type = page.get("change_type", "manual")
    badge = CHANGE_TYPE_BADGES.get(change_type)
    if badge:
        if total_pages > 1:
            lines.append(f"{badge} <i>(Стор. {current_page + 1} з {total_pages})</i>")
        else:
            lines.append(badge)
        lines.append("")

    body = page.get("text") or ""
    if change_type == "deleted":
        body = _strip_deleted_prefix(body)
    if escape_body:
        body = html.escape(body)

    if not body and has_media:
        body = "<i>(Медіа-матеріал без тексту)</i>"

    header_block = "\n".join(lines)
    full_text = f"{header_block}\n{body}" if body else header_block

    limit = TELEGRAM_CAPTION_SAFE_LIMIT if has_media else TELEGRAM_TEXT_SAFE_LIMIT
    if len(full_text) > limit:
        suffix = (
            "\n\n<i>… (повний текст у розділі «Навчання»)</i>"
            if has_media
            else "\n\n<i>[Текст скорочено через обмеження Telegram]</i>"
        )
        allowed_body_len = max(60, limit - len(header_block) - len(suffix) - 2)
        safe_body = html.escape(page.get("text") or "")[:allowed_body_len].rstrip()
        full_text = f"{header_block}\n{safe_body}{suffix}"

    return full_text


async def send_change_page(
    bot: Bot,
    chat_id: int,
    role: str,
    default_day: int,
    pages: List[Any],
    page_idx: int,
    reply_markup: InlineKeyboardMarkup,
    *,
    header_title: str = "📢 <b>Оновлення навчальних матеріалів</b>",
    extra_header_line: Optional[str] = None,
) -> Message:
    """Надсилає нове повідомлення (текст / фото / відео) для сторінки оновлення."""
    norm_pages = normalize_change_pages(pages, default_day=default_day)
    total_pages = len(norm_pages)
    idx = max(0, min(page_idx, total_pages - 1))
    page = norm_pages[idx]
    photo_id = page.get("photo")
    video_id = page.get("video")
    is_media = bool(photo_id or video_id)

    async def _attempt(escape_body: bool) -> Message:
        text = format_material_notification_text(
            role,
            default_day,
            page,
            idx,
            total_pages,
            is_media=is_media,
            header_title=header_title,
            extra_header_line=extra_header_line,
            escape_body=escape_body,
        )
        if photo_id:
            return await bot.send_photo(
                chat_id=chat_id,
                photo=photo_id,
                caption=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        if video_id:
            return await bot.send_video(
                chat_id=chat_id,
                video=video_id,
                caption=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )

    try:
        return await _attempt(escape_body=False)
    except TelegramBadRequest as e:
        if "can't parse entities" in str(e).lower():
            return await _attempt(escape_body=True)
        raise


async def edit_or_replace_change_page(
    message: Message,
    role: str,
    default_day: int,
    pages: List[Any],
    page_idx: int,
    reply_markup: InlineKeyboardMarkup,
    *,
    header_title: str = "📢 <b>Оновлення навчальних матеріалів</b>",
    extra_header_line: Optional[str] = None,
) -> Tuple[Optional[Message], bool]:
    """
    Оновлює існуюче повідомлення на іншу сторінку оновлення.
    Коректно обробляє переходи:
      text -> text (edit_text)
      media -> media (edit_media)
      text <-> media (надсилає нове повідомлення і видаляє старе).
    Повертає (message, was_replaced).
    """
    norm_pages = normalize_change_pages(pages, default_day=default_day)
    total_pages = len(norm_pages)
    idx = max(0, min(page_idx, total_pages - 1))
    page = norm_pages[idx]
    photo_id = page.get("photo")
    video_id = page.get("video")
    target_is_media = bool(photo_id or video_id)
    current_is_media = bool(message.photo or message.video or message.document)

    async def _try_edit(escape_body: bool) -> Tuple[Optional[Message], bool]:
        text = format_material_notification_text(
            role,
            default_day,
            page,
            idx,
            total_pages,
            is_media=target_is_media,
            header_title=header_title,
            extra_header_line=extra_header_line,
            escape_body=escape_body,
        )
        if not current_is_media and not target_is_media:
            await message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
            return message, False

        if current_is_media and target_is_media:
            media = (
                InputMediaPhoto(media=photo_id, caption=text, parse_mode="HTML")
                if photo_id
                else InputMediaVideo(media=video_id, caption=text, parse_mode="HTML")
            )
            await message.edit_media(media=media, reply_markup=reply_markup)
            return message, False

        # Тип повідомлення змінився (text <-> media): створюємо нове і видаляємо старе
        new_msg = await send_change_page(
            message.bot,
            message.chat.id,
            role,
            default_day,
            norm_pages,
            idx,
            reply_markup,
            header_title=header_title,
            extra_header_line=extra_header_line,
        )
        try:
            await message.delete()
        except Exception:
            pass
        return new_msg, True

    try:
        return await _try_edit(escape_body=False)
    except TelegramBadRequest as e:
        err_lower = str(e).lower()
        if "message is not modified" in err_lower or "canceled by new edit message request" in err_lower:
            return message, False
        if "can't parse entities" in err_lower:
            try:
                return await _try_edit(escape_body=True)
            except Exception:
                pass
        # Fallback: replace message cleanly
        new_msg = await send_change_page(
            message.bot,
            message.chat.id,
            role,
            default_day,
            norm_pages,
            idx,
            reply_markup,
            header_title=header_title,
            extra_header_line=extra_header_line,
        )
        try:
            await message.delete()
        except Exception:
            pass
        return new_msg, True


async def send_wave_batch(bot: Bot, recipients: List[Dict[str, Any]]) -> Tuple[int, int]:
    """
    Надсилає повідомлення поточної хвилі списку отримувачів (підтримує текст, фото, відео).
    Повертає (кількість успішно надісланих, кількість помилок).
    """
    sent_count = 0
    failed_count = 0

    for rec in recipients:
        user_id = rec["user_id"]
        rec_id = rec["id"]
        event_id = rec["event_id"]
        role = rec.get("role", "")
        day = rec.get("day", 1)
        pages = normalize_change_pages(
            rec.get("pages_json", "[]"),
            fallback_text=rec.get("description") or "Оновлено навчальні матеріали",
            default_day=day,
        )
        total_pages = len(pages)
        kb = build_material_notification_keyboard(
            event_id, rec_id, 0, total_pages, is_acknowledged=False
        )

        delivered = False
        for attempt in range(2):
            try:
                msg = await send_change_page(
                    bot=bot,
                    chat_id=user_id,
                    role=role,
                    default_day=day,
                    pages=pages,
                    page_idx=0,
                    reply_markup=kb,
                )
                await mark_recipient_sent(rec_id, message_id=msg.message_id)
                sent_count += 1
                delivered = True
                break
            except TelegramRetryAfter as e:
                wait_s = max(1, int(getattr(e, "retry_after", 3)) + 1)
                logger.warning(f"FloodWait for user {user_id}, waiting {wait_s}s...")
                await asyncio.sleep(wait_s)
            except TelegramForbiddenError as e:
                logger.info(f"User {user_id} blocked bot during material notification: {e}")
                break
            except Exception as e:
                logger.warning(f"Failed to send material notification to user {user_id}: {e}")
                break

        if not delivered:
            await mark_recipient_failed(rec_id)
            failed_count += 1

        await asyncio.sleep(PER_MESSAGE_DELAY_SECONDS)

    return sent_count, failed_count


async def dispatch_event_waves(bot: Bot, event_id: int) -> None:
    """
    Фонова задача для послідовного надсилання всіх хвиль події
    (по 40 осіб з інтервалом 4 хвилини між хвилями).
    """
    if event_id in _active_event_ids:
        logger.info(f"Wave broadcast for event {event_id} is already running, skipping duplicate start.")
        return

    _active_event_ids.add(event_id)
    try:
        max_waves = await get_max_wave_for_event(event_id)
        for wave in range(1, max_waves + 1):
            pending_recipients = await get_pending_wave_recipients(
                wave_number=wave, event_id=event_id
            )
            if not pending_recipients:
                continue

            logger.info(
                f"Dispatching wave {wave}/{max_waves} for event {event_id} "
                f"({len(pending_recipients)} users, batch={WAVE_BATCH_SIZE})..."
            )
            sent, failed = await send_wave_batch(bot, pending_recipients)
            logger.info(f"Event {event_id} wave {wave} finished: {sent} sent, {failed} failed.")

            if wave < max_waves:
                remaining = await get_pending_wave_recipients(event_id=event_id)
                if remaining:
                    await asyncio.sleep(WAVE_INTERVAL_SECONDS)

        await mark_event_completed_if_done(event_id)
    except Exception as e:
        logger.error(f"Unexpected error in dispatch_event_waves({event_id}): {e}", exc_info=True)
    finally:
        _active_event_ids.discard(event_id)


def start_event_wave_broadcast(bot: Bot, event_id: int) -> Optional[asyncio.Task]:
    """Запускає асинхронну розсилку хвиль у фоновому режимі (із захистом від дублів)."""
    if event_id in _active_event_ids:
        return None
    return asyncio.create_task(dispatch_event_waves(bot, event_id))


async def resume_pending_wave_broadcasts(bot: Bot) -> int:
    """
    При запуску бота знаходить незавершені події з pending-отримувачами
    та автоматично відновлює їх хвильову розсилку.
    """
    pending_event_ids = await get_events_with_pending_recipients()
    resumed = 0
    for event_id in pending_event_ids:
        if start_event_wave_broadcast(bot, event_id) is not None:
            resumed += 1
    if resumed:
        logger.info(f"Resumed {resumed} pending material notification wave broadcast(s): {pending_event_ids}")
    return resumed
