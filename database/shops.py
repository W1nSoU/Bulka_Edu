"""
database/shops.py
=================
Сервісний шар для роботи з таблицею `shops` (торгові точки).

Джерело правди для магазинів у системі — таблиця `shops` у `database/users.db`.
`AVAILABLE_SHOPS` у `bot/constants.py` використовується для первинного auto-seed
та як безпечний fallback.
"""

from __future__ import annotations

import json
import logging
from typing import Optional, Dict, Any, List, Tuple

import aiosqlite

from . import DB_PATH

logger = logging.getLogger(__name__)

MANAGERS_DB_PATH = DB_PATH.replace("users.db", "managers.db")
TOKENS_DB_PATH = DB_PATH.replace("users.db", "tokens.db")


# ---------------------------------------------------------------------------
# Ініціалізація та Auto-Seed
# ---------------------------------------------------------------------------

async def init_shops_db() -> None:
    """
    Створює таблицю `shops` (якщо не існує) та виконує органічний auto-seed
    з `AVAILABLE_SHOPS`, а також гарантовано підтягує всі існуючі магазини
    користувачів із `users.db` та керівників із `managers.db`.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS shops (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                city TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        await db.commit()

        # 1. Заповнення з AVAILABLE_SHOPS (INSERT OR IGNORE гарантує відсутність дублікатів)
        try:
            from bot.constants import AVAILABLE_SHOPS
            inserted = 0
            for city, shop_list in AVAILABLE_SHOPS.items():
                for shop_name in shop_list:
                    await db.execute(
                        "INSERT OR IGNORE INTO shops (name, city) VALUES (?, ?)",
                        (shop_name.strip(), city.strip())
                    )
                    inserted += 1
            await db.commit()
            logger.info("Auto-seed магазинів з AVAILABLE_SHOPS перевірено/виконано.")
        except Exception as e:
            logger.error(f"Помилка під час auto-seed таблиці `shops` з AVAILABLE_SHOPS: {e}")

        # 2. Органічна міграція існуючих магазинів користувачів із users.db
        try:
            cursor = await db.execute(
                "SELECT DISTINCT shop, city FROM users WHERE shop IS NOT NULL AND shop != ''"
            )
            user_shops = await cursor.fetchall()
            for r in user_shops:
                u_shop = (r[0] or "").strip()
                u_city = (r[1] or "Хмельницький").strip()
                if u_shop:
                    await db.execute(
                        "INSERT OR IGNORE INTO shops (name, city) VALUES (?, ?)",
                        (u_shop, u_city)
                    )
            await db.commit()
        except Exception as e:
            logger.warning(f"Помилка перевірки існуючих магазинів у users: {e}")

        # 3. Органічна міграція магазинів керівників із managers.db
        try:
            async with aiosqlite.connect(MANAGERS_DB_PATH) as mdb:
                mdb.row_factory = aiosqlite.Row
                cursor = await mdb.execute("SELECT city, shops FROM managers WHERE shops IS NOT NULL")
                rows = await cursor.fetchall()
                for row in rows:
                    m_city = (row["city"] or "Хмельницький").strip()
                    m_shops = row["shops"]
                    if not m_shops:
                        continue
                    try:
                        s_list = json.loads(m_shops) if isinstance(m_shops, str) else list(m_shops)
                    except Exception:
                        s_list = [m_shops] if isinstance(m_shops, str) else []
                    for s in s_list:
                        if isinstance(s, str) and s.strip():
                            await db.execute(
                                "INSERT OR IGNORE INTO shops (name, city) VALUES (?, ?)",
                                (s.strip(), m_city)
                            )
            await db.commit()
        except Exception as e:
            logger.warning(f"Помилка перевірки існуючих магазинів у managers.db: {e}")


# ---------------------------------------------------------------------------
# Читання
# ---------------------------------------------------------------------------

async def get_cities_with_shops() -> List[Dict[str, Any]]:
    """
    Повертає список міст з кількістю магазинів у кожному.
    Також включає міста з таблиці `cities`, навіть якщо в них ще немає магазинів.
    """
    result: List[Dict[str, Any]] = []
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Отримуємо всі міста з таблиці cities
        cursor = await db.execute("SELECT name FROM cities ORDER BY name")
        all_cities = [row["name"] for row in await cursor.fetchall()]

        # Отримуємо кількість магазинів по містах
        cursor = await db.execute(
            "SELECT city, COUNT(*) as shop_count FROM shops GROUP BY city"
        )
        shop_counts = {row["city"]: row["shop_count"] for row in await cursor.fetchall()}

        # Якщо таблиця cities ще порожня, беремо унікальні міста з shops
        combined_cities = sorted(list(set(all_cities) | set(shop_counts.keys())))
        for city in combined_cities:
            result.append({
                "city": city,
                "shop_count": shop_counts.get(city, 0)
            })

    return result


async def get_shops_by_city(city: str) -> List[Dict[str, Any]]:
    """Повертає список магазинів для вказаного міста."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, name, city, created_at FROM shops WHERE city = ? ORDER BY name",
            (city.strip(),)
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_all_shops() -> List[Dict[str, Any]]:
    """Повертає всі магазини в системі."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, name, city, created_at FROM shops ORDER BY city, name"
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_shop_by_id(shop_id: int) -> Optional[Dict[str, Any]]:
    """Повертає магазин за його id."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, name, city, created_at FROM shops WHERE id = ?",
            (shop_id,)
        )
        row = await cursor.fetchone()
    return dict(row) if row else None


