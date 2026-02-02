"""Semantic search over training materials using FAISS + SentenceTransformers.

Note: This module requires torch and sentence-transformers which may not be available.
If not installed, the module will provide stub functions that return empty results.
"""

from __future__ import annotations

import asyncio
import json
from typing import List, Optional
from pathlib import Path
from typing import List, TypedDict

# Optional imports - may not be available
try:
    import faiss
    import numpy as np
    from sentence_transformers import SentenceTransformer
    SEMANTIC_AVAILABLE = True
except ImportError:
    SEMANTIC_AVAILABLE = False
    faiss = None
    np = None
    SentenceTransformer = None

BASE_DIR = Path(__file__).resolve().parents[2]
INDEX_DIR = BASE_DIR / "data" / "semantic_index"
INDEX_PATH = INDEX_DIR / "index.faiss"
META_PATH = INDEX_DIR / "meta.json"
DEFAULT_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

_INDEX = None
_META: Optional[List[dict]] = None
_MODEL = None
_MODEL_NAME = DEFAULT_MODEL_NAME
_LOCK = asyncio.Lock()


class SemanticSearchResult(TypedDict, total=False):
    material_id: Optional[int]
    day: Optional[int]
    role: Optional[str]
    block_type: Optional[str]
    score: float
    preview: str


def _index_available() -> bool:
    if not SEMANTIC_AVAILABLE:
        return False
    return INDEX_PATH.exists() and META_PATH.exists()


async def _load_resources():
    global _INDEX, _META, _MODEL, _MODEL_NAME
    
    if not SEMANTIC_AVAILABLE:
        _INDEX = None
        _META = []
        _MODEL = None
        return
    
    if _INDEX is not None and _META is not None and _MODEL is not None:
        return
    if not _index_available():
        _INDEX = None
        _META = []
        _MODEL = None
        return

    # Heavy operations guarded by lock
    faiss_index = faiss.read_index(str(INDEX_PATH))
    with META_PATH.open("r", encoding="utf-8") as meta_file:
        payload = json.load(meta_file)

    items = payload.get("items")
    if items is None:
        # backwards compatibility if meta is just an array
        items = payload
    _META = items or []
    _MODEL_NAME = payload.get("model_name", DEFAULT_MODEL_NAME)
    _INDEX = faiss_index
    _MODEL = SentenceTransformer(_MODEL_NAME)


async def semantic_search(query: str, limit: int = 5) -> List[SemanticSearchResult]:
    if not SEMANTIC_AVAILABLE:
        return []
    
    normalized_query = (query or "").strip()
    if not normalized_query or limit <= 0:
        return []

    async with _LOCK:
        await _load_resources()

    if not _INDEX or _META is None or _MODEL is None:
        return []

    embedding = _MODEL.encode([normalized_query], convert_to_numpy=True, normalize_embeddings=True)
    embedding = embedding.astype("float32")

    distances, indices = _INDEX.search(embedding, limit)
    scores = distances[0]
    ids = indices[0]
    results: List[SemanticSearchResult] = []
    for idx, score in zip(ids, scores):
        if idx == -1 or idx >= len(_META):
            continue
        meta = _META[idx]
        results.append(
            SemanticSearchResult(
                material_id=meta.get("material_id"),
                day=meta.get("day"),
                role=meta.get("role"),
                block_type=meta.get("block_type"),
                preview=meta.get("preview", ""),
                score=float(score),
            )
        )
    return results


async def reset_semantic_search_index():
    """Forces the next search to reload the index from disk."""
    global _INDEX, _META, _MODEL
    async with _LOCK:
        _INDEX = None
        _META = None
        _MODEL = None


async def build_and_reset_embeddings():
    """
    Builds semantic embeddings and then resets the in-memory cache.
    Uses lazy imports to avoid loading heavy libraries at startup.
    """
    # Lazy import heavy libraries only when this function is called
    from database.materials import get_all_materials
    import faiss
    import numpy as np
    from sentence_transformers import SentenceTransformer

    def _prepare_text(record: dict) -> str:
        parts: List[str] = []
        title = (record.get("title") or "").strip()
        content = (record.get("content") or "").strip()
        if title:
            parts.append(title)
        if content:
            parts.append(content)
        return "\n".join(parts).strip()

    def _build_preview(text: str, limit: int = 1500) -> str:
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"

    materials = await get_all_materials()
    documents = []
    metadata = []
    for record in materials:
        text = _prepare_text(record)
        if not text:
            continue
        documents.append(text)
        metadata.append({
            "material_id": record.get("id"),
            "day": record.get("day"),
            "role": record.get("role"),
            "block_type": record.get("content_type"),
            "preview": _build_preview(text),
        })

    if not documents:
        print("⚠️ No text-based materials found to build index.")
        return

    model = SentenceTransformer(DEFAULT_MODEL_NAME)
    embeddings = model.encode(documents, convert_to_numpy=True, normalize_embeddings=True)
    embeddings = embeddings.astype("float32")

    dimension = embeddings.shape[1]
    index = faiss.IndexFlatIP(dimension)
    index.add(embeddings)

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(INDEX_PATH))
    with META_PATH.open("w", encoding="utf-8") as meta_file:
        payload = {
            "model_name": DEFAULT_MODEL_NAME,
            "items": metadata,
        }
        json.dump(payload, meta_file, ensure_ascii=False, indent=2)

    # After building, reset the cache
    await reset_semantic_search_index()


__all__ = [
    "semantic_search", 
    "SemanticSearchResult", 
    "reset_semantic_search_index",
    "build_and_reset_embeddings",
]

