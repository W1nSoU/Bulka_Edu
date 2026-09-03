# Design: Users Menu Restructuring, Advanced Filters & Profile Card

## Overview

Restructure the Telegram bot's `👥 Користувачі` menu in the Developer/Administrator panel into a clean, hierarchical navigation system. Introduce dedicated submenus for "👥 Персонал" and "🔍 Фільтри", add store-level and manager-level subordinate filtering, implement an enhanced visual user profile card with avatar/photo and direction tag (`ВВ`/`ТЗ`), integrate immediate user card display into search, and relocate bulk user promotion to a new "Сервісні функції" section within "🛠 Інше".

---

## 1. Requirements

### 1.1 Main Users Menu (`dev_users_menu`)
Replace the cluttered 9-button list with a clean 4-button menu:
- `👥 Персонал` (`dev_users_staff`)
- `🔍 Фільтри` (`dev_users_filters`)
- `🔎 Пошук` (`dev_users_search`)
- `⬅️ Назад` (`dev_main_team`)

### 1.2 Submenu «👥 Персонал» (`dev_users_staff`)
Groups personnel by core status and creation:
- `🎓 Стажери` (`dev_users_interns`)
- `👷 Працівники` (`dev_users_workers`)
- `📋 Всі користувачі` (`dev_users_list`)
- `➕ Додати` (`dev_users_add`) (visible to Admin and Territorial)
- `⬅️ Назад` (`dev_users_menu`)
*(Note: Remove standalone "❌ Видалити" button from here since delete is available directly inside each user card).*

### 1.3 Submenu «🔍 Фільтри» (`dev_users_filters`)
Groups all filtering criteria:
- `🏙 За містом` (`dev_users_by_city`)
- `🏪 За магазинами` (`dev_users_by_shop`) [NEW]
- `👔 За керівниками` (`dev_users_by_manager`) [NEW]
- `🚀 Активні стажери` (`dev_users_active`)
- `😴 Неактивні` (`dev_users_inactive`)
- `⬅️ Назад` (`dev_users_menu`)

### 1.4 New Filter: «🏪 За магазинами» (`dev_users_by_shop`)
- **Step 1**: City selection for Admins (auto-detected for Territorials).
- **Step 2**: List of shops in that city showing user counts: `[ 🏪 {shop} ({count}) ]`.
- **Step 3**: List of interns & employees assigned to the selected shop: `[ 👤 {name} | {role} ]`.
- Clicking on a user opens their User Profile Card.

### 1.5 New Filter: «👔 За керівниками» (`dev_users_by_manager`)
- **Step 1**: List of active managers (and territorials) with count of subordinates: `[ 👔 {name} ({count}) ]`.
- **Step 2**: List of all interns & workers assigned to this manager (`manager_id == manager_uid`).
- Clicking on a user opens their User Profile Card.

### 1.6 User Profile Card (`_build_user_card_view`)
Presented with photo/avatar (`get_user_avatar_input` + `_send_or_edit_card_photo`):
- Header photo with user avatar or fallback to `img/ava.png`.
- Caption text:
  ```
  👤 {full_name} (@{username})   <-- username only if available
  🏢 Посада: {role} | {direction} <-- direction: ВВ or ТЗ from positions table
  🏙 Місто: {city}
  🏪 Магазин: {shop}
  👨‍🏫 Керівник: {manager_title}   <-- via get_manager_display_title
  📊 Прогрес: {completed_days}/{total_days} ({percent}%)
  ⏱️ Остання активність (в боті): {activity_ago}

  📅 Статус днів
  🔓 День 1
  🔒 День 2
  ...
  ```
- Action Buttons:
  - `[ 📅 Навчальні дні ] [ ✍️ Змінити ]`
  - `[ ❌ Видалити ] [ ⬅️ Назад ]`

### 1.7 Search Enhancement (`dev_users_search`)
- When searching by full name, partial name, or numeric Telegram ID:
  - If exactly 1 match: immediately displays the User Profile Card.
  - If multiple matches: displays inline buttons of matching users.
  - If 0 matches: allows searching again or returning back.

### 1.8 Service Functions in «🛠 Інше» (`dev_main_other`)
- In `_admin_other_keyboard`, add button `[ ⚙️ Сервісні функції ]` (`dev_service_functions_menu`).
- In `dev_service_functions_menu`, include:
  - `[ ✅ Перевести завершених у працівники ]` (`dev_users_bulk_promote`)
  - `[ ⬅️ Назад ]` (`dev_main_other`)

---

## 2. Architecture & Components

1. **`bot/menus/developer.py`**:
   - Update `_users_menu_keyboard`: renders the new 4-button menu.
   - Implement `developer_users_staff_menu`: renders `_users_staff_keyboard`.
   - Implement `developer_users_filters_menu`: renders `_users_filters_keyboard`.
   - Implement `developer_users_by_shop_menu`: handles city selection and store buttons.
   - Implement `developer_users_by_manager_menu`: lists managers and their subordinates.
   - Implement `developer_service_functions_menu`: renders service functions inside "Інше".
   - Refactor `get_user_days_report` / `_show_user_profile_card`: uses avatar photo, adds `| {direction}` to role, and includes `🔓`/`🔒` status.
   - Update `process_user_search`: opens profile card directly if single result found.
2. **Database & Helper Queries**:
   - `get_position_direction(role_name: str) -> Optional[str]`: queries `positions` table for `territorial_type` (`ВВ` / `ТЗ`).
   - `get_users_by_shop(city: str, shop: str) -> List[dict]`.
   - `get_users_by_manager(manager_id: int) -> List[dict]`.

---

## 3. Verification Plan

1. **Unit & Integration Tests (`scratch/test_users_menu_restructure.py`)**:
   - Test `_users_menu_keyboard` layout (Персонал, Фільтри, Пошук, Назад).
   - Test `_users_staff_keyboard` (Стажери, Працівники, Всі, Додати, Назад).
   - Test `_users_filters_keyboard` (За містом, За магазинами, За керівниками, Активні, Неактивні, Назад).
   - Test `_admin_other_keyboard` has `Сервісні функції`, and service menu has `Перевести завершених у працівники`.
   - Test store filter and manager filter data extraction.
   - Test user profile card caption includes `| ТЗ` or `| ВВ`, manager full name, and avatar photo.
   - Test search with single result immediately renders card.
2. **Regression Testing**:
   - Run all existing test suites in `scratch/`.
