from __future__ import annotations
import io
import json
import re
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional

import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

from database import DB_PATH
from database.attestation import (
    get_wave_by_id,
    get_wave_shop_stats,
    get_shop_members_details,
    get_wave_statistics,
    get_wave_managers_details,
    get_questions_by_ids
)


def _sanitize_sheet_title(title: str, existing_titles: set[str]) -> str:
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


# Стилі для Excel у фірмовій темі BULKA
HEADER_FILL_GOLD = PatternFill(start_color="D97706", end_color="D97706", fill_type="solid") # Бурштиновий
HEADER_FILL_DARK = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid") # Темний графіт
HEADER_FILL_SUB = PatternFill(start_color="F59E0B", end_color="F59E0B", fill_type="solid")
SUBHEADER_FILL = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")  # Світло-бежевий
PASS_FILL = PatternFill(start_color="D1FAE5", end_color="D1FAE5", fill_type="solid")       # М'який зелений
FAIL_FILL = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")       # М'який червоний
ZEBRA_FILL = PatternFill(start_color="F9FAFB", end_color="F9FAFB", fill_type="solid")

FONT_TITLE = Font(name="Calibri", size=14, bold=True, color="FFFFFF")
FONT_HEADER = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
FONT_SUBHEADER = Font(name="Calibri", size=11, bold=True, color="1F2937")
FONT_DATA = Font(name="Calibri", size=10, color="111827")
FONT_BOLD = Font(name="Calibri", size=10, bold=True, color="111827")
FONT_PASS = Font(name="Calibri", size=10, bold=True, color="065F46")
FONT_FAIL = Font(name="Calibri", size=10, bold=True, color="991B1B")

BORDER_THIN = Border(
    left=Side(style='thin', color='E5E7EB'),
    right=Side(style='thin', color='E5E7EB'),
    top=Side(style='thin', color='E5E7EB'),
    bottom=Side(style='thin', color='E5E7EB')
)


def generate_attestation_template(roles: List[str]) -> io.BytesIO:
    """
    Генерує еталонний файл-шаблон template_attestation.xlsx,
    де кожен аркуш відповідає конкретній посаді в системі.
    """
    wb = openpyxl.Workbook()
    # Видаляємо дефолтний аркуш
    wb.remove(wb.active)

    headers = [
        "Питання",
        "Варіант 1",
        "Варіант 2",
        "Варіант 3",
        "Варіант 4",
        "Вірна відповідь (1-4)",
        "Бали",
        "Пояснення (опціонально)"
    ]

    existing_titles: set[str] = set()

    for role in roles:
        safe_title = _sanitize_sheet_title(role, existing_titles)
        ws = wb.create_sheet(title=safe_title)
        ws.views.sheetView[0].showGridLines = True

        # Заголовок посади
        ws.merge_cells("A1:H1")
        top_cell = ws["A1"]
        top_cell.value = f"🥐 БАНК ПИТАНЬ АТЕСТАЦІЇ: {role.upper()}"
        top_cell.font = FONT_TITLE
        top_cell.fill = HEADER_FILL_GOLD
        top_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[1].height = 32

        # Шапка таблиці
        ws.row_dimensions[2].height = 24
        for col_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=2, column=col_idx, value=h)
            cell.font = FONT_HEADER
            cell.fill = HEADER_FILL_DARK
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = BORDER_THIN

        # Зразок рядка
        sample_row = [
            "Приклад запитання: Який термін реалізації свіжих круасанів з моменту випікання?",
            "4 години",
            "12 годин",
            "24 години",
            "48 годин",
            2, # вірна відповідь
            1, # бали
            "Згідно зі стандартом якості BULKA свіжа листкова випічка реалізується до 12 год."
        ]
        ws.row_dimensions[3].height = 22
        for col_idx, val in enumerate(sample_row, 1):
            c = ws.cell(row=3, column=col_idx, value=val)
            c.font = FONT_DATA
            c.border = BORDER_THIN
            if col_idx == 6 or col_idx == 7:
                c.alignment = Alignment(horizontal="center", vertical="center")
            else:
                c.alignment = Alignment(horizontal="left", vertical="center")

        # Автоширина колонок
        col_widths = [45, 20, 20, 20, 20, 22, 12, 40]
        for col_idx, width in enumerate(col_widths, 1):
            col_letter = get_column_letter(col_idx)
            ws.column_dimensions[col_letter].width = width

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output


