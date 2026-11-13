"""Hybrid retrieval engine over training materials (OpenAI embeddings + Ukrainian lexical/exact scan).

Zero heavy ML dependencies (no faiss/torch/sentence-transformers): computes cosine
similarity in pure Python over cached SQLite vectors in `material_chunks` and
guarantees complete exact-token recall within context budget.
"""

from __future__ import annotations

import asyncio
import math
import re
from typing import Dict, List, Optional, Sequence, Tuple, TypedDict

from bot.services.knowledge_chunker import (
    UNASSIGNED_ROLE,
    UNASSIGNED_ROLE_LABEL,
    build_deduplicated_chunks,
)
from bot.services.logger import get_logger
from database import DB_PATH
from database.knowledge_chunks import (
    get_all_knowledge_chunks,
    get_materials_fingerprint,
    get_materials_rows,
    save_chunk_embeddings,
    sync_knowledge_chunk_rows,
)

logger = get_logger()

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_BATCH_SIZE = 50
MAX_CONTEXT_CHARS = 35000
TOP_FULL_CHUNKS = 10

_APOSTROPHES_RE = re.compile(r"[ʼ’`]")
_TOKEN_RE = re.compile(r"[0-9a-zA-Zа-яА-ЯіїєґІЇЄҐ']+")

_STOP_WORDS = frozenset(
    {
        "що",
        "як",
        "де",
        "чи",
        "та",
        "і",
        "в",
        "на",
        "по",
        "про",
        "для",
        "це",
        "коли",
        "до",
        "із",
        "зі",
        "від",
        "при",
        "за",
        "над",
        "під",
        "або",
        "але",
        "не",
        "ні",
        "без",
        "через",
        "після",
        "перед",
        "між",
        "скільки",
        "який",
        "яка",
        "яке",
        "які",
        "можна",
        "треба",
        "мене",
        "мені",
        "хто",
        "чому",
        "буде",
        "є",
    }
)

# Longest suffixes first; only applied when resulting stem stays >= 3-4 chars.
_UK_LONG_SUFFIXES = (
    "уватися",
    "юватися",
    "ування",
    "ювання",
    "овання",
    "ання",
    "ення",
    "єння",
    "іння",
    "увати",
    "ювати",
    "овати",
    "ться",
    "тися",
    "ості",
    "ість",
    "овий",
    "ового",
    "овому",
    "овою",
    "ових",
    "овим",
    "ного",
    "ному",
    "ними",
    "ний",
    "ною",
    "них",
    "ним",
    "ати",
    "яти",
    "ити",
    "іти",
    "ові",
    "еві",
    "єві",
    "ами",
    "ями",
    "іми",
    "ях",
    "ах",
    "ом",
    "ем",
    "єм",
    "ім",
    "им",
    "их",
    "іх",
    "ою",
    "ею",
    "єю",
    "ої",
    "ій",
    "ні",
    "ти",
)
_UK_SHORT_ENDINGS = ("а", "я", "о", "у", "ю", "е", "и", "і", "ь")

_LOCK_MAP: dict[str, asyncio.Lock] = {}
_FINGERPRINT_CACHE: dict[str, str] = {}
_CHUNKS_CACHE: dict[str, list[dict]] = {}


def _get_sync_lock(db_path: str) -> asyncio.Lock:
    lock = _LOCK_MAP.get(db_path)
    if lock is None:
        lock = asyncio.Lock()
        _LOCK_MAP[db_path] = lock
    return lock


class SemanticSearchResult(TypedDict, total=False):
    material_id: Optional[int]
    day: Optional[int]
    role: Optional[str]
    block_type: Optional[str]
    score: float
    preview: str


def uk_stem(token: str) -> str:
    """Lightweight suffix stemmer for Ukrainian/Cyrillic tokens. Preserves short acronyms."""
    norm = _APOSTROPHES_RE.sub("'", (token or "").strip().lower()).strip("'")
    if len(norm) < 4 or norm.isdigit():
        return norm

    if len(norm) >= 5:
        for suffix in _UK_LONG_SUFFIXES:
            if norm.endswith(suffix) and len(norm) - len(suffix) >= 4:
                return norm[: -len(suffix)]

    if norm[-1] in _UK_SHORT_ENDINGS and len(norm) >= 4:
        return norm[:-1]

    return norm


