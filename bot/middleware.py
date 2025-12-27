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
            
        # Перевірка, чи є користувач керівником
        manager_info = await get_manager_by_uid(user_id)
        if manager_info:
            # Керівник завжди має доступ
            # Оновлюємо активність керівника
            await update_last_activity(user_id)
            return await handler(event, data)

        # Додаткова перевірка для привілейованих користувачів (Dev/HR), які не є менеджерами
        if await is_privileged_user(user_id):
            await update_last_activity(user_id) # Оновлюємо активність для privileged users
            return await handler(event, data)
            
        # Перевірка, чи існує користувач у базі даних
        user_details = await get_user_details(user_id)

        # Спочатку перевіряємо наявність користувача в базі
        # Якщо його немає, або у нього немає керівника чи ролі - блокуємо доступ
        if not user_details or not (user_details.get('manager_id') and user_details.get('role')):
            # Для команди /start дозволяємо доступ, щоб користувач міг зареєструватись
            if isinstance(event, Message) and event.text and event.text.startswith("/start"):
                return await handler(event, data)
                
            # Блокуємо доступ та виводимо повідомлення про відмову
            access_denied_msg = (
                "⚠️ <b>Доступ обмежено</b> ⚠️\n\n"
                "Вибачте, але у вас немає доступу до корпоративної навчальної платформи Булка.\n\n"
                "Доступ надається виключно працівникам компанії за запрошенням від керівника.\n\n"
                "Якщо ви співробітник компанії, будь ласка, зверніться до свого керівника для отримання посилання-запрошення."
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
            