def parse_attestation_excel(file_bytes: bytes, valid_roles: List[str]) -> Tuple[Dict[str, List[Dict[str, Any]]], List[str]]:
    """
    Зчитує завантажений файл Excel та валідує питання за аркушами (посадами).
    Повертає ({role_name: [questions]}, [warnings_or_errors]).
    """
    warnings: List[str] = []
    result: Dict[str, List[Dict[str, Any]]] = {}

    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    except Exception as e:
        return {}, [f"Помилка відкриття файлу Excel: {str(e)}"]

    # Карта для нечутливого до регістру зіставлення посад
    valid_roles_map = {r.strip().lower(): r.strip() for r in valid_roles}

    for sheet_name in wb.sheetnames:
        clean_sheet_name = sheet_name.strip()
        matched_role = valid_roles_map.get(clean_sheet_name.lower())

        if not matched_role:
            # Спробуємо зіставити початок назви, якщо аркуш обрізався лімітом Excel у 31 символ
            for vr_lower, vr_orig in valid_roles_map.items():
                if vr_lower.startswith(clean_sheet_name.lower()[:25]):
                    matched_role = vr_orig
                    break

        if not matched_role:
            warnings.append(f"Аркуш '{sheet_name}' пропущено: посаду не знайдено серед діючих посад бота.")
            continue

        ws = wb[sheet_name]
        questions: List[Dict[str, Any]] = []

        # Визначаємо стартовий рядок (пропускаємо заголовок)
        start_row = 1
        for r in range(1, 10):
            val = str(ws.cell(row=r, column=1).value or "").strip().lower()
            if "питання" in val and "варіант" in str(ws.cell(row=r, column=2).value or "").lower():
                start_row = r + 1
                break

        for row_idx in range(start_row, ws.max_row + 1):
            q_text = ws.cell(row=row_idx, column=1).value
            if not q_text or not str(q_text).strip():
                continue

            q_text = str(q_text).strip()
            opt1 = str(ws.cell(row=row_idx, column=2).value or "").strip()
            opt2 = str(ws.cell(row=row_idx, column=3).value or "").strip()
            opt3 = str(ws.cell(row=row_idx, column=4).value or "").strip()
            opt4 = str(ws.cell(row=row_idx, column=5).value or "").strip()

            correct_raw = ws.cell(row=row_idx, column=6).value
            points_raw = ws.cell(row=row_idx, column=7).value
            explanation = str(ws.cell(row=row_idx, column=8).value or "").strip()

            if not opt1 or not opt2:
                warnings.append(f"Посада '{matched_role}', рядок {row_idx}: питання має містити щонайменше 2 варіанти відповідей. Пропущено.")
                continue

            try:
                correct_opt = int(correct_raw)
                if correct_opt < 1 or correct_opt > 4:
                    warnings.append(f"Посада '{matched_role}', рядок {row_idx}: вірна відповідь має бути числом від 1 до 4 (вказано: {correct_raw}). Пропущено.")
                    continue
            except Exception:
                warnings.append(f"Посада '{matched_role}', рядок {row_idx}: некоректне значення вірної відповіді '{correct_raw}'. Пропущено.")
                continue

            try:
                points = int(points_raw) if points_raw is not None else 1
                if points < 1:
                    points = 1
            except Exception:
                points = 1

            questions.append({
                "question_text": q_text,
                "option_1": opt1,
                "option_2": opt2,
                "option_3": opt3 if opt3 else None,
                "option_4": opt4 if opt4 else None,
                "correct_option": correct_opt,
                "points": points,
                "explanation": explanation if explanation else None
            })

        if questions:
            result[matched_role] = questions
        else:
            warnings.append(f"На аркуші '{matched_role}' не знайдено коректних запитань.")

    return result, warnings


