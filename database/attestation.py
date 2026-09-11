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


def get_current_kyiv_datetime() -> datetime:
    tz = pytz.timezone(TIMEZONE)
    return datetime.now(tz)


async def init_attestation_db(db_path: str = DB_PATH) -> None:
    """Ініціалізує таблиці атестації в базі даних."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute('''
        CREATE TABLE IF NOT EXISTS attestation_waves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft', -- draft | active | completed
            created_by INTEGER NOT NULL,
            duration_minutes INTEGER NOT NULL DEFAULT 20,
            passing_score_pct INTEGER NOT NULL DEFAULT 80,
            deadline_date TEXT NOT NULL,           -- YYYY-MM-DD HH:MM:SS
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            closed_at TIMESTAMP
        )
        ''')

        await db.execute('''
        CREATE TABLE IF NOT EXISTS attestation_wave_shops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wave_id INTEGER NOT NULL,
            shop_name TEXT NOT NULL,
            FOREIGN KEY (wave_id) REFERENCES attestation_waves(id) ON DELETE CASCADE,
            UNIQUE(wave_id, shop_name)
        )
        ''')

        await db.execute('''
        CREATE TABLE IF NOT EXISTS attestation_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role_name TEXT NOT NULL,
            question_text TEXT NOT NULL,
            option_1 TEXT NOT NULL,
            option_2 TEXT NOT NULL,
            option_3 TEXT,
            option_4 TEXT,
            correct_option INTEGER NOT NULL,      -- 1..4
            points INTEGER NOT NULL DEFAULT 1,
            explanation TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        await db.execute('''
        CREATE TABLE IF NOT EXISTS attestation_participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wave_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            full_name TEXT,
            role_name TEXT NOT NULL,
            shop_name TEXT NOT NULL,
            is_manager INTEGER DEFAULT 0,         -- 1 керівник, 0 працівник
            notification_sent INTEGER DEFAULT 0,
            reminders_sent INTEGER DEFAULT 0,
            last_reminder_at TIMESTAMP,
            FOREIGN KEY (wave_id) REFERENCES attestation_waves(id) ON DELETE CASCADE,
            UNIQUE(wave_id, user_id)
        )
        ''')

        await db.execute('''
        CREATE TABLE IF NOT EXISTS attestation_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wave_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            role_name TEXT NOT NULL,
            shop_name TEXT NOT NULL,
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            duration_seconds INTEGER DEFAULT 0,
            score INTEGER DEFAULT 0,
            max_score INTEGER DEFAULT 0,
            score_pct REAL DEFAULT 0.0,
            status TEXT NOT NULL DEFAULT 'in_progress', -- in_progress | passed | failed
            answers_json TEXT,                         -- {question_id: selected_option}
            can_retake INTEGER DEFAULT 0,
            retake_granted_by INTEGER,
            retake_granted_at TIMESTAMP,
            FOREIGN KEY (wave_id) REFERENCES attestation_waves(id) ON DELETE CASCADE
        )
        ''')

        await db.commit()
    logger.info("Таблиці атестації успішно ініціалізовано.")


# -------------------------------------------------------------
# Керування питаннями
# -------------------------------------------------------------

async def save_questions_for_role(role_name: str, questions: List[Dict[str, Any]], db_path: str = DB_PATH) -> int:
    """
    Повністю оновлює банк питань для конкретної посади.
    Видаляє старі питання цієї посади та записує нові.
    """
    async with aiosqlite.connect(db_path) as db:
        await db.execute("DELETE FROM attestation_questions WHERE role_name = ?", (role_name,))
        inserted = 0
        for q in questions:
            await db.execute('''
            INSERT INTO attestation_questions 
            (role_name, question_text, option_1, option_2, option_3, option_4, correct_option, points, explanation)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                role_name,
                q.get("question_text", "").strip(),
                q.get("option_1", "").strip(),
                q.get("option_2", "").strip(),
                q.get("option_3", "").strip() if q.get("option_3") else None,
                q.get("option_4", "").strip() if q.get("option_4") else None,
                int(q.get("correct_option", 1)),
                int(q.get("points", 1)),
                q.get("explanation", "").strip() if q.get("explanation") else None
            ))
            inserted += 1
        await db.commit()
        return inserted


async def get_questions_for_role(role_name: str, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Повертає всі питання для вказаної посади."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM attestation_questions WHERE role_name = ? ORDER BY id ASC",
            (role_name,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def get_questions_count_by_role(db_path: str = DB_PATH) -> Dict[str, int]:
    """Повертає словник {role_name: count}."""
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT role_name, COUNT(*) FROM attestation_questions GROUP BY role_name"
        ) as cursor:
            rows = await cursor.fetchall()
            return {row[0]: row[1] for row in rows}


# -------------------------------------------------------------
# Керування хвилями атестації
# -------------------------------------------------------------

async def create_wave(
    title: str,
    created_by: int,
    duration_minutes: int,
    passing_score_pct: int,
    deadline_date: str,
    shops: List[str],
    db_path: str = DB_PATH
) -> int:
    """Створює нову хвилю атестації та повертає її ID."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute('''
        INSERT INTO attestation_waves (title, status, created_by, duration_minutes, passing_score_pct, deadline_date)
        VALUES (?, 'draft', ?, ?, ?, ?)
        ''', (title, created_by, duration_minutes, passing_score_pct, deadline_date))
        wave_id = cursor.lastrowid

        for shop in shops:
            await db.execute('''
            INSERT OR IGNORE INTO attestation_wave_shops (wave_id, shop_name)
            VALUES (?, ?)
            ''', (wave_id, shop.strip()))

        await db.commit()
        return wave_id


async def activate_wave(wave_id: int, db_path: str = DB_PATH) -> bool:
    """Переводить хвилю у статус active."""
    async with aiosqlite.connect(db_path) as db:
        # Перевіряємо чи немає вже іншої активної хвилі
        async with db.execute("SELECT id FROM attestation_waves WHERE status = 'active'") as cursor:
            active_row = await cursor.fetchone()
            if active_row and active_row[0] != wave_id:
                # Завершуємо попередню хвилю
                await db.execute(
                    "UPDATE attestation_waves SET status = 'completed', closed_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (active_row[0],)
                )

        await db.execute("UPDATE attestation_waves SET status = 'active' WHERE id = ?", (wave_id,))
        await db.commit()
        return True


async def close_wave(wave_id: int, db_path: str = DB_PATH) -> bool:
    """Завершує хвилю атестації."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE attestation_waves SET status = 'completed', closed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (wave_id,)
        )
        await db.commit()
        return True


async def get_active_wave(db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Повертає поточну активну хвилю або None."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM attestation_waves WHERE status = 'active'") as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            wave_dict = dict(row)

            # Перевіряємо дедлайн
            tz = pytz.timezone(TIMEZONE)
            now = datetime.now(tz)
            try:
                deadline = datetime.strptime(wave_dict["deadline_date"], "%Y-%m-%d %H:%M:%S")
                deadline = tz.localize(deadline) if deadline.tzinfo is None else deadline
                if now > deadline:
                    # Дедлайн вийшов — авто-закриття
                    await db.execute(
                        "UPDATE attestation_waves SET status = 'completed', closed_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (wave_dict["id"],)
                    )
                    await db.commit()
                    return None
            except Exception as e:
                logger.error(f"Помилка парсингу дедлайну хвилі {wave_dict['id']}: {e}")

            # Завантажуємо магазини
            async with db.execute(
                "SELECT shop_name FROM attestation_wave_shops WHERE wave_id = ?",
                (wave_dict["id"],)
            ) as s_cursor:
                s_rows = await s_cursor.fetchall()
                wave_dict["shops"] = [r[0] for r in s_rows]

            return wave_dict


async def get_wave_by_id(wave_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Повертає хвилю за ID разом зі списком магазинів."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM attestation_waves WHERE id = ?", (wave_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            wave_dict = dict(row)

            async with db.execute(
                "SELECT shop_name FROM attestation_wave_shops WHERE wave_id = ?",
                (wave_id,)
            ) as s_cursor:
                s_rows = await s_cursor.fetchall()
                wave_dict["shops"] = [r[0] for r in s_rows]

            return wave_dict


async def get_all_waves(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Повертає всі хвилі від нових до старих."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM attestation_waves ORDER BY id DESC") as cursor:
            rows = await cursor.fetchall()
            waves = []
            for r in rows:
                w = dict(r)
                async with db.execute(
                    "SELECT shop_name FROM attestation_wave_shops WHERE wave_id = ?",
                    (w["id"],)
                ) as s_cursor:
                    s_rows = await s_cursor.fetchall()
                    w["shops"] = [sr[0] for sr in s_rows]
                waves.append(w)
            return waves


# -------------------------------------------------------------
# Керування учасниками хвилі
# -------------------------------------------------------------

async def add_participants_batch(
    wave_id: int,
    participants: List[Dict[str, Any]],
    db_path: str = DB_PATH
) -> int:
    """Масово додає учасників до хвилі."""
    async with aiosqlite.connect(db_path) as db:
        added = 0
        for p in participants:
            await db.execute('''
            INSERT OR REPLACE INTO attestation_participants 
            (wave_id, user_id, full_name, role_name, shop_name, is_manager)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                wave_id,
                p["user_id"],
                p.get("full_name", ""),
                p["role_name"],
                p["shop_name"],
                1 if p.get("is_manager") else 0
            ))
            added += 1
        await db.commit()
        return added