def tokenize_text(text: str, drop_stop_words: bool = False) -> list[str]:
    """Extracts normalized lowercase tokens >= 2 chars."""
    normalized = _APOSTROPHES_RE.sub("'", (text or "").lower())
    tokens = [
        m.group(0).strip("'")
        for m in _TOKEN_RE.finditer(normalized)
        if len(m.group(0).strip("'")) >= 2
    ]
    if not drop_stop_words:
        return tokens
    meaningful = [t for t in tokens if t not in _STOP_WORDS]
    return meaningful if meaningful else tokens


def tokenize_query(query: str) -> list[str]:
    """Extracts deduplicated meaningful query tokens, preserving order."""
    raw = tokenize_text(query, drop_stop_words=True)
    seen: set[str] = set()
    ordered: list[str] = []
    for tok in raw:
        if tok not in seen:
            seen.add(tok)
            ordered.append(tok)
    return ordered


def _cosine_similarity(vec_a: Optional[Sequence[float]], vec_b: Optional[Sequence[float]]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for a, b in zip(vec_a, vec_b):
        dot += a * b
        norm_a += a * a
        norm_b += b * b
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    score = dot / (math.sqrt(norm_a) * math.sqrt(norm_b))
    return max(0.0, min(1.0, score))


def _get_openai_client():
    from bot.services.openai_ai import get_client, is_openai_configured

    if not is_openai_configured():
        return None
    return get_client()


async def _embed_texts(texts: list[str], client=None) -> Optional[list[list[float]]]:
    if not texts:
        return []
    active_client = client if client is not None else _get_openai_client()
    if active_client is None:
        return None

    try:
        resp = await active_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=texts,
        )
        return [list(item.embedding) for item in resp.data]
    except Exception as e:
        logger.warning(f"OpenAI embeddings request failed (fallback to lexical): {e}")
        return None


async def reset_semantic_search_index() -> None:
    """Clears in-memory chunk caches so next query reads/syncs fresh state from SQLite."""
    _FINGERPRINT_CACHE.clear()
    _CHUNKS_CACHE.clear()


async def sync_knowledge_index(
    compute_embeddings: bool = True,
    db_path: str = DB_PATH,
    client=None,
) -> list[dict]:
    """Rebuilds deduplicated chunks if needed and fills missing OpenAI embeddings."""
    async with _get_sync_lock(db_path):
        materials = await get_materials_rows(db_path)
        deduped = build_deduplicated_chunks(materials)
        missing_hashes = await sync_knowledge_chunk_rows(
            deduped, embedding_model=EMBEDDING_MODEL, db_path=db_path
        )

        if compute_embeddings and missing_hashes:
            chunk_by_hash = {c["chunk_hash"]: c["chunk_text"] for c in deduped}
            for start in range(0, len(missing_hashes), EMBEDDING_BATCH_SIZE):
                batch_hashes = missing_hashes[start : start + EMBEDDING_BATCH_SIZE]
                batch_texts = [chunk_by_hash[h] for h in batch_hashes if h in chunk_by_hash]
                if not batch_texts:
                    continue
                vectors = await _embed_texts(batch_texts, client=client)
                if not vectors or len(vectors) != len(batch_hashes):
                    break
                await save_chunk_embeddings(
                    dict(zip(batch_hashes, vectors)),
                    model=EMBEDDING_MODEL,
                    db_path=db_path,
                )

        stored = await get_all_knowledge_chunks(db_path)
        _CHUNKS_CACHE[db_path] = stored
        _FINGERPRINT_CACHE[db_path] = await get_materials_fingerprint(db_path)
        return stored


async def _ensure_chunks_fresh(
    db_path: str = DB_PATH,
    compute_embeddings: bool = True,
    client=None,
) -> list[dict]:
    current_fp = await get_materials_fingerprint(db_path)
    cached_fp = _FINGERPRINT_CACHE.get(db_path)
    cached_chunks = _CHUNKS_CACHE.get(db_path)

    if cached_chunks is not None and cached_fp == current_fp:
        # If OpenAI became available after an offline start, try to fill null embeddings once.
        has_missing = any(c.get("embedding") is None for c in cached_chunks)
        if not (compute_embeddings and has_missing and (client is not None or _get_openai_client() is not None)):
            return cached_chunks

    return await sync_knowledge_index(
        compute_embeddings=compute_embeddings, db_path=db_path, client=client
    )


async def build_and_reset_embeddings(db_path: str = DB_PATH, client=None) -> None:
    """Syncs SQLite knowledge chunks and computes any missing embeddings."""
    try:
        chunks = await sync_knowledge_index(compute_embeddings=True, db_path=db_path, client=client)
        logger.info(f"[Knowledge Index] Synced {len(chunks)} deduplicated chunks.")
    except Exception as e:
        logger.error(f"[Knowledge Index] Failed to sync embeddings: {e}", exc_info=True)