async def _generate_managers_attestation_results_xlsx(
    wb: openpyxl.Workbook,
    wave: Dict[str, Any],
    wave_id: int,
    overall_stats: Dict[str, Any],
    db_path: str = DB_PATH
):
    """
    Генерує спеціальний звіт для атестації керівників:
    - Аркуш 1: «Зведений рейтинг керівників»
    - Аркуші 2..N: Детальний аудит запитань та відповідей по кожному керівнику
    """
    title = wave.get("title", f"Атестація #{wave_id}")
    passing_pct = wave.get("passing_score_pct", 80)
    deadline = wave.get("deadline_date", "")

    mgrs = await get_wave_managers_details(wave_id, db_path=db_path)
    existing_titles: set[str] = set()

    # -------------------------------------------------------------
    # АРКУШ 1: Зведений рейтинг керівників
    # -------------------------------------------------------------
    ws_summary = wb.create_sheet(title="Зведений рейтинг керівників")
    existing_titles.add("зведений рейтинг керівників")
    ws_summary.views.sheetView[0].showGridLines = True

    # Заголовок
    ws_summary.merge_cells("A1:H1")
    top_cell = ws_summary["A1"]
    top_cell.value = f"🥐 КОРПОРАТИВНА АТЕСТАЦІЯ BULKA: {title.upper()} (КЕРІВНИКИ)"
    top_cell.font = FONT_TITLE
    top_cell.fill = HEADER_FILL_GOLD
    top_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws_summary.row_dimensions[1].height = 34

    # Інфо-блок
    info_rows = [
        f"Дедлайн здачі: {deadline} | Прохідний поріг: {passing_pct}% | Всього зареєстровано: {overall_stats['total_participants']} ос.",
        f"Завершили тест: {overall_stats['completed_count']} ос. | Склали успішно: {overall_stats['passed_count']} ос. | Середній бал: {overall_stats['avg_score']}%"
    ]
    for idx, info_text in enumerate(info_rows, 2):
        ws_summary.merge_cells(f"A{idx}:H{idx}")
        cell = ws_summary[f"A{idx}"]
        cell.value = info_text
        cell.font = FONT_BOLD
        cell.fill = SUBHEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws_summary.row_dimensions[idx].height = 20

    # Шапка таблиці рейтингу
    summary_headers = [
        "№",
        "ПІБ керівника",
        "Магазин",
        "Набрано балів",
        "Макс. балів",
        "% успішності",
        "Вердикт",
        "Дата здачі"
    ]
    ws_summary.row_dimensions[5].height = 26
    for col_idx, h in enumerate(summary_headers, 1):
        c = ws_summary.cell(row=5, column=col_idx, value=h)
        c.font = FONT_HEADER
        c.fill = HEADER_FILL_DARK
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = BORDER_THIN

    # Сортування керівників за результатом (відсоток, бали)
    sorted_mgrs = sorted(mgrs, key=lambda m: (m.get("score_pct") or 0.0, m.get("score") or 0), reverse=True)

    curr_row = 6
    for idx, m in enumerate(sorted_mgrs, 1):
        ws_summary.row_dimensions[curr_row].height = 22
        st = m.get("attempt_status")
        if st == "passed":
            verdict = "✅ Складено"
        elif st == "failed":
            verdict = "❌ Не складено"
        elif st == "timeout":
            verdict = "⏱ Час вичерпано"
        elif st == "in_progress":
            verdict = "⏳ В процесі"
        else:
            verdict = "💤 Не розпочато"

        score = m.get("score") if m.get("score") is not None else "-"
        max_score = m.get("max_score") if m.get("max_score") is not None else "-"
        score_pct = f"{m.get('score_pct')}%" if m.get("score_pct") is not None else "-"

        fin_at = m.get("finished_at") or "-"
        if fin_at != "-":
            try:
                dt = datetime.strptime(fin_at, "%Y-%m-%d %H:%M:%S")
                fin_at = dt.strftime("%d.%m.%Y %H:%M")
            except Exception:
                pass

        row_vals = [
            idx,
            m.get("full_name") or "Не вказано",
            m.get("shop_name") or "Не вказано",
            score,
            max_score,
            score_pct,
            verdict,
            fin_at
        ]
        for col_idx, val in enumerate(row_vals, 1):
            cell = ws_summary.cell(row=curr_row, column=col_idx, value=val)
            cell.font = FONT_DATA
            cell.border = BORDER_THIN
            if col_idx in (1, 4, 5, 6, 7, 8):
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")

            if col_idx == 7:
                if st == "passed":
                    cell.fill = PASS_FILL
                    cell.font = FONT_PASS
                elif st in ("failed", "timeout"):
                    cell.fill = FAIL_FILL
                    cell.font = FONT_FAIL

        curr_row += 1

    s_widths = [6, 28, 22, 16, 16, 16, 18, 20]
    for c_idx, w in enumerate(s_widths, 1):
        ws_summary.column_dimensions[get_column_letter(c_idx)].width = w

    # -------------------------------------------------------------
    # АРКУШІ 2..N: Детальний аудит питань і відповідей по кожному керівнику
    # -------------------------------------------------------------
    for m in sorted_mgrs:
        full_name = m.get("full_name") or f"Керівник_{m['user_id']}"
        sheet_title = _sanitize_sheet_title(full_name, existing_titles)
        ws_mgr = wb.create_sheet(title=sheet_title)
        ws_mgr.views.sheetView[0].showGridLines = True

        shop_name = m.get("shop_name") or "Не вказано"
        st = m.get("attempt_status")
        if st == "passed":
            verdict = "✅ Складено"
        elif st == "failed":
            verdict = "❌ Не складено"
        elif st == "timeout":
            verdict = "⏱ Час вичерпано"
        elif st == "in_progress":
            verdict = "⏳ В процесі"
        else:
            verdict = "💤 Не розпочато"

        score = m.get("score") if m.get("score") is not None else "-"
        max_score = m.get("max_score") if m.get("max_score") is not None else "-"
        score_pct = f"{m.get('score_pct')}%" if m.get("score_pct") is not None else "-"

        fin_at = m.get("finished_at") or "-"
        if fin_at != "-":
            try:
                dt = datetime.strptime(fin_at, "%Y-%m-%d %H:%M:%S")
                fin_at = dt.strftime("%d.%m.%Y %H:%M")
            except Exception:
                pass

        # Заголовок аркуша
        ws_mgr.merge_cells("A1:G1")
        h_cell = ws_mgr["A1"]
        h_cell.value = f"👔 РЕЗУЛЬТАТИ АТЕСТАЦІЇ: {full_name.upper()} ({shop_name})"
        h_cell.font = FONT_TITLE
        h_cell.fill = HEADER_FILL_GOLD
        h_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws_mgr.row_dimensions[1].height = 32

        # Інфо рядки
        ws_mgr.merge_cells("A2:G2")
        cell_i1 = ws_mgr["A2"]
        cell_i1.value = f"Магазин: {shop_name} | Посада: Керівник | Статус: {verdict}"
        cell_i1.font = FONT_BOLD
        cell_i1.fill = SUBHEADER_FILL
        cell_i1.alignment = Alignment(horizontal="center", vertical="center")
        ws_mgr.row_dimensions[2].height = 20

        ws_mgr.merge_cells("A3:G3")
        cell_i2 = ws_mgr["A3"]
        cell_i2.value = f"Набрано балів: {score} з {max_score} ({score_pct}) | Час здачі: {fin_at}"
        cell_i2.font = FONT_BOLD
        cell_i2.fill = SUBHEADER_FILL
        cell_i2.alignment = Alignment(horizontal="center", vertical="center")
        ws_mgr.row_dimensions[3].height = 20

        # Шапка питань
        q_headers = [
            "№",
            "Запитання",
            "Відповідь керівника",
            "Правильна відповідь",
            "Вердикт",
            "Бали",
            "Пояснення"
        ]
        ws_mgr.row_dimensions[5].height = 24
        for col_idx, qh in enumerate(q_headers, 1):
            c = ws_mgr.cell(row=5, column=col_idx, value=qh)
            c.font = FONT_HEADER
            c.fill = HEADER_FILL_DARK
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border = BORDER_THIN

        # Парсимо питання та відповіді
        q_ids = []
        if m.get("questions_order_json"):
            try:
                q_ids = json.loads(m["questions_order_json"])
            except Exception:
                q_ids = []

        ans_map = {}
        if m.get("answers_json"):
            try:
                ans_map = json.loads(m["answers_json"])
            except Exception:
                ans_map = {}

        if not q_ids:
            ws_mgr.row_dimensions[6].height = 24
            ws_mgr.merge_cells("A6:G6")
            empty_c = ws_mgr["A6"]
            empty_c.value = "Керівник ще не проходив тестування або відповіді відсутні."
            empty_c.font = FONT_DATA
            empty_c.alignment = Alignment(horizontal="center", vertical="center")
            empty_c.border = BORDER_THIN
        else:
            q_dict = await get_questions_by_ids(q_ids, db_path=db_path)
            q_row = 6
            for q_idx, q_id in enumerate(q_ids, 1):
                ws_mgr.row_dimensions[q_row].height = 24
                q = q_dict.get(q_id, {})
                q_text = q.get("question_text") or f"Питання #{q_id}"

                user_opt = ans_map.get(str(q_id))
                if user_opt is None:
                    user_opt = ans_map.get(q_id)

                corr_opt = q.get("correct_option")
                corr_ans = q.get(f"option_{corr_opt}") if corr_opt else "-"

                if user_opt is not None:
                    try:
                        user_opt_int = int(user_opt)
                        user_ans = q.get(f"option_{user_opt_int}") or f"Варіант {user_opt_int}"
                        is_correct = (user_opt_int == corr_opt)
                    except Exception:
                        user_ans = str(user_opt)
                        is_correct = False
                    verdict_q = "✅ Вірно" if is_correct else "❌ Помилка"
                    pts = q.get("points", 1) if is_correct else 0
                else:
                    user_ans = "Немає відповіді"
                    is_correct = False
                    verdict_q = "⏱ Без відповіді"
                    pts = 0

                expl = q.get("explanation") or "-"

                row_q_vals = [
                    q_idx,
                    q_text,
                    user_ans,
                    corr_ans,
                    verdict_q,
                    pts,
                    expl
                ]
                for c_idx, val in enumerate(row_q_vals, 1):
                    cell = ws_mgr.cell(row=q_row, column=c_idx, value=val)
                    cell.font = FONT_DATA
                    cell.border = BORDER_THIN
                    if c_idx in (1, 5, 6):
                        cell.alignment = Alignment(horizontal="center", vertical="center")
                    else:
                        cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

                    if c_idx == 5:
                        if is_correct:
                            cell.fill = PASS_FILL
                            cell.font = FONT_PASS
                        else:
                            cell.fill = FAIL_FILL
                            cell.font = FONT_FAIL

                q_row += 1

        mgr_widths = [6, 40, 30, 30, 16, 10, 35]
        for c_idx, w in enumerate(mgr_widths, 1):
            ws_mgr.column_dimensions[get_column_letter(c_idx)].width = w


