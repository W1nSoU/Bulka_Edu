import re

def patch_developer_py():
    with open("bot/menus/developer.py", "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Replace all "⬅️ До Dev-панелі" with "⬅️ До Панелі Адміністратора"
    content = content.replace("⬅️ До Dev-панелі", "⬅️ До Панелі Адміністратора")

    # 2. Text in developer_remove_dev_menu and developer_remove_dev
    content = content.replace("Немає розробників для видалення.", "Немає адміністраторів для видалення.")
    content = content.replace("🗑 Оберіть розробника для видалення:", "🗑 Оберіть адміністратора для видалення:")
    content = content.replace("⛔️ Ви не можете видалити головного розробника.", "⛔️ Ви не можете видалити головного адміністратора.")
    content = content.replace('f"Розробника {user_id_to_remove} видалено з команди."', 'f"Адміністратора {user_id_to_remove} видалено з команди."')

    # 3. In _build_managers_team_view (2 places: empty and normal)
    # Match _build_managers_team_view function and replace its back buttons to dev_main_team
    mgr_pattern = r'(async def _build_managers_team_view[\s\S]*?)(buttons\.append\(\[InlineKeyboardButton\(text="⬅️ Назад", callback_data="developer_menu"\)\]\))([\s\S]*?)(buttons\.append\(\[InlineKeyboardButton\(text="⬅️ Назад", callback_data="developer_menu"\)\]\))'
    def replace_mgr_back(m):
        return m.group(1) + 'buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="dev_main_team")])' + m.group(3) + 'buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="dev_main_team")])'
    content = re.sub(mgr_pattern, replace_mgr_back, content, count=1)

    # 4. In _users_menu_keyboard
    users_pattern = r'(def _users_menu_keyboard[\s\S]*?buttons\.append\(\[InlineKeyboardButton\(text="⬅️ Назад", callback_data=")(developer_menu)("\)\]\))'
    content = re.sub(users_pattern, r'\g<1>dev_main_team\g<3>', content, count=1)

    # 5. In _materials_menu_keyboard
    mat_kb_pattern = r'(def _materials_menu_keyboard[\s\S]*?callback_data=")(developer_menu)("\)\])'
    content = re.sub(mat_kb_pattern, r'\g<1>dev_main_study\g<3>', content, count=1)

    # 6. In developer_materials_menu cancel button
    mat_menu_pattern = r'(async def developer_materials_menu[\s\S]*?buttons\.append\(\[InlineKeyboardButton\(text="❌ Скасувати", callback_data=")(developer_menu)("\)\]\))'
    content = re.sub(mat_menu_pattern, r'\g<1>dev_main_study\g<3>', content, count=1)

    # 7. In developer_videos_menu cancel button
    vid_menu_pattern = r'(async def developer_videos_menu[\s\S]*?buttons\.append\(\[InlineKeyboardButton\(text="❌ Скасувати", callback_data=")(developer_menu)("\)\]\))'
    content = re.sub(vid_menu_pattern, r'\g<1>dev_main_study\g<3>', content, count=1)

    # 8. In developer_tests_menu back button
    test_menu_pattern = r'(async def developer_tests_menu[\s\S]*?buttons\.append\(\[InlineKeyboardButton\(text="⬅️ Назад", callback_data=")(developer_menu)("\)\]\))'
    content = re.sub(test_menu_pattern, r'\g<1>dev_main_study\g<3>', content, count=1)

    # 9. In developer_photos_menu cancel button
    photo_menu_pattern = r'(async def developer_photos_menu[\s\S]*?buttons\.append\(\[InlineKeyboardButton\(text="❌ Скасувати", callback_data=")(developer_menu)("\)\]\))'
    content = re.sub(photo_menu_pattern, r'\g<1>dev_main_study\g<3>', content, count=1)

    # 10. In developer_syllabus_menu cancel button
    syl_menu_pattern = r'(async def developer_syllabus_menu[\s\S]*?buttons\.append\(\[InlineKeyboardButton\(text="❌ Скасувати", callback_data=")(developer_menu)("\)\]\))'
    content = re.sub(syl_menu_pattern, r'\g<1>dev_main_study\g<3>', content, count=1)

    # 11. In developer_reminder_history back button
    rem_hist_pattern = r'(async def developer_reminder_history[\s\S]*?\[InlineKeyboardButton\(text="⬅️ Назад", callback_data=")(developer_menu)("\)\])'
    content = re.sub(rem_hist_pattern, r'\g<1>dev_main_analyt\g<3>', content, count=1)

    # 12. In developer_analytics_menu back button
    an_menu_pattern = r'(async def developer_analytics_menu[\s\S]*?\[InlineKeyboardButton\(text="⬅️ Назад", callback_data=")(developer_menu)("\)\])'
    content = re.sub(an_menu_pattern, r'\g<1>dev_main_analyt\g<3>', content, count=1)

    # 13. In developer_tokens_menu back button & developer_tokens_cleanup back button
    tok_menu_pattern = r'(async def developer_tokens_menu[\s\S]*?\[InlineKeyboardButton\(text="⬅️ Назад", callback_data=")(developer_menu)("\)\])'
    content = re.sub(tok_menu_pattern, r'\g<1>dev_main_other\g<3>', content, count=1)

    tok_clean_pattern = r'(async def developer_tokens_cleanup[\s\S]*?\[InlineKeyboardButton\(text="⬅️ Назад", callback_data=")(developer_menu)("\)\])'
    content = re.sub(tok_clean_pattern, r'\g<1>dev_main_other\g<3>', content, count=1)

    # 14. In developer_health_status back button
    health_pattern = r'(async def developer_health_status[\s\S]*?\[InlineKeyboardButton\(text="⬅️ Назад", callback_data=")(developer_menu)("\)\])'
    content = re.sub(health_pattern, r'\g<1>dev_main_other\g<3>', content, count=1)

    # 15. In developer_xlsx_menu back button
    xlsx_pattern = r'(async def developer_xlsx_menu[\s\S]*?\[InlineKeyboardButton\(text="⬅️ Назад", callback_data=")(developer_menu)("\)\])'
    content = re.sub(xlsx_pattern, r'\g<1>dev_main_analyt\g<3>', content, count=1)

    with open("bot/menus/developer.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("✅ bot/menus/developer.py patched successfully!")


def patch_handlers_py():
    with open("bot/handlers.py", "r", encoding="utf-8") as f:
        content = f.read()

    # 1. remind_topic_global_callback back button to dev_main_study
    content = content.replace(
        'back_button_cb = "developer_menu" if is_dev else "manager_menu"',
        'back_button_cb = "dev_main_study" if is_dev else "manager_menu"'
    )

    # 2. show_test_error_statistics back button to dev_main_analyt if is_dev
    content = content.replace(
        '''    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад до головного меню", callback_data="main_menu_photo")]
    ])''',
        '''    back_cb = "dev_main_analyt" if is_dev else "main_menu_photo"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=back_cb)]
    ])'''
    )

    with open("bot/handlers.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("✅ bot/handlers.py patched successfully!")


if __name__ == "__main__":
    patch_developer_py()
    patch_handlers_py()
