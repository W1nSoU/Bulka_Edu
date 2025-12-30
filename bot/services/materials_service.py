from typing import Dict, List, Tuple

from bot.constants import CONTENT_TYPES
from database.materials import get_materials_for_day

CONTENT_TYPE_METADATA = {
    "comic": {"label": "Комікс", "icon": "📚"},
    "info": {"label": "Інформація", "icon": "📝"},
    "text": {"label": "Текст", "icon": "📄"},
    "video_files": {"label": "Відео (завантажено)", "icon": "📹"}, # New content type
    "photo_files": {"label": "Фото", "icon": "🖼"},
}

CONTENT_TYPE_ORDER = ["video_files", "photo_files", "text", "comic", "info"] # Prioritize uploaded videos, then text


def _normalize_type(content_type: str) -> str:
    if content_type in CONTENT_TYPE_METADATA:
        return content_type
    return "text"


def _group_by_type(materials: List[dict]) -> Dict[str, List[dict]]:
    grouped: Dict[str, List[dict]] = {}
    for material in materials:
        ctype = _normalize_type(material.get("content_type", "text"))
        grouped.setdefault(ctype, []).append(material)
    return grouped


async def load_grouped_materials(role: str, day: int) -> Dict[str, List[dict]]:
    """
    Повертає матеріали, згруповані за типом, для конкретної ролі та дня.
    Якщо роль не передана, використовуються універсальні матеріали (ALL).
    """
    normalized_role = role or "ALL"
    materials = await get_materials_for_day(normalized_role, day)
    return _group_by_type(materials)


def describe_available_types(grouped: Dict[str, List[dict]]) -> List[str]:
    """Готує короткий опис доступних типів матеріалів для повідомлення."""
    lines: List[str] = []
    for ctype in CONTENT_TYPE_ORDER:
        items = grouped.get(ctype)
        if not items:
            continue
        meta = CONTENT_TYPE_METADATA.get(ctype, {"label": ctype.title(), "icon": "📄"})
        lines.append(f"{meta['icon']} <b>{meta['label']}</b> · {len(items)}")
    return lines


def type_button_payload(day: int, ctype: str) -> Tuple[str, str]:
    meta = CONTENT_TYPE_METADATA.get(ctype, {"label": ctype.title(), "icon": "📄"})
    text = f"{meta['icon']} {meta['label']}"
    callback_data = f"daymat_{day}_{ctype}"
    return text, callback_data


def render_materials_details(day: int, ctype: str, materials: List[dict]) -> str:
    meta = CONTENT_TYPE_METADATA.get(ctype, {"label": ctype.title(), "icon": "📄"})
    lines = [
        f"{meta['icon']} <b>{meta['label']}</b> · День {day}",
        "",
    ]
    for idx, material in enumerate(materials, 1):
        title = material.get("title") or f"{meta['label']} #{idx}"
        content = material.get("content") or ""
        resource_url = material.get("resource_url")
        lines.append(f"<b>{idx}. {title}</b>")
        if content.strip():
            lines.append(content.strip())
        if resource_url:
            lines.append(f"🔗 {resource_url}")
        lines.append("")  # розділяємо матеріали порожнім рядком
    return "\n".join(line for line in lines if line is not None)


__all__ = [
    "load_grouped_materials",
    "describe_available_types",
    "type_button_payload",
    "render_materials_details",
    "CONTENT_TYPE_METADATA",
    "CONTENT_TYPE_ORDER",
]