async def generate_attestation_results_xlsx(wave_id: int, db_path: str = DB_PATH) -> io.BytesIO:
    """
    Генерує підсумковий звіт результатів атестаційної хвилі:
    - Для працівників: «Зведений рейтинг магазинів» + деталізація по магазинах
    - Для керівників: «Зведений рейтинг керівників» + детальні аркуші по кожному керівнику
    """
    wave = await get_wave_by_id(wave_id, db_path=db_path)
    if not wave:
        raise ValueError(f"Хвилю атестації {wave_id} не знайдено.")

    title = wave.get("title", f"Атестація #{wave_id}")
    passing_pct = wave.get("passing_score_pct", 80)
    deadline = wave.get("deadline_date", "")

    overall_stats = await get_wave_statistics(wave_id, db_path=db_path)

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # прибираємо дефолтний

    if wave.get("target_type") == "managers":
        await _generate_managers_attestation_results_xlsx(wb, wave, wave_id, overall_stats, db_path=db_path)
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output

    shop_stats = await get_wave_shop_stats(wave_id, db_path=db_path)
    existing_titles: set[str] = set()

    # -------------------------------------------------------------
    # АРКУШ 1: Зведений рейтинг магазинів
    # -------------------------------------------------------------
    ws_summary = wb.create_sheet(title="Зведений рейтинг магазинів")
    existing_titles.add("зведений рейтинг магазинів")
    ws_summary.views.sheetView[0].showGridLines = True

    # Заголовок хвилі
    ws_summary.merge_cells("A1:H1")
    top_cell = ws_summary["A1"]
    top_cell.value = f"🥐 КОРПОРАТИВНА АТЕСТАЦІЯ BULKA: {title.upper()}"
    top_cell.font = FONT_TITLE
    top_cell.fill = HEADER_FILL_GOLD
    top_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws_summary.row_dimensions[1].height = 34

    # Інфо-блок
    info_rows = [
        f"Дедлайн здачі: {deadline} | Прохідний поріг: {passing_pct}% | Всього зареєстровано: {overall_stats['total_participants']} ос.",
        f"Завершили тест: {overall_stats['completed_count']} ос. | Склали успішно: {overall_stats['passed_count']} ос. | Середній бал мережі: {overall_stats['avg_score']}%"
    ]
    for idx, info_text in enumerate(info_rows, 2):
        ws_summary.merge_cells(f"A{idx}:H{idx}")
        cell = ws_summary[f"A{idx}"]
        cell.value = info_text
        cell.font = FONT_BOLD
        cell.fill = SUBHEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws_summary.row_dimensions[idx].height = 20

    # Шапка таблиці рейтингу
    summary_headers = [
        "№",
        "Магазин",
        "Всього учасників",
        "Пройшли тест",
        "Склали успішно",
        "Не склали",
        "Середній бал %",
        "Статус магазину"
    ]
    ws_summary.row_dimensions[5].height = 26
    for col_idx, h in enumerate(summary_headers, 1):
        c = ws_summary.cell(row=5, column=col_idx, value=h)
        c.font = FONT_HEADER
        c.fill = HEADER_FILL_DARK
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = BORDER_THIN

    # Сортування магазинів за рейтингом (середній бал)
    sorted_shops = sorted(shop_stats, key=lambda s: (s["avg_score_pct"], s["passed"]), reverse=True)

    curr_row = 6
    for idx, s in enumerate(sorted_shops, 1):
        ws_summary.row_dimensions[curr_row].height = 22
        failed_count = s["completed"] - s["passed"]
        status_text = "✅ Завершено успішно" if s["avg_score_pct"] >= passing_pct and s["completed"] == s["total_participants"] else \
                      ("⏳ В процесі" if s["completed"] < s["total_participants"] else "⚠️ Потребує уваги")

        row_vals = [
            idx,
            s["shop_name"],
            s["total_participants"],
            s["completed"],
            s["passed"],
            failed_count,
            f"{s['avg_score_pct']}%",
            status_text
        ]
        for col_idx, val in enumerate(row_vals, 1):
            cell = ws_summary.cell(row=curr_row, column=col_idx, value=val)
            cell.font = FONT_DATA
            cell.border = BORDER_THIN
            if col_idx in (1, 3, 4, 5, 6, 7):
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")

            # Підсвічування середнього балу
            if col_idx == 7:
                cell.font = FONT_BOLD
                if s["avg_score_pct"] >= passing_pct:
                    cell.fill = PASS_FILL
                elif s["completed"] > 0:
                    cell.fill = FAIL_FILL

        curr_row += 1

    # Ширини колонок
    s_widths = [6, 22, 18, 16, 16, 14, 18, 24]
    for c_idx, w in enumerate(s_widths, 1):
        ws_summary.column_dimensions[get_column_letter(c_idx)].width = w

    # -------------------------------------------------------------
    # АРКУШІ 2..N: Деталізація по кожному магазину
    # -------------------------------------------------------------
    for shop in sorted_shops:
        shop_name = shop["shop_name"]
        sheet_title = _sanitize_sheet_title(shop_name, existing_titles)
        ws_shop = wb.create_sheet(title=sheet_title)
        ws_shop.views.sheetView[0].showGridLines = True

        # Заголовок магазину
        ws_shop.merge_cells("A1:I1")
        h_cell = ws_shop["A1"]
        h_cell.value = f"🏪 МАГАЗИН: {shop_name.upper()} | РЕЗУЛЬТАТИ АТЕСТАЦІЇ"
        h_cell.font = FONT_TITLE
        h_cell.fill = HEADER_FILL_GOLD
        h_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws_shop.row_dimensions[1].height = 32

        # Шапка деталей
        detail_headers = [
            "№",
            "ПІБ співробітника",
            "Посада",
            "Роль",
            "Набрано балів",
            "Макс. балів",
            "% успішності",
            "Вердикт",
            "Дата здачі"
        ]
        ws_shop.row_dimensions[3].height = 24
        for col_idx, dh in enumerate(detail_headers, 1):
            c = ws_shop.cell(row=3, column=col_idx, value=dh)
            c.font = FONT_HEADER
            c.fill = HEADER_FILL_DARK
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border = BORDER_THIN

        members = await get_shop_members_details(wave_id, shop_name, db_path=db_path)
        m_row = 4
        for m_idx, m in enumerate(members, 1):
            ws_shop.row_dimensions[m_row].height = 20
            role_type = "👔 Керівник" if m.get("is_manager") else "👷 Працівник"

            status = m.get("attempt_status")
            if status == "passed":
                verdict = "✅ Складено"
            elif status == "failed":
                verdict = "❌ Не складено"
            elif status == "in_progress":
                verdict = "⏳ В процесі"
            else:
                verdict = "💤 Не розпочато"

            score = m.get("score") if m.get("score") is not None else "-"
            max_score = m.get("max_score") if m.get("max_score") is not None else "-"
            score_pct = f"{m.get('score_pct')}%" if m.get("score_pct") is not None else "-"

            fin_at = m.get("finished_at") or "-"
            if fin_at != "-":
                try:
                    dt = datetime.strptime(fin_at, "%Y-%m-%d %H:%M:%S")
                    fin_at = dt.strftime("%d.%m.%Y %H:%M")
                except Exception:
                    pass

            row_data = [
                m_idx,
                m.get("full_name") or "Не вказано",
                m.get("role_name") or "-",
                role_type,
                score,
                max_score,
                score_pct,
                verdict,
                fin_at
            ]

            for c_idx, val in enumerate(row_data, 1):
                cell = ws_shop.cell(row=m_row, column=c_idx, value=val)
                cell.font = FONT_DATA
                cell.border = BORDER_THIN
                if c_idx in (1, 4, 5, 6, 7, 8, 9):
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                else:
                    cell.alignment = Alignment(horizontal="left", vertical="center")

                # Стилізація вердикту
                if c_idx == 8:
                    if status == "passed":
                        cell.fill = PASS_FILL
                        cell.font = FONT_PASS
                    elif status == "failed":
                        cell.fill = FAIL_FILL
                        cell.font = FONT_FAIL

            m_row += 1

        d_widths = [6, 28, 24, 16, 14, 14, 14, 18, 20]
        for c_idx, w in enumerate(d_widths, 1):
            ws_shop.column_dimensions[get_column_letter(c_idx)].width = w

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output
