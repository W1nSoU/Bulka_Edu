from __future__ import annotations
import aiosqlite
from . import DB_PATH
import json

MANAGERS_DB_PATH = DB_PATH.replace("users.db", "managers.db")

async def init_managers_db():
    """Ініціалізація бази даних керівників"""
    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        await db.execute('''
        CREATE TABLE IF NOT EXISTS managers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid INTEGER UNIQUE,
            process TEXT,
            full_name TEXT,
            username TEXT,
            shops TEXT,
            city TEXT,
            responsible_uid INTEGER,
            territorial_type TEXT,
            status TEXT DEFAULT 'active',
            fired_at TIMESTAMP DEFAULT NULL
        )
        ''')
        
        # Перевіряємо та додаємо колонки, якщо вони не існують
        cursor = await db.execute("PRAGMA table_info(managers)")
        columns = [row[1] for row in await cursor.fetchall()]
        
        if 'shops' not in columns:
            await db.execute("ALTER TABLE managers ADD COLUMN shops TEXT")
            
        if 'city' not in columns:
            await db.execute("ALTER TABLE managers ADD COLUMN city TEXT")

        if 'responsible_uid' not in columns:
            await db.execute("ALTER TABLE managers ADD COLUMN responsible_uid INTEGER")

        if 'territorial_type' not in columns:
            await db.execute("ALTER TABLE managers ADD COLUMN territorial_type TEXT")

        if 'status' not in columns:
            await db.execute("ALTER TABLE managers ADD COLUMN status TEXT DEFAULT 'active'")
            await db.execute("UPDATE managers SET status = 'active' WHERE status IS NULL")

        if 'fired_at' not in columns:
            await db.execute("ALTER TABLE managers ADD COLUMN fired_at TIMESTAMP DEFAULT NULL")

        # Автоматично додаємо/синхронізуємо MAIN_DEVELOPER_ID як Developer
        try:
            from bot.config import MAIN_DEVELOPER_ID
            if MAIN_DEVELOPER_ID > 0:
                cursor = await db.execute("SELECT uid, status FROM managers WHERE uid = ?", (MAIN_DEVELOPER_ID,))
                row = await cursor.fetchone()
                if not row:
                    async with aiosqlite.connect(DB_PATH) as u_db:
                        u_cur = await u_db.execute("SELECT full_name, username FROM users WHERE user_id = ?", (MAIN_DEVELOPER_ID,))
                        u_data = await u_cur.fetchone()
                    full_name = u_data[0] if u_data and u_data[0] else "Головний Адміністратор"
                    username = u_data[1] if u_data and u_data[1] else None
                    await db.execute(
                        "INSERT INTO managers (uid, process, full_name, username, status) VALUES (?, 'Developer', ?, ?, 'active')",
                        (MAIN_DEVELOPER_ID, full_name, username)
                    )
                elif row[1] == 'fired':
                    await db.execute("UPDATE managers SET status = 'active', process = 'Developer' WHERE uid = ?", (MAIN_DEVELOPER_ID,))
        except Exception:
            pass

        await db.commit()

async def add_manager(uid, process, full_name=None, username=None, shops: list = None, city: str = None, responsible_uid: int = None, territorial_type: str = None):
    """
    Додає керівника вручну за UID та посадою.
    Якщо full_name та username не передані, вони підтягуються з таблиці users.
    territorial_type — для Територіалів: 'ТЗ' або 'ВВ'
    """
    shops_json = json.dumps(shops) if shops else None
    async with aiosqlite.connect(DB_PATH) as users_db, aiosqlite.connect(MANAGERS_DB_PATH) as managers_db:
        # Якщо ім'я або username не надані, спробувати отримати їх з таблиці users
        if full_name is None or username is None:
            cursor = await users_db.execute("SELECT username, full_name FROM users WHERE user_id = ?", (uid,))
            row = await cursor.fetchone()
            if row:
                username_from_db, full_name_from_db = row
                if username is None:
                    username = username_from_db
                if full_name is None:
                    full_name = full_name_from_db

        if responsible_uid is None:
            cursor = await managers_db.execute("SELECT responsible_uid FROM managers WHERE uid = ?", (uid,))
            row = await cursor.fetchone()
            if row and row[0] is not None:
                responsible_uid = row[0]

        # Забезпечуємо, що значення не будуть None
        username = username if username else ""
        full_name = full_name if full_name else ""

        await managers_db.execute(
            """INSERT INTO managers (uid, username, full_name, process, shops, city, responsible_uid, territorial_type, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')
               ON CONFLICT(uid) DO UPDATE SET
                 username=excluded.username,
                 full_name=excluded.full_name,
                 process=excluded.process,
                 shops=excluded.shops,
                 city=excluded.city,
                 responsible_uid=excluded.responsible_uid,
                 territorial_type=excluded.territorial_type,
                 status='active',
                 fired_at=NULL""",
            (uid, username, full_name, process, shops_json, city, responsible_uid, territorial_type)
        )
        await managers_db.commit()