async def get_wave_participants(wave_id: int, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Повертає всіх зареєстрованих учасників хвилі."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM attestation_participants WHERE wave_id = ? ORDER BY shop_name, role_name",
            (wave_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


# -------------------------------------------------------------
# Керування спробами та проходженням тесту
# -------------------------------------------------------------

async def get_user_latest_attempt(wave_id: int, user_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Повертає останню спробу користувача для даної хвилі."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('''
        SELECT * FROM attestation_attempts 
        WHERE wave_id = ? AND user_id = ?
        ORDER BY id DESC LIMIT 1
        ''', (wave_id, user_id)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def start_user_attempt(
    wave_id: int,
    user_id: int,
    role_name: str,
    shop_name: str,
    db_path: str = DB_PATH
) -> Dict[str, Any]:
    """
    Розпочинає спробу тестування. Фіксує started_at.
    Якщо спроба вже була і вона in_progress — повертає існуючу.
    Якщо вже завершена і can_retake == 0 — повертає завершену (не створює нову).
    """
    now_str = get_current_kyiv_time_str()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        # Шукаємо останню спробу
        async with db.execute('''
        SELECT * FROM attestation_attempts 
        WHERE wave_id = ? AND user_id = ? 
        ORDER BY id DESC LIMIT 1
        ''', (wave_id, user_id)) as cursor:
            last = await cursor.fetchone()

        if last:
            last_dict = dict(last)
            # Якщо спроба триває — повертаємо її
            if last_dict["status"] == "in_progress":
                return last_dict
            # Якщо завершена, але дозволено перездачу (can_retake == 1)
            if last_dict["can_retake"] == 1:
                # Знімаємо прапорець can_retake та створюємо нову спробу
                await db.execute(
                    "UPDATE attestation_attempts SET can_retake = 0 WHERE id = ?",
                    (last_dict["id"],)
                )
            else:
                # Перездача заборонена — повертаємо фінішовану спробу
                return last_dict

        # Створюємо нову спробу
        cursor = await db.execute('''
        INSERT INTO attestation_attempts 
        (wave_id, user_id, role_name, shop_name, started_at, status, answers_json)
        VALUES (?, ?, ?, ?, ?, 'in_progress', '{}')
        ''', (wave_id, user_id, role_name, shop_name, now_str))
        attempt_id = cursor.lastrowid
        await db.commit()

        async with db.execute("SELECT * FROM attestation_attempts WHERE id = ?", (attempt_id,)) as cur:
            row = await cur.fetchone()
            return dict(row)


async def submit_user_attempt(
    attempt_id: int,
    answers: Dict[str, int], # {question_id_str: selected_option_int}
    db_path: str = DB_PATH
) -> Dict[str, Any]:
    """
    Фіксує фінальні відповіді користувача, підраховує бали та визначає статус (passed / failed).
    """
    now = get_current_kyiv_datetime()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM attestation_attempts WHERE id = ?", (attempt_id,)) as cursor:
            attempt = await cursor.fetchone()
            if not attempt:
                raise ValueError(f"Attempt with id {attempt_id} not found")
            attempt_dict = dict(attempt)

        wave_id = attempt_dict["wave_id"]
        role_name = attempt_dict["role_name"]

        # Отримуємо параметри хвилі
        async with db.execute("SELECT passing_score_pct FROM attestation_waves WHERE id = ?", (wave_id,)) as w_cur:
            w_row = await w_cur.fetchone()
            passing_score_pct = w_row["passing_score_pct"] if w_row else 80

        # Отримуємо питання посади
        async with db.execute(
            "SELECT id, correct_option, points FROM attestation_questions WHERE role_name = ?",
            (role_name,)
        ) as q_cur:
            questions = await q_cur.fetchall()

        total_score = 0
        max_score = 0
        for q in questions:
            q_id = str(q["id"])
            q_points = q["points"]
            max_score += q_points
            user_answer = answers.get(q_id)
            if user_answer is not None and int(user_answer) == q["correct_option"]:
                total_score += q_points

        score_pct = round((total_score / max_score * 100.0), 1) if max_score > 0 else 0.0
        status = "passed" if score_pct >= passing_score_pct else "failed"

        # Розрахунок тривалості
        duration_seconds = 0
        if attempt_dict["started_at"]:
            try:
                start_dt = datetime.strptime(attempt_dict["started_at"], "%Y-%m-%d %H:%M:%S")
                tz = pytz.timezone(TIMEZONE)
                start_dt = tz.localize(start_dt) if start_dt.tzinfo is None else start_dt
                duration_seconds = int((now - start_dt).total_seconds())
            except Exception:
                duration_seconds = 0

        await db.execute('''
        UPDATE attestation_attempts 
        SET finished_at = ?, duration_seconds = ?, score = ?, max_score = ?, 
            score_pct = ?, status = ?, answers_json = ?
        WHERE id = ?
        ''', (
            now_str,
            duration_seconds,
            total_score,
            max_score,
            score_pct,
            status,
            json.dumps(answers),
            attempt_id
        ))
        await db.commit()

        async with db.execute("SELECT * FROM attestation_attempts WHERE id = ?", (attempt_id,)) as res_cur:
            final_row = await res_cur.fetchone()
            return dict(final_row)


async def allow_user_retake(wave_id: int, user_id: int, admin_id: int, db_path: str = DB_PATH) -> bool:
    """Дозволяє перездачу: позначає останню спробу can_retake = 1."""
    now_str = get_current_kyiv_time_str()
    async with aiosqlite.connect(db_path) as db:
        # Знаходимо останню спробу
        cursor = await db.execute('''
        UPDATE attestation_attempts 
        SET can_retake = 1, retake_granted_by = ?, retake_granted_at = ?
        WHERE id = (
            SELECT id FROM attestation_attempts 
            WHERE wave_id = ? AND user_id = ? 
            ORDER BY id DESC LIMIT 1
        )
        ''', (admin_id, now_str, wave_id, user_id))
        await db.commit()
        return cursor.rowcount > 0


# -------------------------------------------------------------
# Статистика та звіти
# -------------------------------------------------------------

async def get_wave_statistics(wave_id: int, db_path: str = DB_PATH) -> Dict[str, Any]:
    """Повертає зведену статистику хвилі атестації."""
    async with aiosqlite.connect(db_path) as db:
        # Всього учасників
        async with db.execute(
            "SELECT COUNT(*) FROM attestation_participants WHERE wave_id = ?",
            (wave_id,)
        ) as c1:
            total_participants = (await c1.fetchone())[0]

        # Завершені спроби (найсвіжіша спроба для кожного користувача)
        async with db.execute('''
        SELECT status, score_pct, shop_name, user_id FROM attestation_attempts
        WHERE wave_id = ? AND status IN ('passed', 'failed')
        GROUP BY user_id
        HAVING id = MAX(id)
        ''', (wave_id,)) as c2:
            completed_attempts = await c2.fetchall()

        completed_count = len(completed_attempts)
        passed_count = sum(1 for a in completed_attempts if a[0] == 'passed')
        failed_count = sum(1 for a in completed_attempts if a[0] == 'failed')
        avg_score = round(sum(a[1] for a in completed_attempts) / completed_count, 1) if completed_count > 0 else 0.0

        return {
            "total_participants": total_participants,
            "completed_count": completed_count,
            "passed_count": passed_count,
            "failed_count": failed_count,
            "avg_score": avg_score
        }


async def get_wave_shop_stats(wave_id: int, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Повертає статистику в розрізі магазинів."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        # Отримуємо всі магазини хвилі разом з id
        async with db.execute(
            "SELECT id, shop_name FROM attestation_wave_shops WHERE wave_id = ? ORDER BY shop_name",
            (wave_id,)
        ) as cur_shops:
            shops_rows = await cur_shops.fetchall()

        results = []
        for r in shops_rows:
            shop_id = r["id"]
            shop = r["shop_name"]
            # Учасники магазину
            async with db.execute(
                "SELECT COUNT(*) FROM attestation_participants WHERE wave_id = ? AND shop_name = ?",
                (wave_id, shop)
            ) as p_cur:
                total_shop_participants = (await p_cur.fetchone())[0]

            # Останні спроби працівників цього магазину
            async with db.execute('''
            SELECT status, score_pct FROM attestation_attempts
            WHERE wave_id = ? AND shop_name = ? AND status IN ('passed', 'failed')
            GROUP BY user_id
            HAVING id = MAX(id)
            ''', (wave_id, shop)) as a_cur:
                attempts = await a_cur.fetchall()

            completed = len(attempts)
            passed = sum(1 for a in attempts if a[0] == 'passed')
            avg_pct = round(sum(a[1] for a in attempts) / completed, 1) if completed > 0 else 0.0

            results.append({
                "shop_id": shop_id,
                "shop_name": shop,
                "total_participants": total_shop_participants,
                "completed": completed,
                "passed": passed,
                "avg_score_pct": avg_pct
            })

        return results


async def get_wave_shop_by_id(wave_shop_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Повертає магазин хвилі за його ID."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, wave_id, shop_name FROM attestation_wave_shops WHERE id = ?",
            (wave_shop_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None



async def get_shop_members_details(wave_id: int, shop_name: str, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """
    Повертає деталізований список учасників магазину з їхніми останніми результатами атестації.
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('''
        SELECT p.user_id, p.full_name, p.role_name, p.shop_name, p.is_manager,
               a.status AS attempt_status, a.score, a.max_score, a.score_pct,
               a.finished_at, a.duration_seconds, a.can_retake
        FROM attestation_participants p
        LEFT JOIN (
            SELECT * FROM attestation_attempts
            WHERE wave_id = ?
            GROUP BY user_id
            HAVING id = MAX(id)
        ) a ON p.user_id = a.user_id
        WHERE p.wave_id = ? AND p.shop_name = ?
        ORDER BY p.is_manager DESC, p.full_name ASC
        ''', (wave_id, wave_id, shop_name)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