def filter_chunks_by_scope(
    chunks: list[dict],
    role_filter: Optional[str],
    scope: str = "role",
) -> list[dict]:
    """Filters chunks to user's role (+ ALL) for Stage 1 or returns all for global/fallback."""
    if scope != "role" or not role_filter:
        return chunks

    matched: list[dict] = []
    for ch in chunks:
        sources = ch.get("sources") or []
        role_sources = [s for s in sources if s.get("role") in (role_filter, "ALL")]
        if role_sources:
            matched.append({**ch, "scoped_sources": role_sources})
    return matched


def _token_matches_chunk(
    q_token: str,
    q_stem: str,
    chunk_lower: str,
    chunk_tokens_set: set[str],
    chunk_stems_set: set[str],
) -> Tuple[bool, bool]:
    """Returns (exact_word_or_stem_hit, is_strict_exact_boundary_hit)."""
    strict_re = re.compile(
        rf"(?<![0-9a-zA-Zа-яА-ЯіїєґІЇЄҐ']){re.escape(q_token)}(?![0-9a-zA-Zа-яА-ЯіїєґІЇЄҐ'])"
    )
    if strict_re.search(chunk_lower):
        return True, True

    if q_token in chunk_tokens_set:
        return True, True

    # For acronyms / tiny words (< 4 chars like 'рц', 'тз', 'вв'), only accept strict boundary hits
    # so 'рц' never matches inside 'серце'.
    if len(q_token) < 4:
        return False, False

    if q_stem in chunk_stems_set:
        return True, True

    if len(q_stem) >= 5 and q_stem in chunk_lower:
        return True, True

    return False, False


def _score_chunk(
    chunk: dict,
    query_lower: str,
    query_tokens: list[str],
    query_stems: list[str],
    query_embedding: Optional[list[float]],
) -> dict:
    sources = chunk.get("scoped_sources") or chunk.get("sources") or []
    titles_text = " ".join((s.get("title") or "") for s in sources).strip()
    searchable_text = f"{titles_text}\n{chunk['chunk_text']}".strip() if titles_text else chunk["chunk_text"]
    searchable_lower = _APOSTROPHES_RE.sub("'", searchable_text.lower())

    c_tokens = tokenize_text(searchable_lower, drop_stop_words=False)
    c_tokens_set = set(c_tokens)
    c_stems_set = {uk_stem(t) for t in c_tokens}

    matched_count = 0
    strict_count = 0
    for qt, qs in zip(query_tokens, query_stems):
        hit, strict_hit = _token_matches_chunk(qt, qs, searchable_lower, c_tokens_set, c_stems_set)
        if hit:
            matched_count += 1
        if strict_hit:
            strict_count += 1

    total_q = max(1, len(query_tokens))
    lexical_coverage = matched_count / total_q
    phrase_bonus = 0.25 if (len(query_lower) >= 3 and query_lower in searchable_lower) else 0.0
    lexical_score = min(1.0, lexical_coverage + phrase_bonus)

    # Full match for 1-2 word queries; >= 50% (and at least 1 hit) for longer questions.
    if total_q <= 2:
        is_exact_match = strict_count == total_q and total_q > 0
        has_partial_exact = strict_count > 0
    else:
        is_exact_match = strict_count >= max(2, math.ceil(total_q * 0.5))
        has_partial_exact = strict_count > 0

    vector_score = (
        _cosine_similarity(query_embedding, chunk.get("embedding"))
        if query_embedding is not None and chunk.get("embedding") is not None
        else None
    )

    if vector_score is not None:
        base_score = 0.60 * vector_score + 0.40 * lexical_score
    else:
        base_score = lexical_score

    exact_boost = 0.30 if is_exact_match else (0.12 if has_partial_exact else 0.0)
    final_score = base_score + exact_boost

    return {
        "chunk": chunk,
        "final_score": final_score,
        "vector_score": vector_score if vector_score is not None else 0.0,
        "lexical_score": lexical_score,
        "matched_ratio": matched_count / total_q,
        "matched_count": matched_count,
        "strict_count": strict_count,
        "is_exact_match": is_exact_match,
        "has_partial_exact": has_partial_exact,
    }