async def get_shop_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Повертає магазин за його точною назвою."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, name, city, created_at FROM shops WHERE name = ?",
            (name.strip(),)
        )
        row = await cursor.fetchone()
    return dict(row) if row else None


async def count_users_in_shop(shop_name: str) -> Dict[str, int]:
    """
    Рахує кількість користувачів, закріплених за магазином:
    - total: всього
    - workers: працівників
    - interns: стажерів
    """
    clean_name = shop_name.strip()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM users WHERE shop = ?",
            (clean_name,)
        )
        total = (await cursor.fetchone())[0]

        cursor = await db.execute(
            "SELECT COUNT(*) FROM users WHERE shop = ? AND status = 'Працівник'",
            (clean_name,)
        )
        workers = (await cursor.fetchone())[0]

    return {
        "total": total,
        "workers": workers,
        "interns": max(0, total - workers)
    }


# ---------------------------------------------------------------------------
# Зв'язок з керівниками в managers.db
# ---------------------------------------------------------------------------

async def get_shop_manager(shop_name: str) -> Optional[Dict[str, Any]]:
    """
    Знаходить активного керівника, у якого в `managers.shops` записаний цей магазин.
    """
    clean_name = shop_name.strip()
    try:
        async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT uid, username, full_name, process, city, shops, status
                FROM managers
                WHERE status = 'active'
                """
            )
            rows = await cursor.fetchall()
            for r in rows:
                shops_raw = r["shops"]
                if not shops_raw:
                    continue
                try:
                    shops_list = json.loads(shops_raw) if isinstance(shops_raw, str) else shops_raw
                    if isinstance(shops_list, list) and clean_name in shops_list:
                        return dict(r)
                except Exception:
                    continue
    except Exception as e:
        logger.error(f"Помилка отримання керівника для магазину {clean_name}: {e}")

    return None


async def set_shop_manager(shop_name: str, new_manager_uid: Optional[int]) -> bool:
    """
    Закріплює магазин за керівником (або відкріплює, якщо new_manager_uid is None).
    Якщо магазин був закріплений за іншим керівником — знімає його з попереднього.
    """
    clean_name = shop_name.strip()
    try:
        async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT uid, shops FROM managers WHERE status = 'active'")
            rows = await cursor.fetchall()

            for r in rows:
                uid = r["uid"]
                shops_raw = r["shops"]
                if not shops_raw:
                    current_shops = []
                else:
                    try:
                        current_shops = json.loads(shops_raw) if isinstance(shops_raw, str) else list(shops_raw)
                    except Exception:
                        current_shops = []

                changed = False
                if uid == new_manager_uid:
                    # Додаємо магазин новому керівнику, якщо його там ще немає
                    if clean_name not in current_shops:
                        current_shops.append(clean_name)
                        changed = True
                else:
                    # Видаляємо магазин у всіх інших керівників
                    if clean_name in current_shops:
                        current_shops = [s for s in current_shops if s != clean_name]
                        changed = True

                if changed:
                    await db.execute(
                        "UPDATE managers SET shops = ? WHERE uid = ?",
                        (json.dumps(current_shops, ensure_ascii=False), uid)
                    )

            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Помилка закріплення керівника {new_manager_uid} за магазином {clean_name}: {e}")
        return False


async def get_active_managers_for_city(city: str) -> List[Dict[str, Any]]:
    """
    Повертає список активних керівників у вказаному місті.
    """
    clean_city = city.strip()
    managers: List[Dict[str, Any]] = []
    try:
        async with aiosqlite.connect(MANAGERS_DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT uid, username, full_name, process, city, status
                FROM managers
                WHERE status = 'active' AND (city = ? OR city IS NULL OR city = '')
                ORDER BY full_name
                """,
                (clean_city,)
            )
            rows = await cursor.fetchall()
            managers = [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Помилка отримання керівників для міста {clean_city}: {e}")

    return managers


# ---------------------------------------------------------------------------
# Модифікація: Створення, Перейменування, Зміна міста, Видалення
# ---------------------------------------------------------------------------

async def add_shop(name: str, city: str) -> Tuple[bool, str]:
    """Додає новий магазин до бази даних."""
    clean_name = name.strip()
    clean_city = city.strip()

    if not clean_name:
        return False, "Назва магазину не може бути порожньою."
    if not clean_city:
        return False, "Місто не може бути порожнім."

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO shops (name, city) VALUES (?, ?)",
                (clean_name, clean_city)
            )
            await db.commit()
            logger.info(f"Додано новий магазин: {clean_name} ({clean_city})")
            return True, f"Магазин «{clean_name}» успішно додано!"
    except aiosqlite.IntegrityError:
        return False, f"Магазин з назвою «{clean_name}» вже існує."
    except Exception as e:
        logger.error(f"Помилка додавання магазину {clean_name}: {e}")
        return False, f"Помилка бази даних: {e}"


