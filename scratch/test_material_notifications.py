import asyncio
import json
from datetime import datetime, timedelta
import aiosqlite

from database.schema import init_db
from database.managers import init_managers_db, add_manager, delete_manager_by_uid
from database.users import register_user, set_intern_extra, delete_user
from database.material_notifications import (
    init_material_notifications_db,
    create_material_change_event,
    create_recipients_for_event,
    get_pending_wave_recipients,
    mark_recipient_sent,
    mark_recipient_acknowledged,
    get_recipient_by_user_and_event,
    get_event_by_id,
    get_events_for_category,
    get_event_analytics_for_category,
    get_event_shop_breakdown,
    get_event_shop_users,
    prune_old_material_events,
    NOTIFICATIONS_DB_PATH
)
from bot.services.wave_broadcaster import (
    build_material_notification_keyboard,
    format_material_notification_text
)


async def run_tests():
    print("🚀 Starting Material Change Notifications & Analytics (Пункт 8) tests...")
    await init_db()
    await init_managers_db()
    await init_material_notifications_db()

    test_role = "ТестКасирПункт8"
    test_shop_1 = "вул. Хрещатик, 1"
    test_shop_2 = "просп. Перемоги, 25"

    # Setup test users:
    # 45 users of test_role (40 in shop_1, 5 in shop_2)
    # 5 managers
    print("\n1. Setting up test users and managers...")
    test_user_ids = []
    for i in range(1, 46):
        uid = 888000 + i
        test_user_ids.append(uid)
        await delete_user(uid)
        await register_user(uid, username=f"cashier_{i}", full_name=f"Касир Тестовий {i}")
        shop = test_shop_1 if i <= 40 else test_shop_2
        status = "Працівник" if i % 2 == 0 else None
        await set_intern_extra(uid, 777000, test_role, "Хмельницький", shop=shop)
        if status == "Працівник":
            async with aiosqlite.connect(NOTIFICATIONS_DB_PATH.replace("material_notifications.db", "users.db")) as db:
                await db.execute("UPDATE users SET status = 'Працівник' WHERE user_id = ?", (uid,))
                await db.commit()

    test_mgr_ids = []
    for i in range(1, 6):
        m_uid = 889000 + i
        test_mgr_ids.append(m_uid)
        await delete_manager_by_uid(m_uid)
        await add_manager(
            uid=m_uid,
            process="Керівник",
            full_name=f"Керівник Тестовий {i}",
            username=f"mgr_{i}",
            shops=[test_shop_1],
            city="Хмельницький",
            responsible_uid=777000
        )

    print(f"✅ Created 45 {test_role} users + 5 managers (Total = 50 target recipients).")

    # 2. Test event creation & wave recipient batching
    print("\n2. Testing Event Creation & Recipient Wave Batching (40/wave)...")
    pages = [
        "Сторінка 1: Оновлені правила обслуговування гостей.",
        "Сторінка 2: Нові стандарти викладки випічки на вітрину.",
        "Сторінка 3: Інструкція з прийому оплати за новими терміналами."
    ]
    event_id = await create_material_change_event(
        role=test_role,
        day=2,
        content_type="text",
        description="Оновлення стандартів обслуговування",
        pages=pages
    )
    assert event_id > 0, "Event ID should be > 0"

    total_recipients = await create_recipients_for_event(event_id, test_role)
    assert total_recipients == 50, f"Expected 50 recipients, got {total_recipients}"

    # Verify wave 1 has 40 recipients, wave 2 has 10 recipients
    wave_1_rec = await get_pending_wave_recipients(wave_number=1, event_id=event_id)
    wave_2_rec = await get_pending_wave_recipients(wave_number=2, event_id=event_id)
    assert len(wave_1_rec) == 40, f"Expected 40 in wave 1, got {len(wave_1_rec)}"
    assert len(wave_2_rec) == 10, f"Expected 10 in wave 2, got {len(wave_2_rec)}"
    print("✅ Waves correctly split: Wave 1 = 40 users, Wave 2 = 10 users.")

    # 3. Test Message Formatting & Pagination Keyboard
    print("\n3. Testing Notification Message Formatting & Keyboard...")
    text_p0 = format_material_notification_text(test_role, 2, pages[0], 0, 3)
    assert "📢" in text_p0 and "Сторінка 1" in text_p0

    # Page 0 keyboard: Navigation buttons, no ack button
    kb_p0 = build_material_notification_keyboard(event_id, wave_1_rec[0]['id'], 0, 3, is_acknowledged=False)
    nav_row_p0 = [row for row in kb_p0.inline_keyboard if any(btn.callback_data == "ignore" for btn in row)][0]
    assert nav_row_p0[0].text == "📄 1/3"
    assert nav_row_p0[1].callback_data == f"mat_ch_pag:{event_id}:{wave_1_rec[0]['id']}:1"
    
    # Page 2 (last page) keyboard: Navigation + Ack button
    kb_p2 = build_material_notification_keyboard(event_id, wave_1_rec[0]['id'], 2, 3, is_acknowledged=False)
    ack_btn_row = [row for row in kb_p2.inline_keyboard if any("mat_ch_ack:" in btn.callback_data for btn in row)]
    assert len(ack_btn_row) == 1, "Last page must contain acknowledgment button"
    assert ack_btn_row[0][0].text == "🔘 Зі змінами ознайомлений/а"
    
    # Acknowledged state keyboard: shows green text
    kb_p2_ack = build_material_notification_keyboard(event_id, wave_1_rec[0]['id'], 2, 3, is_acknowledged=True)
    assert any("✅ Ви ознайомлені зі змінами" in btn.text for row in kb_p2_ack.inline_keyboard for btn in row)
    print("✅ Notification pagination and acknowledgment button verified!")

    # 4. Test Acknowledgment Flow (On-time vs Late >72h)
    print("\n4. Testing Acknowledgment Flow & 72h Late Detection...")
    user_ontime = 888001
    user_late = 888002
    user_unack = 888003

    # Mark user_ontime as sent now
    rec_ontime = await get_recipient_by_user_and_event(event_id, user_ontime)
    await mark_recipient_sent(rec_ontime['id'], message_id=1001)
    
    # Acknowledge user_ontime within 72h
    ok_1, is_late_1 = await mark_recipient_acknowledged(event_id, user_ontime)
    assert ok_1 and not is_late_1, f"Expected on-time ack, got is_late={is_late_1}"

    # Mark user_late as sent 75 hours ago
    rec_late = await get_recipient_by_user_and_event(event_id, user_late)
    old_sent_time = (datetime.utcnow() - timedelta(hours=75)).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(NOTIFICATIONS_DB_PATH) as db:
        await db.execute(
            "UPDATE material_change_recipients SET status = 'sent', sent_at = ? WHERE id = ?",
            (old_sent_time, rec_late['id'])
        )
        await db.commit()

    # Acknowledge user_late after 72h
    ok_2, is_late_2 = await mark_recipient_acknowledged(event_id, user_late)
    assert ok_2 and is_late_2, f"Expected late ack (is_late=True), got {is_late_2}"

    # Also acknowledge 1 manager on-time
    mgr_uid = test_mgr_ids[0]
    rec_mgr = await get_recipient_by_user_and_event(event_id, mgr_uid)
    await mark_recipient_sent(rec_mgr['id'], message_id=2001)
    await mark_recipient_acknowledged(event_id, mgr_uid)

    print("✅ Acknowledgment logic verified: On-time (is_late=0) and Late (is_late=1).")

    # 5. Test Analytics Calculation & 75h Threshold Logic
    print("\n5. Testing Analytics Calculation & 75h Threshold...")
    
    # Check stats for 'працівник'
    stats_worker = await get_event_analytics_for_category(event_id, "працівник")
    assert stats_worker['total'] > 0
    assert stats_worker['acknowledged_count'] >= 1
    
    # Check stats for 'керівник'
    stats_mgr = await get_event_analytics_for_category(event_id, "керівник")
    assert stats_mgr['total'] == 5
    assert stats_mgr['acknowledged_count'] == 1
    assert stats_mgr['unacknowledged_count'] == 4

    # Test time passed < 75h
    ev = await get_event_by_id(event_id)
    ev_dt = datetime.fromisoformat(ev['created_at'].replace("Z", "+00:00")) if "T" in ev['created_at'] else datetime.strptime(ev['created_at'], "%Y-%m-%d %H:%M:%S")
    time_passed = datetime.utcnow() - ev_dt
    assert time_passed.total_seconds() < 75 * 3600, "Fresh event should have passed < 75 hours"
    print("✅ Fresh event correctly detected as < 75h (countdown active).")

    # 6. Test Shop Breakdown and User Details
    print("\n6. Testing Shop Breakdown & User Drilldown...")
    shops_ack = await get_event_shop_breakdown(event_id, "стажер", acknowledged=True)
    shops_noack = await get_event_shop_breakdown(event_id, "стажер", acknowledged=False)
    assert len(shops_ack) > 0 or len(shops_noack) > 0

    # Test user drilldown in shop_1
    users_in_shop = await get_event_shop_users(event_id, "стажер", acknowledged=True, shop=test_shop_1)
    for u in users_in_shop:
        assert "full_name" in u and len(u["full_name"]) > 0
    print("✅ Shop grouping and user detail list verified!")

    # 7. Test 90-day Retention Pruning
    print("\n7. Testing 90-day Pruning...")
    old_date = (datetime.utcnow() - timedelta(days=95)).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(NOTIFICATIONS_DB_PATH) as db:
        await db.execute(
            '''
            INSERT INTO material_change_events (role, day, content_type, description, pages_json, created_at, status)
            VALUES ('СтараПосада', 1, 'text', 'Стара зміна', '[]', ?, 'completed')
            ''',
            (old_date,)
        )
        await db.commit()

    deleted = await prune_old_material_events(days=90)
    assert deleted >= 1, f"Expected at least 1 deleted old event, got {deleted}"
    print(f"✅ Successfully pruned {deleted} old event(s) (>90 days).")

    # Clean up test users
    print("\n8. Cleaning up test data...")
    for uid in test_user_ids:
        await delete_user(uid)
    for m_uid in test_mgr_ids:
        await delete_manager_by_uid(m_uid)
    print("✅ Cleaned up test data.")

    print("\n🎉 ALL POINT 8 MATERIAL CHANGE NOTIFICATION & ANALYTICS TESTS PASSED 100%!")


if __name__ == "__main__":
    asyncio.run(run_tests())
