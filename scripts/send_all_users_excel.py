#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script to generate an Excel file with ALL users of Bulka Education bot
and send it via Telegram Bot API to:
- 1001226587 (Ірина Душинська)
- 738460434 (Данік)
"""

import sqlite3
import os
import datetime
import subprocess
import json
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

def main():
    base_dir = os.environ.get("BULKA_DIR", "/home/admin1/Bulka_Edu")
    if not os.path.exists(base_dir):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    u_path = os.path.join(base_dir, "database/users.db")
    m_path = os.path.join(base_dir, "database/managers.db")

    if not os.path.exists(u_path):
        print(f"Error: {u_path} not found")
        return

    u_con = sqlite3.connect(u_path)
    u_con.row_factory = sqlite3.Row
    
    mgr_map = {}
    if os.path.exists(m_path):
        m_con = sqlite3.connect(m_path)
        m_con.row_factory = sqlite3.Row
        mgr_map = {
            m["uid"]: f"{m['full_name']} ({m['process']})"
            for m in m_con.execute("SELECT uid, full_name, process FROM managers").fetchall()
        }

    days_map = {
        r["name"].strip(): (r["days_count"] or 5)
        for r in u_con.execute("SELECT name, days_count FROM positions").fetchall()
    }

    prog_map = {}
    for r in u_con.execute("SELECT user_id, COUNT(*) as c FROM progress WHERE completed = 1 GROUP BY user_id").fetchall():
        prog_map[r["user_id"]] = r["c"]

    cur = u_con.cursor()
    cur.execute("""
        SELECT user_id, full_name, username, role, status, city, shop, manager_id, manager_name, current_block, first_seen, last_activity
        FROM users
        ORDER BY 
            CASE 
                WHEN role IN ('Developer', 'Адміністратор') THEN 1
                WHEN role IN ('Керівник', 'Наглядач', 'Територіал', 'HR') THEN 2
                WHEN status = 'Працівник' THEN 3
                ELSE 4
            END,
            city, shop, full_name
    """)
    users = cur.fetchall()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Всі користувачі"
    ws.views.sheetView[0].showGridLines = True

    headers = [
        "№", "User ID", "ПІБ", "Username", "Посада (Role)", "Статус",
        "Місто", "Магазин", "Керівник", "Поточний блок", "Прогрес днів",
        "Дата реєстрації", "Остання активність"
    ]

    ws.append(headers)

    font_header = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    fill_header = PatternFill(start_color="0A2540", end_color="0A2540", fill_type="solid")
    align_header = Alignment(horizontal="center", vertical="center", wrap_text=True)

    thin_border = Border(
        left=Side(style="thin", color="D0D5DD"),
        right=Side(style="thin", color="D0D5DD"),
        top=Side(style="thin", color="D0D5DD"),
        bottom=Side(style="thin", color="D0D5DD")
    )

    for col_num in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_num)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = align_header
        cell.border = thin_border
    ws.row_dimensions[1].height = 28

    fill_alt = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

    for idx, u in enumerate(users, start=1):
        role = (u["role"] or "Не вказано").strip()
        status = (u["status"] or "Стажер").strip()
        total_d = days_map.get(role, 5)
        done_d = prog_map.get(u["user_id"], 0)
        prog_str = f"{done_d} / {total_d}" if role not in ("Developer", "Адміністратор", "Керівник", "Наглядач", "Територіал", "HR") else "—"
        
        mgr_str = mgr_map.get(u["manager_id"]) or u["manager_name"] or "Не призначено"
        uname_str = f"@{u['username']}" if u["username"] else "—"
        
        row_data = [
            idx,
            u["user_id"],
            u["full_name"] or "Не вказано",
            uname_str,
            role,
            status,
            u["city"] or "—",
            u["shop"] or "—",
            mgr_str,
            u["current_block"] if u["current_block"] is not None else "—",
            prog_str,
            str(u["first_seen"])[:16] if u["first_seen"] else "—",
            str(u["last_activity"])[:16] if u["last_activity"] else "—"
        ]
        ws.append(row_data)
        row_num = idx + 1
        ws.row_dimensions[row_num].height = 20
        is_even = (idx % 2 == 0)
        for col_idx in range(1, len(row_data) + 1):
            c = ws.cell(row=row_num, column=col_idx)
            c.font = Font(name="Calibri", size=10)
            c.border = thin_border
            if is_even:
                c.fill = fill_alt
            if col_idx in (1, 2, 10, 11, 12, 13):
                c.alignment = Alignment(horizontal="center", vertical="center")
            elif col_idx in (5, 6, 7, 8):
                c.alignment = Alignment(horizontal="center", vertical="center")
            else:
                c.alignment = Alignment(horizontal="left", vertical="center")

    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = 0
        for cell in col:
            val_str = str(cell.value or "")
            if len(val_str) > max_len:
                max_len = len(val_str)
        ws.column_dimensions[col_letter].width = max(max_len + 3, 10)

    excel_path = os.path.join(base_dir, "all_users_list.xlsx")
    wb.save(excel_path)
    now_str = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    print(f"✅ Файл Excel сформовано: {excel_path} (всього користувачів: {len(users)})")

    # Read token
    token = None
    env_path = os.path.join(base_dir, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.startswith("BOT_API_TOKEN="):
                    token = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

    if not token:
        print("❌ Не вдалося знайти BOT_API_TOKEN в .env")
        return

    recipients = [1001226587, 738460434]
    caption = f"📊 Повний список усіх зареєстрованих користувачів Bulka Education станом на {now_str}.\nВсього користувачів: {len(users)}."

    for chat_id in recipients:
        res = subprocess.run([
            "curl", "-s", "-F", f"chat_id={chat_id}",
            "-F", f"document=@{excel_path}",
            "-F", f"caption={caption}",
            f"https://api.telegram.org/bot{token}/sendDocument"
        ], capture_output=True, text=True)
        try:
            resp_json = json.loads(res.stdout)
            if resp_json.get("ok"):
                print(f"📤 Успішно надіслано в Telegram ID: {chat_id}")
            else:
                print(f"⚠️ Помилка відправки для {chat_id}: {resp_json.get('description')}")
        except Exception as e:
            print(f"⚠️ Помилка обробки відповіді для {chat_id}: {e}")

if __name__ == "__main__":
    main()
