from __future__ import annotations

import logging
import math
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite
import pytz

from bot.config import TIMEZONE
from . import DB_PATH

logger = logging.getLogger(__name__)

INSTRUCTIONS_FILES_DIR = os.path.join(os.path.dirname(DB_PATH), "instructions_files")


def _resolve_db_path(db_path: Optional[str]) -> str:
    return db_path or DB_PATH


def _get_kyiv_time_str() -> str:
    """Повертає поточний час у часовому поясі Europe/Kyiv у форматі YYYY-MM-DD HH:MM:SS."""
    tz = pytz.timezone(TIMEZONE)
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")


async def _safe_remove_file(file_path: Optional[str]) -> None:
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except OSError as exc:
            logger.warning(f"Could not remove instruction file {file_path}: {exc}")


async def init_instructions_db(db_path: Optional[str] = None) -> None:
    """Ініціалізує таблицю instructions, авто-мігрує нові колонки та створює папку файлів."""
    target_db = _resolve_db_path(db_path)
    os.makedirs(INSTRUCTIONS_FILES_DIR, exist_ok=True)
    async with aiosqlite.connect(target_db) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS instructions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT DEFAULT '',
                file_path TEXT DEFAULT NULL,
                telegram_file_id TEXT DEFAULT NULL,
                file_name TEXT DEFAULT NULL,
                original_file_path TEXT DEFAULT NULL,
                original_telegram_file_id TEXT DEFAULT NULL,
                original_file_name TEXT DEFAULT NULL,
                created_by INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor = await db.execute("PRAGMA table_info(instructions)")
        existing_cols = {row[1] for row in await cursor.fetchall()}
        for col_name, col_def in (
            ("original_file_path", "TEXT DEFAULT NULL"),
            ("original_telegram_file_id", "TEXT DEFAULT NULL"),
            ("original_file_name", "TEXT DEFAULT NULL"),
        ):
            if col_name not in existing_cols:
                await db.execute(f"ALTER TABLE instructions ADD COLUMN {col_name} {col_def}")
        await db.commit()
    logger.info("Instructions database initialized successfully.")


async def create_instruction(
    title: str,
    content: str = "",
    file_path: Optional[str] = None,
    telegram_file_id: Optional[str] = None,
    file_name: Optional[str] = None,
    original_file_path: Optional[str] = None,
    original_telegram_file_id: Optional[str] = None,
    original_file_name: Optional[str] = None,
    created_by: int = 0,
    db_path: Optional[str] = None,
) -> int:
    """Створює нову інструкцію в БД та повертає її ID."""
    target_db = _resolve_db_path(db_path)
    clean_title = (title or "").strip()
    if not clean_title:
        raise ValueError("Назва теми інструкції не може бути порожньою.")

    now_str = _get_kyiv_time_str()
    await init_instructions_db(db_path=target_db)
    async with aiosqlite.connect(target_db) as db:
        cursor = await db.execute(
            """
            INSERT INTO instructions (
                title, content, file_path, telegram_file_id, file_name,
                original_file_path, original_telegram_file_id, original_file_name,
                created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clean_title,
                content or "",
                file_path,
                telegram_file_id,
                file_name,
                original_file_path,
                original_telegram_file_id,
                original_file_name,
                created_by,
                now_str,
                now_str,
            ),
        )
        inst_id = cursor.lastrowid
        await db.commit()
        return int(inst_id)


async def get_instruction_by_id(
    inst_id: int,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Повертає інструкцію за ID або None."""
    target_db = _resolve_db_path(db_path)
    async with aiosqlite.connect(target_db) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM instructions WHERE id = ?", (inst_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_all_instructions(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Повертає всі інструкції (найновіші першими)."""
    target_db = _resolve_db_path(db_path)
    await init_instructions_db(db_path=target_db)
    async with aiosqlite.connect(target_db) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM instructions ORDER BY id DESC")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_instructions_paginated(
    page: int = 1,
    page_size: int = 8,
    db_path: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], int, int]:
    """Повертає (items_on_page, total_count, total_pages) для інлайн-пагінації."""
    target_db = _resolve_db_path(db_path)
    await init_instructions_db(db_path=target_db)
    safe_page_size = max(1, page_size)
    async with aiosqlite.connect(target_db) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT COUNT(*) FROM instructions")
        row = await cursor.fetchone()
        total_count = int(row[0]) if row else 0

        total_pages = max(1, math.ceil(total_count / safe_page_size))
        safe_page = max(1, min(page, total_pages))
        offset = (safe_page - 1) * safe_page_size

        cursor = await db.execute(
            "SELECT * FROM instructions ORDER BY id DESC LIMIT ? OFFSET ?",
            (safe_page_size, offset),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows], total_count, total_pages