async def rename_shop(shop_id: int, new_name: str) -> Tuple[bool, str]:
    """
    Каскадно перейменовує магазин у `shops`, `users.shop`, `managers.shops`,
    `tokens.shop` та `training_events.shop`.
    """
    clean_new_name = new_name.strip()
    if not clean_new_name:
        return False, "Нова назва магазину не може бути порожньою."

    old_shop = await get_shop_by_id(shop_id)
    if not old_shop:
        return False, "Магазин не знайдено."

    old_name = old_shop["name"]
    if old_name == clean_new_name:
        return True, "Назва не змінилася."

    # Перевірка чи немає вже магазину з новою назвою
    existing = await get_shop_by_name(clean_new_name)
    if existing and existing["id"] != shop_id:
        return False, f"Магазин з назвою «{clean_new_name}» вже існує."

    try:
        # 1. Оновлюємо в основній базі users.db
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE shops SET name = ? WHERE id = ?", (clean_new_name, shop_id))
            await db.execute("UPDATE users SET shop = ? WHERE shop = ?", (clean_new_name, old_name))
            await db.execute("UPDATE training_events SET shop = ? WHERE shop = ?", (clean_new_name, old_name))
            await db.commit()

        # 2. Оновлюємо в tokens.db
        try:
            async with aiosqlite.connect(TOKENS_DB_PATH) as tdb:
                await tdb.execute("UPDATE tokens SET shop = ? WHERE shop = ?", (clean_new_name, old_name))
                await tdb.commit()
        except Exception as e:
            logger.warning(f"Помилка оновлення tokens.shop при перейменуванні магазину: {e}")

        # 3. Оновлюємо в managers.db (масив shops)
        try:
            async with aiosqlite.connect(MANAGERS_DB_PATH) as mdb:
                mdb.row_factory = aiosqlite.Row
                cursor = await mdb.execute("SELECT uid, shops FROM managers")
                rows = await cursor.fetchall()
                for r in rows:
                    uid = r["uid"]
                    shops_raw = r["shops"]
                    if not shops_raw:
                        continue
                    try:
                        shops_list = json.loads(shops_raw) if isinstance(shops_raw, str) else list(shops_raw)
                        if old_name in shops_list:
                            updated_shops = [clean_new_name if s == old_name else s for s in shops_list]
                            await mdb.execute(
                                "UPDATE managers SET shops = ? WHERE uid = ?",
                                (json.dumps(updated_shops, ensure_ascii=False), uid)
                            )
                    except Exception:
                        continue
                await mdb.commit()
        except Exception as e:
            logger.warning(f"Помилка оновлення managers.shops при перейменуванні магазину: {e}")

        logger.info(f"Магазин id={shop_id} перейменовано: «{old_name}» -> «{clean_new_name}»")
        return True, f"Магазин успішно перейменовано на «{clean_new_name}»!"

    except Exception as e:
        logger.error(f"Помилка каскадного перейменування магазину: {e}")
        return False, f"Помилка при збереженні: {e}"