async def get_manager_by_uid(uid):
    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM managers WHERE uid = ?", (uid,))
        manager_row = await cursor.fetchone()
        if not manager_row:
            return None
        
        manager = dict(manager_row)
        if manager.get("shops"):
            try:
                manager["shops"] = json.loads(manager["shops"])
            except (json.JSONDecodeError, TypeError):
                manager["shops"] = []
        else:
            manager["shops"] = []
            
        return manager

async def get_all_managers():
    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM managers")
        manager_rows = await cursor.fetchall()
        managers = []
        for row in manager_rows:
            manager = dict(row)
            if manager.get("shops"):
                try:
                    manager["shops"] = json.loads(manager["shops"])
                except (json.JSONDecodeError, TypeError):
                    manager["shops"] = []
            else:
                manager["shops"] = []
            managers.append(manager)
        return managers

async def delete_manager_by_uid(uid, cascade_user: bool = True):
    """Видаляє керівника за його Telegram ID (hard delete) та очищає всі пов'язані дані."""
    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        cursor = await db.execute("SELECT process FROM managers WHERE uid = ?", (uid,))
        row = await cursor.fetchone()
        if row and row[0] == "Територіал":
            await db.execute("UPDATE managers SET responsible_uid = NULL WHERE responsible_uid = ?", (uid,))

        await db.execute("DELETE FROM managers WHERE uid = ?", (uid,))
        await db.commit()

    # Також видаляємо з hr_users та з users.db при cascade_user=True
    try:
        async with aiosqlite.connect(DB_PATH) as u_db:
            await u_db.execute("DELETE FROM hr_users WHERE user_id = ?", (uid,))
            if cascade_user:
                await u_db.execute("DELETE FROM users WHERE user_id = ?", (uid,))
                await u_db.execute("DELETE FROM progress WHERE user_id = ?", (uid,))
                await u_db.execute("UPDATE conversations SET status = 'closed' WHERE manager_id = ? OR user_id = ?", (uid, uid))
                await u_db.execute("UPDATE users SET manager_id = NULL WHERE manager_id = ?", (uid,))
                await u_db.execute("DELETE FROM reminder_history WHERE intern_id = ? OR sender_id = ?", (uid, uid))
                await u_db.execute("DELETE FROM support_logs WHERE user_id = ?", (uid,))
            await u_db.commit()
    except Exception as e:
        print(f"Error cascading manager deletion to users.db: {e}")

    try:
        from database.material_notifications import NOTIF_DB_PATH
        async with aiosqlite.connect(NOTIF_DB_PATH) as ndb:
            await ndb.execute("DELETE FROM material_change_recipients WHERE user_id = ?", (uid,))
            await ndb.commit()
    except Exception:
        pass

    return None

