"""SQLite persistence layer for deduplicated knowledge chunks and cached embeddings."""

from __future__ import annotations

import hashlib
import json
from typing import Optional

import aiosqlite

from . import DB_PATH


async def init_knowledge_chunks_db(db_path: str = DB_PATH) -> None:
    """Initializes the material_chunks table if it does not exist."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS material_chunks (
                chunk_hash TEXT PRIMARY KEY,
                chunk_text TEXT NOT NULL,
                sources_json TEXT NOT NULL,
                embedding_json TEXT DEFAULT NULL,
                embedding_model TEXT DEFAULT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.commit()


async def get_materials_fingerprint(db_path: str = DB_PATH) -> str:
    """Computes a lightweight deterministic fingerprint of materials table contents."""
    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                """
                SELECT id, role, day, content_type,
                       coalesce(title, ''), coalesce(updated_at, ''),
                       length(coalesce(content, ''))
                FROM materials
                ORDER BY id ASC
                """
            )
            rows = await cursor.fetchall()
    except aiosqlite.OperationalError:
        return ""

    h = hashlib.sha256()
    for row in rows:
        h.update("|".join(str(col) for col in row).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


async def get_materials_rows(db_path: str = DB_PATH) -> list[dict]:
    """Reads all rows from materials table for a specific SQLite path."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM materials ORDER BY id ASC")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_all_knowledge_chunks(db_path: str = DB_PATH) -> list[dict]:
    """Returns all stored knowledge chunks with decoded sources and optional embeddings."""
    await init_knowledge_chunks_db(db_path)
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT chunk_hash, chunk_text, sources_json, embedding_json, embedding_model, updated_at
            FROM material_chunks
            ORDER BY updated_at ASC, chunk_hash ASC
            """
        )
        rows = await cursor.fetchall()

    results: list[dict] = []
    for row in rows:
        try:
            sources = json.loads(row["sources_json"]) if row["sources_json"] else []
        except (json.JSONDecodeError, TypeError):
            sources = []

        embedding: Optional[list[float]] = None
        if row["embedding_json"]:
            try:
                parsed_emb = json.loads(row["embedding_json"])
                if isinstance(parsed_emb, list) and parsed_emb:
                    embedding = [float(x) for x in parsed_emb]
            except (json.JSONDecodeError, TypeError, ValueError):
                embedding = None

        results.append(
            {
                "chunk_hash": row["chunk_hash"],
                "chunk_text": row["chunk_text"],
                "sources": sources,
                "embedding": embedding,
                "embedding_model": row["embedding_model"],
                "updated_at": row["updated_at"],
            }
        )
    return results


async def sync_knowledge_chunk_rows(
    chunks: list[dict],
    embedding_model: str,
    db_path: str = DB_PATH,
) -> list[str]:
    """
    Reconciles material_chunks table with freshly built deduplicated chunks.

    Preserves cached embeddings for unchanged chunk hashes and returns the list
    of chunk hashes that currently lack an embedding for `embedding_model`.
    """
    await init_knowledge_chunks_db(db_path)
    valid_hashes = {c["chunk_hash"] for c in chunks}

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT chunk_hash, sources_json, embedding_json, embedding_model FROM material_chunks"
        )
        existing = {row["chunk_hash"]: row for row in await cursor.fetchall()}

        stale_hashes = [h for h in existing if h not in valid_hashes]
        if stale_hashes:
            placeholders = ",".join("?" for _ in stale_hashes)
            await db.execute(
                f"DELETE FROM material_chunks WHERE chunk_hash IN ({placeholders})",
                stale_hashes,
            )

        missing_embedding_hashes: list[str] = []
        for chunk in chunks:
            ch = chunk["chunk_hash"]
            sources_json = json.dumps(chunk["sources"], ensure_ascii=False, sort_keys=True)
            row = existing.get(ch)
            if row is None:
                await db.execute(
                    """
                    INSERT INTO material_chunks (chunk_hash, chunk_text, sources_json)
                    VALUES (?, ?, ?)
                    """,
                    (ch, chunk["chunk_text"], sources_json),
                )
                missing_embedding_hashes.append(ch)
            else:
                if row["sources_json"] != sources_json:
                    await db.execute(
                        """
                        UPDATE material_chunks
                        SET sources_json = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE chunk_hash = ?
                        """,
                        (sources_json, ch),
                    )
                if not row["embedding_json"] or row["embedding_model"] != embedding_model:
                    missing_embedding_hashes.append(ch)

        await db.commit()

    return missing_embedding_hashes


async def save_chunk_embeddings(
    hash_to_embedding: dict[str, list[float]],
    model: str,
    db_path: str = DB_PATH,
) -> None:
    """Stores computed embedding vectors for the given chunk hashes."""
    if not hash_to_embedding:
        return
    await init_knowledge_chunks_db(db_path)
    async with aiosqlite.connect(db_path) as db:
        for chunk_hash, vector in hash_to_embedding.items():
            await db.execute(
                """
                UPDATE material_chunks
                SET embedding_json = ?, embedding_model = ?, updated_at = CURRENT_TIMESTAMP
                WHERE chunk_hash = ?
                """,
                (json.dumps(vector), model, chunk_hash),
            )
        await db.commit()
