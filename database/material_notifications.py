from __future__ import annotations
import aiosqlite
import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any

from . import DB_PATH
from database.managers import MANAGERS_DB_PATH

NOTIFICATIONS_DB_PATH = DB_PATH.replace("users.db", "material_notifications.db")


async def init_material_notifications_db():
    """Ініціалізація бази даних сповіщень про зміни навчальних матеріалів."""
    async with aiosqlite.connect(NOTIFICATIONS_DB_PATH) as db:
        await db.execute('''
        CREATE TABLE IF NOT EXISTS material_change_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            day INTEGER NOT NULL,
            content_type TEXT NOT NULL,
            description TEXT,
            pages_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'in_progress'
        )
        ''')

        await db.execute('''
        CREATE TABLE IF NOT EXISTS material_change_recipients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            role_type TEXT NOT NULL,
            shop TEXT,
            city TEXT,
            wave_number INTEGER DEFAULT 1,
            status TEXT DEFAULT 'pending',
            sent_at TIMESTAMP,
            acknowledged_at TIMESTAMP,
            is_late INTEGER DEFAULT 0,
            message_id INTEGER,
            FOREIGN KEY (event_id) REFERENCES material_change_events (id) ON DELETE CASCADE
        )
        ''')

        await db.execute('CREATE INDEX IF NOT EXISTS idx_mat_recip_event ON material_change_recipients(event_id)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_mat_recip_user ON material_change_recipients(user_id)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_mat_recip_wave ON material_change_recipients(wave_number, status)')
        await db.commit()


async def create_material_change_event(
    role: str,
    day: int,
    content_type: str,
    description: str,
    pages: List[str]
) -> int:
    """Створює нову подію зміни матеріалів."""
    pages_json = json.dumps(pages if pages else [description], ensure_ascii=False)
    async with aiosqlite.connect(NOTIFICATIONS_DB_PATH) as db:
        cursor = await db.execute(
            '''
            INSERT INTO material_change_events (role, day, content_type, description, pages_json, created_at, status)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 'in_progress')
            ''',
            (role, day, content_type, description, pages_json)
        )
        await db.commit()
        return cursor.lastrowid