async def get_all_developers():
    """Отримує список всіх адміністраторів (Developer), включаючи MAIN_DEVELOPER_ID та hr_users."""
    from bot.config import MAIN_DEVELOPER_ID

    devs_by_uid = {}

    # 1. Головний розробник з конфігурації
    if MAIN_DEVELOPER_ID > 0:
        devs_by_uid[MAIN_DEVELOPER_ID] = {
            "uid": MAIN_DEVELOPER_ID,
            "process": "Developer",
            "full_name": "Головний Адміністратор",
            "username": None,
            "status": "active"
        }

    # 2. Адміністратори з managers.db
    managers = await get_all_managers()
    for m in managers:
        if m.get("process") == "Developer" and (m.get("status") == "active" or m.get("status") is None):
            devs_by_uid[m["uid"]] = m

    # 3. Адміністратори з hr_users (users.db)
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT user_id as uid, username, full_name, 'Developer' as process, 'active' as status FROM hr_users WHERE role = 'Developer'")
            for row in await cursor.fetchall():
                d = dict(row)
                if d["uid"] not in devs_by_uid:
                    devs_by_uid[d["uid"]] = d
    except Exception:
        pass

    # 4. Збагачуємо актуальними іменами з users.db
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            for uid, dev in list(devs_by_uid.items()):
                cursor = await db.execute("SELECT full_name, username FROM users WHERE user_id = ?", (uid,))
                u_row = await cursor.fetchone()
                if u_row:
                    if u_row["full_name"]:
                        dev["full_name"] = u_row["full_name"]
                    if u_row["username"]:
                        dev["username"] = u_row["username"]
    except Exception:
        pass

    return list(devs_by_uid.values())

async def get_all_kerivnyky():
    """Отримує список всіх активних керівників з роллю 'Керівник' або 'Керівник Стажер'."""
    managers = await get_all_managers()
    return [
        m for m in managers
        if m.get("process") in ("Керівник", "Керівник Стажер") and (m.get("status") == "active" or m.get("status") is None)
    ]

async def is_manager_user(user_id: int) -> bool:
    """Перевіряє, чи користувач є активним керівником (роль 'Керівник' або 'Керівник Стажер') у таблиці managers."""
    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        cursor = await db.execute(
            "SELECT uid FROM managers WHERE uid = ? AND process IN ('Керівник', 'Керівник Стажер') AND (status = 'active' OR status IS NULL)",
            (user_id,)
        )
        return bool(await cursor.fetchone())

async def is_manager_trainee(user_id: int) -> bool:
    """Перевіряє, чи є керівник стажером ('Керівник Стажер')."""
    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        cursor = await db.execute(
            "SELECT uid FROM managers WHERE uid = ? AND process = 'Керівник Стажер' AND (status = 'active' OR status IS NULL)",
            (user_id,)
        )
        return bool(await cursor.fetchone())

async def promote_manager_trainee(uid: int) -> bool:
    """Переводить керівника-стажера в статус повноцінного 'Керівник'."""
    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        await db.execute(
            "UPDATE managers SET process = 'Керівник' WHERE uid = ? AND process = 'Керівник Стажер'",
            (uid,)
        )
        await db.commit()
        
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET status = 'Працівник' WHERE user_id = ?",
            (uid,)
        )
        await db.commit()
    return True

async def get_manager_trainees_by_territorial(territorial_uid: int) -> list[dict]:
    """Отримує список керівників-стажерів, закріплених за певним територіалом."""
    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM managers WHERE responsible_uid = ? AND process = 'Керівник Стажер' AND (status = 'active' OR status IS NULL) ORDER BY full_name ASC",
            (territorial_uid,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def get_all_territorials():
    """Отримує список всіх активних керівників з роллю 'Територіал'."""
    managers = await get_all_managers()
    return [
        m for m in managers
        if m.get("process") == "Територіал" and (m.get("status") == "active" or m.get("status") is None)
    ]

async def update_manager_responsible(manager_uid: int, responsible_uid = None):
    """Оновлює відповідального для конкретного керівника."""
    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        await db.execute("UPDATE managers SET responsible_uid = ? WHERE uid = ?", (responsible_uid, manager_uid))
        await db.commit()

async def reassign_city_managers_to_territorial(city: str, territorial_uid: int) -> int:
    """Призначає нового територіала відповідальним за всіх активних керівників та керівників-стажерів певного міста."""
    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE managers SET responsible_uid = ? WHERE city = ? AND process IN ('Керівник', 'Керівник Стажер') AND (status = 'active' OR status IS NULL)",
            (territorial_uid, city)
        )
        await db.commit()
        return cursor.rowcount

async def is_territorial_user(user_id: int) -> bool:
    """Перевіряє, чи користувач є активним територіалом у таблиці managers."""
    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        cursor = await db.execute(
            "SELECT uid FROM managers WHERE uid = ? AND process = 'Територіал' AND (status = 'active' OR status IS NULL)",
            (user_id,)
        )
        return bool(await cursor.fetchone())

