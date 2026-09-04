# Design Spec: Manager Trainee Registration Menu & Manager Main Menu Keyboards

## 1. Context & Problem
Upon completing registration for a Manager Trainee (`Керівник Стажер`), the bot currently calls `show_student_main_menu`, which displays the standard intern welcome card (`img/b_start.jpg`), the "Твій булочковий прогрес" text, and the student keyboard (`Розпочати навчання`, `Профіль`, `Зв'язок з керівником`).
This is incorrect according to the requirements: a Manager Trainee is a managerial role and must immediately receive the official Manager menu, not the intern progress card.
Additionally, the buttons in the manager's main menu keyboard needed to be updated to replace "Адміністрування стажерів" with "Панель керівника" and place "Навчання" at the top.

## 2. Proposed Changes

### 2.1 bot/handlers.py
In the registration completion flow for role `Керівник` / `Керівник Стажер` (around line 2773):
- Replace `await show_student_main_menu(message, user_id, allow_edit=False)` with:
  ```python
  await show_manager_main_menu(message, allow_edit=False, force_new_message=True)
  ```
- This ensures the manager immediately sees the manager photo (`k_menu.jpg`), the manager greeting caption, and the manager keyboard.

### 2.2 bot/keyboards.py
In `main_menu_keyboard(is_manager=True)`:
- Update keyboard buttons to:
  1. `[📚 Навчання]` (callback_data="mgr_study_root")
  2. `[👑 Панель керівника]` (callback_data="manager_menu")
  3. `[👤 Профіль]` (callback_data="profile")
- Remove legacy "📋 Адміністрування стажерів" button.

### 2.3 Verification & Regression
- Verify unit tests for registration routing and manager menus.
- Ensure that clicking "🏠 Головне меню" from any sub-panel routes back to `show_manager_main_menu` with the updated buttons.
