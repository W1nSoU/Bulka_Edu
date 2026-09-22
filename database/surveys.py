from __future__ import annotations
import aiosqlite
import json
import logging
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
import pytz
from bot.config import TIMEZONE
from . import DB_PATH

logger = logging.getLogger(__name__)


def get_current_kyiv_time_str() -> str:
    """Повертає поточний час у часовому поясі Europe/Kyiv у форматі YYYY-MM-DD HH:MM:SS."""
    tz = pytz.timezone(TIMEZONE)
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")


async def init_surveys_db(db_path: str = DB_PATH) -> None:
    """Ініціалізує таблиці опитувань у базі даних."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute('''
        CREATE TABLE IF NOT EXISTS surveys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            raw_template TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            target_roles TEXT NOT NULL, -- JSON-масив: ["Працівник", "Стажер", ...]
            target_city TEXT,           -- NULL для "Усі міста" або назва міста
            status TEXT NOT NULL DEFAULT 'draft', -- draft | broadcasting | active | closed
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            closed_at TIMESTAMP,
            launched_at TIMESTAMP,
            total_recipients INTEGER DEFAULT 0
        )
        ''')

        await db.execute('''
        CREATE TABLE IF NOT EXISTS survey_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            survey_id INTEGER NOT NULL,
            question_idx INTEGER NOT NULL,
            text TEXT NOT NULL,
            question_type TEXT NOT NULL,          -- choice | text
            options_json TEXT,                    -- JSON-масив: ["а. ...", "б. ..."]
            FOREIGN KEY (survey_id) REFERENCES surveys(id) ON DELETE CASCADE
        )
        ''')

        await db.execute('''
        CREATE TABLE IF NOT EXISTS survey_recipients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            survey_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            wave_number INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'pending', -- pending | sent | completed | failed
            current_question_idx INTEGER NOT NULL DEFAULT 1,
            reminders_sent INTEGER NOT NULL DEFAULT 0,
            last_reminder_at TIMESTAMP,
            next_reminder_at TIMESTAMP,
            sent_at TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY (survey_id) REFERENCES surveys(id) ON DELETE CASCADE,
            UNIQUE(survey_id, user_id)
        )
        ''')

        await db.execute('''
        CREATE TABLE IF NOT EXISTS survey_answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            survey_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            question_idx INTEGER NOT NULL,
            answer_text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (survey_id) REFERENCES surveys(id) ON DELETE CASCADE,
            UNIQUE(survey_id, user_id, question_idx)
        )
        ''')

        # Міграція колонок таблиці surveys
        cursor = await db.execute("PRAGMA table_info(surveys)")
        survey_cols = [row[1] for row in await cursor.fetchall()]
        if "launched_at" not in survey_cols:
            await db.execute("ALTER TABLE surveys ADD COLUMN launched_at TIMESTAMP")
        if "total_recipients" not in survey_cols:
            await db.execute("ALTER TABLE surveys ADD COLUMN total_recipients INTEGER DEFAULT 0")

        # Міграція колонок survey_recipients (current_question_idx / current_q_idx та додаткові)
        cursor = await db.execute("PRAGMA table_info(survey_recipients)")
        rec_cols = [row[1] for row in await cursor.fetchall()]
        if "current_question_idx" not in rec_cols:
            await db.execute("ALTER TABLE survey_recipients ADD COLUMN current_question_idx INTEGER NOT NULL DEFAULT 1")
            if "current_q_idx" in rec_cols:
                await db.execute("UPDATE survey_recipients SET current_question_idx = COALESCE(current_q_idx, 1)")
        if "current_q_idx" not in rec_cols:
            await db.execute("ALTER TABLE survey_recipients ADD COLUMN current_q_idx INTEGER NOT NULL DEFAULT 1")
            if "current_question_idx" in rec_cols:
                await db.execute("UPDATE survey_recipients SET current_q_idx = COALESCE(current_question_idx, 1)")

        for col_name, col_def in [
            ("wave_number", "INTEGER NOT NULL DEFAULT 1"),
            ("reminders_sent", "INTEGER NOT NULL DEFAULT 0"),
            ("last_reminder_at", "TIMESTAMP"),
            ("next_reminder_at", "TIMESTAMP"),
            ("sent_at", "TIMESTAMP"),
            ("completed_at", "TIMESTAMP"),
        ]:
            if col_name not in rec_cols:
                await db.execute(f"ALTER TABLE survey_recipients ADD COLUMN {col_name} {col_def}")

        await db.commit()


async def create_survey(
    title: str,
    raw_template: Optional[str] = None,
    created_by: int = 0,
    target_roles: Optional[List[str]] = None,
    target_city: Optional[str] = None,
    template_text: Optional[str] = None,
    questions: Optional[List[Any]] = None,
    recipient_uids: Optional[List[int]] = None,
    db_path: str = DB_PATH
) -> int:
    """Створює нове опитування в БД та повертає його ID. Опціонально додає питання та реципієнтів."""
    final_template = template_text if template_text is not None else raw_template
    target_roles = target_roles or []
    now_str = get_current_kyiv_time_str()
    async with aiosqlite.connect(db_path) as db:
        roles_json = json.dumps(target_roles, ensure_ascii=False)
        cursor = await db.execute(
            """
            INSERT INTO surveys (title, raw_template, created_by, target_roles, target_city, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'draft', ?)
            """,
            (title, final_template, created_by, roles_json, target_city, now_str)
        )
        survey_id = cursor.lastrowid
        await db.commit()

    if questions:
        for q in questions:
            q_idx = q["question_idx"] if hasattr(q, "__getitem__") else getattr(q, "question_idx")
            q_text = q["text"] if hasattr(q, "__getitem__") else getattr(q, "text")
            q_type = q["question_type"] if hasattr(q, "__getitem__") else getattr(q, "question_type")
            q_opts = q["options"] if hasattr(q, "__getitem__") else getattr(q, "options")
            await add_survey_question(
                survey_id=survey_id,
                question_idx=q_idx,
                text=q_text,
                question_type=q_type,
                options=q_opts,
                db_path=db_path
            )

    if recipient_uids:
        await add_survey_recipients(survey_id, recipient_uids, db_path=db_path)

    return survey_id


async def add_survey_question(
    survey_id: int,
    question_idx: int,
    text: str,
    question_type: str,
    options: Optional[List[str]] = None,
    db_path: str = DB_PATH
) -> None:
    """Додає питання до опитування."""
    async with aiosqlite.connect(db_path) as db:
        options_json = json.dumps(options, ensure_ascii=False) if options else None
        await db.execute(
            """
            INSERT INTO survey_questions (survey_id, question_idx, text, question_type, options_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(survey_id, question_idx) DO UPDATE SET
                text=excluded.text,
                question_type=excluded.question_type,
                options_json=excluded.options_json
            """,
            (survey_id, question_idx, text, question_type, options_json)
        )
        await db.commit()


async def get_survey_by_id(survey_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Отримує дані опитування за його ID."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM surveys WHERE id = ?", (survey_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        res = dict(row)
        try:
            parsed_roles = json.loads(res.get("target_roles") or "[]")
            if isinstance(parsed_roles, list):
                res["target_roles"] = parsed_roles
            else:
                res["target_roles"] = [str(parsed_roles)]
        except Exception:
            res["target_roles"] = []
        res["target_roles_list"] = res["target_roles"]
        return res


async def get_matching_survey_recipients(
    target_roles: List[str],
    target_city: Optional[str] = None,
    db_path: str = DB_PATH
) -> List[int]:
    """
    Повертає список Telegram user_id діючих користувачів, які підпадають під умови опитування:
    - target_roles: підмножина ['Працівник', 'Стажер', 'Керівник', 'Наглядач']
    - target_city: назва міста або None / 'ALL' (для всіх міст)
    """
    matched_uids = set()
    city_filter = bool(target_city and str(target_city).strip().lower() not in ("all", "усі міста", "всі міста", "none", ""))

    from database.users import MANAGEMENT_ROLES
    management_tuple = tuple(MANAGEMENT_ROLES)
    mgmt_placeholders = ",".join("?" for _ in management_tuple)

    async with aiosqlite.connect(db_path) as db:
        # 1. Працівники: status == 'Працівник'
        if "Працівник" in target_roles:
            query = """
                SELECT user_id FROM users
                WHERE status = 'Працівник'
                  AND (role IS NULL OR role NOT IN ('Адміністратор', 'Developer', 'Dev', 'Наглядач'))
            """
            params: List[Any] = []
            if city_filter:
                query += " AND city = ?"
                params.append(target_city)
            cursor = await db.execute(query, tuple(params))
            for row in await cursor.fetchall():
                matched_uids.add(row[0])

        # 2. Стажери: status != 'Працівник' and role not in MANAGEMENT_ROLES
        if "Стажер" in target_roles:
            query = f"""
                SELECT user_id FROM users
                WHERE (status IS NULL OR status != 'Працівник')
                  AND (role IS NULL OR role NOT IN ({mgmt_placeholders}))
            """
            params = list(management_tuple)
            if city_filter:
                query += " AND city = ?"
                params.append(target_city)
            cursor = await db.execute(query, tuple(params))
            for row in await cursor.fetchall():
                matched_uids.add(row[0])

        # 3. Керівники: role IN ('Керівник', 'Керівник Стажер') або в managers
        if "Керівник" in target_roles:
            query = """
                SELECT user_id FROM users
                WHERE role IN ('Керівник', 'Керівник Стажер')
            """
            params = []
            if city_filter:
                query += " AND city = ?"
                params.append(target_city)
            cursor = await db.execute(query, tuple(params))
            for row in await cursor.fetchall():
                matched_uids.add(row[0])

            from database.managers import MANAGERS_DB_PATH
            try:
                async with aiosqlite.connect(MANAGERS_DB_PATH) as m_db:
                    m_query = "SELECT uid FROM managers WHERE process IN ('Керівник', 'Керівник Стажер') AND (status = 'active' OR status IS NULL)"
                    m_params: List[Any] = []
                    if city_filter:
                        m_query += " AND city = ?"
                        m_params.append(target_city)
                    m_cursor = await m_db.execute(m_query, tuple(m_params))
                    for row in await m_cursor.fetchall():
                        if row[0]:
                            matched_uids.add(row[0])
            except Exception:
                pass

        # 4. Наглядачі: managers.db WHERE process = 'Наглядач' або users WHERE role = 'Наглядач'
        if "Наглядач" in target_roles:
            query = "SELECT user_id FROM users WHERE role = 'Наглядач'"
            params = []
            if city_filter:
                query += " AND city = ?"
                params.append(target_city)
            cursor = await db.execute(query, tuple(params))
            for row in await cursor.fetchall():
                matched_uids.add(row[0])

            from database.managers import MANAGERS_DB_PATH
            try:
                async with aiosqlite.connect(MANAGERS_DB_PATH) as m_db:
                    query = "SELECT uid FROM managers WHERE process = 'Наглядач' AND (status = 'active' OR status IS NULL)"
                    params = []
                    if city_filter:
                        query += " AND city = ?"
                        params.append(target_city)
                    cursor = await m_db.execute(query, tuple(params))
                    for row in await cursor.fetchall():
                        if row[0]:
                            matched_uids.add(row[0])
            except Exception:
                pass

    return list(matched_uids)


async def get_survey_questions(survey_id: int, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Повертає всі питання опитування, відсортовані за індексом."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM survey_questions WHERE survey_id = ? ORDER BY question_idx ASC",
            (survey_id,)
        )
        rows = await cursor.fetchall()
        result = []
        for r in rows:
            q = dict(r)
            try:
                q["options"] = json.loads(q.get("options_json") or "[]") if q.get("options_json") else []
            except Exception:
                q["options"] = []
            result.append(q)
        return result


async def get_surveys_list(page: int = 0, per_page: int = 6, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Повертає список опитувань із пагінацією (найновіші першими)."""
    offset = page * per_page
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT s.*, 
                   COUNT(CASE WHEN r.status = 'completed' THEN 1 END) as completed_count,
                   COUNT(r.id) as assigned_count
            FROM surveys s
            LEFT JOIN survey_recipients r ON s.id = r.survey_id
            GROUP BY s.id
            ORDER BY s.id DESC
            LIMIT ? OFFSET ?
            """,
            (per_page, offset)
        )
        rows = await cursor.fetchall()
        result = []
        for r in rows:
            item = dict(r)
            try:
                parsed_roles = json.loads(item.get("target_roles") or "[]")
                if isinstance(parsed_roles, list):
                    item["target_roles"] = parsed_roles
                else:
                    item["target_roles"] = [str(parsed_roles)]
            except Exception:
                item["target_roles"] = []
            item["target_roles_list"] = item["target_roles"]
            result.append(item)
        return result


async def get_surveys_count(db_path: str = DB_PATH) -> int:
    """Повертає загальну кількість створених опитувань."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM surveys")
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_all_surveys(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Повертає повний список опитувань."""
    return await get_surveys_list(page=0, per_page=1000, db_path=db_path)


async def update_survey_status(survey_id: int, status: str, db_path: str = DB_PATH) -> None:
    """Оновлює статус опитування (наприклад, broadcasting, active, closed)."""
    tz = pytz.timezone(TIMEZONE)
    now_str = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(db_path) as db:
        if status == 'broadcasting' or status == 'active':
            await db.execute(
                "UPDATE surveys SET status = ?, launched_at = COALESCE(launched_at, ?) WHERE id = ?",
                (status, now_str, survey_id)
            )
        elif status == 'closed':
            await db.execute(
                "UPDATE surveys SET status = ?, closed_at = ? WHERE id = ?",
                (status, now_str, survey_id)
            )
        else:
            await db.execute("UPDATE surveys SET status = ? WHERE id = ?", (status, survey_id))
        await db.commit()


async def add_survey_recipients(
    survey_id: int,
    user_ids: List[int],
    wave_size: int = 50,
    db_path: str = DB_PATH
) -> int:
    """
    Додає отримувачів до опитування, автоматично розбиваючи на хвилі по wave_size осіб.
    Повертає кількість доданих отримувачів.
    """
    if not user_ids:
        return 0

    async with aiosqlite.connect(db_path) as db:
        # Видаляємо дублікати та існуючі записи для цього опитування
        cursor = await db.execute("SELECT user_id FROM survey_recipients WHERE survey_id = ?", (survey_id,))
        existing = {row[0] for row in await cursor.fetchall()}
        
        to_add = [uid for uid in user_ids if uid not in existing]
        if not to_add:
            return 0

        # Поточний максимум хвиль
        cursor = await db.execute("SELECT MAX(wave_number) FROM survey_recipients WHERE survey_id = ?", (survey_id,))
        row = await cursor.fetchone()
        current_max_wave = row[0] or 0

        records = []
        for i, uid in enumerate(to_add):
            wave_num = current_max_wave + (i // wave_size) + 1
            records.append((survey_id, uid, wave_num, 'pending'))

        await db.executemany(
            """
            INSERT INTO survey_recipients (survey_id, user_id, wave_number, status)
            VALUES (?, ?, ?, ?)
            """,
            records
        )
        # Оновлюємо загальну кількість
        await db.execute(
            "UPDATE surveys SET total_recipients = (SELECT COUNT(*) FROM survey_recipients WHERE survey_id = ?) WHERE id = ?",
            (survey_id, survey_id)
        )
        await db.commit()
        return len(records)


async def get_pending_wave_recipients(survey_id: int, wave_number: int, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Отримує отримувачів заданої хвилі зі статусом 'pending'."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT r.*, u.full_name, u.username, u.role, u.city, u.shop
            FROM survey_recipients r
            LEFT JOIN users u ON r.user_id = u.user_id
            WHERE r.survey_id = ? AND r.wave_number = ? AND r.status = 'pending'
            ORDER BY r.id ASC
            """,
            (survey_id, wave_number)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_max_wave_for_survey(survey_id: int, db_path: str = DB_PATH) -> int:
    """Повертає максимальний номер хвилі для опитування."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT MAX(wave_number) FROM survey_recipients WHERE survey_id = ?", (survey_id,))
        row = await cursor.fetchone()
        return row[0] if (row and row[0]) else 1


async def mark_survey_recipient_sent(
    recipient_id: int,
    next_reminder_at: Optional[datetime] = None,
    db_path: str = DB_PATH
) -> None:
    """Позначає отримувача як такого, що отримав опитування ('sent')."""
    now_str = get_current_kyiv_time_str()
    async with aiosqlite.connect(db_path) as db:
        next_rem_str = next_reminder_at.strftime("%Y-%m-%d %H:%M:%S") if next_reminder_at else None
        await db.execute(
            """
            UPDATE survey_recipients
            SET status = 'sent', sent_at = ?, next_reminder_at = ?
            WHERE id = ?
            """,
            (now_str, next_rem_str, recipient_id)
        )
        await db.commit()


async def mark_survey_recipient_failed(recipient_id: int, db_path: str = DB_PATH) -> None:
    """Позначає спробу відправки як невдалу."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute("UPDATE survey_recipients SET status = 'failed' WHERE id = ?", (recipient_id,))
        await db.commit()


async def get_survey_recipient(survey_id: int, user_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Отримує статус респондента в опитуванні."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM survey_recipients WHERE survey_id = ? AND user_id = ?",
            (survey_id, user_id)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def update_survey_recipient_progress(survey_id: int, user_id: int, question_idx: int, db_path: str = DB_PATH) -> None:
    """Оновлює поточне запитання респондента."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("PRAGMA table_info(survey_recipients)")
        columns = [row[1] for row in await cursor.fetchall()]
        sets = ["status = CASE WHEN status = 'pending' THEN 'sent' ELSE status END"]
        params = []
        if "current_question_idx" in columns:
            sets.append("current_question_idx = ?")
            params.append(question_idx)
        if "current_q_idx" in columns:
            sets.append("current_q_idx = ?")
            params.append(question_idx)
        params.extend([survey_id, user_id])
        set_clause = ", ".join(sets)
        await db.execute(
            f"""
            UPDATE survey_recipients
            SET {set_clause}
            WHERE survey_id = ? AND user_id = ?
            """,
            tuple(params)
        )
        await db.commit()


async def mark_survey_recipient_completed(survey_id: int, user_id: int, db_path: str = DB_PATH) -> None:
    """Позначає, що користувач повністю завершив опитування."""
    now_str = get_current_kyiv_time_str()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            UPDATE survey_recipients
            SET status = 'completed', completed_at = ?, next_reminder_at = NULL
            WHERE survey_id = ? AND user_id = ?
            """,
            (now_str, survey_id, user_id)
        )
        await db.commit()


async def save_survey_answer(
    survey_id: int,
    user_id: int,
    question_idx: int,
    answer_text: str,
    db_path: str = DB_PATH
) -> None:
    """Зберігає відповідь користувача на конкретне питання."""
    now_str = get_current_kyiv_time_str()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO survey_answers (survey_id, user_id, question_idx, answer_text, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(survey_id, user_id, question_idx) DO UPDATE SET
                answer_text=excluded.answer_text,
                created_at=excluded.created_at
            """,
            (survey_id, user_id, question_idx, answer_text, now_str)
        )
        await db.commit()


async def get_survey_answers_for_user(survey_id: int, user_id: int, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Повертає всі відповіді конкретного користувача на опитування."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM survey_answers WHERE survey_id = ? AND user_id = ? ORDER BY question_idx ASC",
            (survey_id, user_id)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_survey_stats(survey_id: int, db_path: str = DB_PATH) -> Dict[str, Any]:
    """Повертає зведену статистику опитування (всього, надіслано, в процесі, завершено, відсоток)."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            SELECT 
                COUNT(*) as total,
                COUNT(CASE WHEN status IN ('sent', 'in_progress', 'completed') THEN 1 END) as delivered,
                COUNT(CASE WHEN status = 'in_progress' THEN 1 END) as in_progress,
                COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed,
                COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed
            FROM survey_recipients
            WHERE survey_id = ?
            """,
            (survey_id,)
        )
        row = await cursor.fetchone()
        total = row[0] if row else 0
        delivered = row[1] if row else 0
        in_progress = row[2] if row else 0
        completed = row[3] if row else 0
        failed = row[4] if row else 0
        percent = (completed / delivered * 100.0) if delivered > 0 else 0.0
        return {
            "total": total,
            "delivered": delivered,
            "in_progress": in_progress,
            "completed": completed,
            "failed": failed,
            "completion_percent": round(percent, 1)
        }


async def get_survey_summary_stats(survey_id: int, db_path: str = DB_PATH) -> Dict[str, Any]:
    """Зведена статистика опитування для інтерфейсу адміністратора."""
    base_stats = await get_survey_stats(survey_id, db_path)
    total = base_stats["total"]
    completed = base_stats["completed"]
    in_progress = base_stats["in_progress"]
    delivered = base_stats["delivered"]
    pending = max(0, total - completed - in_progress)
    return {
        "total_recipients": total,
        "completed_count": completed,
        "in_progress_count": in_progress,
        "pending_count": pending,
        "delivered_count": delivered,
        "failed_count": base_stats["failed"],
        "completion_percent": base_stats["completion_percent"]
    }


async def get_survey_recipients_by_wave(survey_id: int, wave_number: int, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Отримує список реципієнтів для вказаної хвилі."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM survey_recipients WHERE survey_id = ? AND wave_number = ?",
            (survey_id, wave_number)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_survey_question_stats(survey_id: int, question_idx: int, db_path: str = DB_PATH) -> Dict[str, int]:
    """Повертає кількість відповідей за кожним варіантом для конкретного питання."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            SELECT answer_text, COUNT(*) as cnt
            FROM survey_answers
            WHERE survey_id = ? AND question_idx = ?
            GROUP BY answer_text
            """,
            (survey_id, question_idx)
        )
        rows = await cursor.fetchall()
        res = {row[0]: row[1] for row in rows}

        q_cursor = await db.execute(
            "SELECT options_json FROM survey_questions WHERE survey_id = ? AND question_idx = ?",
            (survey_id, question_idx)
        )
        q_row = await q_cursor.fetchone()
        if q_row and q_row[0]:
            try:
                opts = json.loads(q_row[0])
                for opt in opts:
                    if opt not in res:
                        res[opt] = 0
            except Exception:
                pass
        return res


async def get_survey_detailed_results(survey_id: int, db_path: str = DB_PATH) -> Dict[str, Any]:
    """
    Повертає деталізовані дані для побудови XLSX-звіту:
    - survey: інформація про опитування
    - questions: список питань з варіантами
    - question_stats: розподіл відповідей (кількість і %) для кожного питання
    - shop_data: словник {shop_name: [список відповідей співробітників]}
    """
    survey = await get_survey_by_id(survey_id, db_path)
    questions = await get_survey_questions(survey_id, db_path)

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        # 1. Отримуємо всі відповіді разом із даними користувача
        cursor = await db.execute(
            """
            SELECT a.question_idx, a.answer_text, a.user_id,
                   u.full_name, u.role, u.shop, u.city,
                   r.completed_at
            FROM survey_answers a
            JOIN survey_recipients r ON a.survey_id = r.survey_id AND a.user_id = r.user_id
            LEFT JOIN users u ON a.user_id = u.user_id
            WHERE a.survey_id = ?
            ORDER BY u.shop ASC, u.full_name ASC, a.question_idx ASC
            """,
            (survey_id,)
        )
        all_answers = [dict(r) for r in await cursor.fetchall()]

        # 2. Розрахунок статистики по питаннях
        q_stats: Dict[int, Dict[str, Any]] = {}
        for q in questions:
            q_idx = q["question_idx"]
            q_type = q["question_type"]
            options = q.get("options") or []
            
            q_answers = [a["answer_text"] for a in all_answers if a["question_idx"] == q_idx]
            total_q_ans = len(q_answers)
            
            opt_counts: Dict[str, int] = {}
            if q_type == 'choice':
                for opt in options:
                    opt_counts[opt] = 0
                for ans in q_answers:
                    opt_counts[ans] = opt_counts.get(ans, 0) + 1
            
            opt_percentages: Dict[str, float] = {}
            for opt, cnt in opt_counts.items():
                pct = round((cnt / total_q_ans * 100.0), 1) if total_q_ans > 0 else 0.0
                opt_percentages[opt] = pct

            q_stats[q_idx] = {
                "question_text": q["text"],
                "question_type": q_type,
                "options": options,
                "total_answers": total_q_ans,
                "option_counts": opt_counts,
                "option_percentages": opt_percentages,
                "raw_text_answers": q_answers if q_type == 'text' else []
            }

        # 3. Групування за магазинами
        # Словник: shop -> user_id -> {full_name, role, shop, completed_at, answers: {q_idx: answer_text}}
        shops_dict: Dict[str, Dict[int, Dict[str, Any]]] = {}
        for a in all_answers:
            shop_name = a.get("shop") or "Не вказано"
            uid = a["user_id"]
            if shop_name not in shops_dict:
                shops_dict[shop_name] = {}
            if uid not in shops_dict[shop_name]:
                shops_dict[shop_name][uid] = {
                    "user_id": uid,
                    "full_name": a.get("full_name") or f"Користувач {uid}",
                    "role": a.get("role") or "Працівник",
                    "shop": shop_name,
                    "city": a.get("city") or "",
                    "completed_at": a.get("completed_at") or "",
                    "answers": {}
                }
            shops_dict[shop_name][uid]["answers"][a["question_idx"]] = a["answer_text"]

        # Перетворюємо на списки
        shops_formatted: Dict[str, List[Dict[str, Any]]] = {}
        for shop_name, users_map in shops_dict.items():
            shops_formatted[shop_name] = list(users_map.values())

        return {
            "survey": survey,
            "questions": questions,
            "question_stats": q_stats,
            "shops": shops_formatted,
            "total_respondents": len({a["user_id"] for a in all_answers})
        }


async def get_due_survey_reminders(now_dt: Optional[datetime] = None, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """
    Повертає отримувачів, яким час надіслати нагадування:
    - survey active/broadcasting
    - survey launched < 72 hours ago
    - recipient status in ('sent', 'in_progress')
    - reminders_sent < 3
    - next_reminder_at <= now
    """
    tz = pytz.timezone(TIMEZONE)
    current_time = (now_dt.astimezone(tz) if (now_dt and now_dt.tzinfo) else tz.localize(now_dt)) if now_dt else datetime.now(tz)
    now_str = current_time.strftime("%Y-%m-%d %H:%M:%S")
    cutoff_72h_str = (current_time - timedelta(hours=72)).strftime("%Y-%m-%d %H:%M:%S")

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT r.*, s.title as survey_title, s.launched_at, u.full_name, u.username
            FROM survey_recipients r
            JOIN surveys s ON r.survey_id = s.id
            LEFT JOIN users u ON r.user_id = u.user_id
            WHERE s.status IN ('active', 'broadcasting')
              AND s.launched_at >= ?
              AND r.status IN ('sent', 'in_progress')
              AND r.reminders_sent < 3
              AND r.next_reminder_at IS NOT NULL
              AND r.next_reminder_at <= ?
            ORDER BY r.next_reminder_at ASC
            LIMIT 50
            """,
            (cutoff_72h_str, now_str)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]



async def record_survey_reminder_sent(
    recipient_id: int,
    next_reminder_at: Optional[datetime] = None,
    db_path: str = DB_PATH
) -> None:
    """Фіксує факт відправки нагадування та призначає час наступного нагадування (або NULL якщо ліміт 3)."""
    now_str = get_current_kyiv_time_str()
    async with aiosqlite.connect(db_path) as db:
        next_rem_str = next_reminder_at.strftime("%Y-%m-%d %H:%M:%S") if next_reminder_at else None
        await db.execute(
            """
            UPDATE survey_recipients
            SET reminders_sent = reminders_sent + 1,
                last_reminder_at = ?,
                next_reminder_at = ?
            WHERE id = ?
            """,
            (now_str, next_rem_str, recipient_id)
        )
        await db.commit()
