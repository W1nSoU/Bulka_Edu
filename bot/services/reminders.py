"""Unified reminder service for managers, HR and automated pings."""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta
from typing import Optional

import pytz
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import TIMEZONE
from database.users import (
    get_user_details,
    get_inactive_interns_for_auto_reminder,
    get_inactive_interns_for_auto_delete,
    touch_auto_reminder,
    get_user_progress,
    is_day3_question_sent,
    mark_day3_question_sent,
    log_reminder,
    log_training_event,
    delete_user,
)
from database.managers import get_manager_by_uid

REMINDER_COOLDOWN_HOURS = 24
INACTIVE_DAYS_THRESHOLD = 3

# Шаблони питань для 3-го дня
DAY_3_QUESTIONS = [
    "Привіт! 🍞 Як проходить твоє стажування? Все зрозуміло?",
    "Вітаю! 🥐 Вже 3-й день навчання! Є якісь питання по матеріалам?",
    "Привіт! 🧁 Як тобі поки що Булка? Маєш труднощі з чимось?",
    "Хей! 🍩 Як справи з навчанням? Керівник завжди готовий допомогти!",
    "Добридень! 🥨 Як враження від перших днів? Є що обговорити?",
]


def _build_keyboard(include_home: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="⬅️ Повернутися до навчання", callback_data="continue_learning")]]
    if include_home:
        rows.append([InlineKeyboardButton(text="🏠 Головне меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _resolve_manager_name(sender_id: Optional[int], intern: dict) -> Optional[str]:
    manager_id = sender_id or intern.get("manager_id")
    if not manager_id:
        return None
    manager = await get_manager_by_uid(manager_id)
    if manager:
        return manager.get("full_name") or manager.get("username")
    return None


async def send_intern_reminder(
    bot: Bot,
    intern_id: int,
    *,
    source: str,
    sender_id: Optional[int] = None,
) -> bool:
    """Send reminder to an intern from manager/HR/auto source."""
    intern = await get_user_details(intern_id)
    if not intern:
        return False

    full_name = intern.get("full_name") or "Булка-котик"
    role = intern.get("role") or "посада не вказана"
    city = intern.get("city") or "місто не вказано"
    manager_name = await _resolve_manager_name(sender_id if source == "manager" else None, intern)

    header_map = {
        "manager": "🔔 <b>Нагадування від вашого керівника</b>",
        "hr": "🔔 <b>Нагадування від HR Bulka</b>",
        "auto": "🤖 <b>Булка нагадує про навчання</b>",
    }
    header = header_map.get(source, header_map["auto"])

    lines = [
        header,
        "",
        f"👤 <b>{full_name}</b> · {role} ({city})",
    ]

    if source == "manager":
        if manager_name:
            lines.append(f"👨‍🏫 Ваш керівник: <b>{manager_name}</b>")
        lines.extend(
            [
                "Керівник турбується, щоб ви не втратили темп навчання. "
                "Поверніться до ботика і продовжіть свій шлях булочки!",
            ]
        )
    elif source == "hr":
        lines.append(
            "Команда HR нагадує: на вас чекають нові блоки та матеріали. "
            "Не соромтеся звертатися до керівника, якщо потрібна допомога."
        )
        if manager_name:
            lines.append(f"Ваш керівник: <b>{manager_name}</b>")
    else:  # auto
        lines.append(
            "Система навчання Булка помітила, що давно не було активності. "
            "Загляньте до ботика і продовжуйте навчання, щоб не втрачати прогрес."
        )
        if manager_name:
            lines.append(f"Ваш керівник: <b>{manager_name}</b> чекає на нові результати 💪")

    lines.append("\nБулочка завжди поруч, щоб підтримати 🥐")

    markup = _build_keyboard(include_home=source in {"manager", "hr"})

    try:
        await bot.send_message(intern_id, "\n".join(lines), reply_markup=markup, parse_mode="HTML")
        await log_reminder(intern_id, source, sender_id)
        return True
    except Exception as exc:
        # "chat not found" — стажер не почав діалог з ботом, це нормально
        error_str = str(exc).lower()
        if "chat not found" in error_str or "blocked" in error_str or "deactivated" in error_str:
            from bot.services.logger import get_logger
            get_logger().debug(f"Reminder skipped for {intern_id}: user hasn't started bot")
        else:
            from bot.services.logger import get_logger
            get_logger().warning(f"Failed to notify intern {intern_id}: {exc}")
        return False


async def get_interns_for_auto_reminder(
    now: datetime,
    *,
    inactive_days: Optional[int] = None,
    cooldown_hours: Optional[int] = None,
) -> list[dict]:
    """Return interns eligible for automatic reminders."""
    return await get_inactive_interns_for_auto_reminder(
        now,
        inactive_days or INACTIVE_DAYS_THRESHOLD,
        cooldown_hours or REMINDER_COOLDOWN_HOURS,
    )


async def send_day3_question(bot: Bot, intern_id: int) -> bool:
    """
    Надсилає питання "Як проходить стажування?" на 3-й день.
    Повідомлення виглядає як від керівника.
    """
    intern = await get_user_details(intern_id)
    if not intern:
        return False
    
    manager_id = intern.get("manager_id")
    manager_name = None
    if manager_id:
        manager = await get_manager_by_uid(manager_id)
        if manager:
            manager_name = manager.get("full_name") or manager.get("username")
    
    question = random.choice(DAY_3_QUESTIONS)
    
    lines = [question]
    if manager_name:
        lines.append(f"\n👨‍🏫 <b>{manager_name}</b>, твій керівник")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✉️ Написати керівнику", callback_data="support")],
        [InlineKeyboardButton(text="⬅️ Продовжити навчання", callback_data="continue_learning")],
    ])
    
    try:
        await bot.send_message(intern_id, "\n".join(lines), reply_markup=kb, parse_mode="HTML")
        return True
    except Exception:
        return False


async def notify_manager_test_failed(bot: Bot, intern_id: int, day: int) -> bool:
    """
    Повідомляє керівника про провал тесту стажером.
    (Застаріла, замінено на щоденний звіт)
    """
    return False # Заглушка, оскільки ця функція тепер не використовується напряму

async def send_daily_test_failure_report_to_manager(bot: Bot, manager_id: int, intern_failures: list[tuple[int, int]]) -> bool:
    """
    Надсилає щоденний консолідований звіт керівнику про стажерів, які не пройшли тест за відкритий день.
    `intern_failures` - список кортежів (intern_id, day_num).
    """
    if not intern_failures:
        return False

    manager_details = await get_manager_by_uid(manager_id)
    manager_name = "Керівник"
    if manager_details:
        manager_name = manager_details.get("full_name") or manager_details.get("username", "Керівник")

    text_lines = [
        f"🔔 <b>Щоденний звіт про тести ({datetime.now(pytz.timezone(TIMEZONE)).strftime('%Y-%m-%d')})</b>",
        f"Шановний(а) <b>{manager_name}</b>,\n",
        "Наступні стажери мають незавершені тести за відкриті навчальні дні:",
    ]

    buttons = []
    for intern_id, day_num in intern_failures:
        intern_details = await get_user_details(intern_id)
        intern_name = intern_details.get("full_name") or intern_details.get("username", f"ID {intern_id}")
        
        text_lines.append(f"\n  • <b>{intern_name}</b> (День {day_num})")

        buttons.append([InlineKeyboardButton(
            text=f"📅 Прогрес {intern_name} (День {day_num})",
            callback_data=f"manager_intern_profile_{intern_id}" # Reuse existing intern profile view
        )])
    
    text_lines.append("\nБудь ласка, перегляньте їхній прогрес та надайте необхідну підтримку.")
    text_lines.append("\n<i>(Сповіщення надсилаються один раз на день о 10:00 за незавершені тести)</i>")

    buttons.append([InlineKeyboardButton(text="👌 Зрозуміло", callback_data="mgr_dismiss_report")])

    try:
        await bot.send_message(manager_id, "\n".join(text_lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
        return True
    except Exception as exc:
        from bot.services.logger import get_logger
        get_logger().error(f"Failed to send daily test failure report to manager {manager_id}: {exc}", exc_info=True)
        return False

async def get_interns_for_day3_question(now: datetime) -> list[dict]:
    """
    Повертає стажерів, які на 3-му дні і ще не отримували питання.
    """
    from database.users import get_all_users
    from bot.services.access import is_privileged_user
    
    result = []
    users = await get_all_users()
    
    for user in users:
        user_id = user.get("user_id")
        
        # Пропускаємо якщо немає керівника
        if not user.get("manager_id"):
            continue
        
        # Пропускаємо privileged users
        if await is_privileged_user(user_id):
            continue
        
        # Перевіряємо чи вже надсилали
        if await is_day3_question_sent(user_id):
            continue
        
        # Перевіряємо прогрес
        progress = await get_user_progress(user_id)
        completed_days = sum(1 for p in progress if p.get("completed"))
        
        # Стажер на 3-му дні (завершив 2 дні)
        if completed_days == 2:
            result.append(user)
    
    return result


async def auto_reminder_loop(bot: Bot) -> None:
    """
    Фонова задача для автоматичних нагадувань.
    Виконується планувальником.
    """
    from bot.services.health import health_check
    from bot.services.logger import get_logger
    from bot.services.access import is_privileged_user
    logger = get_logger()
    
    tz = pytz.timezone(TIMEZONE)
    try:
        health_check.heartbeat_reminder()
        
        now = datetime.now(tz)

        # 0. Автоматичне видалення стажерів з неактивністю >= 3 днів
        to_delete = await get_inactive_interns_for_auto_delete(days=INACTIVE_DAYS_THRESHOLD)
        deleted_count = 0
        for intern in to_delete:
            intern_id = intern["user_id"]
            await log_training_event(
                user_id=intern_id,
                event_type="left_deleted",
                actor_id=None,
                full_name=intern.get("full_name"),
                username=intern.get("username"),
                city=intern.get("city"),
                shop=intern.get("shop"),
                role=intern.get("role"),
                manager_id=intern.get("manager_id"),
            )
            await delete_user(intern_id)
            deleted_count += 1
        if deleted_count:
            logger.info(f"Auto-deleted inactive interns: {deleted_count}")
        
        # 1. Автоматичні нагадування неактивним (тільки стажерам)
        interns = await get_interns_for_auto_reminder(now)
        for intern in interns:
            intern_id = intern["user_id"]
            
            # Пропускаємо privileged users
            if await is_privileged_user(intern_id):
                continue
            
            ok = await send_intern_reminder(bot, intern_id, source="auto", sender_id=None)
            if ok:
                await touch_auto_reminder(intern_id, now)
                logger.debug(f"Auto reminder sent to {intern_id}")
        
        # 2. Питання на 3-й день (один раз на стажера)
        day3_interns = await get_interns_for_day3_question(now)
        for intern in day3_interns:
            intern_id = intern["user_id"]
            ok = await send_day3_question(bot, intern_id)
            if ok:
                await mark_day3_question_sent(intern_id)
                logger.info(f"Day 3 question sent to {intern_id}")
                
    except Exception as exc:
        logger.error(f"auto_reminder_loop error: {exc}", exc_info=True)
        health_check.record_error()


async def send_manager_lagging_report(bot: Bot, manager_id: int, interns: list) -> bool:
    """Sends a daily report to manager about lagging interns. Retries on network errors."""
    if not interns:
        return False
        
    text = "📉 <b>Звіт по навчанню за сьогодні</b>\n\nНаступні стажери ще не пройшли свій блок навчання:\n"
    for i in interns:
        name = i.get('full_name', 'Без імені')
        block = i.get('current_block', 1)
        text += f"• {name} (День {block})\n"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔔 Нагадати всім", callback_data="mgr_remind_all_lagging")],
        [InlineKeyboardButton(text="👌 Зрозуміло", callback_data="mgr_dismiss_report")]
    ])
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            await bot.send_message(manager_id, text, reply_markup=kb, parse_mode="HTML")
            return True
        except Exception as e:
            error_str = str(e).lower()
            # Якщо це мережевий збій Windows — пробуємо ще раз
            if attempt < max_retries - 1 and any(msg in error_str for msg in ["winerror 64", "winerror 121", "semaphore", "network name"]):
                from bot.services.logger import get_logger
                get_logger().debug(f"Attempt {attempt+1} failed for manager {manager_id} (network error). Retrying in 2s...")
                await asyncio.sleep(2)
                continue
                
            from bot.services.logger import get_logger
            get_logger().error(f"Failed to send lagging report to manager {manager_id}: {e}", exc_info=True)
            return False
    return False


async def manager_daily_report_loop(bot: Bot) -> None:
    """
    Щоденний звіт керівникам про відстаючих стажерів.
    Виконується планувальником о 18:00.
    """
    from bot.services.logger import get_logger
    from database.managers import get_all_managers
    from database.users import get_interns_in_progress_for_manager, get_user_progress
    
    logger = get_logger()
    logger.info("🔵 Generating manager daily reports...")
    
    try:
        managers = await get_all_managers()
        
        for mgr in managers:
            mgr_id = mgr['uid']
            # Get active interns (already filters out graduates)
            interns = await get_interns_in_progress_for_manager(mgr_id)
            lagging = []
            
            for intern in interns:
                uid = intern['user_id']
                current_block = intern.get('current_block', 1)
                
                # Check if completed today's block
                progress_rows = await get_user_progress(uid)
                is_completed = False
                for row in progress_rows:
                    if row['day'] == current_block and row['completed']:
                        is_completed = True
                        break
                
                if not is_completed:
                    lagging.append(intern)
            
            if lagging:
                await send_manager_lagging_report(bot, mgr_id, lagging)
                logger.debug(f"Sent report to manager {mgr_id} with {len(lagging)} interns")
        
    except Exception as exc:
        logger.error(f"manager_daily_report_loop error: {exc}", exc_info=True)


__all__ = [
    "INACTIVE_DAYS_THRESHOLD",
    "REMINDER_COOLDOWN_HOURS",
    "auto_reminder_loop",
    "manager_daily_report_loop",
    "get_interns_for_auto_reminder",
    "send_intern_reminder",
    "send_day3_question",
    "notify_manager_test_failed",
    "notify_manager_training_completed",
    "notify_territorial_manager_training_completed",
]

async def notify_manager_training_completed(bot: Bot, intern_id: int) -> bool:
    """
    Надсилає керівнику повідомлення про завершення навчання стажером.
    Кнопки: ✅ «Так, готовий» (переводить у Працівника) та ❌ «Видалити».
    """
    intern = await get_user_details(intern_id)
    if not intern:
        return False

    manager_id = intern.get("manager_id")
    if not manager_id:
        return False

    full_name = intern.get("full_name") or intern.get("username") or f"ID {intern_id}"

    text = (
        f"🎓 <b>Стажер {full_name} завершив навчання!</b>\n\n"
        f"Як гадаєте, чи готовий він розпочати свій шлях та кар'єру в Bulka?\n\n"
        f"<i>Натискаючи, ви підтверджуєте перехід стажера в статус Працівника.</i>"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Так, готовий", callback_data=f"intern_promote_{intern_id}"),
            InlineKeyboardButton(text="❌ Видалити", callback_data=f"intern_dismiss_{intern_id}"),
        ]
    ])

    try:
        await bot.send_message(manager_id, text, reply_markup=kb, parse_mode="HTML")
        return True
    except Exception as exc:
        from bot.services.logger import get_logger
        get_logger().error(f"Failed to notify manager {manager_id} about intern {intern_id} completion: {exc}")
        return False