async def change_shop_city(shop_id: int, new_city: str) -> Tuple[bool, str]:
    """
    Змінює місто для магазину та оновлює місто для закріплених за ним користувачів.
    """
    clean_new_city = new_city.strip()
    shop = await get_shop_by_id(shop_id)
    if not shop:
        return False, "Магазин не знайдено."

    shop_name = shop["name"]
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE shops SET city = ? WHERE id = ?", (clean_new_city, shop_id))
            await db.execute("UPDATE users SET city = ? WHERE shop = ?", (clean_new_city, shop_name))
            await db.commit()

        try:
            async with aiosqlite.connect(TOKENS_DB_PATH) as tdb:
                await tdb.execute("UPDATE tokens SET city = ? WHERE shop = ?", (clean_new_city, shop_name))
                await tdb.commit()
        except Exception as e:
            logger.warning(f"Помилка оновлення tokens.city для магазину {shop_name}: {e}")

        logger.info(f"Магазин «{shop_name}» перенесено в місто «{clean_new_city}»")
        return True, f"Магазин успішно перенесено в місто {clean_new_city}!"
    except Exception as e:
        logger.error(f"Помилка зміни міста магазину {shop_name}: {e}")
        return False, f"Помилка при зміні міста: {e}"


async def delete_shop_and_transfer_users(
    shop_id: int,
    target_shop_name: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Видаляє магазин.
    Якщо в магазині є працівники/стажери, вони обов'язково переносяться в `target_shop_name`.
    Також відкріплює магазин у `managers.db`.
    """
    shop = await get_shop_by_id(shop_id)
    if not shop:
        return False, "Магазин не знайдено."

    old_name = shop["name"]
    users_info = await count_users_in_shop(old_name)
    user_count = users_info["total"]

    if user_count > 0 and not target_shop_name:
        return False, f"У магазині закріплено {user_count} користувачів. Оберіть магазин для переведення."

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # 1. Переведення користувачів
            if user_count > 0 and target_shop_name:
                clean_target = target_shop_name.strip()
                await db.execute(
                    "UPDATE users SET shop = ? WHERE shop = ?",
                    (clean_target, old_name)
                )
                logger.info(f"Переведено {user_count} користувачів з «{old_name}» в «{clean_target}»")

            # 2. Видалення магазину з shops
            await db.execute("DELETE FROM shops WHERE id = ?", (shop_id,))
            await db.commit()

        # 3. Відкріплення в managers.db
        try:
            async with aiosqlite.connect(MANAGERS_DB_PATH) as mdb:
                mdb.row_factory = aiosqlite.Row
                cursor = await mdb.execute("SELECT uid, shops FROM managers")
                rows = await cursor.fetchall()
                for r in rows:
                    uid = r["uid"]
                    shops_raw = r["shops"]
                    if not shops_raw:
                        continue
                    try:
                        shops_list = json.loads(shops_raw) if isinstance(shops_raw, str) else list(shops_raw)
                        if old_name in shops_list:
                            updated_shops = [s for s in shops_list if s != old_name]
                            await mdb.execute(
                                "UPDATE managers SET shops = ? WHERE uid = ?",
                                (json.dumps(updated_shops, ensure_ascii=False), uid)
                            )
                    except Exception:
                        continue
                await mdb.commit()
        except Exception as e:
            logger.warning(f"Помилка відкріплення магазину в managers.db: {e}")

        # 4. Токени
        try:
            async with aiosqlite.connect(TOKENS_DB_PATH) as tdb:
                if target_shop_name:
                    await tdb.execute("UPDATE tokens SET shop = ? WHERE shop = ?", (target_shop_name.strip(), old_name))
                else:
                    await tdb.execute("DELETE FROM tokens WHERE shop = ?", (old_name,))
                await tdb.commit()
        except Exception as e:
            logger.warning(f"Помилка оновлення токенів при видаленні магазину: {e}")

        msg = f"Магазин «{old_name}» успішно видалено."
        if user_count > 0 and target_shop_name:
            msg += f" {user_count} працівників переведено в «{target_shop_name}»."
        return True, msg

    except Exception as e:
        logger.error(f"Помилка видалення магазину {old_name}: {e}")
        return False, f"Помилка видалення магазину: {e}"
