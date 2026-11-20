from __future__ import annotations
import asyncio
import html
import io
import logging
import re
from datetime import datetime
from typing import Dict, Any, List, Optional, Set, Tuple

import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

from database import DB_PATH
from database.news import (
    get_news_by_id,
    get_news_reactions_summary,
    get_news_failed_deliveries_detailed,
    get_news_reactions_detailed,
    get_weekly_news_report_data,
    get_news_report_recipient_ids,
)

logger = logging.getLogger(__name__)


def build_safe_news_media_caption(
    news_id: int,
    sanitized_body: str,
    stats_block: str,
    *,
    limit: int = 1024,
    force_escape_body: bool = False,
) -> str:
    """
    Формує HTML-підпис для відео/фото перегляду новини так, щоб:
    - довжина ніколи не перевищувала `limit` (1024 для Telegram caption);
    - жоден HTML-тег або HTML-сутність не були розрізані посередині;
    - блок `stats_block` (статистика новини) завжди залишався цілим.
    """
    header = f"📰 <b>Новина #{news_id}</b>\n───────────────────\n"
    full_candidate = f"{header}{sanitized_body}\n\n{stats_block}"

    if not force_escape_body and len(full_candidate) <= limit:
        return full_candidate

    # Знімаємо HTML-теги з тіла новини та безпечно підбираємо довжину до екранування,
    # щоб жоден тег або HTML-entity не обрізались посередині.
    stripped = html.unescape(re.sub(r"<[^>]+>", "", sanitized_body or "")).strip()
    overhead = len(header) + len("\n\n") + len(stats_block)
    budget = limit - overhead

    if budget <= 12:
        fallback = f"{header}{stats_block}"
        return fallback if len(fallback) <= limit else fallback[:limit]

    cut_len = min(len(stripped), budget)
    while cut_len > 0:
        snippet = stripped[:cut_len].rstrip()
        if cut_len < len(stripped):
            snippet += "…"
        escaped_snippet = html.escape(snippet)
        candidate = f"{header}{escaped_snippet}\n\n{stats_block}"
        if len(candidate) <= limit:
            return candidate
        cut_len -= max(1, (len(candidate) - limit))

    fallback = f"{header}{stats_block}"
    return fallback if len(fallback) <= limit else fallback[:limit]


def _sanitize_sheet_title(title: str, existing_titles: Set[str]) -> str:
    cleaned = re.sub(r'[\\/*?:\[\]]', '_', title).strip()
    if not cleaned:
        cleaned = "Sheet"
    cleaned = cleaned[:28]

    final_title = cleaned
    counter = 1
    while final_title.lower() in existing_titles:
        final_title = f"{cleaned}_{counter}"[:31]
        counter += 1

    existing_titles.add(final_title.lower())
    return final_title