async def get_managers_by_responsible(territorial_uid: int) -> list[dict]:
    """Отримує список всіх активних керівників, які підпорядковуються конкретному територіалу."""
    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM managers WHERE responsible_uid = ? AND process IN ('Керівник', 'Керівник Стажер') AND (status = 'active' OR status IS NULL) ORDER BY full_name",
            (territorial_uid,)
        )
        rows = await cursor.fetchall()
        managers = []
        for row in rows:
            manager = dict(row)
            if manager.get("shops"):
                try:
                    manager["shops"] = json.loads(manager["shops"])
                except (json.JSONDecodeError, TypeError):
                    manager["shops"] = []
            else:
                manager["shops"] = []
            managers.append(manager)
        return managers

async def get_territorials_by_city(city: str) -> list[dict]:
    """Отримує список активних Територіалів певного міста."""
    managers = await get_all_managers()
    return [
        m for m in managers
        if m.get('process') == 'Територіал' and m.get('city') == city and (m.get('status') == 'active' or m.get('status') is None)
    ]

async def update_manager_name(uid: int, new_name: str) -> bool:
    """Оновлює ПІБ керівника в таблиці managers та таблиці users."""
    try:
        async with aiosqlite.connect(MANAGERS_DB_PATH) as m_db, aiosqlite.connect(DB_PATH) as u_db:
            await m_db.execute("UPDATE managers SET full_name = ? WHERE uid = ?", (new_name, uid))
            await m_db.commit()
            await u_db.execute("UPDATE users SET full_name = ? WHERE user_id = ?", (new_name, uid))
            await u_db.commit()
        return True
    except Exception as e:
        print(f"Error updating manager name: {e}")
        return False

async def update_manager_shops(uid: int, city: str, new_shops: list) -> bool:
    """Оновлює місто та список магазинів керівника."""
    shops_json = json.dumps(new_shops) if new_shops else None
    try:
        async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
            await db.execute(
                "UPDATE managers SET city = ?, shops = ? WHERE uid = ?",
                (city, shops_json, uid)
            )
            await db.commit()
        return True
    except Exception as e:
        print(f"Error updating manager shops: {e}")
        return False

async def fire_manager(uid: int) -> dict:
    """
    Звільняє керівника:
    1. Переводить статус у 'fired', фіксує fired_at.
    2. Знаходить відповідного Територіала (закріпленого або за містом). Якщо немає — NULL (Адміністратор).
    3. Тихо переводить усіх стажерів та працівників керівника на нового відповідального.
    4. Закриває відкриті сесії спілкування.
    """
    manager = await get_manager_by_uid(uid)
    target_uid = None
    target_name = "Адміністратор"
    
    if manager:
        # Спочатку перевіряємо закріпленого територіала
        if manager.get("responsible_uid"):
            target_uid = manager["responsible_uid"]
            resp_mgr = await get_manager_by_uid(target_uid)
            if resp_mgr:
                target_name = f"Територіал {resp_mgr.get('full_name', '')}"
        else:
            # Шукаємо територіала по місту
            city_territorials = await get_territorials_by_city(manager.get("city", ""))
            if city_territorials:
                target_uid = city_territorials[0]["uid"]
                target_name = f"Територіал {city_territorials[0].get('full_name', '')}"

    # Переводимо стажерів та закриваємо бесіди в users.db
    transferred_count = 0
    async with aiosqlite.connect(DB_PATH) as u_db:
        # Рахуємо скільки переносимо
        cursor = await u_db.execute("SELECT COUNT(*) FROM users WHERE manager_id = ?", (uid,))
        row = await cursor.fetchone()
        transferred_count = row[0] if row else 0
        
        # Переприв'язуємо користувачів
        await u_db.execute(
            "UPDATE users SET manager_id = ? WHERE manager_id = ?",
            (target_uid, uid)
        )
        
        # Закриваємо відкриті бесіди
        await u_db.execute(
            "UPDATE conversations SET status = 'closed' WHERE manager_id = ? AND status = 'open'",
            (uid,)
        )
        await u_db.commit()

    # Повністю видаляємо керівника з managers.db та користувача з users.db
    await delete_manager_by_uid(uid, cascade_user=True)

    return {
        "success": True,
        "target_uid": target_uid,
        "target_name": target_name,
        "transferred_count": transferred_count
    }

