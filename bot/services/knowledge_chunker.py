"""Pure helpers for cleaning, chunking, and deduplicating training materials."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Optional

IGNORED_CONTENT_TYPES = frozenset({"test", "photo_files", "video_files"})
UNASSIGNED_ROLE = "__UNASSIGNED__"
UNASSIGNED_ROLE_LABEL = "Загальні матеріали"
MIN_CLEAN_TEXT_LENGTH = 10


def _normalize_line_breaks(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    joined = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", joined)


def extract_clean_text(raw_content: Optional[str], content_type: str = "text") -> str:
    """Extracts human-readable instructional text, stripping media JSON payloads."""
    if not raw_content or (content_type or "text") in IGNORED_CONTENT_TYPES:
        return ""

    stripped = str(raw_content).strip()
    if not stripped:
        return ""

    if (stripped.startswith("[") and stripped.endswith("]")) or (
        stripped.startswith("{") and stripped.endswith("}")
    ):
        try:
            parsed: Any = json.loads(stripped)
            if isinstance(parsed, dict):
                parsed = [parsed]
            if isinstance(parsed, list):
                parts: list[str] = []
                for item in parsed:
                    if isinstance(item, dict):
                        txt = str(item.get("text") or "").strip()
                        if txt:
                            parts.append(txt)
                    elif isinstance(item, str):
                        txt = item.strip()
                        if txt:
                            parts.append(txt)
                return _normalize_line_breaks("\n\n".join(parts))
        except json.JSONDecodeError:
            pass

    return _normalize_line_breaks(stripped)


def _split_oversized_unit(unit: str, max_chars: int) -> list[str]:
    """Splits a long paragraph by sentences, then by words if a sentence exceeds max_chars."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", unit) if s.strip()]
    segments: list[str] = []
    for sent in sentences:
        if len(sent) <= max_chars:
            segments.append(sent)
            continue
        words = sent.split()
        buf: list[str] = []
        buf_len = 0
        for word in words:
            added = len(word) + (1 if buf else 0)
            if buf and buf_len + added > max_chars:
                segments.append(" ".join(buf))
                buf = [word]
                buf_len = len(word)
            else:
                buf.append(word)
                buf_len += added
        if buf:
            segments.append(" ".join(buf))
    return segments


def _tail_overlap(text: str, overlap_chars: int) -> str:
    """Returns trailing word-aligned overlap up to overlap_chars."""
    if overlap_chars <= 0 or not text:
        return ""
    if len(text) <= overlap_chars:
        return text
    candidate = text[-overlap_chars:]
    space_idx = candidate.find(" ")
    if space_idx != -1 and space_idx < len(candidate) - 1:
        return candidate[space_idx + 1 :].strip()
    return candidate.strip()


def split_into_chunks(
    text: str,
    target_chars: int = 750,
    max_chars: int = 900,
    overlap_chars: int = 120,
) -> list[str]:
    """Splits clean instructional text into logical overlapping chunks."""
    cleaned = _normalize_line_breaks(text or "")
    if len(cleaned) < MIN_CLEAN_TEXT_LENGTH:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]

    units: list[str] = []
    for para in re.split(r"\n{2,}", cleaned):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_chars:
            units.append(para)
        else:
            units.extend(_split_oversized_unit(para, max_chars))

    chunks: list[str] = []
    current_parts: list[str] = []
    current_len = 0
    has_non_overlap_content = False

    for unit in units:
        sep_len = 2 if current_parts else 0
        if current_parts and (current_len + sep_len + len(unit) > target_chars) and (
            current_len >= target_chars // 2 or current_len + sep_len + len(unit) > max_chars
        ):
            chunk_body = "\n\n".join(current_parts).strip()
            if len(chunk_body) >= MIN_CLEAN_TEXT_LENGTH:
                chunks.append(chunk_body)
            overlap = _tail_overlap(chunk_body, overlap_chars)
            current_parts = [overlap] if overlap else []
            current_len = len(overlap)
            has_non_overlap_content = False

            # If a single unit + overlap still exceeds max_chars, drop overlap for this unit.
            if current_parts and current_len + 2 + len(unit) > max_chars:
                current_parts = []
                current_len = 0

        if current_parts:
            current_len += 2 + len(unit)
        else:
            current_len += len(unit)
        current_parts.append(unit)
        has_non_overlap_content = True

    if current_parts and has_non_overlap_content:
        chunk_body = "\n\n".join(current_parts).strip()
        if len(chunk_body) >= MIN_CLEAN_TEXT_LENGTH:
            chunks.append(chunk_body)

    return chunks


def normalize_chunk_for_hash(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def compute_chunk_hash(text: str) -> str:
    return hashlib.sha256(normalize_chunk_for_hash(text).encode("utf-8")).hexdigest()


def normalize_source_role(raw_role: Optional[str]) -> tuple[str, str]:
    """Returns (scope_role, display_role) for indexing and display."""
    cleaned = (raw_role or "").strip()
    if not cleaned:
        return UNASSIGNED_ROLE, UNASSIGNED_ROLE_LABEL
    if cleaned == "ALL":
        return "ALL", "Всі посади"
    return cleaned, cleaned


def build_deduplicated_chunks(materials: list[dict]) -> list[dict]:
    """Parses, chunks, and deduplicates material texts while tracking all (role, day) sources."""
    by_hash: dict[str, dict] = {}
    seen_source_keys: dict[str, set[tuple]] = {}

    for record in materials or []:
        content_type = (record.get("content_type") or "text").strip()
        clean_text = extract_clean_text(record.get("content"), content_type=content_type)
        if len(clean_text) < MIN_CLEAN_TEXT_LENGTH:
            continue

        scope_role, display_role = normalize_source_role(record.get("role"))
        source_entry = {
            "material_id": record.get("id"),
            "role": scope_role,
            "display_role": display_role,
            "day": int(record.get("day") or 1),
            "title": (record.get("title") or "").strip(),
        }
        source_key = (source_entry["material_id"], scope_role, source_entry["day"], source_entry["title"])

        for chunk_text in split_into_chunks(clean_text):
            chunk_hash = compute_chunk_hash(chunk_text)
            if chunk_hash not in by_hash:
                by_hash[chunk_hash] = {
                    "chunk_hash": chunk_hash,
                    "chunk_text": chunk_text,
                    "sources": [source_entry],
                }
                seen_source_keys[chunk_hash] = {source_key}
            elif source_key not in seen_source_keys[chunk_hash]:
                by_hash[chunk_hash]["sources"].append(source_entry)
                seen_source_keys[chunk_hash].add(source_key)

    return list(by_hash.values())