async def notify_territorial_manager_training_completed(bot: Bot, manager_uid: int) -> bool:
    """
    Надсилає Територіалу сповіщення про завершення навчання керівником-стажером.
    Кнопки: [ ✅ Перевести у «Керівник» ] та [ ⏳ Залишити «Керівник Стажер» ].
    """
    from database.managers import get_manager_by_uid
    mgr = await get_manager_by_uid(manager_uid)
    if not mgr:
        return False
        
    responsible_uid = mgr.get("responsible_uid")
    if not responsible_uid:
        from bot.config import MAIN_DEVELOPER_ID
        responsible_uid = MAIN_DEVELOPER_ID

    full_name = mgr.get("full_name") or mgr.get("username") or f"ID {manager_uid}"
    city = mgr.get("city") or "Не вказано"
    shops = mgr.get("shops") or "Не вказано"

    text = (
        f"🎓 <b>Керівник-стажер {full_name} завершив(-ла) навчання!</b>\n\n"
        f"🏙 <b>Місто:</b> {city}\n"
        f"🏪 <b>Магазини:</b> {shops}\n\n"
        f"Бажаєте перевести його/її в статус повноцінного <b>Керівника</b>?"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Перевести у «Керівник»", callback_data=f"dev_promote_mgr:{manager_uid}")],
        [InlineKeyboardButton(text="⏳ Залишити «Керівник Стажер»", callback_data=f"dev_keep_mgr_trainee:{manager_uid}")]
    ])

    try:
        await bot.send_message(responsible_uid, text, reply_markup=kb, parse_mode="HTML")
        return True
    except Exception as exc:
        from bot.services.logger import get_logger
        get_logger().error(f"Failed to notify territorial {responsible_uid} about manager {manager_uid} completion: {exc}")
        return False
