import aiosqlite
from typing import Optional
from datetime import datetime, timedelta
import pytz
from bot.config import TIMEZONE
from . import DB_PATH
from database.managers import MANAGERS_DB_PATH, get_manager_by_uid

def _now_str() -> str:
    return datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")

async def register_user(user_id, username=None, full_name=None):
    """Реєструє нового користувача або оновлює дані існуючого"""
    now = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")
    
    # Забезпечуємо, що full_name не буде None
    full_name = full_name if full_name else ""
    username = username if username else ""

    async with aiosqlite.connect(DB_PATH) as db:
        # Перевіряємо, чи користувач вже існує
        cursor = await db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        user = await cursor.fetchone()
        
        if user:
            # Оновлюємо існуючого користувача
            await db.execute(
                "UPDATE users SET username = ?, full_name = ?, last_activity = ? WHERE user_id = ?",
                (username, full_name, now, user_id)
            ) 
            # Виводимо в термінал про оновлення користувача в базі
            # Коментуємо, щоб не виводити зайві повідомлення
            # print(
            #     f"Оновлено дані користувача: {user_id}, username: {username}, full_name: {full_name}, last_activity: {now}"
            # )
        else:
            # Додаємо нового користувача
            await db.execute(
                "INSERT INTO users (user_id, username, full_name, first_seen, current_block, last_activity) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, username, full_name, now, 1, now)
            )
            # print(f"Зареєстровано нового користувача: {user_id}, {username}, {full_name}")
        
        await db.commit()

async def update_progress(user_id, day, completed=True):
    """Оновлює прогрес користувача"""
    now = datetime.now(pytz.timezone(TIMEZONE))
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Перевіряємо чи існує запис
        cursor = await db.execute(
            "SELECT * FROM progress WHERE user_id = ? AND day = ?", 
            (user_id, day)
        )
        record = await cursor.fetchone()
        
        if record:
            # Оновлюємо існуючий запис
            await db.execute(
                "UPDATE progress SET completed = ?, completed_at = ? WHERE user_id = ? AND day = ?",
                (completed, now_str, user_id, day)
            )
        else:
            # Створюємо новий запис
            await db.execute(
                "INSERT INTO progress (user_id, day, completed, completed_at) VALUES (?, ?, ?, ?)",
                (user_id, day, completed, now_str)
            )
        
        # Оновлюємо поточний блок навчання користувача
        if completed:
            cursor = await db.execute("SELECT role FROM users WHERE user_id = ?", (user_id,))
            u_row = await cursor.fetchone()
            u_role = u_row[0] if u_row else None
            from database.positions import get_days_count_for_role
            from bot.config import DAYS_TOTAL
            total_days = await get_days_count_for_role(u_role) if u_role else DAYS_TOTAL
            next_block = min(day + 1, total_days)
            await db.execute(
                "UPDATE users SET current_block = CASE WHEN current_block <= ? THEN ? ELSE current_block END WHERE user_id = ?",
                (day, next_block, user_id)
            )
        else:
            await db.execute(
                "UPDATE users SET current_block = CASE WHEN current_block < ? THEN ? ELSE current_block END WHERE user_id = ?",
                (day, day, user_id)
            )
        
        await db.commit()

    # Оновлюємо in-memory кеш у bot.state якщо він є
    try:
        from bot.state import user_progress
        if user_id not in user_progress:
            user_progress[user_id] = {}
        entry = user_progress[user_id].setdefault(f"day_{day}", {})
        entry["completed"] = bool(completed)
        entry["completed_at"] = now
    except Exception:
        pass
    
    return now  # Повертаємо datetime об'єкт для використання в інших функціях

async def set_manager(user_id, manager_name):
    """Встановлює ім'я керівника для користувача"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET manager_name = ? WHERE user_id = ?",
            (manager_name, user_id)
        )
        await db.commit()

async def get_all_users():
    """Отримує список всіх користувачів"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users ORDER BY last_activity DESC")
        users = await cursor.fetchall()
        return [dict(user) for user in users]

