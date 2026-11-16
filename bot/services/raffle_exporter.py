from __future__ import annotations

import asyncio
import html
import io
import logging
import os
import re
import zipfile
from typing import Any, Dict, List, Optional, Set, Tuple

import openpyxl
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from bot.utils.message_utils import sanitize_telegram_html
from database import DB_PATH
from database.raffles import get_raffle_by_id, get_raffle_submissions_detailed

logger = logging.getLogger(__name__)

PARTICIPATION_TYPE_LABELS: Dict[str, str] = {
    "button": "Натискання «Взяти участь»",
    "text": "Відправка повідомлення",
    "formatted_text": "Повідомлення з форматом",
    "media": "Надсилання фото або відео",
    "document": "Надсилання файлів",
}

TEXT_FORMAT_LABELS: Dict[str, str] = {
    "any": "Текстовий (будь-який текст)",
    "numeric": "Числовий (будь-яке число)",
    "score": "Рахунок (формат X:Y, напр. 0:0)",
}


def describe_raffle_participation(
    participation_type: str,
    text_format: Optional[str] = None,
) -> str:
    """Повертає людиночитаний опис формату участі в розіграші."""
    base = PARTICIPATION_TYPE_LABELS.get(participation_type, participation_type)
    if participation_type == "formatted_text" and text_format:
        fmt_label = TEXT_FORMAT_LABELS.get(text_format, text_format)
        return f"{base} ({fmt_label})"
    return base