async def create_recipients_for_event(event_id: int, role: str) -> int:
    """
    Збирає активних користувачів цільової посади, керівників компанії та територіалів відповідного напрямку.
    Наглядачі гарантовано виключаються зі списку отримувачів.
    Розбиває на хвилі по 40 осіб та зберігає в material_change_recipients.
    Повертає загальну кількість створених записів отримувачів.
    """
    recipients_data: List[Dict[str, Any]] = []
    seen_user_ids = set()

    # 0. Знаходимо активних наглядачів для гарантованого виключення зі списку отримувачів
    excluded_user_ids = set()
    try:
        async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                '''
                SELECT uid FROM managers
                WHERE process = 'Наглядач' AND (status IS NULL OR status != 'fired')
                '''
            ) as cursor:
                async for row in cursor:
                    if row['uid']:
                        excluded_user_ids.add(row['uid'])
    except Exception as e:
        print(f"Помилка завантаження наглядачів для виключення: {e}")

    # 1. Отримуємо носіїв посади (працівники та стажери) з users.db
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            '''
            SELECT user_id, full_name, role, city, shop, status
            FROM users
            WHERE role = ?
            ''',
            (role,)
        ) as cursor:
            async for row in cursor:
                uid = row['user_id']
                if not uid or uid in seen_user_ids or uid in excluded_user_ids:
                    continue
                seen_user_ids.add(uid)
                is_worker = (row['status'] == 'Працівник')
                cat = 'працівник' if is_worker else 'стажер'
                recipients_data.append({
                    'user_id': uid,
                    'role_type': cat,
                    'shop': row['shop'] or 'Не вказано',
                    'city': row['city'] or 'Не вказано'
                })

    # 2. Отримуємо всіх керівників з managers.db
    try:
        async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                '''
                SELECT uid, full_name, shops, city, process, status
                FROM managers
                WHERE process IN ('Керівник', 'Керівник Стажер') AND (status IS NULL OR status != 'fired')
                '''
            ) as cursor:
                async for row in cursor:
                    uid = row['uid']
                    if not uid or uid in seen_user_ids or uid in excluded_user_ids:
                        continue
                    seen_user_ids.add(uid)
                    mgr_shop = row['shops'] or 'Не вказано'
                    if mgr_shop and mgr_shop.startswith('[') and mgr_shop.endswith(']'):
                        try:
                            parsed_s = json.loads(mgr_shop)
                            if isinstance(parsed_s, list) and parsed_s:
                                mgr_shop = parsed_s[0]
                        except Exception:
                            pass
                    recipients_data.append({
                        'user_id': uid,
                        'role_type': 'керівник',
                        'shop': mgr_shop,
                        'city': row['city'] or 'Не вказано'
                    })
    except Exception as e:
        print(f"Помилка завантаження керівників: {e}")

    # 3. Отримуємо територіалів відповідного напрямку (ТЗ / ВВ) з managers.db
    try:
        from database.positions import get_position_direction
        pos_direction = await get_position_direction(role)
    except Exception as e:
        print(f"Помилка визначення напрямку посади {role}: {e}")
        pos_direction = "ТЗ"

    try:
        async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                '''
                SELECT uid, full_name, city, territorial_type, status
                FROM managers
                WHERE process = 'Територіал' AND (status IS NULL OR status != 'fired')
                '''
            ) as cursor:
                async for row in cursor:
                    uid = row['uid']
                    if not uid or uid in seen_user_ids or uid in excluded_user_ids:
                        continue
                    t_type = (row['territorial_type'] or '').strip().upper()
                    # Якщо у територіала зазначений напрямок, порівнюємо з напрямком посади
                    if t_type and t_type != pos_direction:
                        continue
                    seen_user_ids.add(uid)
                    recipients_data.append({
                        'user_id': uid,
                        'role_type': 'територіал',
                        'shop': f'Всі магазини ({pos_direction})',
                        'city': row['city'] or 'Не вказано'
                    })
    except Exception as e:
        print(f"Помилка завантаження територіалів: {e}")

    # 4. Розбиваємо на батчі по 40 осіб
    BATCH_SIZE = 40
    async with aiosqlite.connect(NOTIFICATIONS_DB_PATH) as db:
        for idx, rec in enumerate(recipients_data):
            wave_num = (idx // BATCH_SIZE) + 1
            await db.execute(
                '''
                INSERT INTO material_change_recipients 
                (event_id, user_id, role_type, shop, city, wave_number, status)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
                ''',
                (event_id, rec['user_id'], rec['role_type'], rec['shop'], rec['city'], wave_num)
            )
        await db.commit()

    return len(recipients_data)


async def get_pending_wave_recipients(wave_number: Optional[int] = None, event_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Повертає список отримувачів зі статусом 'pending'."""
    query = '''
    SELECT r.*, e.role, e.day, e.content_type, e.description, e.pages_json, e.created_at as event_created_at
    FROM material_change_recipients r
    JOIN material_change_events e ON r.event_id = e.id
    WHERE r.status = 'pending'
    '''
    params = []
    if wave_number is not None:
        query += " AND r.wave_number = ?"
        params.append(wave_number)
    if event_id is not None:
        query += " AND r.event_id = ?"
        params.append(event_id)

    query += " ORDER BY r.id ASC"

    async with aiosqlite.connect(NOTIFICATIONS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, tuple(params)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def get_max_wave_for_event(event_id: int) -> int:
    """Повертає максимальний номер хвилі для події."""
    async with aiosqlite.connect(NOTIFICATIONS_DB_PATH) as db:
        async with db.execute(
            "SELECT COALESCE(MAX(wave_number), 1) FROM material_change_recipients WHERE event_id = ?",
            (event_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 1


async def mark_recipient_sent(recipient_id: int, message_id: Optional[int] = None) -> bool:
    """Позначає отримувача як такого, кому надіслано повідомлення."""
    async with aiosqlite.connect(NOTIFICATIONS_DB_PATH) as db:
        await db.execute(
            '''
            UPDATE material_change_recipients
            SET status = 'sent', sent_at = CURRENT_TIMESTAMP, message_id = ?
            WHERE id = ?
            ''',
            (message_id, recipient_id)
        )
        await db.commit()
        return True


async def mark_recipient_failed(recipient_id: int) -> bool:
    """Позначає отримувача як помилку відправки."""
    async with aiosqlite.connect(NOTIFICATIONS_DB_PATH) as db:
        await db.execute(
            "UPDATE material_change_recipients SET status = 'failed' WHERE id = ?",
            (recipient_id,)
        )
        await db.commit()
        return True


async def mark_recipient_acknowledged(event_id: int, user_id: int) -> Tuple[bool, bool]:
    """
    Фіксує ознайомлення користувача.
    Повертає (успіх, is_late).
    Якщо від моменту sent_at пройшло > 72 год, is_late = True.
    """
    async with aiosqlite.connect(NOTIFICATIONS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            '''
            SELECT id, sent_at, acknowledged_at, is_late
            FROM material_change_recipients
            WHERE event_id = ? AND user_id = ?
            ''',
            (event_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return False, False
            
            # Якщо вже ознайомлений
            if row['acknowledged_at']:
                return True, bool(row['is_late'])

            # Перевіряємо чи пройшло > 72 год
            sent_at_str = row['sent_at']
            is_late = 0
            if sent_at_str:
                try:
                    sent_dt = datetime.fromisoformat(sent_at_str.replace("Z", "+00:00"))
                except ValueError:
                    try:
                        sent_dt = datetime.strptime(sent_at_str, "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        sent_dt = datetime.utcnow()
                
                if datetime.utcnow() - sent_dt > timedelta(hours=72):
                    is_late = 1

            await db.execute(
                '''
                UPDATE material_change_recipients
                SET acknowledged_at = CURRENT_TIMESTAMP, is_late = ?
                WHERE id = ?
                ''',
                (is_late, row['id'])
            )
            await db.commit()
            return True, bool(is_late)


async def get_recipient_by_user_and_event(event_id: int, user_id: int) -> Optional[Dict[str, Any]]:
    """Повертає запис отримувача за event_id та user_id."""
    async with aiosqlite.connect(NOTIFICATIONS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM material_change_recipients WHERE event_id = ? AND user_id = ?",
            (event_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_recipient_by_id(recipient_id: int) -> Optional[Dict[str, Any]]:
    """Повертає запис отримувача за його ID."""
    async with aiosqlite.connect(NOTIFICATIONS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM material_change_recipients WHERE id = ?",
            (recipient_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_event_by_id(event_id: int) -> Optional[Dict[str, Any]]:
    """Повертає подію зміни матеріалів за ID."""
    async with aiosqlite.connect(NOTIFICATIONS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM material_change_events WHERE id = ?",
            (event_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_events_for_category(category: str, days_limit: int = 90) -> List[Dict[str, Any]]:
    """
    Повертає список подій за останні days_limit днів, які мають отримувачів зазначеної категорії
    ('керівник', 'працівник', 'стажер').
    """
    cat_normalized = category.strip().lower()
    async with aiosqlite.connect(NOTIFICATIONS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = '''
        SELECT DISTINCT e.id, e.role, e.day, e.content_type, e.description, e.created_at, e.status
        FROM material_change_events e
        JOIN material_change_recipients r ON e.id = r.event_id
        WHERE LOWER(r.role_type) = ?
          AND e.created_at >= datetime('now', ?)
        ORDER BY e.created_at DESC
        '''
        async with db.execute(query, (cat_normalized, f"-{days_limit} days")) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def get_event_analytics_for_category(event_id: int, category: str) -> Dict[str, Any]:
    """
    Підраховує аналітику ознайомлення для події та категорії:
    - total
    - acknowledged_count
    - acknowledged_late_count
    - unacknowledged_count
    """
    cat_normalized = category.strip().lower()
    async with aiosqlite.connect(NOTIFICATIONS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # Total
        async with db.execute(
            "SELECT COUNT(*) FROM material_change_recipients WHERE event_id = ? AND LOWER(role_type) = ?",
            (event_id, cat_normalized)
        ) as cursor:
            total = (await cursor.fetchone())[0]

        # Acknowledged
        async with db.execute(
            '''
            SELECT COUNT(*) FROM material_change_recipients 
            WHERE event_id = ? AND LOWER(role_type) = ? AND acknowledged_at IS NOT NULL
            ''',
            (event_id, cat_normalized)
        ) as cursor:
            ack_count = (await cursor.fetchone())[0]

        # Acknowledged Late (is_late = 1)
        async with db.execute(
            '''
            SELECT COUNT(*) FROM material_change_recipients 
            WHERE event_id = ? AND LOWER(role_type) = ? AND acknowledged_at IS NOT NULL AND is_late = 1
            ''',
            (event_id, cat_normalized)
        ) as cursor:
            ack_late_count = (await cursor.fetchone())[0]

        unack_count = max(0, total - ack_count)

        return {
            'total': total,
            'acknowledged_count': ack_count,
            'acknowledged_late_count': ack_late_count,
            'unacknowledged_count': unack_count,
            'ack_percent': round((ack_count / total * 100), 1) if total > 0 else 0.0,
            'unack_percent': round((unack_count / total * 100), 1) if total > 0 else 0.0
        }


async def get_event_shop_breakdown(event_id: int, category: str, acknowledged: bool) -> List[Dict[str, Any]]:
    """
    Повертає список магазинів з кількістю користувачів для події (ознайомлені або неознайомлені).
    """
    cat_normalized = category.strip().lower()
    condition = "acknowledged_at IS NOT NULL" if acknowledged else "acknowledged_at IS NULL"
    query = f'''
    SELECT shop, COUNT(*) as user_count
    FROM material_change_recipients
    WHERE event_id = ? AND LOWER(role_type) = ? AND {condition}
    GROUP BY shop
    ORDER BY user_count DESC, shop ASC
    '''
    async with aiosqlite.connect(NOTIFICATIONS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, (event_id, cat_normalized)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def get_event_shop_users(event_id: int, category: str, acknowledged: bool, shop: str) -> List[Dict[str, Any]]:
    """
    Повертає список користувачів конкретного магазину для події з їх ПІБ, датою відправки та датою ознайомлення.
    """
    cat_normalized = category.strip().lower()
    condition = "r.acknowledged_at IS NOT NULL" if acknowledged else "r.acknowledged_at IS NULL"
    
    # Отримуємо дані отримувачів
    async with aiosqlite.connect(NOTIFICATIONS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = f'''
        SELECT r.id, r.user_id, r.role_type, r.shop, r.city, r.sent_at, r.acknowledged_at, r.is_late
        FROM material_change_recipients r
        WHERE r.event_id = ? AND LOWER(r.role_type) = ? AND r.shop = ? AND {condition}
        ORDER BY r.acknowledged_at ASC, r.id ASC
        '''
        async with db.execute(query, (event_id, cat_normalized, shop)) as cursor:
            recipients = [dict(r) for r in await cursor.fetchall()]

    # Збагачуємо ПІБ та username з users.db або managers.db
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        for rec in recipients:
            uid = rec['user_id']
            full_name = None
            username = None
            async with db.execute("SELECT full_name, username FROM users WHERE user_id = ?", (uid,)) as cursor:
                u_row = await cursor.fetchone()
                if u_row:
                    full_name = u_row['full_name']
                    username = u_row['username']

            # Якщо не знайдено в users, шукаємо в managers.db
            if not full_name:
                try:
                    async with aiosqlite.connect(MANAGERS_DB_PATH) as m_db:
                        m_db.row_factory = aiosqlite.Row
                        async with m_db.execute("SELECT full_name, username FROM managers WHERE uid = ?", (uid,)) as m_cursor:
                            m_row = await m_cursor.fetchone()
                            if m_row:
                                full_name = m_row['full_name']
                                username = m_row['username']
                except Exception:
                    pass

            rec['full_name'] = full_name or f"Користувач ID {uid}"
            rec['username'] = username or ""

    return recipients


async def prune_old_material_events(days: int = 90) -> int:
    """Видаляє події та записи отримувачів старші за days днів."""
    async with aiosqlite.connect(NOTIFICATIONS_DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM material_change_events WHERE created_at < datetime('now', ?)",
            (f"-{days} days",)
        )
        deleted_count = cursor.rowcount
        # Also clean orphaned recipients
        await db.execute(
            "DELETE FROM material_change_recipients WHERE event_id NOT IN (SELECT id FROM material_change_events)"
        )
        await db.commit()
        return max(0, deleted_count)


async def get_all_material_events(days_limit: int = 90) -> List[Dict[str, Any]]:
    """
    Повертає список усіх подій за останні days_limit днів, відсортованих за created_at DESC.
    """
    async with aiosqlite.connect(NOTIFICATIONS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = '''
        SELECT id, role, day, content_type, description, pages_json, created_at, status
        FROM material_change_events
        WHERE created_at >= datetime('now', ?)
        ORDER BY created_at DESC
        '''
        async with db.execute(query, (f"-{days_limit} days",)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def get_event_overall_stats(event_id: int) -> Dict[str, Any]:
    """
    Рахує загальну статистику події (по всіх ролях разом):
    - total
    - acknowledged_count
    - acknowledged_late_count
    - unacknowledged_count
    - ack_percent
    - unack_percent
    """
    async with aiosqlite.connect(NOTIFICATIONS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT COUNT(*) FROM material_change_recipients WHERE event_id = ?",
            (event_id,)
        ) as cursor:
            total = (await cursor.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(*) FROM material_change_recipients WHERE event_id = ? AND acknowledged_at IS NOT NULL",
            (event_id,)
        ) as cursor:
            ack_count = (await cursor.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(*) FROM material_change_recipients WHERE event_id = ? AND acknowledged_at IS NOT NULL AND is_late = 1",
            (event_id,)
        ) as cursor:
            ack_late_count = (await cursor.fetchone())[0]

        unack_count = max(0, total - ack_count)
        return {
            'total': total,
            'acknowledged_count': ack_count,
            'acknowledged_late_count': ack_late_count,
            'unacknowledged_count': unack_count,
            'ack_percent': round((ack_count / total * 100), 1) if total > 0 else 0.0,
            'unack_percent': round((unack_count / total * 100), 1) if total > 0 else 0.0
        }


async def get_event_shops_summary(event_id: int) -> List[Dict[str, Any]]:
    """
    Повертає список унікальних магазинів для події із загальною кількістю отримувачів
    та кількістю тих, хто ознайомився:
    [{'shop': 'b-12', 'total_count': 4, 'ack_count': 3}, ...]
    """
    query = '''
    SELECT 
        shop,
        COUNT(*) as total_count,
        SUM(CASE WHEN acknowledged_at IS NOT NULL THEN 1 ELSE 0 END) as ack_count
    FROM material_change_recipients
    WHERE event_id = ?
    GROUP BY shop
    ORDER BY 
        CASE 
            WHEN shop LIKE 'Всі магазини%' THEN 1
            ELSE 0
        END ASC,
        shop ASC
    '''
    async with aiosqlite.connect(NOTIFICATIONS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, (event_id,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def get_event_all_shop_users(event_id: int, shop: str) -> List[Dict[str, Any]]:
    """
    Повертає всіх отримувачів зазначеного магазину для події,
    збагачених ПІБ та username, відсортованих:
    1) Керівники
    2) Працівники
    3) Стажери
    4) Територіали / інші
    """
    async with aiosqlite.connect(NOTIFICATIONS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = '''
        SELECT id, user_id, role_type, shop, city, sent_at, acknowledged_at, is_late
        FROM material_change_recipients
        WHERE event_id = ? AND shop = ?
        ORDER BY 
            CASE LOWER(role_type)
                WHEN 'керівник' THEN 1
                WHEN 'працівник' THEN 2
                WHEN 'стажер' THEN 3
                WHEN 'територіал' THEN 4
                ELSE 5
            END ASC,
            acknowledged_at DESC,
            id ASC
        '''
        async with db.execute(query, (event_id, shop)) as cursor:
            recipients = [dict(r) for r in await cursor.fetchall()]

    # Збагачуємо ПІБ та username з users.db, managers.db або hr_users
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        for rec in recipients:
            uid = rec['user_id']
            full_name = None
            username = None
            async with db.execute("SELECT full_name, username FROM users WHERE user_id = ?", (uid,)) as cursor:
                u_row = await cursor.fetchone()
                if u_row:
                    full_name = (u_row['full_name'] or "").strip()
                    username = (u_row['username'] or "").strip()

            if not full_name:
                try:
                    async with aiosqlite.connect(MANAGERS_DB_PATH) as m_db:
                        m_db.row_factory = aiosqlite.Row
                        async with m_db.execute("SELECT full_name, username FROM managers WHERE uid = ?", (uid,)) as m_cursor:
                            m_row = await m_cursor.fetchone()
                            if m_row:
                                full_name = (m_row['full_name'] or "").strip()
                                if not username:
                                    username = (m_row['username'] or "").strip()
                except Exception:
                    pass

            if not full_name:
                try:
                    async with db.execute("SELECT full_name, username FROM hr_users WHERE user_id = ?", (uid,)) as hr_cursor:
                        hr_row = await hr_cursor.fetchone()
                        if hr_row:
                            full_name = (hr_row['full_name'] or "").strip()
                            if not username:
                                username = (hr_row['username'] or "").strip()
                except Exception:
                    pass

            rec['full_name'] = full_name or (f"@{username}" if username else f"ID {uid}")
            rec['username'] = username or ""

    return recipients
