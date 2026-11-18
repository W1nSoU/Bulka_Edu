# Implementation Plan: Admin Instructions ("Інструкції") + AI Search Integration

**Дата:** 2026-11-18
**Специфікація:** [2026-11-18-admin-instructions-design.md](../specs/2026-11-18-admin-instructions-design.md)

## 1. Database Layer (`database/instructions.py` & `main.py`)
- Таблиця `instructions` + CRUD + пагінація (`get_instructions_paginated`).
- Збереження файлів у `database/instructions_files/`.
- Ініціалізація `init_instructions_db()` у `main.py`.

## 2. Word (.docx) Template Generator & Parser (`bot/services/instructions_docx.py`)
- `generate_instruction_template_docx(topic_title)` — створення корпоративного шаблону `.docx`.
- `extract_text_from_docx_bytes(file_bytes)` — парсинг параграфів і таблиць із `.docx`.

## 3. AI Search Integration
- `database/knowledge_chunks.py`: включення `instructions` у `get_materials_fingerprint` і `get_materials_rows`.
- `bot/services/knowledge_chunker.py`: префікс назви інструкції при чанкуванні `instruction`.
- `bot/services/semantic_search.py`: чисте форматування джерела `Інструкція: {Назва}` у `format_sources_label`.

## 4. Admin UI & FSM (`bot/menus/instructions.py` & `bot/menus/developer.py`)
- Кнопка `📋 Інструкції` в `_admin_study_keyboard` лише для адміністраторів.
- Повний цикл створення, пагінації, перегляду з файлом, зміни файлу (поточний + шаблон), зміни назви та видалення.

## 5. Verification (`tests/test_instructions.py`)
- Комплексні тести БД, `.docx`-парсингу/шаблону, доступу, FSM-потоків та гібридного пошуку ШІ.
- Прогін усього пакету `./venv/bin/python -m unittest discover tests`.