def _extract_matching_windows(chunk_text: str, query_tokens: list[str], window_sentences: int = 2) -> str:
    """Extracts paragraphs or +-N sentence windows around matching tokens to preserve every mention."""
    if not query_tokens:
        return chunk_text

    stems = [uk_stem(t) for t in query_tokens]

    def _line_matches(segment: str) -> bool:
        seg_lower = _APOSTROPHES_RE.sub("'", segment.lower())
        toks = set(tokenize_text(seg_lower, drop_stop_words=False))
        seg_stems = {uk_stem(t) for t in toks}
        for qt, qs in zip(query_tokens, stems):
            hit, _ = _token_matches_chunk(qt, qs, seg_lower, toks, seg_stems)
            if hit:
                return True
        return False

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", chunk_text) if p.strip()]
    matched_parts: list[str] = []

    for para in paragraphs:
        if not _line_matches(para):
            continue
        if len(para) <= 380:
            matched_parts.append(para)
            continue

        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", para) if s.strip()]
        if len(sentences) <= 3:
            matched_parts.append(para)
            continue

        kept_indices: set[int] = set()
        for idx, sent in enumerate(sentences):
            if _line_matches(sent):
                lo = max(0, idx - window_sentences)
                hi = min(len(sentences) - 1, idx + window_sentences)
                kept_indices.update(range(lo, hi + 1))

        if not kept_indices:
            matched_parts.append(para)
        else:
            sorted_idx = sorted(kept_indices)
            groups: list[str] = []
            cur_group: list[str] = []
            prev_i: Optional[int] = None
            for i in sorted_idx:
                if prev_i is not None and i > prev_i + 1:
                    groups.append(" ".join(cur_group))
                    cur_group = []
                cur_group.append(sentences[i])
                prev_i = i
            if cur_group:
                groups.append(" ".join(cur_group))
            matched_parts.append(" ... ".join(groups))

    return "\n\n".join(matched_parts) if matched_parts else chunk_text


def format_sources_label(chunk: dict, scope: str = "global", max_labels: int = 5) -> str:
    """Formats concise unique [Role, Day X] citations for a chunk."""
    sources = chunk.get("scoped_sources") if scope == "role" else chunk.get("sources")
    if not sources:
        sources = chunk.get("sources") or []

    seen: set[tuple[str, int, str]] = set()
    labels: list[str] = []
    for src in sources:
        role = src.get("display_role") or src.get("role") or UNASSIGNED_ROLE_LABEL
        if role == UNASSIGNED_ROLE:
            role = UNASSIGNED_ROLE_LABEL
        day = int(src.get("day") or 1)
        title = (src.get("title") or "").strip()
        generic_title = f"День {day} — Текст"
        clean_title = title if (title and title != generic_title and title != f"День {day} - Текст") else ""
        key = (role, day, clean_title)
        if key not in seen:
            seen.add(key)
            label = f"{role} (День {day}: {clean_title})" if clean_title else f"{role} (День {day})"
            labels.append(label)

    if len(labels) > max_labels:
        extra = len(labels) - max_labels
        return ", ".join(labels[:max_labels]) + f" та ще {extra}"
    return ", ".join(labels)