async def get_user_progress(user_id):
    """Отримує прогрес конкретного користувача"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM progress WHERE user_id = ? ORDER BY day", 
            (user_id,)
        )
        progress = await cursor.fetchall()
        return [dict(p) for p in progress]

async def get_manager_students(manager_name):
    """Отримати список користувачів для конкретного керівника"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE manager_name = ? ORDER BY last_activity DESC",
            (manager_name,)
        )
        users = await cursor.fetchall()
        return [dict(user) for user in users]

async def set_intern_extra(user_id, manager_id, role, city, shop=None):
    """Оновлює додаткові поля для стажера: manager_id, role, city, shop"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET manager_id = ?, role = ?, city = ?, shop = ? WHERE user_id = ?",
            (manager_id, role, city, shop, user_id)
        )
        await db.commit()
        # print(f"Оновлено дані стажера: {user_id}, керівник: {manager_id}, посада: {role}, місто: {city}, магазин: {shop}")
    await log_training_event(
        user_id=user_id,
        event_type="added",
        actor_id=manager_id,
        city=city,
        shop=shop,
        role=role,
        manager_id=manager_id,
    )

MANAGEMENT_ROLES = {
    "Керівник",
    "Керівник Стажер",
    "Територіал",
    "Наглядач",
    "Developer",
    "Адміністратор",
    "HR",
}

async def delete_user(user_id):
    """Повністю видаляє користувача, його прогрес та зв'язки з бази даних."""
    from database.managers import delete_manager_by_uid
    try:
        await delete_manager_by_uid(user_id, cascade_user=False)
    except Exception as e:
        print(f"Error deleting from managers: {e}")

    # Логуємо подію видалення стажера, якщо він ще не був залогований як rejected/fired
    try:
        existing_user = await get_user_details(user_id)
        if existing_user and existing_user.get("status") != "Працівник" and existing_user.get("role") not in MANAGEMENT_ROLES:
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "SELECT id FROM training_events WHERE user_id = ? AND event_type IN ('rejected', 'fired') AND event_at >= datetime('now', '-2 minutes')",
                    (user_id,)
                )
                recent = await cur.fetchone()
                if not recent:
                    await log_training_event(
                        user_id=user_id,
                        event_type="left_deleted",
                        actor_id=None,
                        full_name=existing_user.get("full_name"),
                        username=existing_user.get("username"),
                        city=existing_user.get("city"),
                        shop=existing_user.get("shop"),
                        role=existing_user.get("role"),
                        manager_id=existing_user.get("manager_id"),
                    )
    except Exception:
        pass

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM progress WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM hr_users WHERE user_id = ?", (user_id,))
        await db.execute("UPDATE conversations SET status = 'closed' WHERE user_id = ? OR manager_id = ?", (user_id, user_id))
        await db.execute("UPDATE users SET manager_id = NULL WHERE manager_id = ?", (user_id,))
        await db.execute("DELETE FROM reminder_history WHERE intern_id = ? OR sender_id = ?", (user_id, user_id))
        await db.execute("DELETE FROM support_logs WHERE user_id = ?", (user_id,))
        await db.commit()

    try:
        from database.material_notifications import NOTIF_DB_PATH
        async with aiosqlite.connect(NOTIF_DB_PATH) as ndb:
            await ndb.execute("DELETE FROM material_change_recipients WHERE user_id = ?", (user_id,))
            await ndb.commit()
    except Exception:
        pass

    try:
        from database.tokens import TOKENS_DB_PATH
        async with aiosqlite.connect(TOKENS_DB_PATH) as tdb:
            await tdb.execute("DELETE FROM tokens WHERE used_by = ?", (user_id,))
            await tdb.commit()
    except Exception:
        pass

    # Очищаємо кеш прогресу в оперативній пам'яті
    try:
        from bot.state import user_progress
        user_progress.pop(user_id, None)
    except Exception:
        pass

    return True


async def change_user_role(user_id: int, new_role: str) -> dict:
    """
    Змінює посаду користувача та адаптує його навчальну програму:
    - Якщо статус 'Працівник':
        - статус залишається 'Працівник'
        - очищується попередній прогрес
        - всі дні нової посади (1..N) стають повністю відкритими (manual_open = 1, completed = 1, manual_opened_by = 'dev')
    - Якщо статус != 'Працівник' (Стажер):
        - очищується попередній прогрес
        - навчання розпочинається наново з 1-го дня (день 1: manual_open = 1, completed = 0, manual_opened_by = 'dev'; дні 2+ заблоковані)
    - Скидається in-memory кеш user_progress[user_id]
    Повертає dict: {"success": bool, "status": str, "old_role": str, "new_role": str, "days_opened": int, "total_days": int}
    """
    from database.positions import get_days_count_for_role
    from database.materials import get_days_for_role
    from bot.state import user_progress

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT role, status, full_name, username, city, manager_id FROM users WHERE user_id = ?",
            (user_id,),
        )
        user = await cursor.fetchone()
        if not user:
            return {"success": False, "error": "Користувача не знайдено"}

        user_status = user["status"]
        old_role = user["role"]

        # 1. Оновлюємо роль у таблиці users
        await db.execute("UPDATE users SET role = ? WHERE user_id = ?", (new_role, user_id))

        # 2. Очищуємо старий прогрес
        await db.execute("DELETE FROM progress WHERE user_id = ?", (user_id,))

        # Отримуємо кількість днів нової посади
        pos_days = await get_days_count_for_role(new_role)
        mat_days = await get_days_for_role(new_role)
        max_mat_day = max(mat_days) if mat_days else 0
        total_days = max(pos_days, max_mat_day, 1)

        if user_status == "Працівник":
            # Працівник: відкриваємо ВСІ дні нової посади
            for d in range(1, total_days + 1):
                await db.execute(
                    "INSERT INTO progress (user_id, day, completed, manual_open, manual_opened_by) VALUES (?, ?, 1, 1, 'dev')",
                    (user_id, d),
                )
            days_opened = total_days
        else:
            # Стажер: відкриваємо лише День 1
            await db.execute(
                "INSERT INTO progress (user_id, day, completed, manual_open, manual_opened_by) VALUES (?, 1, 0, 1, 'dev')",
                (user_id,),
            )
            days_opened = 1

        await db.commit()

    # 3. Синхронізуємо in-memory кеш
    try:
        from bot.state import sync_user_progress_cache
        await sync_user_progress_cache(user_id)
    except Exception:
        pass

    return {
        "success": True,
        "status": user_status,
        "old_role": old_role,
        "new_role": new_role,
        "days_opened": days_opened,
        "total_days": total_days,
    }


async def update_user_role(user_id: int, new_role: str, actor_id: Optional[int] = None) -> None:
    """Оновлює статус користувача (status), не змінюючи посаду (role)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT user_id, username, full_name, city, role, manager_id, status FROM users WHERE user_id = ?",
            (user_id,),
        )
        user = await cursor.fetchone()
        if not user:
            return
        if user["status"] == new_role:
            return

        if new_role == "Працівник":
            now = _now_str()
            await db.execute(
                "UPDATE users SET status = ?, worker_since = COALESCE(worker_since, ?) WHERE user_id = ?",
                (new_role, now, user_id),
            )
            # Переконуємося, що всі навчальні дні посади відкриті та пройдені
            role = user["role"]
            from database.positions import get_days_count_for_role
            from bot.config import DAYS_TOTAL
            total_days = await get_days_count_for_role(role) if role else DAYS_TOTAL
            for d in range(1, total_days + 1):
                await db.execute(
                    """
                    INSERT INTO progress (user_id, day, completed, completed_at, manual_open, manual_opened_by)
                    VALUES (?, ?, 1, ?, 1, 'promotion')
                    ON CONFLICT(user_id, day) DO UPDATE SET completed = 1, manual_open = 1
                    """,
                    (user_id, d, now),
                )
            await db.execute(
                "UPDATE users SET current_block = ? WHERE user_id = ?",
                (total_days, user_id),
            )
        else:
            await db.execute("UPDATE users SET status = ? WHERE user_id = ?", (new_role, user_id))
        await db.commit()

    try:
        from bot.state import sync_user_progress_cache
        await sync_user_progress_cache(user_id)
    except Exception:
        pass

    if new_role == "Працівник":
        await log_training_event(
            user_id=user_id,
            event_type="promoted",
            actor_id=actor_id,
            full_name=user["full_name"],
            username=user["username"],
            city=user["city"],
            role=user["role"],
            manager_id=user["manager_id"],
        )

async def get_user_details(user_id):
    """Отримує детальну інформацію про користувача"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE user_id = ?", 
            (user_id,)
        )
        user = await cursor.fetchone()
        return dict(user) if user else None

async def get_manager_interns(manager_id):
    """Отримує список всіх стажерів конкретного керівника"""
    privileged_ids = await _get_privileged_user_ids()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE manager_id = ? AND (status IS NULL OR status != 'Працівник') ORDER BY last_activity DESC",
            (manager_id,)
        )
        interns = await cursor.fetchall()
        return [
            dict(intern) for intern in interns 
            if intern["role"] not in MANAGEMENT_ROLES and intern["user_id"] not in privileged_ids
        ]

async def get_manager_team_users(manager_id: int) -> list[dict]:
    """
    Отримує всіх закріплених за керівником користувачів (і стажерів, і працівників):
    як за manager_id, так і за прив'язкою до магазинів керівника (city + shops).
    """
    from database.managers import get_manager_by_uid
    manager = await get_manager_by_uid(manager_id)
    
    m_city = manager.get("city") if manager else None
    m_shops = manager.get("shops") if manager else []
    if isinstance(m_shops, str):
        try:
            import json
            m_shops = json.loads(m_shops)
        except Exception:
            m_shops = [s.strip() for s in m_shops.split(",") if s.strip()]
    if not isinstance(m_shops, list):
        m_shops = []

    privileged_ids = await _get_privileged_user_ids()

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # Базовий запит за manager_id
        conditions = ["manager_id = ?"]
        params = [manager_id]
        
        # Додаткова умова за містом і магазинами
        if m_city and m_shops:
            placeholders = ",".join("?" for _ in m_shops)
            conditions.append(f"(city = ? AND shop IN ({placeholders}))")
            params.append(m_city)
            params.extend(m_shops)
            
        where_clause = " OR ".join(conditions)
        query = f"SELECT * FROM users WHERE ({where_clause}) ORDER BY last_activity DESC"
        
        cursor = await db.execute(query, tuple(params))
        rows = await cursor.fetchall()
        
        # Дедуплікація за user_id та виключення привілейованих
        seen = set()
        team = []
        for r in rows:
            uid = r["user_id"]
            if uid not in seen and uid not in privileged_ids and uid != manager_id and r["role"] not in MANAGEMENT_ROLES:
                seen.add(uid)
                team.append(dict(r))
                
        return team

async def get_manager_workers(manager_id: int) -> list[dict]:
    """Отримує лише працівників (випускників), закріплених за керівником"""
    team = await get_manager_team_users(manager_id)
    return [u for u in team if u.get("is_worker") or u.get("status") == "Працівник"]

async def get_manager_interns_full(manager_id: int) -> list[dict]:
    """Отримує лише стажерів, закріплених за керівником"""
    team = await get_manager_team_users(manager_id)
    return [u for u in team if not (u.get("is_worker") or u.get("status") == "Працівник")]

