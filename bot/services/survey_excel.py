from __future__ import annotations
import io
import re
from datetime import datetime
from typing import Dict, Any, List, Set

import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

from database import DB_PATH
from database.surveys import get_survey_detailed_results


def _sanitize_sheet_title(title: str, existing_titles: Set[str]) -> str:
    """
    Очищає назву вкладки Excel від заборонених символів,
    обмежує довжину до 31 символу та гарантує унікальність.
    """
    cleaned = re.sub(r'[\\/*?:\[\]]', '_', title).strip()
    if not cleaned:
        cleaned = "Магазин"
    cleaned = cleaned[:28]

    final_title = cleaned
    counter = 1
    while final_title.lower() in existing_titles:
        final_title = f"{cleaned}_{counter}"[:31]
        counter += 1

    existing_titles.add(final_title.lower())
    return final_title


async def generate_survey_results_xlsx(survey_id: int, db_path: str = DB_PATH) -> io.BytesIO:
    """
    Генерує розгорнутий Excel-звіт за результатами опитування:
    - Аркуш 1: «Загальні результати» (зведення, розподіл % по варіантах відповідей).
    - Аркуші 2..N: Окремі вкладки по кожному магазину (ПІБ, посада, відповіді на кожне питання).
    """
    data = await get_survey_detailed_results(survey_id, db_path=db_path)
    survey = data.get("survey")
    if not survey:
        raise ValueError(f"Опитування з id={survey_id} не знайдено.")

    questions = data.get("questions", [])
    q_stats = data.get("question_stats", {})
    shops = data.get("shops", {})
    total_respondents = data.get("total_respondents", 0)

    title = survey.get("title", "Опитування BULKA")
    created_at = survey.get("created_at", "")
    target_city = survey.get("target_city") or "Усі міста"
    roles_list = survey.get("target_roles_list", [])
    roles_str = ", ".join(roles_list) if roles_list else "Всі категорії"

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # Видаляємо дефолтний аркуш

    # Стилі
    font_title = Font(name="Arial", size=14, bold=True, color="1F2937")
    font_sub = Font(name="Arial", size=10, italic=True, color="4B5563")
    font_section = Font(name="Arial", size=11, bold=True, color="FFFFFF")
    font_header = Font(name="Arial", size=10, bold=True, color="FFFFFF")
    font_data = Font(name="Arial", size=10, color="1F2937")
    font_bold = Font(name="Arial", size=10, bold=True, color="1F2937")

    fill_navy = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    fill_amber = PatternFill(start_color="D97706", end_color="D97706", fill_type="solid")
    fill_header = PatternFill(start_color="3B82F6", end_color="3B82F6", fill_type="solid")
    fill_zebra = PatternFill(start_color="F9FAFB", end_color="F9FAFB", fill_type="solid")

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
    # АРКУШ 1: Загальні результати
    # =========================================================================
    ws_summary = wb.create_sheet(title=_sanitize_sheet_title("Загальні результати", used_sheet_titles))
    ws_summary.views.sheetView[0].showGridLines = True

    # Заголовок
    ws_summary.merge_cells("A1:E1")
    ws_summary["A1"] = f"📊 ЗВІТ ЗА РЕЗУЛЬТАТАМИ ОПИТУВАННЯ: {title.upper()}"
    ws_summary["A1"].font = font_title
    ws_summary["A1"].alignment = align_left
    ws_summary.row_dimensions[1].height = 28

    ws_summary["A2"] = f"📅 Створено: {created_at} | 🏙 Місто: {target_city} | 👥 Аудиторія: {roles_str}"
    ws_summary["A2"].font = font_sub
    ws_summary["A2"].alignment = align_left

    ws_summary["A3"] = f"Всього респондентів, які взяли участь: {total_respondents}"
    ws_summary["A3"].font = font_bold
    ws_summary["A3"].alignment = align_left

    current_row = 5

    for q in questions:
        q_idx = q["question_idx"]
        stats = q_stats.get(q_idx, {})
        q_type = q["question_type"]
        q_text = q["text"]
        total_q_ans = stats.get("total_answers", 0)

        # Заголовок питання
        ws_summary.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=4)
        cell_q = ws_summary.cell(row=current_row, column=1)
        type_badge = " [Вибір варіанту]" if q_type == 'choice' else " [Вільна відповідь]"
        cell_q.value = f"Питання №{q_idx}: {q_text}{type_badge}"
        cell_q.font = font_section
        cell_q.fill = fill_navy
        cell_q.alignment = align_left
        ws_summary.row_dimensions[current_row].height = 22
        current_row += 1

        if q_type == 'choice':
            # Шапка таблиці варіантів
            ws_summary.cell(row=current_row, column=1, value="Варіант відповіді").fill = fill_amber
            ws_summary.cell(row=current_row, column=1).font = font_header
            ws_summary.cell(row=current_row, column=2, value="Кількість відповідей").fill = fill_amber
            ws_summary.cell(row=current_row, column=2).font = font_header
            ws_summary.cell(row=current_row, column=3, value="% від відповідей").fill = fill_amber
            ws_summary.cell(row=current_row, column=3).font = font_header
            ws_summary.cell(row=current_row, column=2).alignment = align_center
            ws_summary.cell(row=current_row, column=3).alignment = align_center
            current_row += 1

            opt_counts = stats.get("option_counts", {})
            opt_percentages = stats.get("option_percentages", {})

            for opt, cnt in opt_counts.items():
                pct = opt_percentages.get(opt, 0.0)
                ws_summary.cell(row=current_row, column=1, value=opt).alignment = align_left
                ws_summary.cell(row=current_row, column=2, value=cnt).alignment = align_center
                ws_summary.cell(row=current_row, column=3, value=f"{pct}%").alignment = align_center

                for col in range(1, 4):
                    c = ws_summary.cell(row=current_row, column=col)
                    c.font = font_data
                    c.border = border_data
                current_row += 1

            # Рядок Всього
            ws_summary.cell(row=current_row, column=1, value="Всього відповіли на питання").font = font_bold
            ws_summary.cell(row=current_row, column=2, value=total_q_ans).font = font_bold
            ws_summary.cell(row=current_row, column=2).alignment = align_center
            ws_summary.cell(row=current_row, column=3, value="100%").font = font_bold
            ws_summary.cell(row=current_row, column=3).alignment = align_center
            for col in range(1, 4):
                ws_summary.cell(row=current_row, column=col).border = border_data
            current_row += 2

        else:
            # Для відкритого питання
            raw_answers = stats.get("raw_text_answers", [])
            ws_summary.cell(row=current_row, column=1, value="Отримано розгорнутих відповідей:").font = font_bold
            ws_summary.cell(row=current_row, column=2, value=len(raw_answers)).font = font_bold
            current_row += 1

            if raw_answers:
                ws_summary.cell(row=current_row, column=1, value="№").font = font_header
                ws_summary.cell(row=current_row, column=1).fill = fill_header
                ws_summary.cell(row=current_row, column=1).alignment = align_center
                ws_summary.merge_cells(start_row=current_row, start_column=2, end_row=current_row, end_column=4)
                cell_h = ws_summary.cell(row=current_row, column=2, value="Текст відповіді")
                cell_h.font = font_header
                cell_h.fill = fill_header
                current_row += 1

                for a_idx, a_txt in enumerate(raw_answers, start=1):
                    ws_summary.cell(row=current_row, column=1, value=a_idx).alignment = align_center
                    ws_summary.merge_cells(start_row=current_row, start_column=2, end_row=current_row, end_column=4)
                    ws_summary.cell(row=current_row, column=2, value=a_txt).alignment = align_wrap
                    
                    for c_idx in range(1, 5):
                        ws_summary.cell(row=current_row, column=c_idx).border = border_data
                        ws_summary.cell(row=current_row, column=c_idx).font = font_data
                    current_row += 1

            current_row += 2

    # Автоматичне налаштування ширини колонок для першого аркуша
    for col in range(1, 5):
        ws_summary.column_dimensions[get_column_letter(col)].width = 30
    ws_summary.column_dimensions["A"].width = 40

    # =========================================================================
    # АРКУШІ 2..N: Вкладки по магазинах
    # =========================================================================
    for shop_name, respondents in shops.items():
        sheet_title = _sanitize_sheet_title(shop_name, used_sheet_titles)
        ws_shop = wb.create_sheet(title=sheet_title)
        ws_shop.views.sheetView[0].showGridLines = True

        # Заголовок магазину
        ws_shop.merge_cells(start_row=1, start_column=1, end_row=1, end_column=4 + len(questions))
        cell_shop_h = ws_shop.cell(row=1, column=1)
        cell_shop_h.value = f"🏪 Магазин: {shop_name} | Відповіли співробітників: {len(respondents)}"
        cell_shop_h.font = font_title
        cell_shop_h.alignment = align_left
        ws_shop.row_dimensions[1].height = 26

        # Шапка колонок таблиці
        headers = ["№", "ПІБ співробітника", "Посада", "Місто"]
        for q in questions:
            short_q = (q["text"][:30] + "...") if len(q["text"]) > 30 else q["text"]
            headers.append(f"П{q['question_idx']}: {short_q}")
        headers.append("Дата проходження")

        row_h = 3
        for col_idx, h_text in enumerate(headers, start=1):
            cell = ws_shop.cell(row=row_h, column=col_idx, value=h_text)
            cell.font = font_header
            cell.fill = fill_header
            cell.alignment = align_center
            cell.border = border_data
        ws_shop.row_dimensions[row_h].height = 24

        # Дані співробітників
        current_data_row = 4
        for idx, resp in enumerate(respondents, start=1):
            row_fill = fill_zebra if idx % 2 == 0 else PatternFill(fill_type=None)
            
            row_vals = [
                idx,
                resp.get("full_name", ""),
                resp.get("role", ""),
                resp.get("city", "")
            ]

            ans_map = resp.get("answers", {})
            for q in questions:
                ans_text = ans_map.get(q["question_idx"], "—")
                row_vals.append(ans_text)

            completed_at = resp.get("completed_at", "")
            if completed_at:
                try:
                    dt = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
                    completed_at = dt.strftime("%d.%m.%Y %H:%M")
                except Exception:
                    completed_at = str(completed_at)[:16]
            row_vals.append(completed_at)

            for col_idx, val in enumerate(row_vals, start=1):
                cell = ws_shop.cell(row=current_data_row, column=col_idx, value=val)
                cell.font = font_data
                cell.border = border_data
                if row_fill.fill_type:
                    cell.fill = row_fill
                
                # Вирівнювання: текст ліворуч, номери та дати по центру
                if col_idx in (1, 4 + len(questions)):
                    cell.alignment = align_center
                else:
                    cell.alignment = align_left

            ws_shop.row_dimensions[current_data_row].height = 20
            current_data_row += 1

        # Автоширина колонок
        for col in range(1, len(headers) + 1):
            col_letter = get_column_letter(col)
            max_len = max(len(str(ws_shop.cell(row=r, column=col).value or '')) for r in range(3, current_data_row))
            ws_shop.column_dimensions[col_letter].width = max(max_len + 4, 12)
        ws_shop.column_dimensions["B"].width = 28  # ПІБ

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer
