"""
Утиліта для безпечної відправки довгих повідомлень в Telegram
"""
from aiogram.types import Message, InlineKeyboardMarkup
from typing import Optional

# Telegram ліміт: 4096 символів
TELEGRAM_MAX_LENGTH = 4096
SAFE_MESSAGE_LENGTH = 4000  # З запасом


async def send_long_message(
    message: Message,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    split_by: str = "\n\n"
) -> None:
    """
    Надсилає довге повідомлення, розбиваючи його на частини якщо потрібно.
    
    Args:
        message: Повідомлення для відповіді
        text: Текст для відправки
        reply_markup: Клавіатура (додається тільки до останнього повідомлення)
        split_by: Розділювач для розбиття (за замовчуванням подвійний перенос рядка)
    """
    if len(text) <= SAFE_MESSAGE_LENGTH:
        # Повідомлення вміщається в один блок
        await message.answer(text, reply_markup=reply_markup)
        return
    
    # Розбиваємо текст на частини
    parts = []
    current_part = ""
    
    # Спочатку пробуємо розбити по параграфах
    paragraphs = text.split(split_by)
    
    for paragraph in paragraphs:
        # Якщо один параграф занадто великий - розбиваємо його
        if len(paragraph) > SAFE_MESSAGE_LENGTH:
            if current_part:
                parts.append(current_part)
                current_part = ""
            
            # Розбиваємо великий параграф на шматки
            for i in range(0, len(paragraph), SAFE_MESSAGE_LENGTH - 100):
                chunk = paragraph[i:i + SAFE_MESSAGE_LENGTH - 100]
                parts.append(chunk)
            continue
        
        # Перевіряємо чи додавання параграфа не перевищить ліміт
        if len(current_part) + len(paragraph) + len(split_by) > SAFE_MESSAGE_LENGTH:
            parts.append(current_part)
            current_part = paragraph
        else:
            if current_part:
                current_part += split_by + paragraph
            else:
                current_part = paragraph
    
    # Додаємо останню частину
    if current_part:
        parts.append(current_part)
    
    # Відправляємо всі частини
    for i, part in enumerate(parts):
        is_last = (i == len(parts) - 1)
        kb = reply_markup if is_last else None
        await message.answer(part, reply_markup=kb)


async def send_message_with_debug(
    message: Message,
    main_text: str,
    debug_text: Optional[str] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None
) -> None:
    """
    Надсилає повідомлення з опціональним debug контекстом.
    Якщо разом вони занадто довгі - відправляє окремо.
    
    Args:
        message: Повідомлення для відповіді
        main_text: Основний текст
        debug_text: Debug контекст (опціонально)
        reply_markup: Клавіатура
    """
    if not debug_text:
        # Немає debug - просто відправляємо основний текст
        await send_long_message(message, main_text, reply_markup=reply_markup)
        return
    
    combined = f"{main_text}\n\n{debug_text}"
    
    if len(combined) <= SAFE_MESSAGE_LENGTH:
        # Все вміщається в одне повідомлення
        await message.answer(combined, reply_markup=reply_markup)
    else:
        # Відправляємо окремо
        await message.answer(main_text, reply_markup=reply_markup)
        
        # Debug може бути довгим - обрізаємо якщо потрібно
        if len(debug_text) > SAFE_MESSAGE_LENGTH:
            debug_text = debug_text[:SAFE_MESSAGE_LENGTH - 100]
            debug_text += "\n\n<i>... (обрізано через обмеження Telegram)</i>"
        
        await message.answer(debug_text)


def truncate_text(text: str, max_length: int = SAFE_MESSAGE_LENGTH) -> str:
    """
    Обрізає текст до максимальної довжини, додаючи "..." в кінці.
    
    Args:
        text: Текст для обрізання
        max_length: Максимальна довжина
        
    Returns:
        Обрізаний текст
    """
    if len(text) <= max_length:
        return text
    
    truncated = text[:max_length - 50]
    truncated += "\n\n<i>... (повідомлення обрізано)</i>"
    return truncated