async def generate_news_report_xlsx(news_id: int, db_path: str = DB_PATH) -> io.BytesIO:
    """
    Генерує брендований Excel-звіт за результатами розсилки новини:
    - Аркуш 1: «Загальний» (метадані, KPI розсилки, аналітика реакцій).
    - Аркуш 2: «Не доставлено» (список співробітників, яким не вдалося доставити, із класифікованими причинами).
    - Аркуш 3: «Реакції» (список співробітників, які залишили реакцію: ПІБ, магазин, посада, емодзі, час).
    """
    news = await get_news_by_id(news_id, db_path=db_path)
    if not news:
        raise ValueError(f"Новину з id={news_id} не знайдено.")

    reactions_summary = await get_news_reactions_summary(news_id, db_path=db_path)
    failed_deliveries = await get_news_failed_deliveries_detailed(news_id, db_path=db_path)
    reactions_detailed = await get_news_reactions_detailed(news_id, db_path=db_path)

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # Видаляємо стандартний порожній аркуш

    # Стилі
    font_title = Font(name="Arial", size=13, bold=True, color="1F2937")
    font_sub = Font(name="Arial", size=9, italic=True, color="4B5563")
    font_section = Font(name="Arial", size=11, bold=True, color="FFFFFF")
    font_header = Font(name="Arial", size=10, bold=True, color="FFFFFF")
    font_data = Font(name="Arial", size=10, color="1F2937")
    font_bold = Font(name="Arial", size=10, bold=True, color="1F2937")

    fill_primary = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")     # Темно-синій
    fill_header = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")      # Синій
    fill_kpi_header = PatternFill(start_color="D97706", end_color="D97706", fill_type="solid")  # Янтарний
    fill_zebra = PatternFill(start_color="F9FAFB", end_color="F9FAFB", fill_type="solid")       # Світло-сірий
    fill_error_header = PatternFill(start_color="DC2626", end_color="DC2626", fill_type="solid")# Червоний
    fill_success_header = PatternFill(start_color="059669", end_color="059669", fill_type="solid") # Зелений

    thin_border_side = Side(style='thin', color="D1D5DB")
    border_data = Border(
        left=thin_border_side,
        right=thin_border_side,
        top=thin_border_side,
        bottom=thin_border_side
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

    # Заголовок
    ws_summary.merge_cells("A1:F1")
    ws_summary["A1"] = f"📰 ЗВІТ РОЗСИЛКИ НОВИНИ #{news_id}"
    ws_summary["A1"].font = font_title
    ws_summary["A1"].alignment = align_left
    ws_summary.row_dimensions[1].height = 25

    created_at = news.get("created_at") or "—"
    target_city = news.get("selected_city") or "all"
    city_str = "Усі міста" if target_city == "all" else target_city
    roles_list = news.get("selected_roles") or []
    roles_str = ", ".join(roles_list) if roles_list else "Всі категорії"

    ws_summary["A2"] = f"📅 Дата розсилки: {created_at} | 🏙 Місто: {city_str} | 👥 Аудиторія: {roles_str}"
    ws_summary["A2"].font = font_sub
    ws_summary["A2"].alignment = align_left

    # Текст новини
    ws_summary.merge_cells("A4:F4")
    ws_summary["A4"] = "Текст публікації:"
    ws_summary["A4"].font = font_bold

    news_text = news.get("text") or "—"
    ws_summary.merge_cells("A5:F5")
    ws_summary["A5"] = news_text
    ws_summary["A5"].font = font_data
    ws_summary["A5"].alignment = align_wrap
    ws_summary.row_dimensions[5].height = min(120, max(45, len(news_text) // 2))

    # Секція: Показники розсилки
    ws_summary.merge_cells("A7:D7")
    cell_sec1 = ws_summary["A7"]
    cell_sec1.value = "📊 ПОКАЗНИКИ ДОСТАВКИ ТА ОХОПЛЕННЯ"
    cell_sec1.font = font_section
    cell_sec1.fill = fill_primary
    cell_sec1.alignment = align_left
    ws_summary.row_dimensions[7].height = 22

    total_recipients = news.get("total_recipients") or 0
    sent_count = news.get("sent_count") or 0
    failed_count = news.get("failed_count") or 0
    total_waves = news.get("total_waves") or 0

    sent_pct = round((sent_count / total_recipients * 100), 1) if total_recipients > 0 else 0
    failed_pct = round((failed_count / total_recipients * 100), 1) if total_recipients > 0 else 0
    total_reactions = reactions_summary.get("total", 0)
    reaction_pct = round((total_reactions / sent_count * 100), 1) if sent_count > 0 else 0

    kpi_data = [
        ("Всього отримувачів у вибірці", total_recipients, "100%"),
        ("✅ Успішно доставлено", sent_count, f"{sent_pct}%"),
        ("❌ Не вдалося доставити", failed_count, f"{failed_pct}%"),
        ("🌊 Кількість хвиль розсилки", total_waves, "хвиль по 50 осіб"),
        ("💬 Всього отримано реакцій", total_reactions, f"{reaction_pct}% від доставлених")
    ]

    r_idx = 8
    for label, val, note in kpi_data:
        ws_summary.merge_cells(start_row=r_idx, start_column=1, end_row=r_idx, end_column=2)
        cell_lbl = ws_summary.cell(row=r_idx, column=1, value=label)
        cell_lbl.font = font_bold
        cell_lbl.border = border_data
        ws_summary.cell(row=r_idx, column=2).border = border_data

        cell_val = ws_summary.cell(row=r_idx, column=3, value=val)
        cell_val.font = font_bold
        cell_val.alignment = align_center
        cell_val.border = border_data

        cell_note = ws_summary.cell(row=r_idx, column=4, value=note)
        cell_note.font = font_sub
        cell_note.alignment = align_left
        cell_note.border = border_data
        r_idx += 1

    # Секція: Розподіл реакцій
    r_idx += 1
    ws_summary.merge_cells(start_row=r_idx, start_column=1, end_row=r_idx, end_column=4)
    cell_sec2 = ws_summary.cell(row=r_idx, column=1)
    cell_sec2.value = "💬 АНАЛІТИКА РЕАКЦІЙ СПІВРОБІТНИКІВ"
    cell_sec2.font = font_section
    cell_sec2.fill = fill_kpi_header
    cell_sec2.alignment = align_left
    ws_summary.row_dimensions[r_idx].height = 22
    r_idx += 1

    reaction_headers = ["Емодзі", "Значення", "Кількість", "Частка"]
    for col_i, h in enumerate(reaction_headers, start=1):
        c = ws_summary.cell(row=r_idx, column=col_i, value=h)
        c.font = font_header
        c.fill = fill_header
        c.alignment = align_center
        c.border = border_data
    r_idx += 1

    reaction_labels = {
        "👍": "Схвалення / Палець вгору",
        "🔥": "Супер / Вогонь",
        "😁": "Смішно / Позитивно",
        "❤️": "Чудово / Любов",
        "🤔": "Замислився",
    }

    breakdown = reactions_summary.get("breakdown", {})
    for emoji, label in reaction_labels.items():
        cnt = breakdown.get(emoji, 0)
        pct = round((cnt / total_reactions * 100), 1) if total_reactions > 0 else 0

        c_emoji = ws_summary.cell(row=r_idx, column=1, value=emoji)
        c_emoji.font = Font(name="Arial", size=14)
        c_emoji.alignment = align_center
        c_emoji.border = border_data

        c_lbl = ws_summary.cell(row=r_idx, column=2, value=label)
        c_lbl.font = font_data
        c_lbl.alignment = align_left
        c_lbl.border = border_data

        c_cnt = ws_summary.cell(row=r_idx, column=3, value=cnt)
        c_cnt.font = font_bold
        c_cnt.alignment = align_center
        c_cnt.border = border_data

        c_pct = ws_summary.cell(row=r_idx, column=4, value=f"{pct}%")
        c_pct.font = font_bold
        c_pct.alignment = align_center
        c_pct.border = border_data

        r_idx += 1

    # =========================================================================
    # АРКУШ 2: Не доставлено
    # =========================================================================
    ws_failed = wb.create_sheet(title=_sanitize_sheet_title("Не доставлено", used_sheet_titles))
    ws_failed.views.sheetView[0].showGridLines = True

    ws_failed.merge_cells("A1:H1")
    ws_failed["A1"] = f"❌ СПИСОК НЕ ДОСТАВЛЕНИХ ПОВІДОМЛЕНЬ ({len(failed_deliveries)} осіб)"
    ws_failed["A1"].font = font_title
    ws_failed["A1"].alignment = align_left
    ws_failed.row_dimensions[1].height = 25

    failed_headers = ["№", "ПІБ", "Посада", "Місто", "Магазин", "Telegram ID", "Причина", "Технічна помилка"]
    for col_i, h in enumerate(failed_headers, start=1):
        c = ws_failed.cell(row=3, column=col_i, value=h)
        c.font = font_header
        c.fill = fill_error_header
        c.alignment = align_center
        c.border = border_data
    ws_failed.row_dimensions[3].height = 22

    for row_idx, item in enumerate(failed_deliveries, start=4):
        fill = fill_zebra if row_idx % 2 == 0 else PatternFill(fill_type=None)

        vals = [
            row_idx - 3,
            item.get("full_name") or "Не вказано",
            item.get("role") or "—",
            item.get("city") or "—",
            item.get("shop") or "—",
            item.get("user_id"),
            item.get("error_reason") or "Невідома помилка",
            item.get("raw_error") or "—"
        ]

        for col_i, val in enumerate(vals, start=1):
            c = ws_failed.cell(row=row_idx, column=col_i, value=val)
            c.font = font_data
            c.border = border_data
            if fill.fill_type:
                c.fill = fill
            if col_i in (1, 6):
                c.alignment = align_center
            elif col_i == 7:
                c.alignment = align_left
                c.font = font_bold
            else:
                c.alignment = align_left

    # =========================================================================
    # АРКУШ 3: Реакції
    # =========================================================================
    ws_react = wb.create_sheet(title=_sanitize_sheet_title("Реакції", used_sheet_titles))
    ws_react.views.sheetView[0].showGridLines = True

    ws_react.merge_cells("A1:G1")
    ws_react["A1"] = f"💬 РЕАКЦІЇ СПІВРОБІТНИКІВ ({len(reactions_detailed)} осіб)"
    ws_react["A1"].font = font_title
    ws_react["A1"].alignment = align_left
    ws_react.row_dimensions[1].height = 25

    react_headers = ["№", "ПІБ", "Магазин", "Посада", "Місто", "Реакція", "Час реакції"]
    for col_i, h in enumerate(react_headers, start=1):
        c = ws_react.cell(row=3, column=col_i, value=h)
        c.font = font_header
        c.fill = fill_success_header
        c.alignment = align_center
        c.border = border_data
    ws_react.row_dimensions[3].height = 22

    for row_idx, item in enumerate(reactions_detailed, start=4):
        fill = fill_zebra if row_idx % 2 == 0 else PatternFill(fill_type=None)

        vals = [
            row_idx - 3,
            item.get("full_name") or "Не вказано",
            item.get("shop") or "—",
            item.get("role") or "—",
            item.get("city") or "—",
            item.get("reaction") or "—",
            item.get("updated_at") or item.get("created_at") or "—"
        ]

        for col_i, val in enumerate(vals, start=1):
            c = ws_react.cell(row=row_idx, column=col_i, value=val)
            c.font = font_data
            c.border = border_data
            if fill.fill_type:
                c.fill = fill
            if col_i in (1, 7):
                c.alignment = align_center
            elif col_i == 6:
                c.alignment = align_center
                c.font = Font(name="Arial", size=14)
            else:
                c.alignment = align_left

    # Автопідбір ширини колонок для всіх аркушів
    for ws in wb.worksheets:
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                # Не враховуємо об'єднані довгі рядки
                if cell.row in (1, 2, 4, 5, 7):
                    continue
                val_str = str(cell.value or "")
                if len(val_str) > max_len:
                    max_len = len(val_str)
            ws.column_dimensions[col_letter].width = max(12, min(max_len + 4, 45))

    stream = io.BytesIO()
    wb.save(stream)
    stream.seek(0)
    return stream


def _plain_news_preview(raw_text: str, max_len: int = 120) -> str:
    clean = html.unescape(re.sub(r"<[^>]+>", "", raw_text or "")).strip()
    clean = re.sub(r"\s+", " ", clean)
    if len(clean) > max_len:
        return clean[: max_len - 1].rstrip() + "…"
    return clean or "—"


def format_weekly_news_summary_caption(report_data: Dict[str, Any]) -> str:
    """Формує коротке HTML-зведення для підпису тижневого Excel-звіту в Telegram."""
    period = report_data.get("period_label") or "Останні 7 днів"
    news_count = report_data.get("news_count", 0)
    total_recipients = report_data.get("total_recipients", 0)
    sent_count = report_data.get("sent_count", 0)
    sent_pct = report_data.get("sent_pct", 0.0)
    failed_count = report_data.get("failed_count", 0)
    total_reactions = report_data.get("total_reactions", 0)
    reaction_pct = report_data.get("reaction_pct", 0.0)
    bd = report_data.get("reactions_breakdown") or {}

    top_line = ""
    top_news = report_data.get("top_news")
    if top_news and top_news.get("reactions_total", 0) > 0:
        preview = html.escape(_plain_news_preview(top_news.get("text", ""), max_len=65))
        top_line = (
            f"\n🏆 <b>Топ-новина:</b> #{top_news['id']} "
            f"({top_news['reactions_total']} реакцій) — <i>{preview}</i>"
        )

    return (
        f"📊 <b>Тижневий звіт по всіх новинах</b>\n"
        f"📅 Період: <b>{period}</b>\n"
        f"───────────────────\n"
        f"📰 Опубліковано новин: <b>{news_count}</b>\n"
        f"📬 Всього відправок: <b>{total_recipients}</b>\n"
        f"✅ Доставлено: <b>{sent_count}</b> ({sent_pct}%)\n"
        f"❌ Помилок доставки: <b>{failed_count}</b>\n"
        f"💬 Реакцій: <b>{total_reactions}</b> ({reaction_pct}%)\n"
        f"👍 {bd.get('👍', 0)} | 🔥 {bd.get('🔥', 0)} | 😁 {bd.get('😁', 0)} | ❤️ {bd.get('❤️', 0)} | 🤔 {bd.get('🤔', 0)}"
        f"{top_line}\n\n"
        f"• <b>Аркуш 1:</b> Зведення тижня та таблиця новин\n"
        f"• <b>Аркуш 2:</b> Реакції за тиждень\n"
        f"• <b>Аркуш 3:</b> Не доставлено"
    )


async def generate_weekly_news_report_xlsx(
    days: int = 7,
    db_path: str = DB_PATH,
    now_dt: Optional[datetime] = None,
) -> Tuple[io.BytesIO, Dict[str, Any]]:
    """
    Генерує тижневий Excel-звіт по всіх новинах за останні `days` днів:
    - Аркуш 1: «Зведення тижня» (KPI + таблиця всіх новин із доставкою, % реакцій та емоціями).
    - Аркуш 2: «Реакції за тиждень» (усі персональні реакції).
    - Аркуш 3: «Не доставлено» (усі помилки доставки за тиждень).
    """
    report_data = await get_weekly_news_report_data(days=days, db_path=db_path, now_dt=now_dt)

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    font_title = Font(name="Arial", size=13, bold=True, color="1F2937")
    font_sub = Font(name="Arial", size=9, italic=True, color="4B5563")
    font_section = Font(name="Arial", size=11, bold=True, color="FFFFFF")
    font_header = Font(name="Arial", size=10, bold=True, color="FFFFFF")
    font_data = Font(name="Arial", size=10, color="1F2937")
    font_bold = Font(name="Arial", size=10, bold=True, color="1F2937")

    fill_primary = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    fill_header = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")
    fill_kpi_header = PatternFill(start_color="D97706", end_color="D97706", fill_type="solid")
    fill_zebra = PatternFill(start_color="F9FAFB", end_color="F9FAFB", fill_type="solid")
    fill_error_header = PatternFill(start_color="DC2626", end_color="DC2626", fill_type="solid")
    fill_success_header = PatternFill(start_color="059669", end_color="059669", fill_type="solid")

    thin_side = Side(style="thin", color="D1D5DB")
    border_data = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")
    align_wrap = Alignment(horizontal="left", vertical="top", wrap_text=True)

    used_titles: Set[str] = set()

    # =========================================================================
    # АРКУШ 1: Зведення тижня
    # =========================================================================
    ws_sum = wb.create_sheet(title=_sanitize_sheet_title("Зведення тижня", used_titles))
    ws_sum.views.sheetView[0].showGridLines = True

    ws_sum.merge_cells("A1:P1")
    ws_sum["A1"] = f"📰 ТИЖНЕВИЙ ЗВІТ ПО ВСІХ НОВИНАХ ({report_data['period_label']})"
    ws_sum["A1"].font = font_title
    ws_sum["A1"].alignment = align_left
    ws_sum.row_dimensions[1].height = 25

    ws_sum.merge_cells("A2:P2")
    ws_sum["A2"] = (
        f"Період: {report_data['start_str']} — {report_data['end_str']} (Europe/Kyiv) | "
        f"Всього новин: {report_data['news_count']}"
    )
    ws_sum["A2"].font = font_sub
    ws_sum["A2"].alignment = align_left

    # Блок KPI
    ws_sum.merge_cells("A4:D4")
    ws_sum["A4"] = "📊 СУМАРНІ ПОКАЗНИКИ ТИЖНЯ"
    ws_sum["A4"].font = font_section
    ws_sum["A4"].fill = fill_primary
    ws_sum["A4"].alignment = align_left
    ws_sum.row_dimensions[4].height = 22

    bd = report_data["reactions_breakdown"]
    kpi_rows = [
        ("📰 Опубліковано новин", report_data["news_count"], f"за останні {days} днів"),
        ("📬 Всього відправок (аудиторія)", report_data["total_recipients"], "100%"),
        ("✅ Успішно доставлено", report_data["sent_count"], f"{report_data['sent_pct']}%"),
        ("❌ Не вдалося доставити", report_data["failed_count"], f"{report_data['failed_pct']}%"),
        ("💬 Всього реакцій", report_data["total_reactions"], f"{report_data['reaction_pct']}% від доставлених"),
        (
            "🎭 Розподіл емоцій",
            f"👍 {bd['👍']} | 🔥 {bd['🔥']} | 😁 {bd['😁']} | ❤️ {bd['❤️']} | 🤔 {bd['🤔']}",
            "сумарно за тиждень",
        ),
    ]
    r_idx = 5
    for label, val, note in kpi_rows:
        ws_sum.merge_cells(start_row=r_idx, start_column=1, end_row=r_idx, end_column=2)
        c_lbl = ws_sum.cell(row=r_idx, column=1, value=label)
        c_lbl.font = font_bold
        c_lbl.border = border_data
        ws_sum.cell(row=r_idx, column=2).border = border_data

        c_val = ws_sum.cell(row=r_idx, column=3, value=val)
        c_val.font = font_bold
        c_val.alignment = align_center
        c_val.border = border_data

        c_note = ws_sum.cell(row=r_idx, column=4, value=note)
        c_note.font = font_sub
        c_note.alignment = align_left
        c_note.border = border_data
        r_idx += 1

    # Таблиця всіх новин тижня
    r_idx += 1
    ws_sum.merge_cells(start_row=r_idx, start_column=1, end_row=r_idx, end_column=16)
    sec_tbl = ws_sum.cell(row=r_idx, column=1, value="📋 УСІ НОВИНИ ЗА ТИЖДЕНЬ")
    sec_tbl.font = font_section
    sec_tbl.fill = fill_kpi_header
    sec_tbl.alignment = align_left
    ws_sum.row_dimensions[r_idx].height = 22
    r_idx += 1

    news_headers = [
        "ID",
        "Дата публікації",
        "Текст новини (превʼю)",
        "Аудиторія",
        "Місто",
        "Всього",
        "Доставлено",
        "% дост.",
        "Помилки",
        "Реакції",
        "% реакцій",
        "👍",
        "🔥",
        "😁",
        "❤️",
        "🤔",
    ]
    for col_i, h in enumerate(news_headers, start=1):
        c = ws_sum.cell(row=r_idx, column=col_i, value=h)
        c.font = font_header
        c.fill = fill_header
        c.alignment = align_center
        c.border = border_data
    ws_sum.row_dimensions[r_idx].height = 22
    r_idx += 1

    news_items = report_data["news_items"]
    if not news_items:
        ws_sum.merge_cells(start_row=r_idx, start_column=1, end_row=r_idx, end_column=16)
        c_empty = ws_sum.cell(row=r_idx, column=1, value="За обраний тиждень новин не публікувалось.")
        c_empty.font = font_sub
        c_empty.alignment = align_center
    else:
        for idx_i, item in enumerate(news_items):
            fill = fill_zebra if idx_i % 2 == 1 else PatternFill(fill_type=None)
            roles_list = item.get("selected_roles") or []
            roles_str = ", ".join(roles_list) if roles_list else "Всі"
            city_raw = item.get("selected_city") or "all"
            city_str = "Усі міста" if city_raw == "all" else city_raw
            n_bd = item.get("reactions_breakdown") or {}

            vals = [
                f"#{item['id']}",
                item.get("created_at") or "—",
                _plain_news_preview(item.get("text", ""), max_len=140),
                roles_str,
                city_str,
                item.get("total_recipients") or 0,
                item.get("sent_count") or 0,
                f"{item.get('sent_pct', 0.0)}%",
                item.get("failed_count") or 0,
                item.get("reactions_total", 0),
                f"{item.get('reaction_pct', 0.0)}%",
                n_bd.get("👍", 0),
                n_bd.get("🔥", 0),
                n_bd.get("😁", 0),
                n_bd.get("❤️", 0),
                n_bd.get("🤔", 0),
            ]
            for col_i, val in enumerate(vals, start=1):
                c = ws_sum.cell(row=r_idx, column=col_i, value=val)
                c.font = font_data
                c.border = border_data
                if fill.fill_type:
                    c.fill = fill
                if col_i in (3, 4):
                    c.alignment = align_wrap
                elif col_i == 5:
                    c.alignment = align_left
                else:
                    c.alignment = align_center
            ws_sum.row_dimensions[r_idx].height = 28
            r_idx += 1

    # =========================================================================
    # АРКУШ 2: Реакції за тиждень
    # =========================================================================
    ws_react = wb.create_sheet(title=_sanitize_sheet_title("Реакції за тиждень", used_titles))
    ws_react.views.sheetView[0].showGridLines = True

    ws_react.merge_cells("A1:I1")
    ws_react["A1"] = f"💬 РЕАКЦІЇ СПІВРОБІТНИКІВ ЗА ТИЖДЕНЬ ({report_data['period_label']})"
    ws_react["A1"].font = font_title
    ws_react["A1"].alignment = align_left
    ws_react.row_dimensions[1].height = 24

    react_headers = ["№", "Новина", "Дата новини", "ПІБ", "Посада", "Магазин", "Місто", "Реакція", "Час реакції"]
    for col_i, h in enumerate(react_headers, start=1):
        c = ws_react.cell(row=3, column=col_i, value=h)
        c.font = font_header
        c.fill = fill_success_header
        c.alignment = align_center
        c.border = border_data
    ws_react.row_dimensions[3].height = 22

    reactions_detailed = report_data["reactions_detailed"]
    if not reactions_detailed:
        ws_react.merge_cells("A4:I4")
        c_empty = ws_react.cell(row=4, column=1, value="За цей тиждень реакцій не зафіксовано.")
        c_empty.font = font_sub
        c_empty.alignment = align_center
    else:
        for row_idx, rec in enumerate(reactions_detailed, start=4):
            fill = fill_zebra if row_idx % 2 == 1 else PatternFill(fill_type=None)
            vals = [
                row_idx - 3,
                f"#{rec.get('news_id')}",
                rec.get("news_created_at") or "—",
                rec.get("full_name") or f"ID {rec.get('user_id')}",
                rec.get("role") or "—",
                rec.get("shop") or "—",
                rec.get("city") or "—",
                rec.get("reaction") or "—",
                rec.get("updated_at") or rec.get("created_at") or "—",
            ]
            for col_i, val in enumerate(vals, start=1):
                c = ws_react.cell(row=row_idx, column=col_i, value=val)
                c.font = Font(name="Arial", size=14) if col_i == 8 else font_data
                c.border = border_data
                if fill.fill_type:
                    c.fill = fill
                c.alignment = align_center if col_i in (1, 2, 3, 8, 9) else align_left

    # =========================================================================
    # АРКУШ 3: Не доставлено
    # =========================================================================
    ws_fail = wb.create_sheet(title=_sanitize_sheet_title("Не доставлено", used_titles))
    ws_fail.views.sheetView[0].showGridLines = True

    ws_fail.merge_cells("A1:H1")
    ws_fail["A1"] = f"❌ НЕ ДОСТАВЛЕНО ЗА ТИЖДЕНЬ ({report_data['period_label']})"
    ws_fail["A1"].font = font_title
    ws_fail["A1"].alignment = align_left
    ws_fail.row_dimensions[1].height = 24

    fail_headers = ["№", "Новина", "Дата новини", "ПІБ", "Посада", "Магазин", "Місто", "Причина"]
    for col_i, h in enumerate(fail_headers, start=1):
        c = ws_fail.cell(row=3, column=col_i, value=h)
        c.font = font_header
        c.fill = fill_error_header
        c.alignment = align_center
        c.border = border_data
    ws_fail.row_dimensions[3].height = 22

    failed_deliveries = report_data["failed_deliveries"]
    if not failed_deliveries:
        ws_fail.merge_cells("A4:H4")
        c_empty = ws_fail.cell(row=4, column=1, value="Усі новини за тиждень доставлено без помилок!")
        c_empty.font = font_sub
        c_empty.alignment = align_center
    else:
        for row_idx, rec in enumerate(failed_deliveries, start=4):
            fill = fill_zebra if row_idx % 2 == 1 else PatternFill(fill_type=None)
            vals = [
                row_idx - 3,
                f"#{rec.get('news_id')}",
                rec.get("news_created_at") or "—",
                rec.get("full_name") or f"ID {rec.get('user_id')}",
                rec.get("role") or "—",
                rec.get("shop") or "—",
                rec.get("city") or "—",
                rec.get("error_reason") or rec.get("raw_error") or "Невідома помилка",
            ]
            for col_i, val in enumerate(vals, start=1):
                c = ws_fail.cell(row=row_idx, column=col_i, value=val)
                c.font = font_data
                c.border = border_data
                if fill.fill_type:
                    c.fill = fill
                c.alignment = align_center if col_i in (1, 2, 3) else align_left

    # Автопідбір ширини колонок
    for ws in wb.worksheets:
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                if cell.row in (1, 2):
                    continue
                val_str = str(cell.value or "")
                if len(val_str) > max_len:
                    max_len = len(val_str)
            ws.column_dimensions[col_letter].width = max(10, min(max_len + 4, 46))

    stream = io.BytesIO()
    wb.save(stream)
    stream.seek(0)
    return stream, report_data


async def auto_weekly_news_report_sender(bot, days: int = 7) -> int:
    """
    Автоматично формує та розсилає тижневий Excel-звіт по всіх новинах
    усім Адміністраторам та активним Наглядачам (щопонеділка о 09:00).
    Повертає кількість успішно надісланих повідомлень.
    """
    from aiogram.types import BufferedInputFile

    stream, report_data = await generate_weekly_news_report_xlsx(days=days)
    if report_data["news_count"] == 0:
        logger.info("ℹ️ Тижневий звіт по новинах пропущено: за останні 7 днів публікацій не було.")
        return 0

    recipients = await get_news_report_recipient_ids()
    if not recipients:
        logger.warning("⚠️ Не знайдено отримувачів (Адміни/Наглядачі) для тижневого звіту по новинах.")
        return 0

    caption = format_weekly_news_summary_caption(report_data)
    file_bytes = stream.getvalue()
    now_tag = datetime.now().strftime("%Y%m%d")
    filename = f"weekly_news_report_{now_tag}.xlsx"

    sent = 0
    for uid in recipients:
        try:
            doc = BufferedInputFile(file_bytes, filename=filename)
            await bot.send_document(
                chat_id=uid,
                document=doc,
                caption=caption,
                parse_mode="HTML",
            )
            sent += 1
        except Exception as e:
            logger.warning(f"Failed to send weekly news report to {uid}: {e}")
        await asyncio.sleep(0.08)

    logger.info(f"📊 Тижневий звіт по новинах надіслано {sent}/{len(recipients)} отримувачам.")
    return sent