async def search_managers(query: str, is_admin: bool = True, territorial_uid: int = None) -> list[dict]:
    """
    Пошук активних керівників за ПІБ, username або Telegram ID.
    Якщо is_admin=False, шукає лише серед підлеглих territorial_uid.
    """
    query = query.strip().lower()
    if not query:
        return []

    if is_admin:
        managers = await get_all_kerivnyky()
    elif territorial_uid:
        managers = await get_managers_by_responsible(territorial_uid)
    else:
        managers = []

    clean_query = query.lstrip("@")
    results = []
    
    for m in managers:
        uid_str = str(m.get("uid", ""))
        full_name = (m.get("full_name") or "").lower()
        username = (m.get("username") or "").lower().lstrip("@")
        
        # Перевірка за числовим ID
        if query == uid_str:
            results.append(m)
            continue
            
        # Перевірка за username
        if clean_query and clean_query in username:
            results.append(m)
            continue
            
        # Перевірка за частинами імені/прізвища
        if any(part in full_name for part in query.split()):
            results.append(m)
            continue

    return results

async def transfer_users_to_territorial_or_admin(from_manager_uid: int) -> int:
    """Тихо переносить усіх стажерів та працівників керівника до його Територіала або Адміна."""
    manager = await get_manager_by_uid(from_manager_uid)
    target_uid = None
    if manager:
        if manager.get("responsible_uid"):
            target_uid = manager["responsible_uid"]
        else:
            city_territorials = await get_territorials_by_city(manager.get("city", ""))
            if city_territorials:
                target_uid = city_territorials[0]["uid"]

    async with aiosqlite.connect(DB_PATH) as u_db:
        cursor = await u_db.execute("SELECT COUNT(*) FROM users WHERE manager_id = ?", (from_manager_uid,))
        row = await cursor.fetchone()
        count = row[0] if row else 0
        
        await u_db.execute("UPDATE users SET manager_id = ? WHERE manager_id = ?", (target_uid, from_manager_uid))
        await u_db.commit()
        return count

async def count_users_in_shops(city: str, shop_names: list[str]) -> tuple[int, int]:
    """Рахує кількість стажерів та працівників у заданих магазинах міста."""
    if not shop_names:
        return 0, 0
    placeholders = ",".join("?" for _ in shop_names)
    async with aiosqlite.connect(DB_PATH) as db:
        # Стажери
        cursor_interns = await db.execute(
            f"SELECT COUNT(*) FROM users WHERE city = ? AND shop IN ({placeholders}) AND (status IS NULL OR status != 'Працівник')",
            (city, *shop_names)
        )
        interns_count = (await cursor_interns.fetchone())[0]
        
        # Працівники
        cursor_workers = await db.execute(
            f"SELECT COUNT(*) FROM users WHERE city = ? AND shop IN ({placeholders}) AND status = 'Працівник'",
            (city, *shop_names)
        )
        workers_count = (await cursor_workers.fetchone())[0]
        
        return interns_count, workers_count

async def transfer_users_by_shops(city: str, shop_names: list[str], target_manager_uid: int) -> int:
    """Переносить користувачів зазначених магазинів на target_manager_uid."""
    if not shop_names:
        return 0
    placeholders = ",".join("?" for _ in shop_names)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            f"SELECT COUNT(*) FROM users WHERE city = ? AND shop IN ({placeholders})",
            (city, *shop_names)
        )
        count = (await cursor.fetchone())[0]
        
        await db.execute(
            f"UPDATE users SET manager_id = ? WHERE city = ? AND shop IN ({placeholders})",
            (target_manager_uid, city, *shop_names)
        )
        await db.commit()
        return count


async def get_appropriate_territorial_for_user(city: str, role: str) -> int | None:
    """
    Знаходить найбільш підходящого активного Територіала для міста та посади:
    - За напрямком посади (ТЗ або ВВ)
    - Для РЦ та ОФІС територіали не призначаються (повертає None)
    - Якщо точного збігу немає - першого активного територіала міста
    - Якщо в місті немає територіалів - None
    """
    from database.positions import get_position_direction
    direction = await get_position_direction(role or "")
    if direction in ("РЦ", "ОФІС"):
        return None
    territorials = await get_territorials_by_city(city)
    if not territorials:
        return None
    for t in territorials:
        if t.get("territorial_type") == direction:
            return t["uid"]
    return territorials[0]["uid"]


