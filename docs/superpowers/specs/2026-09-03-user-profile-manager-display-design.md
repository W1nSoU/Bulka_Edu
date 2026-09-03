# Design: User Profile Manager Display by Full Name and Role

## Overview

In the user profile (viewed by interns and employees when clicking "👤 Профіль"), the line indicating who the manager is must display the actual Full Name (ПІБ) of the manager, rather than their generic job title/role. If the user is managed by a Territorial manager (for example, when a store currently lacks a regular manager), the role must be explicitly suffixed as `(Територіал)`. If the user is managed directly by an Administrator (fallback when neither regular manager nor territorial exists), the role must be suffixed as `(Адміністратор)`. For regular managers, only the full name is shown without any role suffix.

---

## 1. Requirements

1. **User Profile Scope**:
   - Applies specifically to the user's personal profile card (`profile_handler_new_message` in `bot/handlers.py`).
2. **Display Format**:
   - **Regular Manager** (`process` in `'Керівник'`, `'Керівник Стажер'`):
     `{full_name}` (e.g. `Тарас Керівниченко`).
   - **Territorial Manager** (`process == 'Територіал'` or `is_territorial_user`):
     `{full_name} (Територіал)` (e.g. `Олена Петрівна (Територіал)`).
   - **Administrator** (`is_admin_user` / `is_developer`):
     `{full_name} (Адміністратор)` (e.g. `Головний Адміністратор (Адміністратор)`).
   - **Unassigned** (`manager_id is None` or 0):
     `Не призначено`.
3. **Data Resolution & Fallbacks**:
   - Primary source for `full_name`: `managers` table by `uid == manager_id`.
   - Secondary source for `full_name`: `users` table by `user_id == manager_id`.
   - If `full_name` is missing or empty in DB: query Telegram API via `bot.get_chat(manager_id)`, extract `chat.full_name`, and persist it back to the database.
   - If Telegram API lookup fails (e.g., bot blocked or chat not found): fallback to `@username`, or `ID: {manager_id}` as the last resort.
   - HTML escaping: All returned values must be safe for HTML parse mode.

---

## 2. Architecture & Components

### 2.1 Helper Function: `get_manager_display_title`
Located in `bot/utils.py`:

```python
async def get_manager_display_title(bot, manager_id: Optional[int]) -> str:
    """
    Resolves and formats the manager's full name and optional role suffix:
    - Regular manager: "ПІБ"
    - Territorial: "ПІБ (Територіал)"
    - Administrator: "ПІБ (Адміністратор)"
    - Unassigned: "Не призначено"
    """
```

### 2.2 Integration in `bot/handlers.py`
In `profile_handler_new_message`:
```python
manager_id = user_details.get('manager_id')
manager_name_display = await get_manager_display_title(callback.bot, manager_id)
```
In template text:
```python
f"🔹 Керівник: <b>{html.escape(manager_name_display)}</b>\n\n"
```

---

## 3. Edge Cases & Error Handling

- **`manager_id` is None / 0**: Return `"Не призначено"`.
- **Manager marked as `fired` or inactive**: Still display their name appropriately or fallback.
- **Telegram API Error (`TelegramBadRequest`, `TelegramForbiddenError`)**: Caught cleanly with warning logs without raising uncaught exceptions.
- **Special Characters in Name**: Escaped via `html.escape` to ensure message formatting never breaks.

---

## 4. Verification Plan

1. **Unit and Integration Tests (`scratch/test_user_profile_manager_display.py`)**:
   - Test regular manager: returns `ПІБ` without suffix.
   - Test territorial manager: returns `ПІБ (Територіал)`.
   - Test administrator: returns `ПІБ (Адміністратор)`.
   - Test unassigned: returns `Не призначено`.
   - Test missing `full_name` with mocked `bot.get_chat` resolution.
2. **Regression Testing**:
   - Run existing test suites (`scratch/test_manager_territorial_invite_links.py`, `scratch/test_inline_cards_avatar.py`, etc.) to guarantee 100% compatibility.
