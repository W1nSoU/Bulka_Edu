#!/usr/bin/env python3
"""
Міграційний скрипт для перенесення контенту з days/*.py у таблицю materials.

Алгоритм:
1. Імпортує всі модулі у каталозі days з префіксом dayN.
2. Збирає legacy-структури (MATERIALS / LEGACY_MATERIALS / get_content()).
3. Нормалізує їх до записів: роль, день, тип контенту, назва, текст/URL.
4. Заносить дані в БД через database.materials.add_or_update_material.
"""
from __future__ import annotations

import asyncio
import importlib
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from database.schema import init_db  # noqa: E402
from database.materials import add_or_update_material  # noqa: E402

DEFAULT_ROLE = "ALL"
KNOWN_RECORD_FIELDS = {"role", "content_type", "title", "content", "resource_url", "order_index"}
KNOWN_CONTENT_TYPES = {"video", "comic", "info", "text", "audio", "image", "other"}


def discover_day_modules() -> List[tuple[int, str]]:
    """Повертає відсортований список (день, модуль) для days/dayN.py."""
    modules: List[tuple[int, str]] = []
    for path in sorted((ROOT_DIR / "days").glob("day*.py")):
        name = path.stem
        if name == "__init__":
            continue
        try:
            day = int(name.replace("day", ""))
        except ValueError:
            continue
        modules.append((day, f"days.{name}"))
    return sorted(modules, key=lambda x: x[0])


def resolve_raw_material(module: Any) -> Any:
    """Повертає сирі дані з модуля дня."""
    if hasattr(module, "LEGACY_MATERIALS"):
        return module.LEGACY_MATERIALS
    if hasattr(module, "MATERIALS"):
        return module.MATERIALS
    if hasattr(module, "get_materials"):
        return module.get_materials()
    if hasattr(module, "get_content"):
        return module.get_content()
    return None


def _flatten_materials(
    raw: Any,
    day: int,
    *,
    forced_role: str | None = None,
    forced_type: str | None = None,
) -> List[Dict[str, Any]]:
    """Перетворює довільні структури у список словників матеріалів."""
    results: List[Dict[str, Any]] = []
    if raw is None:
        return results

    if callable(raw):
        return _flatten_materials(raw(), day, forced_role=forced_role, forced_type=forced_type)

    if isinstance(raw, str):
        results.append(
            {
                "role": forced_role or DEFAULT_ROLE,
                "content_type": (forced_type or "text").lower(),
                "title": f"День {day} · Legacy контент",
                "content": raw.strip(),
            }
        )
        return results

    if isinstance(raw, dict):
        if any(key in KNOWN_RECORD_FIELDS for key in raw.keys()):
            record = dict(raw)
            record.setdefault("role", forced_role or DEFAULT_ROLE)
            record.setdefault("content_type", forced_type or "text")
            record.setdefault("title", f"День {day} · Legacy контент")
            results.append(record)
            return results

        for key, value in raw.items():
            key_lower = key.lower() if isinstance(key, str) else str(key)
            if key_lower in KNOWN_CONTENT_TYPES:
                results.extend(
                    _flatten_materials(
                        value,
                        day,
                        forced_role=forced_role or DEFAULT_ROLE,
                        forced_type=key_lower,
                    )
                )
            else:
                results.extend(
                    _flatten_materials(
                        value,
                        day,
                        forced_role=key if isinstance(key, str) else forced_role,
                        forced_type=forced_type,
                    )
                )
        return results

    if isinstance(raw, (list, tuple, set)):
        for idx, item in enumerate(raw):
            nested = _flatten_materials(item, day, forced_role=forced_role, forced_type=forced_type)
            for record in nested:
                record.setdefault("order_index", idx)
                results.append(record)
        return results

    results.append(
        {
            "role": forced_role or DEFAULT_ROLE,
            "content_type": forced_type or "text",
            "title": f"День {day} · Legacy контент",
            "content": str(raw),
        }
    )
    return results


def normalize_records(records: Iterable[Dict[str, Any]], day: int) -> List[Dict[str, Any]]:
    """Гарантує наявність усіх обов'язкових полів та коректних order_index."""
    counters: Dict[tuple[str, str], int] = defaultdict(int)
    normalized: List[Dict[str, Any]] = []

    for record in records:
        role = record.get("role") or DEFAULT_ROLE
        content_type = (record.get("content_type") or "text").lower()
        key = (role, content_type)
        order_index = record.get("order_index")
        if order_index is None:
            order_index = counters[key]
        counters[key] = max(counters[key], order_index + 1)

        normalized.append(
            {
                "role": role,
                "day": day,
                "content_type": content_type,
                "title": record.get("title") or f"День {day} · Legacy контент",
                "content": record.get("content"),
                "resource_url": record.get("resource_url"),
                "order_index": order_index,
            }
        )
    return normalized


async def migrate() -> None:
    await init_db()
    modules = discover_day_modules()
    if not modules:
        print("❌ Не знайдено модулів днів у каталозі days/.")
        return

    total_records = 0

    for day, module_path in modules:
        module = importlib.import_module(module_path)
        raw = resolve_raw_material(module)
        records = _flatten_materials(raw, day)
        normalized = normalize_records(records, day)

        if not normalized:
            print(f"⚠️ День {day}: не знайдено контенту для міграції.")
            continue

        for record in normalized:
            await add_or_update_material(
                role=record["role"],
                day=record["day"],
                content_type=record["content_type"],
                title=record["title"],
                content=record["content"],
                resource_url=record["resource_url"],
                order_index=record["order_index"],
            )
            total_records += 1

        print(f"✅ День {day}: мігровано {len(normalized)} матеріал(и/ів).")

    print(f"\nГотово! Усього записів: {total_records}.")


if __name__ == "__main__":
    asyncio.run(migrate())
