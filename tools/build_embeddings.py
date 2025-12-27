#!/usr/bin/env python3
"""
Builds semantic embeddings for training materials using SentenceTransformers + FAISS.
"""

import asyncio
import json
from pathlib import Path
import sys
from typing import List

# Add project root to PYTHONPATH
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
from database.materials import get_all_materials

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
INDEX_DIR = project_root / "data" / "semantic_index"
INDEX_PATH = INDEX_DIR / "index.faiss"
META_PATH = INDEX_DIR / "meta.json"


def _prepare_text(record: dict) -> str:
    parts: List[str] = []
    title = (record.get("title") or "").strip()
    content = (record.get("content") or "").strip()
    if title:
        parts.append(title)
    if content:
        parts.append(content)
    return "\n".join(parts).strip()


def _build_preview(text: str, limit: int = 300) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


async def build_embeddings():
    materials = await get_all_materials()
    documents = []
    metadata = []
    for record in materials:
        text = _prepare_text(record)
        if not text:
            continue
        documents.append(text)
        metadata.append(
            {
                "material_id": record.get("id"),
                "day": record.get("day"),
                "role": record.get("role"),
                "block_type": record.get("content_type"),
                "preview": _build_preview(text),
            }
        )

    if not documents:
        print("⚠️ Немає матеріалів із текстом для побудови індексу.")
        return

    print(f"Завантажуємо модель {MODEL_NAME}…")
    model = SentenceTransformer(MODEL_NAME)
    print(f"Генеруємо ембедінги для {len(documents)} матеріалів…")
    embeddings = model.encode(documents, convert_to_numpy=True, normalize_embeddings=True)
    embeddings = embeddings.astype("float32")

    dimension = embeddings.shape[1]
    index = faiss.IndexFlatIP(dimension)
    index.add(embeddings)

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(INDEX_PATH))
    with META_PATH.open("w", encoding="utf-8") as meta_file:
        payload = {
            "model_name": MODEL_NAME,
            "items": metadata,
        }
        json.dump(payload, meta_file, ensure_ascii=False, indent=2)

    print("✅ Готово!")
    print(f"Матеріалів опрацьовано: {len(documents)}")
    print(f"Розмір вектора: {dimension}")
    print(f"Індекс: {INDEX_PATH}")
    print(f"Метадані: {META_PATH}")


if __name__ == "__main__":
    asyncio.run(build_embeddings())