async def get_all_active_users(days=3):
    """Отримує список активних стажерів (виключаючи Dev/Керівників)"""
    cutoff_date = (datetime.now(pytz.timezone(TIMEZONE)) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    privileged_ids = await _get_privileged_user_ids()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = """
            SELECT * FROM users
            WHERE (status IS NULL OR status != 'Працівник')
            AND (last_activity >= ? OR last_activity IS NULL)
            ORDER BY last_activity DESC
        """
        cursor = await db.execute(query, (cutoff_date,))
        users = await cursor.fetchall()
        return [
            dict(user) for user in users 
            if user["user_id"] not in privileged_ids and user["role"] not in MANAGEMENT_ROLES
        ]

async def get_all_inactive_users(days=3):
    """Отримує список неактивних стажерів"""
    from bot.config import DAYS_TOTAL
    cutoff_date = (datetime.now(pytz.timezone(TIMEZONE)) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    privileged_ids = await _get_privileged_user_ids()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = """
            SELECT * FROM users 
            WHERE (status IS NULL OR status != 'Працівник')
            AND last_activity < ? 
            AND user_id NOT IN (
                SELECT user_id
                FROM progress
                WHERE completed = 1
                GROUP BY user_id
                HAVING COUNT(day) >= ?
            )
            ORDER BY last_activity ASC
        """
        cursor = await db.execute(query, (cutoff_date, DAYS_TOTAL))
        users = await cursor.fetchall()
        return [
            dict(user) for user in users 
            if user["user_id"] not in privileged_ids and user["role"] not in MANAGEMENT_ROLES
        ]

async def _get_privileged_user_ids() -> set[int]:
    async with aiosqlite.connect(MANAGERS_DB_PATH) as mdb:
        cur = await mdb.execute("SELECT uid FROM managers")
        privileged_ids = {row[0] for row in await cur.fetchall()}

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM hr_users")
        privileged_ids |= {row[0] for row in await cur.fetchall()}

    return privileged_ids

async def get_all_interns() -> list:
    """Повертає всіх стажерів — користувачів з users, які не є керівниками/HR/Dev і не стали Працівниками."""
    privileged_ids = await _get_privileged_user_ids()

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE (status IS NULL OR status != 'Працівник') ORDER BY full_name ASC")
        rows = await cursor.fetchall()
        return [
            dict(r) for r in rows 
            if r["user_id"] not in privileged_ids and r["role"] not in MANAGEMENT_ROLES
        ]

async def get_all_workers() -> list:
    """Повертає всіх працівників (status = 'Працівник'), сортуючи за ПІБ."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE status = 'Працівник' ORDER BY full_name ASC"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

async def get_interns_in_progress_for_manager(manager_id, active_only=True):
    """
    Отримує список стажерів, які не завершили навчання.
    Якщо active_only=True, повертає лише тих, хто був активний останні 3 дні.
    """
    from bot.config import DAYS_TOTAL
    cutoff_date = (datetime.now(pytz.timezone(TIMEZONE)) - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # Базовий запит для стажерів цього керівника
        query = "SELECT * FROM users WHERE manager_id = ? AND (status IS NULL OR status != 'Працівник')"
        if active_only:
            query += " AND (last_activity >= ? OR last_activity IS NULL)"
            params = (manager_id, cutoff_date)
        else:
            params = (manager_id,)
            
        cursor = await db.execute(query, params)
        interns = await cursor.fetchall()
        
        in_progress = []
        from database.positions import get_days_count_for_role
        for intern in interns:
            if intern["role"] in MANAGEMENT_ROLES:
                continue
            # Перевіряємо чи завершено навчання
            cursor = await db.execute(
                "SELECT COUNT(*) FROM progress WHERE user_id = ? AND completed = 1",
                (intern['user_id'],)
            )
            completed_days = (await cursor.fetchone())[0]
            role = intern.get("role") or ""
            required_days = await get_days_count_for_role(role)
            
            if completed_days < required_days:
                in_progress.append(dict(intern))
        
        return in_progress

async def get_inactive_interns_for_manager(manager_id, days=3):
    """Отримує список стажерів, які не завершили навчання ТА не були активні вказану кількість днів"""
    cutoff_date = (datetime.now(pytz.timezone(TIMEZONE)) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Тільки ті, хто не заходив давно
        cursor = await db.execute(
            "SELECT * FROM users WHERE manager_id = ? AND (status IS NULL OR status != 'Працівник') AND last_activity < ? ORDER BY last_activity ASC",
            (manager_id, cutoff_date)
        )
        interns = await cursor.fetchall()
        
        inactive = []
        from database.positions import get_days_count_for_role
        for intern in interns:
            if intern["role"] in MANAGEMENT_ROLES:
                continue
            cursor = await db.execute(
                "SELECT COUNT(*) FROM progress WHERE user_id = ? AND completed = 1",
                (intern['user_id'],)
            )
            completed_days = (await cursor.fetchone())[0]
            role = intern.get("role") or ""
            required_days = await get_days_count_for_role(role)
            
            if completed_days < required_days:
                inactive.append(dict(intern))
        
        return inactive

async def get_inactive_interns_for_auto_delete(days: int = 3) -> list[dict]:
    """
    Повертає стажерів для автоматичного видалення:
    неактивні >= days, не є Працівниками, мають керівника, не завершили навчання.
    """
    from database.positions import get_days_count_for_role
    cutoff_date = (datetime.now(pytz.timezone(TIMEZONE)) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    privileged_ids = await _get_privileged_user_ids()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM users
            WHERE manager_id IS NOT NULL
              AND (status IS NULL OR status != 'Працівник')
              AND last_activity IS NOT NULL
              AND last_activity < ?
            ORDER BY last_activity ASC
            """,
            (cutoff_date,),
        )
        rows = await cursor.fetchall()
        
        eligible = []
        for r in rows:
            user = dict(r)
            uid = user["user_id"]
            if uid in privileged_ids or user.get("role") in MANAGEMENT_ROLES:
                continue
            role = user.get("role") or ""
            required_days = await get_days_count_for_role(role)
            p_cur = await db.execute(
                "SELECT COUNT(day) FROM progress WHERE user_id = ? AND completed = 1",
                (uid,)
            )
            completed_days = (await p_cur.fetchone())[0]
            if completed_days >= required_days:
                continue
            eligible.append(user)
        return eligible

async def update_last_activity(user_id):
    """Оновлює час останньої активності користувача"""
    now = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET last_activity = ? WHERE user_id = ?",
            (now, user_id)
        )
        await db.commit()

