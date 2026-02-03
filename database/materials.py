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
        
        # Перевіряємо та додаємо колонку is_enabled
        cursor = await db.execute("PRAGMA table_info(materials)")
        columns = [row[1] for row in await cursor.fetchall()]
        if 'is_enabled' not in columns:
            await db.execute("ALTER TABLE materials ADD COLUMN is_enabled BOOLEAN DEFAULT 1")
            
        await db.commit()
    # print(f"База матеріалів ініціалізована за шляхом: {DB_PATH}")


async def toggle_test_status(role: str, day: int, is_enabled: bool) -> bool:
    """Вмикає або вимикає тест для ролі та дня."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE materials 
            SET is_enabled = ? 
            WHERE (role = ? OR role = 'ALL') AND day = ? AND content_type = 'test'
            """,
            (is_enabled, role, day)
        )
        await db.commit()
        return True


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
    # Розширюємо пошук синонімами та варіаціями
    search_terms = [keyword.lower()]
    
    # Додаємо варіації для алкоголю
    if "алкоголь" in keyword.lower() or keyword.lower() == "алкоголь":
        search_terms.extend(["спирт", "алкогол", "горілк", "пив", "вин", "алкогольн"])
    
    # Додаємо варіації для списання
    elif "списув" in keyword.lower() or "спис" in keyword.lower():
        search_terms.extend(["спис", "списання", "списати", "списувати"])
    
    # Додаємо варіації для конфліктів
    elif "конфлікт" in keyword.lower() or "конфлікт" in keyword:
        search_terms.extend(["конфлікт", "суперечк", "скарг", "незадовол", "проблем", "ситуац"])
    
    # Додаємо варіації для роботи з клієнтами
    elif any(word in keyword.lower() for word in ["клієнт", "покупец", "обслуговув", "сервіс"]):
        search_terms.extend(["клієнт", "покупец", "обслуговув", "сервіс", "стандарт", "якість"])
    
    # Для загальних питань типу "як", "що робити"
    elif any(word in keyword.lower() for word in ["як", "що робити", "як вирішити"]):
        # Шукаємо також по процедурах та інструкціях
        search_terms.extend(["процедур", "інструкц", "алгоритм", "кроки", "дії"])
    
    # Для випадків з продукцією (багет, хліб тощо)
    elif any(word in keyword.lower() for word in ["багет", "хліб", "випав", "пакет", "продукція"]):
        search_terms.extend(["багет", "хліб", "круассан", "випав", "пакет", "продукція", "компенсац", "заміню", "їжа"])
    
    # Для загальних слів - додаємо контекстні варіанти
    if len(search_terms) == 1:  # Тільки оригінальне слово
        original = keyword.lower()
        # Додаємо загальні варіанти для кращого пошуку
        if len(original) > 3:  # Тільки для довгих слів
            # Додаємо частину слова для пошуку коренів
            if len(original) >= 5:
                search_terms.append(original[:4])  # Перші 4 символи
    
    # Створюємо умови для пошуку з пріоритетами
    priority_conditions = []
    standard_conditions = []
    params: List = []
    
    # Пріоритетний пошук: точна фраза в заголовку або на початку контенту
    exact_phrase = keyword.lower()
    priority_conditions.append("(lower(title) LIKE ? OR lower(substr(content, 1, 500)) LIKE ?)")
    params.extend([f"%{exact_phrase}%", f"%{exact_phrase}%"])
    
    # Стандартний пошук по всьому контенту
    for term in search_terms:
        pattern = f"%{term}%"
        standard_conditions.append("(lower(content) LIKE ? OR lower(title) LIKE ?)")
        params.extend([pattern, pattern])
    
    # Комбінуємо умови з пріоритетами
    all_conditions = priority_conditions + standard_conditions
    
    query = f"""
        SELECT *, 
        CASE 
            WHEN lower(title) LIKE ? THEN 100
            WHEN lower(substr(content, 1, 500)) LIKE ? THEN 90
            ELSE 50
        END as relevance_score
        FROM materials
        WHERE ({' OR '.join(all_conditions)})
    """
    
    # Додаємо параметри для скорингу
    score_params = [f"%{exact_phrase}%", f"%{exact_phrase}%"] + params

    if role:
        query += " AND (role = ? OR role = 'ALL')"
        score_params.append(role)

    query += " ORDER BY relevance_score DESC, day ASC, order_index ASC LIMIT ?"
    score_params.append(limit)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, score_params)
        rows = await cursor.fetchall()
        results = [dict(row) for row in rows]
        
        return results


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
