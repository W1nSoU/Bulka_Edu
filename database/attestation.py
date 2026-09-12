from __future__ import annotations
import aiosqlite
import json
import logging
import random
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
            target_type TEXT NOT NULL DEFAULT 'staff', -- staff | managers
            status TEXT NOT NULL DEFAULT 'draft',      -- draft | active | completed
            created_by INTEGER NOT NULL,
            duration_minutes INTEGER NOT NULL DEFAULT 20,
            passing_score_pct INTEGER NOT NULL DEFAULT 80,
            deadline_date TEXT NOT NULL,               -- YYYY-MM-DD HH:MM:SS
            questions_count INTEGER NOT NULL DEFAULT 10,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            closed_at TIMESTAMP
        )
        ''')

        await db.execute('''
        CREATE TABLE IF NOT EXISTS attestation_wave_shops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wave_id INTEGER NOT NULL,
            shop_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',     -- active | closed
            started_at TIMESTAMP,
            closed_at TIMESTAMP,
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
            correct_option INTEGER NOT NULL,          -- 1..4
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
            is_manager INTEGER DEFAULT 0,             -- 1 керівник, 0 працівник
            status TEXT NOT NULL DEFAULT 'pending',   -- pending | in_progress | passed | failed | timeout
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
            expires_at TIMESTAMP,
            finished_at TIMESTAMP,
            duration_seconds INTEGER DEFAULT 0,
            questions_order_json TEXT,                 -- [q_id1, q_id2, ...]
            options_order_json TEXT,                   -- {q_id: [opt_idx1, opt_idx2, ...]}
            current_question_index INTEGER DEFAULT 0,  -- 0..N-1
            score INTEGER DEFAULT 0,
            max_score INTEGER DEFAULT 0,
            score_pct REAL DEFAULT 0.0,
            status TEXT NOT NULL DEFAULT 'in_progress', -- in_progress | passed | failed | timeout
            answers_json TEXT DEFAULT '{}',            -- {question_id: selected_option}
            can_retake INTEGER DEFAULT 0,
            retake_granted_by INTEGER,
            retake_granted_at TIMESTAMP,
            FOREIGN KEY (wave_id) REFERENCES attestation_waves(id) ON DELETE CASCADE
        )
        ''')

        # Безпечні міграції колонок (якщо таблиці вже існували)
        migrations = [
            ("attestation_waves", "target_type", "TEXT NOT NULL DEFAULT 'staff'"),
            ("attestation_waves", "questions_count", "INTEGER NOT NULL DEFAULT 10"),
            ("attestation_wave_shops", "status", "TEXT NOT NULL DEFAULT 'active'"),
            ("attestation_wave_shops", "started_at", "TIMESTAMP"),
            ("attestation_wave_shops", "closed_at", "TIMESTAMP"),
            ("attestation_participants", "status", "TEXT NOT NULL DEFAULT 'pending'"),
            ("attestation_attempts", "expires_at", "TIMESTAMP"),
            ("attestation_attempts", "questions_order_json", "TEXT"),
            ("attestation_attempts", "options_order_json", "TEXT"),
            ("attestation_attempts", "current_question_index", "INTEGER DEFAULT 0"),
        ]
        for table, col, col_type in migrations:
            try:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
            except Exception:
                pass

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
    target_type: str = 'staff',
    questions_count: int = 10,
    db_path: str = DB_PATH
) -> int:
    """Створює нову хвилю атестації та повертає її ID."""
    now_str = get_current_kyiv_time_str()
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute('''
        INSERT INTO attestation_waves 
        (title, target_type, status, created_by, duration_minutes, passing_score_pct, deadline_date, questions_count)
        VALUES (?, ?, 'draft', ?, ?, ?, ?, ?)
        ''', (title, target_type, created_by, duration_minutes, passing_score_pct, deadline_date, questions_count))
        wave_id = cursor.lastrowid

        for shop in shops:
            await db.execute('''
            INSERT OR IGNORE INTO attestation_wave_shops (wave_id, shop_name, status, started_at)
            VALUES (?, ?, 'active', ?)
            ''', (wave_id, shop.strip(), now_str))

        await db.commit()
        return wave_id


async def add_shop_to_active_wave(wave_id: int, shop_name: str, db_path: str = DB_PATH) -> bool:
    """Підключає новий магазин до активної хвилі."""
    now_str = get_current_kyiv_time_str()
    async with aiosqlite.connect(db_path) as db:
        # Перевіряємо чи магазин вже додано
        async with db.execute(
            "SELECT id, status FROM attestation_wave_shops WHERE wave_id = ? AND shop_name = ?",
            (wave_id, shop_name)
        ) as cur:
            row = await cur.fetchone()
            if row:
                # Якщо був закритий — відкриваємо знову
                await db.execute(
                    "UPDATE attestation_wave_shops SET status = 'active', started_at = ?, closed_at = NULL WHERE id = ?",
                    (now_str, row[0])
                )
            else:
                await db.execute('''
                INSERT INTO attestation_wave_shops (wave_id, shop_name, status, started_at)
                VALUES (?, ?, 'active', ?)
                ''', (wave_id, shop_name, now_str))
        await db.commit()
        return True


async def close_shop_in_active_wave(wave_id: int, shop_name: str, db_path: str = DB_PATH) -> bool:
    """Зупиняє проходження атестації для конкретного магазину в активній хвилі."""
    now_str = get_current_kyiv_time_str()
    async with aiosqlite.connect(db_path) as db:
        await db.execute('''
        UPDATE attestation_wave_shops 
        SET status = 'closed', closed_at = ?
        WHERE wave_id = ? AND shop_name = ?
        ''', (now_str, wave_id, shop_name))
        await db.commit()
        return True


async def is_shop_active_in_wave(wave_id: int, shop_name: str, db_path: str = DB_PATH) -> bool:
    """Перевіряє, чи магазин активний у вказаній хвилі."""
    async with aiosqlite.connect(db_path) as db:
        async with db.execute('''
        SELECT status FROM attestation_wave_shops 
        WHERE wave_id = ? AND shop_name = ?
        ''', (wave_id, shop_name)) as cur:
            row = await cur.fetchone()
            if not row:
                return False
            return row[0] == 'active'


async def get_wave_shops_status(wave_id: int, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Повертає список магазинів хвилі з їхнім статусом (active/closed)."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, wave_id, shop_name, status, started_at, closed_at FROM attestation_wave_shops WHERE wave_id = ? ORDER BY shop_name",
            (wave_id,)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


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


async def start_inline_attempt(
    wave_id: int,
    user_id: int,
    role_name: str,
    shop_name: str,
    duration_minutes: int = 20,
    db_path: str = DB_PATH
) -> Dict[str, Any]:
    """
    Ініціалізує спробу нативного інлайн-тестування:
    - Завантажує питання для посади та випадковим чином перемішує їх
    - Для кожного питання тасує порядок варіантів відповідей (захист від списування)
    - Встановлює таймер expires_at = now + duration_minutes
    - Зберігає повний стан у БД (State-in-DB)
    """
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        # 1. Перевіряємо наявність попередньої спроби
        async with db.execute('''
        SELECT * FROM attestation_attempts 
        WHERE wave_id = ? AND user_id = ? 
        ORDER BY id DESC LIMIT 1
        ''', (wave_id, user_id)) as cursor:
            last = await cursor.fetchone()

        if last:
            last_dict = dict(last)
            # Якщо спроба вже завершена
            if last_dict["status"] in ("passed", "failed", "timeout"):
                if last_dict.get("can_retake") == 1:
                    # Дозволено перездачу: скидаємо прапорець і створюємо нову спробу
                    await db.execute(
                        "UPDATE attestation_attempts SET can_retake = 0 WHERE id = ?",
                        (last_dict["id"],)
                    )
                else:
                    return last_dict

            # Якщо спроба ще триває (in_progress)
            elif last_dict["status"] == "in_progress":
                # Перевіряємо чи не вичерпано час
                if last_dict.get("expires_at"):
                    try:
                        exp_dt = datetime.strptime(last_dict["expires_at"], "%Y-%m-%d %H:%M:%S")
                        exp_dt = tz.localize(exp_dt) if exp_dt.tzinfo is None else exp_dt
                        if now > exp_dt:
                            # Час вийшов — завершуємо як timeout
                            return await finish_inline_attempt(last_dict["id"], force_timeout=True, db_path=db_path)
                    except Exception as e:
                        logger.error(f"Помилка перевірки expires_at спроби {last_dict['id']}: {e}")
                return last_dict

        # 2. Створюємо нову спробу
        # Отримуємо ліміт питань з налаштувань хвилі
        q_limit = 10
        async with db.execute("SELECT questions_count FROM attestation_waves WHERE id = ?", (wave_id,)) as w_cur:
            w_row = await w_cur.fetchone()
            if w_row and w_row["questions_count"]:
                q_limit = int(w_row["questions_count"])

        # Отримуємо всі питання для цієї посади
        async with db.execute(
            "SELECT * FROM attestation_questions WHERE role_name = ? ORDER BY id ASC",
            (role_name,)
        ) as q_cur:
            q_rows = await q_cur.fetchall()
            questions = [dict(r) for r in q_rows]

        if not questions:
            raise ValueError(f"Не знайдено питань у базі для посади '{role_name}'")

        # Перемішуємо порядок питань і відбираємо рівно q_limit питань без повторень
        random.shuffle(questions)
        if q_limit and len(questions) > q_limit:
            questions = questions[:q_limit]

        q_ids = [q["id"] for q in questions]

        # Для кожного обраного запитання перемішуємо порядок варіантів 1..4
        options_order: Dict[str, List[int]] = {}
        for q in questions:
            opts = [1, 2]
            if q.get("option_3"):
                opts.append(3)
            if q.get("option_4"):
                opts.append(4)
            random.shuffle(opts)
            options_order[str(q["id"])] = opts

        expires_dt = now + timedelta(minutes=duration_minutes)
        expires_str = expires_dt.strftime("%Y-%m-%d %H:%M:%S")

        cursor = await db.execute('''
        INSERT INTO attestation_attempts 
        (wave_id, user_id, role_name, shop_name, started_at, expires_at,
         questions_order_json, options_order_json, current_question_index,
         answers_json, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, '{}', 'in_progress')
        ''', (
            wave_id,
            user_id,
            role_name,
            shop_name,
            now_str,
            expires_str,
            json.dumps(q_ids),
            json.dumps(options_order)
        ))
        attempt_id = cursor.lastrowid

        # Оновлюємо статус учасника
        await db.execute('''
        UPDATE attestation_participants 
        SET status = 'in_progress' 
        WHERE wave_id = ? AND user_id = ?
        ''', (wave_id, user_id))

        await db.commit()

        async with db.execute("SELECT * FROM attestation_attempts WHERE id = ?", (attempt_id,)) as cur:
            row = await cur.fetchone()
            return dict(row)


async def get_inline_attempt_card_data(attempt_id: int, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """
    Повертає структуровані дані для відображення поточного питання в інлайн-повідомленні:
    - Текст запитання, номер з N
    - Залишок секунд таймера
    - Перемішані варіанти відповідей з позначкою раніше обраного (🔘)
    - Наявність кнопки 'Назад'
    - Статус завершення (якщо час вичерпано або тест складено)
    """
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM attestation_attempts WHERE id = ?", (attempt_id,)) as cur:
            att_row = await cur.fetchone()
            if not att_row:
                return None
            att = dict(att_row)

        # Якщо вже завершено
        if att["status"] in ("passed", "failed", "timeout"):
            return {"is_finished": True, "attempt": att}

        # Перевіряємо дедлайн таймера
        exp_dt = None
        if att.get("expires_at"):
            try:
                exp_dt = datetime.strptime(att["expires_at"], "%Y-%m-%d %H:%M:%S")
                exp_dt = tz.localize(exp_dt) if exp_dt.tzinfo is None else exp_dt
                if now > exp_dt:
                    finished = await finish_inline_attempt(attempt_id, force_timeout=True, db_path=db_path)
                    return {"is_finished": True, "attempt": finished, "timeout": True}
            except Exception as e:
                logger.error(f"Помилка розрахунку expires_at: {e}")

        remaining_seconds = 0
        if exp_dt:
            remaining_seconds = max(0, int((exp_dt - now).total_seconds()))

        # Завантажуємо порядок питань та варіантів
        q_order = json.loads(att["questions_order_json"] or "[]")
        opt_order_dict = json.loads(att["options_order_json"] or "{}")
        answers = json.loads(att["answers_json"] or "{}")
        current_idx = att["current_question_index"]

        if not q_order or current_idx >= len(q_order):
            finished = await finish_inline_attempt(attempt_id, force_timeout=False, db_path=db_path)
            return {"is_finished": True, "attempt": finished}

        current_q_id = q_order[current_idx]
        async with db.execute("SELECT * FROM attestation_questions WHERE id = ?", (current_q_id,)) as q_cur:
            q_row = await q_cur.fetchone()
            if not q_row:
                return None
            q_data = dict(q_row)

        # Формуємо список варіантів у збереженому перемішаному порядку
        opt_seq = opt_order_dict.get(str(current_q_id), [1, 2, 3, 4])
        selected_orig_opt = answers.get(str(current_q_id))

        options_list = []
        for orig_num in opt_seq:
            text = q_data.get(f"option_{orig_num}")
            if text:
                options_list.append({
                    "orig_num": orig_num,
                    "text": str(text).strip(),
                    "is_selected": (selected_orig_opt == orig_num)
                })

        return {
            "is_finished": False,
            "attempt_id": attempt_id,
            "wave_id": att["wave_id"],
            "user_id": att["user_id"],
            "role_name": att["role_name"],
            "shop_name": att["shop_name"],
            "current_index": current_idx,
            "current_q_num": current_idx + 1,
            "total_questions": len(q_order),
            "question_id": current_q_id,
            "question_text": q_data["question_text"],
            "points": q_data.get("points", 1),
            "options": options_list,
            "has_previous": current_idx > 0,
            "has_next": (selected_orig_opt is not None and (current_idx + 1) < len(q_order)),
            "remaining_seconds": remaining_seconds,
            "expires_at": att.get("expires_at", "")
        }


async def save_inline_answer(
    attempt_id: int,
    question_id: int,
    selected_option_orig: int,
    db_path: str = DB_PATH
) -> Tuple[Dict[str, Any], bool]:
    """
    Зберігає відповідь на запитання та пересуває індекс вперед.
    Повертає (attempt_dict, is_finished).
    """
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM attestation_attempts WHERE id = ?", (attempt_id,)) as cur:
            att = await cur.fetchone()
            if not att:
                raise ValueError(f"Спробу {attempt_id} не знайдено")
            att_dict = dict(att)

        # Перевіряємо чи не закінчився час
        if att_dict.get("expires_at"):
            try:
                exp_dt = datetime.strptime(att_dict["expires_at"], "%Y-%m-%d %H:%M:%S")
                exp_dt = tz.localize(exp_dt) if exp_dt.tzinfo is None else exp_dt
                if now > exp_dt:
                    finished = await finish_inline_attempt(attempt_id, force_timeout=True, db_path=db_path)
                    return finished, True
            except Exception:
                pass

        answers = json.loads(att_dict["answers_json"] or "{}")
        answers[str(question_id)] = int(selected_option_orig)
        q_order = json.loads(att_dict["questions_order_json"] or "[]")
        next_idx = att_dict["current_question_index"] + 1

        if next_idx >= len(q_order):
            # Останнє питання — завершуємо тест!
            await db.execute('''
            UPDATE attestation_attempts 
            SET answers_json = ?, current_question_index = ? 
            WHERE id = ?
            ''', (json.dumps(answers), next_idx, attempt_id))
            await db.commit()
            finished = await finish_inline_attempt(attempt_id, force_timeout=False, db_path=db_path)
            return finished, True
        else:
            await db.execute('''
            UPDATE attestation_attempts 
            SET answers_json = ?, current_question_index = ? 
            WHERE id = ?
            ''', (json.dumps(answers), next_idx, attempt_id))
            await db.commit()

            async with db.execute("SELECT * FROM attestation_attempts WHERE id = ?", (attempt_id,)) as c2:
                updated = await c2.fetchone()
                return dict(updated), False


async def navigate_inline_question(
    attempt_id: int,
    delta: int,
    db_path: str = DB_PATH
) -> Tuple[Dict[str, Any], bool]:
    """
    Змінює поточний індекс запитання (наприклад, -1 для кнопки Назад або +1 для Далі).
    Повертає (attempt_dict, is_finished).
    """
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM attestation_attempts WHERE id = ?", (attempt_id,)) as cur:
            att = await cur.fetchone()
            if not att:
                raise ValueError(f"Спробу {attempt_id} не знайдено")
            att_dict = dict(att)

        # Перевірка дедлайну
        if att_dict.get("expires_at"):
            try:
                exp_dt = datetime.strptime(att_dict["expires_at"], "%Y-%m-%d %H:%M:%S")
                exp_dt = tz.localize(exp_dt) if exp_dt.tzinfo is None else exp_dt
                if now > exp_dt:
                    finished = await finish_inline_attempt(attempt_id, force_timeout=True, db_path=db_path)
                    return finished, True
            except Exception:
                pass

        q_order = json.loads(att_dict["questions_order_json"] or "[]")
        total = len(q_order)
        new_idx = max(0, min(total - 1, att_dict["current_question_index"] + delta))

        await db.execute(
            "UPDATE attestation_attempts SET current_question_index = ? WHERE id = ?",
            (new_idx, attempt_id)
        )
        await db.commit()

        async with db.execute("SELECT * FROM attestation_attempts WHERE id = ?", (attempt_id,)) as c2:
            updated = await c2.fetchone()
            return dict(updated), False


async def finish_inline_attempt(
    attempt_id: int,
    force_timeout: bool = False,
    db_path: str = DB_PATH
) -> Dict[str, Any]:
    """
    Фіналізує спробу тестування, підраховує бали та оновлює статус учасника.
    """
    now = get_current_kyiv_datetime()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM attestation_attempts WHERE id = ?", (attempt_id,)) as cur:
            att = await cur.fetchone()
            if not att:
                raise ValueError(f"Спробу {attempt_id} не знайдено")
            att_dict = dict(att)

        wave_id = att_dict["wave_id"]
        user_id = att_dict["user_id"]
        role_name = att_dict["role_name"]

        # Параметри хвилі
        async with db.execute("SELECT passing_score_pct FROM attestation_waves WHERE id = ?", (wave_id,)) as w_cur:
            w_row = await w_cur.fetchone()
            passing_score_pct = w_row["passing_score_pct"] if w_row else 80

        # Отримуємо всі питання посади
        async with db.execute(
            "SELECT id, correct_option, points FROM attestation_questions WHERE role_name = ?",
            (role_name,)
        ) as q_cur:
            q_rows = await q_cur.fetchall()
            questions_map = {q["id"]: dict(q) for q in q_rows}

        q_order = json.loads(att_dict["questions_order_json"] or "[]")
        answers = json.loads(att_dict["answers_json"] or "{}")

        total_score = 0
        max_score = 0
        for q_id in q_order:
            q_info = questions_map.get(q_id)
            if q_info:
                pts = q_info.get("points", 1)
                max_score += pts
                user_ans = answers.get(str(q_id))
                if user_ans is not None and int(user_ans) == q_info["correct_option"]:
                    total_score += pts

        score_pct = round((total_score / max_score * 100.0), 1) if max_score > 0 else 0.0

        if score_pct >= passing_score_pct:
            final_status = "passed"
        elif force_timeout:
            final_status = "timeout"
        else:
            final_status = "failed"

        # Тривалість
        duration_seconds = 0
        if att_dict.get("started_at"):
            try:
                start_dt = datetime.strptime(att_dict["started_at"], "%Y-%m-%d %H:%M:%S")
                tz = pytz.timezone(TIMEZONE)
                start_dt = tz.localize(start_dt) if start_dt.tzinfo is None else start_dt
                duration_seconds = int((now - start_dt).total_seconds())
            except Exception:
                duration_seconds = 0

        await db.execute('''
        UPDATE attestation_attempts 
        SET finished_at = ?, duration_seconds = ?, score = ?, max_score = ?,
            score_pct = ?, status = ?
        WHERE id = ?
        ''', (
            now_str,
            duration_seconds,
            total_score,
            max_score,
            score_pct,
            final_status,
            attempt_id
        ))

        # Оновлюємо статус в таблиці учасників
        await db.execute('''
        UPDATE attestation_participants 
        SET status = ? 
        WHERE wave_id = ? AND user_id = ?
        ''', (final_status, wave_id, user_id))

        await db.commit()

        async with db.execute("SELECT * FROM attestation_attempts WHERE id = ?", (attempt_id,)) as c2:
            row = await c2.fetchone()
            return dict(row)


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