async def update_user_current_block(user_id, new_block):
    """Безпосередньо оновлює поточний блок навчання користувача"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Виводимо додаткові дані для діагностики
        cursor = await db.execute("SELECT current_block FROM users WHERE user_id = ?", (user_id,))
        old_block = await cursor.fetchone()
        old_block_value = old_block[0] if old_block else "не знайдено"
        
        # Виконуємо оновлення блоку
        await db.execute(
            "UPDATE users SET current_block = ? WHERE user_id = ?",
            (new_block, user_id)
        )
        await db.commit()
        
        # Перевіряємо, чи відбулося оновлення
        cursor = await db.execute("SELECT current_block FROM users WHERE user_id = ?", (user_id,))
        updated_block = await cursor.fetchone()
        updated_block_value = updated_block[0] if updated_block else "не знайдено"
        
        print(f"📝 Оновлення поточного блоку для користувача {user_id}: {old_block_value} -> {updated_block_value}")
        return updated_block_value

MAX_OPEN_CONVERSATIONS = 2

async def can_start_conversation(user_id: int) -> bool:
    """Перевіряє, чи може стажер почати нову розмову."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM conversations WHERE user_id = ? AND status = 'open'",
            (user_id,)
        )
        result = await cursor.fetchone()
        return result[0] < MAX_OPEN_CONVERSATIONS if result else True

async def create_conversation(user_id: int, manager_id: int) -> None:
    """Створює новий запис про відкриту розмову."""
    now = datetime.now(pytz.timezone(TIMEZONE))
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO conversations (user_id, manager_id, created_at, status) VALUES (?, ?, ?, 'open')",
            (user_id, manager_id, now)
        )
        await db.commit()

