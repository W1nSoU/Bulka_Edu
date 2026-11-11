from typing import Dict, Any, Callable, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject, InlineKeyboardMarkup, InlineKeyboardButton
from database.users import get_user_details, update_last_activity
from database.managers import get_manager_by_uid
from bot.services.access import is_privileged_user # Import is_privileged_user

class AccessMiddleware(BaseMiddleware):
    """Middleware для перевірки доступу користувачів та оновлення їх активності"""
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        # Отримання user_id з будь-якого типу події
        user_id = None
        if isinstance(event, Message):
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id
            
        if not user_id:
            return await handler(event, data)

        # 1. Завжди дозволяємо доступ, якщо у користувача є активний FSM-стан
        # (наприклад, введення ПІБ під час реєстрації або відповідь на опитування/тест)
        state_obj = data.get("state")
        current_state = await state_obj.get_state() if state_obj else None
        if current_state:
            return await handler(event, data)

        # 2. Перевірка, чи є користувач керівником у managers.db
        manager_info = await get_manager_by_uid(user_id)
        if manager_info:
            if manager_info.get("status") == "fired":
                access_denied_msg = (
                    "⚠️ <b>Доступ обмежено</b> ⚠️\n\n"
                    "Вибачте, але ваш обліковий запис деактивовано."
                )
                if isinstance(event, CallbackQuery):
                    await event.answer("Обліковий запис деактивовано", show_alert=True)
                    return None
                elif isinstance(event, Message):
                    await event.answer(access_denied_msg)
                    return None
            # Активний керівник завжди має доступ
            await update_last_activity(user_id)
            return await handler(event, data)

        # 3. Перевірка наглядача напряму
        from database.managers import is_observer_user
        if await is_observer_user(user_id):
            await update_last_activity(user_id)
            return await handler(event, data)

        # 4. Додаткова перевірка для привілейованих користувачів (Dev/HR)
        if await is_privileged_user(user_id):
            await update_last_activity(user_id)
            return await handler(event, data)

        # 5. Для команди /start дозволяємо доступ завжди, щоб користувач міг пройти реєстрацію
        if isinstance(event, Message) and event.text and event.text.startswith("/start"):
            return await handler(event, data)
            
        # 6. Перевірка наявності користувача в базі даних users.db
        user_details = await get_user_details(user_id)
        has_role = bool(user_details and user_details.get('role'))
        has_manager = bool(user_details and user_details.get('manager_id'))
        is_worker = bool(user_details and (user_details.get('status') == 'Працівник' or user_details.get('is_worker')))

        from database.users import MANAGEMENT_ROLES
        is_management = bool(user_details and user_details.get('role') in MANAGEMENT_ROLES)

        if user_details and has_role and (is_worker or has_manager or is_management):
            await update_last_activity(user_id)
            return await handler(event, data)

        # 7. Блокуємо доступ та виводимо повідомлення про відмову
        from bot.services.logger import get_logger
        get_logger().info(f"⛔ AccessMiddleware block: uid={user_id}, event={type(event).__name__}, details={user_details}")

        access_denied_msg = (
            "⚠️ <b>Доступ обмежено</b> ⚠️\n\n"
            "Вибачте, але у вас немає доступу до корпоративної навчальної платформи BULKA.\n\n"
            "Доступ надається виключно працівникам компанії за запрошенням від керівника.\n\n"
            "Якщо ви співробіттник компанії, будь ласка, зверніться до свого керівника для отримання посилання-запрошення."
        )
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Доступ заблоковано", callback_data="none")]
        ])
        
        if isinstance(event, CallbackQuery):
            # Обробляємо будь-який callback (особливо "continue_learning")
            try:
                # Намагаємося редагувати повідомлення, якщо можливо
                await event.message.edit_text(access_denied_msg, reply_markup=kb)
            except Exception:
                # Якщо редагування не вдалося - відправляємо нове повідомлення
                await event.message.answer(access_denied_msg, reply_markup=kb)
            
            # Відповідаємо на callback, щоб зникла "годинник" на кнопці
            await event.answer("Доступ заблоковано", show_alert=True)
            
            # Повертаємо None щоб припинити обробку
            return None
        elif isinstance(event, Message):
            # Для звичайних повідомлень просто відповідаємо
            await event.answer(access_denied_msg, reply_markup=kb)
            return None
                
        # Оновлення часу останньої активності користувача
        await update_last_activity(user_id)
        
        # Продовження обробки події
        return await handler(event, data)
    