def sanitize_participant_filename(full_name: Optional[str], fallback_id: int) -> str:
    """
    Формує безпечне ім'я файлу на основі ПІБ учасника.
    Заборонені для ФС символи видаляються, пробіли замінюються на підкреслення.
    """
    raw = (full_name or "").strip()
    cleaned = re.sub(r'[\\/*?:"<>|\r\n\t]+', "", raw)
    cleaned = re.sub(r"[^\w\s\-'.а-яА-ЯіїєґІЇЄҐ]", "", cleaned, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._ ")
    if not cleaned:
        return f"Учасник_{fallback_id}"
    return cleaned[:100]


def validate_raffle_text_submission(
    text: Optional[str],
    participation_type: str,
    text_format: Optional[str] = None,
) -> Tuple[bool, str, str]:
    """
    Валідує текстову відповідь користувача згідно з правилами розіграшу.
    Повертає (is_valid, normalized_text, error_message).
    """
    raw = (text or "").strip()
    if not raw:
        return (
            False,
            "",
            "⚠️ Повідомлення не може бути порожнім. Будь ласка, надішліть текстову відповідь.",
        )

    if participation_type == "text":
        return True, raw, ""

    if participation_type == "formatted_text":
        fmt = text_format or "any"
        if fmt == "any":
            return True, raw, ""

        if fmt == "numeric":
            if re.match(r"^[+-]?\d+(?:[.,]\d+)?$", raw):
                return True, raw, ""
            return (
                False,
                "",
                "⚠️ Невірний формат! Потрібно надіслати <b>число</b> "
                "(наприклад: <code>42</code> або <code>12.5</code>).\n\n"
                "Спробуйте ще раз:",
            )

        if fmt == "score":
            match = re.match(r"^(\d+)\s*:\s*(\d+)$", raw)
            if match:
                normalized = f"{match.group(1)}:{match.group(2)}"
                return True, normalized, ""
            return (
                False,
                "",
                "⚠️ Невірний формат! Потрібно вказати <b>рахунок у форматі 0:0</b> "
                "(наприклад: <code>2:1</code> або <code>0:0</code>).\n\n"
                "Спробуйте ще раз:",
            )

    return True, raw, ""


def _strip_html(raw: str) -> str:
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", "", raw)
    return html.unescape(text).strip()


def _sanitize_sheet_title(title: str, existing_titles: Set[str]) -> str:
    cleaned = re.sub(r"[\\/*?:\[\]]", "_", title).strip() or "Sheet"
    cleaned = cleaned[:28]
    final_title = cleaned
    counter = 1
    while final_title.lower() in existing_titles:
        final_title = f"{cleaned}_{counter}"[:31]
        counter += 1
    existing_titles.add(final_title.lower())
    return final_title


async def generate_raffle_report_xlsx(
    raffle_id: int,
    db_path: str = DB_PATH,
) -> io.BytesIO:
    """
    Генерує брендований Excel-звіт учасників розіграшу (у форматі звітів новин):
    - Аркуш 1: «Загальний» (метадані розіграшу, формат, умови, кількість учасників).
    - Аркуш 2: «Учасники» (повний список учасників та їхні відповіді / назви файлів).
    """
    raffle = await get_raffle_by_id(raffle_id, db_path=db_path)
    if not raffle:
        raise ValueError(f"Розіграш з id={raffle_id} не знайдено.")

    submissions = await get_raffle_submissions_detailed(raffle_id, db_path=db_path)

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    font_title = Font(name="Arial", size=13, bold=True, color="1F2937")
    font_sub = Font(name="Arial", size=9, italic=True, color="4B5563")
    font_section = Font(name="Arial", size=11, bold=True, color="FFFFFF")
    font_header = Font(name="Arial", size=10, bold=True, color="FFFFFF")
    font_data = Font(name="Arial", size=10, color="1F2937")
    font_bold = Font(name="Arial", size=10, bold=True, color="1F2937")

    fill_primary = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    fill_success_header = PatternFill(start_color="059669", end_color="059669", fill_type="solid")
    fill_zebra = PatternFill(start_color="F9FAFB", end_color="F9FAFB", fill_type="solid")

    thin_border_side = Side(style="thin", color="D1D5DB")
    border_data = Border(
        left=thin_border_side,
        right=thin_border_side,
        top=thin_border_side,
        bottom=thin_border_side,
    )

    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")
    align_wrap = Alignment(horizontal="left", vertical="top", wrap_text=True)

    used_sheet_titles: Set[str] = set()

    # =========================================================================
    # АРКУШ 1: Загальний
    # =========================================================================
    ws_summary = wb.create_sheet(title=_sanitize_sheet_title("Загальний", used_sheet_titles))
    ws_summary.views.sheetView[0].showGridLines = True

    ws_summary.merge_cells("A1:F1")
    ws_summary["A1"] = f"🎁 ЗВІТ РОЗІГРАШУ #{raffle_id}: {raffle.get('title', '')}"
    ws_summary["A1"].font = font_title
    ws_summary["A1"].alignment = align_left
    ws_summary.row_dimensions[1].height = 25

    created_at = raffle.get("created_at") or "-"
    deadline = raffle.get("deadline") or "-"
    target_city = raffle.get("selected_city") or "all"
    city_str = "Усі міста" if target_city == "all" else target_city
    roles_list = raffle.get("selected_roles") or []
    roles_str = ", ".join(roles_list) if roles_list else "Усі ролі"
    status_str = "Активний" if raffle.get("status") == "active" else "Завершений"
    format_str = describe_raffle_participation(
        raffle.get("participation_type", "button"),
        raffle.get("text_format"),
    )

    ws_summary["A2"] = (
        f"📅 Запуск: {created_at} | ⏳ Дедлайн: {deadline} | 🏙 Місто: {city_str} | 👥 Ролі: {roles_str}"
    )
    ws_summary["A2"].font = font_sub
    ws_summary["A2"].alignment = align_left

    ws_summary.merge_cells("A4:F4")
    ws_summary["A4"] = "Умови розіграшу:"
    ws_summary["A4"].font = font_bold

    clean_terms = _strip_html(raffle.get("text") or "-")
    ws_summary.merge_cells("A5:F5")
    ws_summary["A5"] = clean_terms
    ws_summary["A5"].font = font_data
    ws_summary["A5"].alignment = align_wrap
    ws_summary.row_dimensions[5].height = min(140, max(45, len(clean_terms) // 2))

    ws_summary.merge_cells("A7:D7")
    sec_cell = ws_summary["A7"]
    sec_cell.value = "📊 ЗАГАЛЬНА СТАТИСТИКА РОЗІГРАШУ"
    sec_cell.font = font_section
    sec_cell.fill = fill_primary
    sec_cell.alignment = align_left
    ws_summary.row_dimensions[7].height = 22

    kpi_rows = [
        ("Статус розіграшу", status_str),
        ("Формат участі", format_str),
        ("Всього учасників", len(submissions)),
        ("Фактичний час завершення", raffle.get("completed_at") or "-"),
    ]

    r_idx = 8
    for label, val in kpi_rows:
        ws_summary.merge_cells(start_row=r_idx, start_column=1, end_row=r_idx, end_column=2)
        c_lbl = ws_summary.cell(row=r_idx, column=1, value=label)
        c_lbl.font = font_bold
        c_lbl.border = border_data
        ws_summary.cell(row=r_idx, column=2).border = border_data

        ws_summary.merge_cells(start_row=r_idx, start_column=3, end_row=r_idx, end_column=4)
        c_val = ws_summary.cell(row=r_idx, column=3, value=val)
        c_val.font = font_data
        c_val.alignment = align_center
        c_val.border = border_data
        ws_summary.cell(row=r_idx, column=4).border = border_data
        r_idx += 1

    # =========================================================================
    # АРКУШ 2: Учасники
    # =========================================================================
    ws_part = wb.create_sheet(title=_sanitize_sheet_title("Учасники", used_sheet_titles))
    ws_part.views.sheetView[0].showGridLines = True

    ws_part.merge_cells("A1:H1")
    ws_part["A1"] = f"👥 СПИСОК УЧАСНИКІВ РОЗІГРАШУ ({len(submissions)} осіб)"
    ws_part["A1"].font = font_title
    ws_part["A1"].alignment = align_left
    ws_part.row_dimensions[1].height = 25

    headers = [
        "№",
        "ПІБ",
        "Магазин",
        "Посада",
        "Місто",
        "Username",
        "Відповідь / Файл",
        "Час участі",
    ]
    for col_i, h in enumerate(headers, start=1):
        c = ws_part.cell(row=3, column=col_i, value=h)
        c.font = font_header
        c.fill = fill_success_header
        c.alignment = align_center
        c.border = border_data
    ws_part.row_dimensions[3].height = 22

    for row_idx, item in enumerate(submissions, start=4):
        fill = fill_zebra if row_idx % 2 == 0 else PatternFill(fill_type=None)
        username_raw = item.get("username") or ""
        username_disp = f"@{username_raw}" if username_raw and not username_raw.startswith("@") else (username_raw or "-")

        sub_text = (item.get("submission_text") or "").strip()
        m_type = item.get("media_type")
        l_path = item.get("local_file_path")
        if m_type:
            fname = os.path.basename(l_path) if l_path else m_type
            answer_disp = f"[{m_type}] {fname}" + (f" | {sub_text}" if sub_text else "")
        else:
            answer_disp = sub_text or "Взяв участь"

        vals = [
            row_idx - 3,
            item.get("full_name") or "Не вказано",
            item.get("shop") or "-",
            item.get("role") or "-",
            item.get("city") or "-",
            username_disp,
            answer_disp,
            item.get("created_at") or "-",
        ]

        for col_i, val in enumerate(vals, start=1):
            c = ws_part.cell(row=row_idx, column=col_i, value=val)
            c.font = font_data
            c.border = border_data
            if fill.fill_type:
                c.fill = fill
            if col_i in (1, 8):
                c.alignment = align_center
            elif col_i == 7:
                c.alignment = align_wrap
            else:
                c.alignment = align_left

    # Автопідбір ширини колонок
    for ws in wb.worksheets:
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                if cell.row in (1, 2, 4, 5, 7) and ws == ws_summary:
                    continue
                if cell.row == 1 and ws == ws_part:
                    continue
                val_str = str(cell.value or "")
                if len(val_str) > max_len:
                    max_len = len(val_str)
            ws.column_dimensions[col_letter].width = max(12, min(max_len + 4, 48))

    stream = io.BytesIO()
    wb.save(stream)
    stream.seek(0)
    return stream


def _build_zip_bytes(entries: List[Tuple[str, str]]) -> bytes:
    """Пакує список (disk_path, archive_filename) у ZIP-байтпотік."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for disk_path, arcname in entries:
            zf.write(disk_path, arcname=arcname)
    return buf.getvalue()


def _build_chunked_zips_sync(
    entries: List[Tuple[str, str]],
    max_zip_bytes: int,
    raffle_id: int,
) -> List[Tuple[str, bytes]]:
    """
    Синхронний пакувальник файлів у один або кілька ZIP-архівів до max_zip_bytes.
    Виконує O(N) оцінку розміру, перевіряє стиснутий розмір на межі тому
    та гарантує, що жоден файл не загубиться.
    """
    chunks: List[bytes] = []
    idx = 0
    n = len(entries)

    while idx < n:
        chunk: List[Tuple[str, str]] = []
        est_bytes = 256  # резерв під End of Central Directory

        while idx < n:
            disk_path, arcname = entries[idx]
            raw_size = os.path.getsize(disk_path)
            entry_overhead = 256 + len(arcname.encode("utf-8")) * 2
            projected = est_bytes + raw_size + entry_overhead

            if not chunk or projected <= max_zip_bytes:
                chunk.append((disk_path, arcname))
                est_bytes = projected
                idx += 1
            else:
                trial_bytes = _build_zip_bytes(chunk + [(disk_path, arcname)])
                if len(trial_bytes) <= max_zip_bytes:
                    chunk.append((disk_path, arcname))
                    est_bytes = len(trial_bytes)
                    idx += 1
                else:
                    break

        chunk_bytes = _build_zip_bytes(chunk)
        while len(chunk_bytes) > max_zip_bytes and len(chunk) > 1:
            chunk.pop()
            idx -= 1
            chunk_bytes = _build_zip_bytes(chunk)

        chunks.append(chunk_bytes)

    if len(chunks) == 1:
        return [(f"Розіграш_{raffle_id}_медіа.zip", chunks[0])]

    return [
        (f"Розіграш_{raffle_id}_частина_{i}.zip", chunk_data)
        for i, chunk_data in enumerate(chunks, start=1)
    ]


async def generate_raffle_media_zips(
    raffle_id: int,
    max_zip_bytes: int = 45 * 1024 * 1024,
    db_path: str = DB_PATH,
) -> List[Tuple[str, bytes]]:
    """
    Формує ZIP-архіви з медіафайлами/документами учасників.
    Кожен файл всередині перейменований за ПІБ учасника.
    Якщо сумарний розмір перевищує max_zip_bytes (за замовчуванням 45 МБ),
    архіви розбиваються на окремі частини, кожна з яких не перевищує ліміт
    (за винятком ситуації, коли один окремий файл сам більший за max_zip_bytes).
    """
    submissions = await get_raffle_submissions_detailed(raffle_id, db_path=db_path)

    entries: List[Tuple[str, str]] = []
    used_names: Set[str] = set()

    for sub in submissions:
        disk_path = sub.get("local_file_path")
        if not disk_path or not os.path.isfile(disk_path):
            continue

        _, ext = os.path.splitext(disk_path)
        if not ext:
            m_type = sub.get("media_type")
            if m_type == "photo":
                ext = ".jpg"
            elif m_type == "video":
                ext = ".mp4"
            else:
                ext = ".bin"

        base_name = sanitize_participant_filename(
            sub.get("full_name") or sub.get("user_full_name"),
            sub["user_id"],
        )
        candidate = f"{base_name}{ext}"
        if candidate.lower() in used_names:
            candidate = f"{base_name}_{sub['user_id']}{ext}"
        counter = 2
        while candidate.lower() in used_names:
            candidate = f"{base_name}_{sub['user_id']}_{counter}{ext}"
            counter += 1

        used_names.add(candidate.lower())
        entries.append((disk_path, candidate))

    if not entries:
        return []

    return await asyncio.to_thread(_build_chunked_zips_sync, entries, max_zip_bytes, raffle_id)


async def dispatch_raffle_announcement_waves(
    bot: Bot,
    recipient_uids: List[int],
    raffle: Dict[str, Any],
    admin_chat_id: Optional[int] = None,
    wave_size: int = 50,
    wave_delay_sec: float = 1.5,
) -> Tuple[int, int]:
    """
    Надсилає анонс нового розіграшу обраним користувачам хвилями по wave_size осіб
    із мікропаузою 0.08с та кнопкою переходу до розіграшу.
    """
    if not recipient_uids:
        return 0, 0

    deadline_display = str(raffle.get("deadline", ""))[:16]
    fmt_label = describe_raffle_participation(
        raffle.get("participation_type", "button"),
        raffle.get("text_format"),
    )
    terms_text = sanitize_telegram_html(raffle.get("text") or "")

    announcement_text = (
        f"🎁 <b>Стартував новий розіграш у BULKA!</b>\n"
        f"───────────────────\n"
        f"{terms_text}\n\n"
        f"📌 <b>Формат участі:</b> {fmt_label}\n"
        f"⏳ <b>Дедлайн:</b> {deadline_display}\n\n"
        f"<i>Натисніть кнопку нижче або відкрийте розділ «🎁 Розіграш» у головному меню!</i>"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Перейти до розіграшу", callback_data="user_raffle_menu")]
        ]
    )

    photo_file_id = raffle.get("photo_file_id")
    video_file_id = raffle.get("video_file_id")
    media_type = raffle.get("media_type")

    total_sent = 0
    total_failed = 0
    waves = [recipient_uids[i : i + wave_size] for i in range(0, len(recipient_uids), wave_size)]

    for wave_idx, wave_uids in enumerate(waves, start=1):
        for uid in wave_uids:
            try:
                if media_type == "video" and video_file_id:
                    if len(announcement_text) <= 1000:
                        await bot.send_video(
                            chat_id=uid,
                            video=video_file_id,
                            caption=announcement_text,
                            reply_markup=kb,
                            parse_mode="HTML",
                        )
                    else:
                        await bot.send_video(chat_id=uid, video=video_file_id)
                        await bot.send_message(
                            chat_id=uid,
                            text=announcement_text,
                            reply_markup=kb,
                            parse_mode="HTML",
                        )
                elif media_type == "photo" and photo_file_id:
                    if len(announcement_text) <= 1000:
                        await bot.send_photo(
                            chat_id=uid,
                            photo=photo_file_id,
                            caption=announcement_text,
                            reply_markup=kb,
                            parse_mode="HTML",
                        )
                    else:
                        await bot.send_photo(chat_id=uid, photo=photo_file_id)
                        await bot.send_message(
                            chat_id=uid,
                            text=announcement_text,
                            reply_markup=kb,
                            parse_mode="HTML",
                        )
                else:
                    try:
                        await bot.send_message(
                            chat_id=uid,
                            text=announcement_text,
                            reply_markup=kb,
                            parse_mode="HTML",
                        )
                    except TelegramBadRequest:
                        await bot.send_message(
                            chat_id=uid,
                            text=_strip_html(announcement_text),
                            reply_markup=kb,
                            parse_mode=None,
                        )
                total_sent += 1
            except TelegramRetryAfter as tre:
                await asyncio.sleep(tre.retry_after + 0.5)
                try:
                    await bot.send_message(
                        chat_id=uid,
                        text=announcement_text,
                        reply_markup=kb,
                        parse_mode="HTML",
                    )
                    total_sent += 1
                except Exception:
                    total_failed += 1
            except Exception as exc:
                logger.warning(f"[Raffle Broadcaster] Failed to send announcement to {uid}: {exc}")
                total_failed += 1

            await asyncio.sleep(0.08)

        if wave_idx < len(waves) and wave_delay_sec > 0:
            await asyncio.sleep(wave_delay_sec)

    if admin_chat_id:
        try:
            await bot.send_message(
                chat_id=admin_chat_id,
                text=(
                    f"📣 <b>Анонс розіграшу завершено!</b>\n"
                    f"───────────────────\n"
                    f"✅ Надіслано: <b>{total_sent}</b>\n"
                    f"❌ Помилок доставки: <b>{total_failed}</b>"
                ),
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.warning(f"[Raffle Broadcaster] Could not send summary to admin {admin_chat_id}: {exc}")

    return total_sent, total_failed