async def close_conversation(user_id: int, manager_id: int) -> None:
    """Закриває останню відкриту розмову між стажером та керівником."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Знаходимо останню відкриту розмову, щоб закрити саме її
        cursor = await db.execute(
            "SELECT id FROM conversations WHERE user_id = ? AND manager_id = ? AND status = 'open' ORDER BY created_at DESC LIMIT 1",
            (user_id, manager_id)
        )
        last_conversation = await cursor.fetchone()
        
        if last_conversation:
            await db.execute(
                "UPDATE conversations SET status = 'closed' WHERE id = ?",
                (last_conversation[0],)
            )
            await db.commit()

async def get_inactive_interns_for_auto_reminder(now: datetime, inactive_days: int, cooldown_hours: int) -> list[dict]:
    """Повертає стажерів, які відповідають критеріям для автоматичного нагадування."""
    from database.positions import get_days_count_for_role
    
    inactive_cutoff = now - timedelta(days=inactive_days)
    cooldown_cutoff = now - timedelta(hours=cooldown_hours)
    privileged_ids = await _get_privileged_user_ids()
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # Отримуємо тільки стажерів (статус не 'Працівник')
        cursor = await db.execute("SELECT * FROM users WHERE (status IS NULL OR status != 'Працівник')")
        all_users = await cursor.fetchall()
        
        eligible_users = []
        for user_row in all_users:
            user = dict(user_row)
            user_id = user["user_id"]
            
            # Пропускаємо privileged та керівні ролі
            if user_id in privileged_ids or user.get("role") in MANAGEMENT_ROLES:
                continue
            
            # Перевіряємо чи завершив курс для своєї посади
            role = user.get("role") or ""
            required_days = await get_days_count_for_role(role)
            p_cur = await db.execute(
                "SELECT COUNT(day) FROM progress WHERE user_id = ? AND completed = 1",
                (user_id,)
            )
            completed_days = (await p_cur.fetchone())[0]
            if completed_days >= required_days:
                continue
            
            # Перевірка неактивності
            last_activity_str = user.get("last_activity")
            if not last_activity_str:
                continue
            
            try:
                last_activity_dt = datetime.fromisoformat(last_activity_str).astimezone(pytz.timezone(TIMEZONE))
                if last_activity_dt > inactive_cutoff:
                    continue
            except (ValueError, TypeError):
                continue

            # Перевірка кулдауну
            last_reminder_str = user.get("last_auto_reminder_at")
            if last_reminder_str:
                try:
                    last_reminder_dt = datetime.fromisoformat(last_reminder_str).astimezone(pytz.timezone(TIMEZONE))
                    if last_reminder_dt > cooldown_cutoff:
                        continue
                except (ValueError, TypeError):
                    pass
            
            eligible_users.append(user)
            
        return eligible_users

async def touch_auto_reminder(user_id: int, now: datetime) -> None:
    """Оновлює час останнього автоматичного нагадування для користувача."""
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET last_auto_reminder_at = ? WHERE user_id = ?",
            (now_str, user_id)
        )
        await db.commit()

async def is_day3_question_sent(user_id: int) -> bool:
    """Перевіряє, чи було надіслано питання 3-го дня."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT day3_question_sent FROM users WHERE user_id = ?", (user_id,))
        result = await cursor.fetchone()
        return result[0] == 1 if result else False

async def mark_day3_question_sent(user_id: int) -> None:
    """Позначає, що питання 3-го дня було надіслано."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET day3_question_sent = 1 WHERE user_id = ?", (user_id,))
        await db.commit()

async def log_support_request(user_id: int) -> None:
    """Logs a support request from an intern to the database."""
    now = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO support_logs (user_id, created_at) VALUES (?, ?)",
            (user_id, now)
        )
        await db.commit()

async def get_user_by_username(username: str) -> Optional[dict]:
    """Отримує детальну інформацію про користувача за його username.
    
    Пошук не чутливий до регістру.
    Наприклад, "@Username", "@username", "@USERNAME" - всі знайдуть того самого користувача.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Використовуємо LOWER() для регістронезалежного пошуку
        cursor = await db.execute(
            "SELECT * FROM users WHERE LOWER(username) = LOWER(?)", 
            (username.lstrip('@'),)
        )
        user = await cursor.fetchone()
        return dict(user) if user else None

async def log_reminder(intern_id: int, source: str, sender_id: Optional[int] = None) -> None:
    """Logs a reminder sent to an intern."""
    now = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO reminder_history (intern_id, sender_id, source, sent_at) VALUES (?, ?, ?, ?)",
            (intern_id, sender_id, source, now)
        )
        await db.commit()

