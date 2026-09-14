# Materials Pagination Navigation & Single-Message Flow Design

## Overview
When an intern opens text material for a learning day (callback `daymat_{day}_text`), the current pagination keyboard lacks an exit/back button on initial and intermediate pages. Furthermore, transitioning between the photo-based format selection menu and plain-text reading material can lead to orphaned messages or duplicate context if not handled cleanly.

This design establishes a predictable, clean single-message navigation flow for day materials:
1. Every material page (from page 1 to the final page) includes an explicit back navigation button `[ ⬅️ Повернутися до вибору формату ]` returning to `day_{day}`.
2. When transitioning from text material back to the day formats menu, the bot seamlessly edits the message in place (`edit_text`).
3. Message cleanup during media-to-text and text-to-media transitions is hardened so that no duplicate or orphaned cards (such as the student main menu) linger in the intern's chat.

---

## 1. Keyboard Architecture (`bot/keyboards.py`)

### `get_pagination_keyboard`
Function signature:
```python
def get_pagination_keyboard(
    current_page: int,
    total_pages: int,
    content_identifier: str,
    day: int,
    final_button: Optional[InlineKeyboardButton] = None,
    back_button: Optional[InlineKeyboardButton] = None,
) -> InlineKeyboardMarkup:
```

### Layout Rules:
* **Row 1 (Pagination Controls):**
  * `[ ⬅️ Назад ]` (if `current_page > 0`, callback `paginate:{content_identifier}:{day}:{current_page - 1}`)
  * `[ 📄 {current_page + 1}/{total_pages} ]` (if `total_pages > 1`, callback `do_nothing`)
  * `[ Далі ➡️ ]` (if `current_page < total_pages - 1`, callback `paginate:{content_identifier}:{day}:{current_page + 1}`)
* **Row 2 (Completion Action — Last Page Only):**
  * Present only when `current_page == total_pages - 1` and `final_button` is supplied.
  * E.g. `[ ➡️ До тесту ]` (callback `day{day}_test`) or `[ ✅ Завершити день ]` (callback `complete_day_{day}`).
* **Row 3 (Persistent Navigation — All Pages):**
  * Always present on all pages:
  * Default: `[ ⬅️ Повернутися до вибору формату ]` (callback `day_{day}`).
  * Can be customized via `back_button` parameter if needed (e.g. for media files).

---

## 2. Handler & Flow Architecture (`bot/handlers.py`)

### A. Entering Text Material (`day_material_detail` & `_show_material_entry`)
1. User clicks `[ 📄 Текст ]` (`daymat_{day}_text`).
2. If the current message has a photo (`kerivn_books_study.jpg` format menu):
   - Safely delete the photo message (`await callback.message.delete()`).
   - Send the first page of text as a new text message (`await callback.message.answer(text_0, reply_markup=keyboard)`).
3. If the current message is already text:
   - Edit the message in place (`await callback.message.edit_text(text_0, reply_markup=keyboard)`).
4. Do not dispatch or trigger `show_student_main_menu`.

### B. Returning to Formats Menu (`day_content`, callback `day_{day}`)
1. User clicks `[ ⬅️ Повернутися до вибору формату ]` (`day_{day}`).
2. Since the message is already a text message:
   - `_show_text_menu` uses `edit_text` directly: updates text to `"🍞 День {day} • {role}\n\nОберіть формат матеріалу..."` and inline buttons `[ 📄 Текст ]`, `[ 📝 Тести ]`, `[ ⬅️ Повернутися до блоків навчання ]`.
   - No new message is created.

### C. Returning to Course Blocks (`menu_days`, callback `continue_learning`)
1. User clicks `[ ⬅️ Повернутися до блоків навчання ]` (`continue_learning`).
2. The current message is text, but `menu_days` renders `kerivn_books_study.jpg`:
   - `_show_photo_menu` safely deletes the text message and sends the photo menu with day block buttons.
   - Result: exactly 1 message in the chat.

---

## 3. Error Handling & Edge Cases
1. **Single-page materials (`total_pages == 1`):**
   - Row 1 pagination controls are omitted.
   - Row 2 (final button) is displayed.
   - Row 3 (`[ ⬅️ Повернутися до вибору формату ]`) is displayed.
2. **Deleting message fails (e.g. Telegram rate limit or older message):**
   - Wrap deletion in `try...except Exception: pass` so that the message sending never breaks.
3. **Double-clicks or rapid navigation:**
   - Callback queries are acknowledged immediately via `await callback.answer()`.

---

## 4. Verification Plan
1. **Unit Tests (`tests/test_materials_pagination.py`):**
   - Test `get_pagination_keyboard` on page 0/7: verifies presence of `[ 📄 1/7 ]`, `[ Далі ➡️ ]`, and `[ ⬅️ Повернутися до вибору формату ]`.
   - Test `get_pagination_keyboard` on page 3/7: verifies `[ ⬅️ Назад ]`, `[ 📄 4/7 ]`, `[ Далі ➡️ ]`, and back button.
   - Test `get_pagination_keyboard` on page 6/7: verifies `[ ⬅️ Назад ]`, `[ 📄 7/7 ]`, `[ ➡️ До тесту ]`, and back button.
   - Test `get_pagination_keyboard` on single page (1/1): verifies final button and back button.
2. **End-to-End Simulation Test (`scratch/test_daymat_flow.py`):**
   - Simulate entering `daymat_1_text` from photo message -> verifies 1 delete, 1 answer, proper keyboard.
   - Simulate clicking `day_1` back from text -> verifies `edit_text` called with day format options.