async def hybrid_search_chunks(
    query: str,
    role_filter: Optional[str] = None,
    scope: str = "role",
    max_context_chars: int = MAX_CONTEXT_CHARS,
    exclude_hashes: Optional[set[str]] = None,
    db_path: str = DB_PATH,
    client=None,
    query_embedding: Optional[list[float]] = None,
) -> dict:
    """
    Runs hybrid vector + lexical + guaranteed exact-token search over indexed chunks.

    Returns:
        {
            "results": list[dict],          # selected entries with 'excerpt', 'sources_label', 'chunk', 'score', ...
            "scoped_chunk_count": int,      # total chunks available in this scope
            "has_relevant_match": bool,     # whether any entry passes relevance threshold
            "used_vectors": bool,
        }
    """
    normalized_query = _APOSTROPHES_RE.sub("'", (query or "").strip())
    if not normalized_query:
        return {"results": [], "scoped_chunk_count": 0, "has_relevant_match": False, "used_vectors": False}

    all_chunks = await _ensure_chunks_fresh(db_path=db_path, compute_embeddings=True, client=client)
    scoped = filter_chunks_by_scope(all_chunks, role_filter=role_filter, scope=scope)
    if exclude_hashes:
        remaining = [c for c in scoped if c["chunk_hash"] not in exclude_hashes]
        if remaining:
            scoped = remaining

    if not scoped:
        return {"results": [], "scoped_chunk_count": 0, "has_relevant_match": False, "used_vectors": False}

    has_any_vectors = any(c.get("embedding") is not None for c in scoped)
    active_q_emb = query_embedding
    if active_q_emb is None and has_any_vectors:
        vecs = await _embed_texts([normalized_query], client=client)
        if vecs:
            active_q_emb = vecs[0]

    q_lower = normalized_query.lower()
    q_tokens = tokenize_query(normalized_query)
    q_stems = [uk_stem(t) for t in q_tokens]

    scored = [
        _score_chunk(c, q_lower, q_tokens, q_stems, active_q_emb)
        for c in scoped
    ]
    scored.sort(
        key=lambda item: (
            1 if item["is_exact_match"] else 0,
            item["final_score"],
            item["lexical_score"],
            item["vector_score"],
        ),
        reverse=True,
    )

    top_item = scored[0]
    has_relevant = bool(
        top_item["is_exact_match"]
        or top_item["has_partial_exact"]
        or top_item["lexical_score"] >= 0.20
        or (active_q_emb is not None and top_item["vector_score"] >= 0.25)
    )

    selected: list[dict] = []
    selected_hashes: set[str] = set()
    used_chars = 0

    def _add_entry(entry: dict, excerpt: str) -> bool:
        nonlocal used_chars
        ch_hash = entry["chunk"]["chunk_hash"]
        if ch_hash in selected_hashes:
            return False
        label = format_sources_label(entry["chunk"], scope=scope)
        block_len = len(excerpt) + len(label) + 40
        if selected and used_chars + block_len > max_context_chars:
            return False
        selected.append(
            {
                "chunk_hash": ch_hash,
                "excerpt": excerpt,
                "full_text": entry["chunk"]["chunk_text"],
                "sources": entry["chunk"].get("scoped_sources") or entry["chunk"].get("sources") or [],
                "sources_label": label,
                "score": entry["final_score"],
                "vector_score": entry["vector_score"],
                "lexical_score": entry["lexical_score"],
                "is_exact_match": entry["is_exact_match"],
            }
        )
        selected_hashes.add(ch_hash)
        used_chars += block_len
        return True

    # 1. Include top relevant full chunks (always consider #0; filter clear zero-signal tail).
    for idx, item in enumerate(scored[:TOP_FULL_CHUNKS]):
        if (
            idx == 0
            or item["is_exact_match"]
            or item["has_partial_exact"]
            or item["lexical_score"] > 0
            or item["vector_score"] >= 0.18
        ):
            _add_entry(item, item["chunk"]["chunk_text"])

    # 2. Guarantee coverage for ALL remaining chunks containing exact term matches.
    exact_overflow = [item for item in scored[TOP_FULL_CHUNKS:] if item["is_exact_match"]]
    # If few full exact hits, also check partial exact hits when query is multi-word.
    if len(q_tokens) > 2:
        exact_overflow.extend(
            item
            for item in scored[TOP_FULL_CHUNKS:]
            if not item["is_exact_match"] and item["has_partial_exact"]
        )

    for item in exact_overflow:
        windowed = _extract_matching_windows(item["chunk"]["chunk_text"], q_tokens)
        candidate_text = (
            item["chunk"]["chunk_text"]
            if used_chars + len(item["chunk"]["chunk_text"]) < max_context_chars * 0.7
            else windowed
        )
        if not _add_entry(item, candidate_text):
            # Try tighter windowed snippet if full chunk didn't fit remaining budget.
            if candidate_text != windowed:
                _add_entry(item, windowed)

    return {
        "results": selected,
        "scoped_chunk_count": len(scoped),
        "has_relevant_match": has_relevant,
        "used_vectors": active_q_emb is not None,
    }


async def semantic_search(query: str, limit: int = 5, db_path: str = DB_PATH) -> List[SemanticSearchResult]:
    """Compatibility wrapper over hybrid_search_chunks returning SemanticSearchResult items."""
    if not (query or "").strip() or limit <= 0:
        return []
    search_out = await hybrid_search_chunks(query=query, role_filter=None, scope="global", db_path=db_path)
    out: List[SemanticSearchResult] = []
    for item in search_out["results"][:limit]:
        first_src = (item.get("sources") or [{}])[0]
        out.append(
            SemanticSearchResult(
                material_id=first_src.get("material_id"),
                day=first_src.get("day"),
                role=first_src.get("display_role") or first_src.get("role"),
                block_type="text",
                score=float(item.get("score") or 0.0),
                preview=item.get("excerpt") or "",
            )
        )
    return out


__all__ = [
    "EMBEDDING_MODEL",
    "MAX_CONTEXT_CHARS",
    "SemanticSearchResult",
    "build_and_reset_embeddings",
    "filter_chunks_by_scope",
    "format_sources_label",
    "hybrid_search_chunks",
    "reset_semantic_search_index",
    "semantic_search",
    "sync_knowledge_index",
    "tokenize_query",
    "uk_stem",
]