async def get_reminder_history_count() -> int:
    """Retrieves total count of reminder history records."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM reminder_history")
        row = await cursor.fetchone()
        return row[0] if row else 0

async def get_reminder_history(limit: int = 50, offset: int = 0) -> list[dict]:
    """Retrieves the global reminder history, ordered by date descending."""
    history_records = []
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = """
            SELECT rh.*, 
                   u.full_name as intern_name 
            FROM reminder_history rh
            LEFT JOIN users u ON rh.intern_id = u.user_id
            ORDER BY rh.sent_at DESC
            LIMIT ? OFFSET ?
        """
        cursor = await db.execute(query, (limit, offset))
        rows = await cursor.fetchall()
        
        for row in rows:
            record = dict(row)
            # Fetch sender details separately if sender_id exists
            if record["sender_id"]:
                manager_info = await get_manager_by_uid(record["sender_id"])
                if manager_info:
                    record["sender_name"] = manager_info.get("full_name")
                    record["sender_role"] = manager_info.get("process")
                else:
                    user_info = await get_user_details(record["sender_id"])
                    if user_info:
                        record["sender_name"] = user_info.get("full_name") or user_info.get("username")
                        record["sender_role"] = user_info.get("role")
                    else:
                        record["sender_name"] = None
                        record["sender_role"] = None
            else:
                record["sender_name"] = None
                record["sender_role"] = None
            history_records.append(record)
            
        return history_records

async def get_users_by_city(city: str) -> list[dict]:
    """Retrieves a list of users filtered by city."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE city = ? ORDER BY last_activity DESC",
            (city,)
        )
        users = await cursor.fetchall()
        return [dict(user) for user in users]

async def get_users_by_managers(manager_ids: list[int], active_only: bool = False) -> list[dict]:
    """Retrieves a list of users that belong to any of the specified manager IDs."""
    if not manager_ids:
        return []
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        placeholders = ', '.join(['?'] * len(manager_ids))
        query = f"SELECT * FROM users WHERE manager_id IN ({placeholders})"
        if active_only:
            query += " AND status = 'Активний'"
        query += " ORDER BY last_activity DESC"
        
        cursor = await db.execute(query, tuple(manager_ids))
        users = await cursor.fetchall()
        return [dict(user) for user in users]

async def get_users_by_full_name(full_name: str) -> list[dict]:
    """Retrieves a list of users matching a full name (case-insensitive).
    
    Пошук не чутливий до регістру та знаходить часткові збіги.
    Наприклад, "іван" знайде "Іванов Іван Іванович", "ІВАНОВ", "іванова" тощо.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Використовуємо LOWER() для регістронезалежного пошуку
        cursor = await db.execute(
            "SELECT * FROM users WHERE LOWER(full_name) LIKE LOWER(?)", 
            (f'%{full_name}%',)
        )
        users = await cursor.fetchall()
        return [dict(user) for user in users]

async def get_users_by_shop(city: str, shop: str) -> list[dict]:
    """Retrieves a list of users filtered by city and shop."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE city = ? AND shop = ? ORDER BY last_activity DESC",
            (city, shop)
        )
        users = await cursor.fetchall()
        return [dict(user) for user in users]

async def get_users_by_manager(manager_id: int) -> list[dict]:
    """Retrieves a list of all users assigned to a specific manager."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE manager_id = ? ORDER BY last_activity DESC",
            (manager_id,)
        )
        users = await cursor.fetchall()
        return [dict(user) for user in users]

async def count_users_by_shop(city: str, shop: str) -> int:
    """Returns total number of users in a specific city and shop."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM users WHERE city = ? AND shop = ?",
            (city, shop)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

async def count_users_by_manager(manager_id: int) -> int:
    """Returns total number of users assigned to a specific manager."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM users WHERE manager_id = ?",
            (manager_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

async def log_training_event(
    user_id: int,
    event_type: str,
    actor_id: Optional[int] = None,
    *,
    event_at: Optional[str] = None,
    full_name: Optional[str] = None,
    username: Optional[str] = None,
    city: Optional[str] = None,
    shop: Optional[str] = None,
    role: Optional[str] = None,
    manager_id: Optional[int] = None,
) -> None:
    """
    Логує події навчального процесу для аналітики.
    event_type: added | promoted | rejected
    """
    event_at = event_at or _now_str()
    if full_name is None or username is None or city is None or shop is None or role is None or manager_id is None:
        user = await get_user_details(user_id)
        if user:
            full_name = full_name if full_name is not None else user.get("full_name")
            username = username if username is not None else user.get("username")
            city = city if city is not None else user.get("city")
            shop = shop if shop is not None else user.get("shop")
            role = role if role is not None else user.get("role")
            manager_id = manager_id if manager_id is not None else user.get("manager_id")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO training_events
            (user_id, event_type, event_at, actor_id, full_name, username, city, shop, role, manager_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, event_type, event_at, actor_id, full_name, username, city, shop, role, manager_id),
        )
        await db.commit()
