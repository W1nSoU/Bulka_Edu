# Implementation Plan: Instruction Original Document Support

**Дата:** 2026-11-18
**Специфікація:** [2026-11-18-instruction-original-file-design.md](../specs/2026-11-18-instruction-original-file-design.md)

## 1. Database Layer (`database/instructions.py`)
- Додати колонки `original_file_path`, `original_telegram_file_id`, `original_file_name` в таблицю `instructions` з авто-міграцією існуючих БД.
- Оновити `create_instruction` і `delete_instruction` (очищення обох файлів на диску).
- Додати `update_instruction_original_file` та `get_instructions_with_original_by_ids`.

## 2. Admin UI & FSM (`bot/menus/instructions.py`)
- Розширити `InstructionStates`: `waiting_new_original_file`, `waiting_edit_original_file`.
- Оновити створення інструкції до 3 кроків (Назва -> Інструкція .docx / пусто -> Оригінал документу / без оригіналу).
- Оновити `_render_instruction_card` для відправки обох файлів послідовно (з клавіатурою на другому/наявному файлі).
- Замінити пряму кнопку редагування файлу на `🔄 Замінити файл` з підменю `📄 Замінити інструкцію` та `📎 Замінити оригінал інструкції`.

## 3. AI Search Integration (`bot/services/openai_ai.py`, `bot/handlers.py`)
- Реалізувати `_extract_used_instruction_ids(results, answer_text)` і додати `used_instruction_ids` у відповідь `answer_remind_topic`.
- У `process_keyword_search` після текстової відповіді ШІ надсилати файли оригіналів використаних інструкцій.

## 4. Verification (`tests/test_instructions.py`)
- Тести міграції БД, 3-крокового створення, відображення 2 файлів у картці, підменю заміни, заміни оригіналу, екстракції `used_instruction_ids` та відправки оригіналу в `process_keyword_search`.
- Прогін усього пакету `./venv/bin/python -m unittest discover tests`.