async def get_manager_by_shop(city: str, shop: str) -> dict | None:
    """
    Шукає активного керівника, закріпленого за зазначеним магазином у місті.
    """
    if not shop:
        return None
    managers = await get_all_kerivnyky()
    for m in managers:
        m_city = m.get("city")
        if m_city and city and m_city != city:
            continue
        m_shops = m.get("shops") or []
        if isinstance(m_shops, str):
            try:
                m_shops = json.loads(m_shops)
            except Exception:
                m_shops = [m_shops]
        if shop in m_shops:
            return m
    return None


async def reassign_removed_shops_users_to_territorial(city: str, removed_shops: list[str], manager_uid: int) -> int:
    """
    Переводить користувачів (стажерів і працівників) відкріплених магазинів від цього керівника
    до відповідного Територіала міста (ТЗ або ВВ) та закриває відкриті бесіди з колишнім керівником.
    """
    if not removed_shops:
        return 0
    placeholders = ",".join("?" for _ in removed_shops)
    reassigned_count = 0
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT user_id, role FROM users WHERE city = ? AND shop IN ({placeholders}) AND manager_id = ?",
            (city, *removed_shops, manager_uid)
        )
        users_to_move = await cursor.fetchall()
        for u in users_to_move:
            u_id = u["user_id"]
            u_role = u["role"] or ""
            target_t_uid = await get_appropriate_territorial_for_user(city, u_role)
            await db.execute("UPDATE users SET manager_id = ? WHERE user_id = ?", (target_t_uid, u_id))
            reassigned_count += 1
            
        if reassigned_count > 0:
            await db.execute(
                "UPDATE conversations SET status = 'closed' WHERE manager_id = ? AND status = 'open'",
                (manager_uid,)
            )
            await db.commit()
            
    return reassigned_count


async def count_unassigned_or_territorial_users_in_shops(city: str, shop_names: list[str], exclude_manager_uid: int = None) -> tuple[int, int]:
    """
    Рахує кількість стажерів та працівників у заданих магазинах, які закріплені за Територіалом або Адміністратором
    (тобто не підпорядковані іншому діючому керівнику магазину).
    """
    if not shop_names:
        return 0, 0
    placeholders = ",".join("?" for _ in shop_names)
    active_store_managers = await get_all_kerivnyky()
    other_store_mgr_uids = set(
        m["uid"] for m in active_store_managers
        if exclude_manager_uid is None or m.get("uid") != exclude_manager_uid
    )
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT user_id, manager_id, status FROM users WHERE city = ? AND shop IN ({placeholders})",
            (city, *shop_names)
        )
        rows = await cursor.fetchall()
        
    interns_count = 0
    workers_count = 0
    for r in rows:
        m_id = r["manager_id"]
        # Якщо вже під цим керівником - пропускаємо
        if exclude_manager_uid and m_id == exclude_manager_uid:
            continue
        # Якщо під іншим діючим керівником магазину - не чіпаємо
        if m_id in other_store_mgr_uids:
            continue
        # Інакше (під Територіалом, Адміном або NULL)
        if r["status"] == "Працівник":
            workers_count += 1
        else:
            interns_count += 1
            
    return interns_count, workers_count


async def transfer_shop_users_to_manager(city: str, shop_names: list[str], target_manager_uid: int) -> int:
    """
    Переводить стажерів та працівників обраних магазинів (які були під Територіалом/Адміном) під target_manager_uid.
    """
    if not shop_names:
        return 0
    placeholders = ",".join("?" for _ in shop_names)
    active_store_managers = await get_all_kerivnyky()
    other_store_mgr_uids = set(
        m["uid"] for m in active_store_managers
        if m.get("uid") != target_manager_uid
    )
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT user_id, manager_id FROM users WHERE city = ? AND shop IN ({placeholders})",
            (city, *shop_names)
        )
        rows = await cursor.fetchall()
        
        target_user_ids = [
            r["user_id"] for r in rows
            if r["manager_id"] != target_manager_uid and r["manager_id"] not in other_store_mgr_uids
        ]
        
        if target_user_ids:
            u_placeholders = ",".join("?" for _ in target_user_ids)
            await db.execute(
                f"UPDATE users SET manager_id = ? WHERE user_id IN ({u_placeholders})",
                (target_manager_uid, *target_user_ids)
            )
            await db.commit()
            
        return len(target_user_ids)