async def update_instruction_title(
    inst_id: int,
    new_title: str,
    db_path: Optional[str] = None,
) -> bool:
    """Оновлює назву інструкції."""
    target_db = _resolve_db_path(db_path)
    clean_title = (new_title or "").strip()
    if not clean_title:
        raise ValueError("Назва теми інструкції не може бути порожньою.")

    now_str = _get_kyiv_time_str()
    async with aiosqlite.connect(target_db) as db:
        cursor = await db.execute(
            "UPDATE instructions SET title = ?, updated_at = ? WHERE id = ?",
            (clean_title, now_str, inst_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def update_instruction_file(
    inst_id: int,
    content: str,
    file_path: Optional[str],
    telegram_file_id: Optional[str],
    file_name: Optional[str],
    db_path: Optional[str] = None,
) -> bool:
    """Оновлює файл та текстовий вміст інструкції, безпечно видаляючи попередній локальний файл."""
    target_db = _resolve_db_path(db_path)
    existing = await get_instruction_by_id(inst_id, db_path=target_db)
    if not existing:
        return False

    old_file_path = existing.get("file_path")
    now_str = _get_kyiv_time_str()
    async with aiosqlite.connect(target_db) as db:
        cursor = await db.execute(
            """
            UPDATE instructions
            SET content = ?, file_path = ?, telegram_file_id = ?, file_name = ?, updated_at = ?
            WHERE id = ?
            """,
            (content or "", file_path, telegram_file_id, file_name, now_str, inst_id),
        )
        await db.commit()
        updated = cursor.rowcount > 0

    if updated and old_file_path and old_file_path != file_path:
        await _safe_remove_file(old_file_path)

    return updated


async def update_instruction_original_file(
    inst_id: int,
    original_file_path: Optional[str],
    original_telegram_file_id: Optional[str],
    original_file_name: Optional[str],
    db_path: Optional[str] = None,
) -> bool:
    """Оновлює файл оригіналу інструкції та видаляє попередній локальний файл оригіналу."""
    target_db = _resolve_db_path(db_path)
    await init_instructions_db(db_path=target_db)
    existing = await get_instruction_by_id(inst_id, db_path=target_db)
    if not existing:
        return False

    old_orig_path = existing.get("original_file_path")
    now_str = _get_kyiv_time_str()
    async with aiosqlite.connect(target_db) as db:
        cursor = await db.execute(
            """
            UPDATE instructions
            SET original_file_path = ?, original_telegram_file_id = ?, original_file_name = ?, updated_at = ?
            WHERE id = ?
            """,
            (original_file_path, original_telegram_file_id, original_file_name, now_str, inst_id),
        )
        await db.commit()
        updated = cursor.rowcount > 0

    if updated and old_orig_path and old_orig_path != original_file_path:
        await _safe_remove_file(old_orig_path)

    return updated


async def get_instructions_with_original_by_ids(
    inst_ids: List[int],
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Повертає інструкції у заданому порядку, якщо до них прикріплений файл оригіналу."""
    unique_ids: List[int] = []
    seen: set[int] = set()
    for raw_id in inst_ids or []:
        try:
            iid = int(raw_id)
        except (TypeError, ValueError):
            continue
        if iid > 0 and iid not in seen:
            seen.add(iid)
            unique_ids.append(iid)

    if not unique_ids:
        return []

    target_db = _resolve_db_path(db_path)
    await init_instructions_db(db_path=target_db)
    placeholders = ",".join("?" for _ in unique_ids)
    async with aiosqlite.connect(target_db) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT * FROM instructions WHERE id IN ({placeholders})",
            unique_ids,
        )
        rows = await cursor.fetchall()

    by_id = {int(row["id"]): dict(row) for row in rows}
    result: List[Dict[str, Any]] = []
    for iid in unique_ids:
        inst = by_id.get(iid)
        if inst and (inst.get("original_file_path") or inst.get("original_telegram_file_id")):
            result.append(inst)
    return result


async def delete_instruction(inst_id: int, db_path: Optional[str] = None) -> bool:
    """Видаляє інструкцію з БД та обидва її локальні файли з диска."""
    target_db = _resolve_db_path(db_path)
    existing = await get_instruction_by_id(inst_id, db_path=target_db)
    if not existing:
        return False

    old_file_path = existing.get("file_path")
    old_orig_path = existing.get("original_file_path")
    async with aiosqlite.connect(target_db) as db:
        cursor = await db.execute("DELETE FROM instructions WHERE id = ?", (inst_id,))
        await db.commit()
        deleted = cursor.rowcount > 0

    if deleted:
        await _safe_remove_file(old_file_path)
        if old_orig_path != old_file_path:
            await _safe_remove_file(old_orig_path)

    return deleted
