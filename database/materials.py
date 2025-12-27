import aiosqlite
from typing import List, Optional
from . import DB_PATH


async def init_materials_db():
    """Ініціалізація бази даних навчальних матеріалів."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
        CREATE TABLE IF NOT EXISTS materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            day INTEGER NOT NULL,
            content_type TEXT NOT NULL,
            title TEXT,
            content TEXT,
            resource_url TEXT,
            order_index INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (role, day, content_type, order_index)
        )
        ''')
        await db.commit()
    # print(f"База матеріалів ініціалізована за шляхом: {DB_PATH}")


async def add_or_update_material(
    role: str,
    day: int,
    content_type: str,
    title: Optional[str],
    content: Optional[str],
    resource_url: Optional[str],
    order_index: int = 0,
) -> int:
    """
    Створює або оновлює запис навчального матеріалу для конкретної ролі та дня.
    Повертає ID запису.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO materials (role, day, content_type, title, content, resource_url, order_index)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(role, day, content_type, order_index)
            DO UPDATE SET
                title=excluded.title,
                content=excluded.content,
                resource_url=excluded.resource_url,
                updated_at=CURRENT_TIMESTAMP
            """,
            (role, day, content_type, title, content, resource_url, order_index),
        )
        await db.commit()
        return cursor.lastrowid


async def get_materials_for_day(role: str, day: int) -> List[dict]:
    """
    Повертає всі матеріали для конкретної ролі та дня.
    Також включає спільні матеріали з роллю 'ALL'.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT *
            FROM materials
            WHERE day = ?
              AND (role = ? OR role = 'ALL')
            ORDER BY
                CASE WHEN role = 'ALL' THEN 1 ELSE 0 END,
                order_index ASC,
                content_type ASC
            """,
            (day, role),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def search_materials(keyword: str, role: Optional[str] = None, limit: int = 20) -> List[dict]:
    """
    Простий пошук матеріалів за ключовим словом.
    Використовується як базовий варіант до впровадження semantic search.
    """
    like_pattern = f"%{keyword.lower()}%"
    query = """
        SELECT *
        FROM materials
        WHERE lower(content) LIKE ?
           OR lower(title) LIKE ?
    """
    params: List = [like_pattern, like_pattern]

    if role:
        query += " AND (role = ? OR role = 'ALL')"
        params.append(role)

    query += " ORDER BY day ASC, order_index ASC LIMIT ?"
    params.append(limit)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_all_materials() -> List[dict]:
    """Повертає всі матеріали незалежно від ролі/дня."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM materials ORDER BY id ASC"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_material_by_id(material_id: int) -> Optional[dict]:
    """Повертає матеріал за ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM materials WHERE id = ?",
            (material_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_material_by_role_day_type(role: str, day: int, content_type: str) -> Optional[dict]:
    """Повертає матеріал за роллю, днем та типом контенту."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM materials 
            WHERE role = ? AND day = ? AND content_type = ?
            ORDER BY order_index ASC
            LIMIT 1
            """,
            (role, day, content_type)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def update_material_content(material_id: int, content: str) -> bool:
    """Оновлює текстовий контент матеріалу."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE materials 
            SET content = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (content, material_id)
        )
        await db.commit()
        return True


async def update_material_resource_url(material_id: int, resource_url: str) -> bool:
    """Оновлює URL ресурсу (відео) матеріалу."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE materials 
            SET resource_url = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (resource_url, material_id)
        )
        await db.commit()
        return True


async def get_unique_roles_from_materials() -> List[str]:
    """Повертає унікальні ролі з таблиці materials."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT DISTINCT role FROM materials WHERE role != 'ALL' ORDER BY role"
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


async def get_days_for_role(role: str) -> List[int]:
    """Повертає список днів, для яких є матеріали для конкретної ролі."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT DISTINCT day FROM materials 
            WHERE role = ? OR role = 'ALL'
            ORDER BY day
            """,
            (role,)
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


async def get_test_by_role_and_day(role: str, day: int) -> Optional[dict]:
    """Повертає тест (матеріал з типом 'test') для конкретної ролі та дня."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM materials 
            WHERE (role = ? OR role = 'ALL') AND day = ? AND content_type = 'test'
            ORDER BY CASE WHEN role = 'ALL' THEN 1 ELSE 0 END
            LIMIT 1
            """,
            (role, day)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
