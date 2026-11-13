"""Hybrid retrieval engine over training materials (OpenAI embeddings + Ukrainian lexical/exact scan).

Zero heavy ML dependencies (no faiss/torch/sentence-transformers): computes cosine
similarity in pure Python over cached SQLite vectors in `material_chunks` and
guarantees complete exact-token recall within context budget.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
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
    "ого",
    "ому",
    "ий",
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


_TRAILING_TIME_SLASH_RE = re.compile(r"(?:\s+\d{1,2}:\d{2})?\s*/{2,}\s*$")
_STANDALONE_SLASHES_RE = re.compile(r"(?:^|\s)/{2,}(?=\s|$)")
_LEADING_TIMESTAMP_RE = re.compile(r"^\s*\[[^\]]*\d{1,2}[:.]\d{2}[^\]]*\]\s*")
_SUBORDINATE_WORDS = frozenset(
    {"якщо", "коли", "тому", "щоб", "аби", "чому", "скільки", "який", "яка", "яке", "які", "хто"}
)


@dataclass(frozen=True)
class DomainConceptSpec:
    """Bidirectional acronym/phrase equivalence class for BULKA retail instructions."""

    key: str
    exact_words: tuple[str, ...] = ()
    prefix_phrases: tuple[tuple[str, ...], ...] = ()
    regex_patterns: tuple[re.Pattern, ...] = ()
    abbr_hint: str = ""
    full_hint: str = ""
    prompt_note: str = ""


@dataclass(frozen=True)
class QueryConcept:
    """Single semantic unit extracted from the user query (domain concept or stemmed token)."""

    key: str
    domain_spec: Optional[DomainConceptSpec] = None
    token: str = ""
    stem: str = ""


_BOUNDARY_FMT = r"(?<![0-9a-zA-Zа-яА-ЯіїєґІЇЄҐ']){pat}(?![0-9a-zA-Zа-яА-ЯіїєґІЇЄҐ'])"

_DOMAIN_CONCEPT_GROUPS: tuple[DomainConceptSpec, ...] = (
    DomainConceptSpec(
        key="rc",
        exact_words=("рц",),
        prefix_phrases=(
            ("розподільч", "центр"),
            ("розподільн", "центр"),
            ("розподільч", "склад"),
            ("розподільн", "склад"),
        ),
        abbr_hint="РЦ",
        full_hint="Розподільчий центр",
        prompt_note="«РЦ» у матеріалах означає «Розподільчий центр» (і навпаки).",
    ),
    DomainConceptSpec(
        key="tt",
        exact_words=("тт",),
        prefix_phrases=(
            ("торгов", "точк"),
            ("торгов", "точц"),
            ("торгівельн", "точк"),
            ("торгівельн", "точц"),
            ("торговельн", "точк"),
            ("торговельн", "точц"),
        ),
        abbr_hint="ТТ",
        full_hint="Торгова точка",
        prompt_note="«ТТ» у матеріалах означає «Торгова точка» (магазин).",
    ),
    DomainConceptSpec(
        key="sb",
        exact_words=("сб",),
        prefix_phrases=(("служб", "безпек"), ("служб", "безпец")),
        abbr_hint="СБ",
        full_hint="Служба безпеки",
        prompt_note="«СБ» у матеріалах означає «Служба безпеки».",
    ),
    DomainConceptSpec(
        key="dmp",
        exact_words=("дмп",),
        prefix_phrases=(("додатков", "місц", "продаж"),),
        abbr_hint="ДМП",
        full_hint="Додаткове місце продажу",
        prompt_note="«ДМП» у матеріалах означає «Додаткове місце продажу».",
    ),
    DomainConceptSpec(
        key="tzd",
        exact_words=("тзд", "тсд"),
        prefix_phrases=(("термінал", "збор", "дан"),),
        abbr_hint="ТЗД / ТСД",
        full_hint="Термінал збору даних",
        prompt_note="«ТЗД» / «ТСД» у матеріалах означає «Термінал збору даних».",
    ),
    DomainConceptSpec(
        key="ho",
        exact_words=("хо",),
        prefix_phrases=(("холодильн", "обладн"), ("холодильн", "камер")),
        abbr_hint="ХО",
        full_hint="Холодильне обладнання",
        prompt_note="«ХО» у матеріалах означає «Холодильне обладнання».",
    ),
    DomainConceptSpec(
        key="km",
        exact_words=("км",),
        prefix_phrases=(("категорійн", "менеджер"),),
        abbr_hint="КМ",
        full_hint="Категорійний менеджер",
        prompt_note="«КМ» у матеріалах означає «Категорійний менеджер».",
    ),
    DomainConceptSpec(
        key="csi",
        exact_words=("csi",),
        prefix_phrases=(("індекс", "задоволен"),),
        abbr_hint="CSI",
        full_hint="Індекс задоволеності покупців",
        prompt_note="«CSI» у матеріалах означає «Індекс задоволеності споживачів/покупців».",
    ),
    DomainConceptSpec(
        key="fifo",
        exact_words=("fifo", "фіфо"),
        abbr_hint="FIFO",
        full_hint="ФІФО",
        prompt_note="«FIFO» і «ФІФО» позначають один і той самий принцип ротації товару.",
    ),
    DomainConceptSpec(
        key="sku",
        exact_words=("sku", "скю"),
        abbr_hint="SKU",
        full_hint="СКЮ",
        prompt_note="«СКЮ» і «SKU» позначають товарну позицію.",
    ),
    DomainConceptSpec(
        key="fo",
        prefix_phrases=(("фрукт", "овоч"), ("овоч", "фрукт")),
        regex_patterns=(re.compile(r"(?<![0-9a-zA-Zа-яА-ЯіїєґІЇЄҐ])ф/о(?![0-9a-zA-Zа-яА-ЯіїєґІЇЄҐ])"),),
        abbr_hint="ф/о",
        full_hint="фрукти та овочі",
        prompt_note="«ф/о» у матеріалах означає «фрукти та овочі».",
    ),
    DomainConceptSpec(
        key="vv",
        exact_words=("вв",),
        prefix_phrases=(("власн", "виробництв"),),
        abbr_hint="ВВ",
        full_hint="Власне виробництво",
        prompt_note="«ВВ» у матеріалах означає «Власне виробництво».",
    ),
)

_EXACT_WORD_REGEXES: dict[str, re.Pattern] = {
    word: re.compile(_BOUNDARY_FMT.format(pat=re.escape(word)))
    for spec in _DOMAIN_CONCEPT_GROUPS
    for word in spec.exact_words
}


def sanitize_search_query(query: str) -> str:
    """Strips copy-paste messenger artifacts (e.g. '09:29 //', leading timestamps) safely."""
    raw = (query or "").strip()
    if not raw:
        return ""
    cleaned = _LEADING_TIMESTAMP_RE.sub("", raw)
    cleaned = _TRAILING_TIME_SLASH_RE.sub("", cleaned)
    cleaned = _STANDALONE_SLASHES_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" \t\r\n,;/")
    return cleaned if cleaned else raw


def is_topic_list_query(query: str) -> bool:
    """Returns True when query looks like a comma/semicolon-separated topic list."""
    cleaned = sanitize_search_query(query)
    if not cleaned or "?" in cleaned:
        return False
    if "," not in cleaned and ";" not in cleaned:
        return False
    parts = [p.strip() for p in re.split(r"[,;]+", cleaned) if p.strip()]
    if len(parts) < 2:
        return False
    lower_tokens = set(tokenize_text(cleaned, drop_stop_words=False))
    if lower_tokens & _SUBORDINATE_WORDS:
        return False
    return all(len(part.split()) <= 4 for part in parts)


def _phrase_prefixes_nearby(
    prefixes: tuple[str, ...],
    ordered_tokens: Sequence[str],
    max_span: int = 5,
) -> Optional[list[int]]:
    """Returns matched token indices when all prefixes appear within `max_span` tokens."""
    pos_lists = [
        [idx for idx, tok in enumerate(ordered_tokens) if tok.startswith(pref)]
        for pref in prefixes
    ]
    if any(not lst for lst in pos_lists):
        return None
    for anchor in pos_lists[0]:
        chosen = [anchor]
        used = {anchor}
        ok = True
        for lst in pos_lists[1:]:
            match_idx = next(
                (pos for pos in lst if pos not in used and abs(pos - anchor) <= max_span),
                None,
            )
            if match_idx is None:
                ok = False
                break
            chosen.append(match_idx)
            used.add(match_idx)
        if ok and (max(chosen) - min(chosen)) <= max_span:
            return chosen
    return None


def analyze_query_concepts(query: str) -> dict:
    """Decomposes user query into canonical domain concepts + remaining lexical tokens."""
    cleaned = sanitize_search_query(query)
    norm_lower = _APOSTROPHES_RE.sub("'", cleaned.lower())
    clauses_with_offsets: list[tuple[int, list[str]]] = []
    ordered_tokens: list[str] = []
    for sub_clause in re.split(r"[,;]+", norm_lower):
        sub_tokens = tokenize_text(sub_clause, drop_stop_words=False)
        if sub_tokens:
            clauses_with_offsets.append((len(ordered_tokens), sub_tokens))
            ordered_tokens.extend(sub_tokens)

    concepts: list[QueryConcept] = []
    seen_keys: set[str] = set()
    consumed_indices: set[int] = set()
    matched_specs: list[DomainConceptSpec] = []

    for spec in _DOMAIN_CONCEPT_GROUPS:
        matched_here = False
        for w in spec.exact_words:
            for idx, tok in enumerate(ordered_tokens):
                if tok == w:
                    consumed_indices.add(idx)
                    matched_here = True
        for rx in spec.regex_patterns:
            if rx.search(norm_lower):
                matched_here = True
        for offset, sub_tokens in clauses_with_offsets:
            for phrase in spec.prefix_phrases:
                hit_indices = _phrase_prefixes_nearby(phrase, sub_tokens, max_span=5)
                if hit_indices is not None:
                    consumed_indices.update(offset + i for i in hit_indices)
                    matched_here = True
                    break
        if matched_here and spec.key not in seen_keys:
            seen_keys.add(spec.key)
            matched_specs.append(spec)
            concepts.append(QueryConcept(key=f"domain:{spec.key}", domain_spec=spec))

    for idx, tok in enumerate(ordered_tokens):
        if idx in consumed_indices or tok in _STOP_WORDS:
            continue
        key = f"tok:{tok}"
        if key not in seen_keys:
            seen_keys.add(key)
            concepts.append(QueryConcept(key=key, token=tok, stem=uk_stem(tok)))

    if not concepts and ordered_tokens:
        for tok in ordered_tokens:
            key = f"tok:{tok}"
            if key not in seen_keys:
                seen_keys.add(key)
                concepts.append(QueryConcept(key=key, token=tok, stem=uk_stem(tok)))

    alias_additions: list[str] = []
    term_hints: list[str] = []
    for spec in matched_specs:
        if spec.prompt_note:
            term_hints.append(spec.prompt_note)
        abbr_lower = spec.abbr_hint.lower()
        if spec.abbr_hint and abbr_lower not in norm_lower and spec.abbr_hint not in alias_additions:
            alias_additions.append(spec.abbr_hint)

    embedding_text = (
        f"{cleaned} ({', '.join(alias_additions)})"
        if alias_additions and cleaned
        else cleaned
    )

    return {
        "cleaned_query": cleaned,
        "concepts": concepts,
        "embedding_text": embedding_text,
        "term_hints": term_hints,
        "is_topic_list": is_topic_list_query(cleaned),
    }


def build_term_hints(query: str) -> list[str]:
    """Returns concise domain terminology notes relevant to the query."""
    return analyze_query_concepts(query)["term_hints"]


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


def _concept_matches_text(
    concept: QueryConcept,
    text_lower: str,
    ordered_tokens: Sequence[str],
    tokens_set: set[str],
    stems_set: set[str],
) -> Tuple[bool, bool]:
    """Evaluates whether a QueryConcept matches text, handling domain aliases bidirectionally."""
    spec = concept.domain_spec
    if spec is None:
        return _token_matches_chunk(
            concept.token, concept.stem, text_lower, tokens_set, stems_set
        )

    for word in spec.exact_words:
        if word in tokens_set or _EXACT_WORD_REGEXES[word].search(text_lower):
            return True, True

    for rx in spec.regex_patterns:
        if rx.search(text_lower):
            return True, True

    for phrase in spec.prefix_phrases:
        if _phrase_prefixes_nearby(phrase, ordered_tokens, max_span=5) is not None:
            return True, True

    return False, False


def _score_chunk(
    chunk: dict,
    query_lower: str,
    concepts: Sequence[QueryConcept],
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
    for concept in concepts:
        hit, strict_hit = _concept_matches_text(
            concept, searchable_lower, c_tokens, c_tokens_set, c_stems_set
        )
        if hit:
            matched_count += 1
        if strict_hit:
            strict_count += 1

    total_q = max(1, len(concepts))
    lexical_coverage = matched_count / total_q
    phrase_bonus = 0.25 if (len(query_lower) >= 3 and query_lower in searchable_lower) else 0.0
    lexical_score = min(1.0, lexical_coverage + phrase_bonus)

    # Full match for 1-2 concept queries; >= 50% (and at least 2 hits) for longer questions.
    if total_q <= 2:
        is_exact_match = strict_count == total_q and len(concepts) > 0
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


def _extract_matching_windows(
    chunk_text: str,
    query_tokens: Sequence[str],
    window_sentences: int = 2,
    concepts: Optional[Sequence[QueryConcept]] = None,
) -> str:
    """Extracts paragraphs or +-N sentence windows around matching concepts/tokens."""
    active_concepts: Sequence[QueryConcept] = (
        concepts
        if concepts is not None
        else [QueryConcept(key=f"tok:{t}", token=t, stem=uk_stem(t)) for t in query_tokens]
    )
    if not active_concepts:
        return chunk_text

    def _line_matches(segment: str) -> bool:
        seg_lower = _APOSTROPHES_RE.sub("'", segment.lower())
        ordered = tokenize_text(seg_lower, drop_stop_words=False)
        toks = set(ordered)
        seg_stems = {uk_stem(t) for t in toks}
        for concept in active_concepts:
            hit, _ = _concept_matches_text(concept, seg_lower, ordered, toks, seg_stems)
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
    analysis = analyze_query_concepts(query)
    cleaned_query = analysis["cleaned_query"]
    normalized_query = _APOSTROPHES_RE.sub("'", cleaned_query)
    if not normalized_query:
        return {
            "results": [],
            "scoped_chunk_count": 0,
            "has_relevant_match": False,
            "used_vectors": False,
            "cleaned_query": "",
            "concept_count": 0,
            "is_topic_list": False,
            "term_hints": [],
        }

    all_chunks = await _ensure_chunks_fresh(db_path=db_path, compute_embeddings=True, client=client)
    scoped = filter_chunks_by_scope(all_chunks, role_filter=role_filter, scope=scope)
    if exclude_hashes:
        remaining = [c for c in scoped if c["chunk_hash"] not in exclude_hashes]
        if remaining:
            scoped = remaining

    if not scoped:
        return {
            "results": [],
            "scoped_chunk_count": 0,
            "has_relevant_match": False,
            "used_vectors": False,
            "cleaned_query": cleaned_query,
            "concept_count": len(analysis["concepts"]),
            "is_topic_list": analysis["is_topic_list"],
            "term_hints": analysis["term_hints"],
        }

    has_any_vectors = any(c.get("embedding") is not None for c in scoped)
    active_q_emb = query_embedding
    if active_q_emb is None and has_any_vectors:
        embed_input = _APOSTROPHES_RE.sub("'", analysis["embedding_text"] or normalized_query)
        vecs = await _embed_texts([embed_input], client=client)
        if vecs:
            active_q_emb = vecs[0]

    q_lower = normalized_query.lower()
    concepts = analysis["concepts"]
    q_tokens = tokenize_query(normalized_query)

    scored = [
        _score_chunk(c, q_lower, concepts, active_q_emb)
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
                "has_partial_exact": entry["has_partial_exact"],
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
    # For multi-word queries or comma-separated topic lists, also bring partial exact hits within budget.
    if len(concepts) > 2 or analysis["is_topic_list"]:
        exact_overflow.extend(
            item
            for item in scored[TOP_FULL_CHUNKS:]
            if not item["is_exact_match"] and item["has_partial_exact"]
        )

    for item in exact_overflow:
        windowed = _extract_matching_windows(
            item["chunk"]["chunk_text"], q_tokens, concepts=concepts
        )
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
        "cleaned_query": cleaned_query,
        "concept_count": len(concepts),
        "is_topic_list": analysis["is_topic_list"],
        "term_hints": analysis["term_hints"],
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
    "analyze_query_concepts",
    "build_and_reset_embeddings",
    "build_term_hints",
    "filter_chunks_by_scope",
    "format_sources_label",
    "hybrid_search_chunks",
    "is_topic_list_query",
    "reset_semantic_search_index",
    "sanitize_search_query",
    "semantic_search",
    "sync_knowledge_index",
    "tokenize_query",
    "uk_stem",
]