async def get_all_observers() -> list[dict]:
    """Отримує список всіх активних наглядачів (process='Наглядач')."""
    managers = await get_all_managers()
    return [
        m for m in managers
        if m.get("process") == "Наглядач" and (m.get("status") == "active" or m.get("status") is None)
    ]

async def is_observer_user(user_id: int) -> bool:
    """Перевіряє, чи користувач є активним наглядачем."""
    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        cursor = await db.execute(
            "SELECT uid FROM managers WHERE uid = ? AND process = 'Наглядач' AND (status = 'active' OR status IS NULL)",
            (user_id,)
        )
        return bool(await cursor.fetchone())

async def get_observer_by_uid(uid: int) -> dict | None:
    """Отримує дані наглядача за UID."""
    manager = await get_manager_by_uid(uid)
    if manager and manager.get("process") == "Наглядач" and (manager.get("status") == "active" or manager.get("status") is None):
        return manager
    return None

async def add_observer(uid: int, full_name: str, username: str | None, responsible_uid: int | None = None) -> bool:
    """Додає або оновлює наглядача в базі managers."""
    await add_manager(
        uid=uid,
        username=username or "",
        full_name=full_name,
        process="Наглядач",
        responsible_uid=responsible_uid
    )
    return True

async def delete_observer_by_uid(uid: int) -> bool:
    """Видаляє наглядача з бази managers та очищає пов'язані дані."""
    await delete_manager_by_uid(uid, cascade_user=True)
    return True


async def is_user_without_store_manager(user: dict) -> bool:
    """
    Визначає, чи у користувача немає активного керівника магазину:
    1. manager_id відсутній (None)
    2. АБО manager_id є ID Територіала (закріплений на територіала тимчасово через відсутність керівника)
    3. АБО для магазину користувача в його місті немає активного керівника в managers.
    4. АБО закріплений керівник має статус 'fired'.
    """
    manager_id = user.get("manager_id")
    if not manager_id:
        return True
    
    # Якщо manager_id належить територіалу - це тимчасова прив'язка через відсутність керівника
    if await is_territorial_user(manager_id):
        return True
        
    city = user.get("city")
    shop = user.get("shop")
    if city and shop:
        shop_mgr = await get_manager_by_shop(city, shop)
        if not shop_mgr or shop_mgr.get("status") == "fired":
            return True
            
    # Перевіряємо чи сам закріплений керівник активний
    mgr = await get_manager_by_uid(manager_id)
    if not mgr or mgr.get("status") == "fired":
        return True

    return False


async def get_city_supervisors(city: str, target_shop: str = None) -> dict:
    """
    Повертає структурований список діючих керівників та територіалів для вказаного міста:
    {
        "shop_managers": [...],   # керівники, за якими закріплений target_shop
        "other_managers": [...],  # інші діючі керівники цього міста
        "territorials": [...]     # діючі територіали цього міста
    }
    """
    if not city:
        return {"shop_managers": [], "other_managers": [], "territorials": []}

    norm_city = city.strip().lower()
    shop_managers = []
    other_managers = []
    territorials = []

    async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM managers WHERE (status = 'active' OR status IS NULL) ORDER BY full_name ASC"
        )
        rows = await cursor.fetchall()
        for r in rows:
            m = dict(r)
            m_city = (m.get("city") or "").strip().lower()
            if m_city != norm_city:
                continue

            proc = m.get("process")
            if proc == "Територіал":
                territorials.append(m)
            elif proc in ("Керівник", "Керівник Стажер"):
                m_shops = []
                try:
                    if m.get("shops"):
                        m_shops = json.loads(m["shops"])
                except Exception:
                    pass
                m["shops_list"] = m_shops

                if target_shop and any(target_shop.strip().lower() in s.strip().lower() or s.strip().lower() in target_shop.strip().lower() for s in m_shops):
                    shop_managers.append(m)
                else:
                    other_managers.append(m)

    return {
        "shop_managers": shop_managers,
        "other_managers": other_managers,
        "territorials": territorials
    }
