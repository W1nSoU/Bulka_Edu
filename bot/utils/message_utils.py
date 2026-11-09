"""
Утиліта для безпечної відправки довгих повідомлень в Telegram та санітизації HTML
"""
import re
import html
from aiogram.types import Message, InlineKeyboardMarkup
from typing import Optional

# Telegram ліміт: 4096 символів
TELEGRAM_MAX_LENGTH = 4096
SAFE_MESSAGE_LENGTH = 4000  # З запасом


def sanitize_telegram_html(text: str) -> str:
    """
    Санітизує текст для безпечної відправки в Telegram з parse_mode='HTML':
    - Перетворює списки <ul>, <ol>, <li> на зрозумілі текстові буліти ('• item').
    - Перетворює <p>, <div>, <br> на відповідні переноси рядків.
    - Перетворює заголовки <h1>...<h6> на <b>...</b>.
    - Залишає виключно підтримувані Telegram HTML-теги:
      <b>, <strong>, <i>, <em>, <u>, <ins>, <s>, <strike>, <del>,
      <code>, <pre>, <blockquote>, <tg-spoiler>, <tg-emoji>, <a href="...">.
    - Стрипає будь-які заборонені теги (span без tg-spoiler, table тощо), зберігаючи текст всередині.
    - Автоматично закриває незакриті теги та прибирає осиротілі закриваючі теги.
    - Екранує непарні/сирі символи '<' та '&', що не є частиною валідних тегів/сутностей.
    """
    if not text:
        return ""

    raw = str(text)

    # 1. Заміна блочних та спискових елементів на читабельний текст
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?i)</p>", "\n\n", raw)
    raw = re.sub(r"(?i)<p[^>]*>", "", raw)
    raw = re.sub(r"(?i)<li[^>]*>", "• ", raw)
    raw = re.sub(r"(?i)</li>", "\n", raw)
    raw = re.sub(r"(?i)</?[uo]l[^>]*>", "\n", raw)
    raw = re.sub(r"(?i)<h[1-6][^>]*>(.*?)</h[1-6]>", r"<b>\1</b>\n", raw)
    raw = re.sub(r"(?i)</?div[^>]*>", "\n", raw)

    # Підтримувані прості теги
    simple_tags = {
        "b": "b", "strong": "strong",
        "i": "i", "em": "em",
        "u": "u", "ins": "ins",
        "s": "s", "strike": "strike", "del": "del",
        "code": "code", "pre": "pre",
        "blockquote": "blockquote",
        "tg-spoiler": "tg-spoiler",
        "tg-emoji": "tg-emoji"
    }

    # Обробка спойлерів через span
    raw = re.sub(r'(?i)<span[^>]*class=["\']tg-spoiler["\'][^>]*>(.*?)</span>', r'<tg-spoiler>\1</tg-spoiler>', raw)
    raw = re.sub(r'(?i)</?span[^>]*>', '', raw)

    # 2. Парсинг тегів зі стеком для збалансованості
    tag_regex = re.compile(r'</?([a-zA-Z0-9_-]+)([^>]*)>')
    result = []
    stack = []
    last_idx = 0

    for m in tag_regex.finditer(raw):
        start, end = m.span()
        tag_str = m.group(0)
        tag_name = m.group(1).lower()
        attrs = m.group(2)
        is_closing = tag_str.startswith("</")

        # Текст між тегами: екрануємо сирі '<' та '&'
        chunk = raw[last_idx:start]
        if chunk:
            # Екрануємо & що не є частиною сутностей
            chunk = re.sub(r'&(?!(?:amp|lt|gt|quot|#\d+|#x[0-9a-fA-F]+);)', '&amp;', chunk)
            # Екрануємо непарні <
            chunk = chunk.replace("<", "&lt;")
            result.append(chunk)
        last_idx = end

        if is_closing:
            if tag_name in stack:
                while stack and stack[-1] != tag_name:
                    unclosed = stack.pop()
                    result.append(f"</{unclosed}>")
                if stack and stack[-1] == tag_name:
                    stack.pop()
                    result.append(f"</{tag_name}>")
            # Якщо закриваючий тег не відкривався — ігноруємо
        else:
            if tag_name in simple_tags:
                canonical = simple_tags[tag_name]
                if canonical == "blockquote" and "expandable" in attrs.lower():
                    result.append("<blockquote expandable>")
                else:
                    result.append(f"<{canonical}>")
                stack.append(canonical)
            elif tag_name == "a":
                href_m = re.search(r'href=["\']([^"\']+)["\']', attrs, re.IGNORECASE)
                if href_m:
                    href = href_m.group(1)
                    result.append(f'<a href="{href}">')
                    stack.append("a")
            # Інші заборонені теги ігноруються

    # Залишок тексту
    tail = raw[last_idx:]
    if tail:
        tail = re.sub(r'&(?!(?:amp|lt|gt|quot|#\d+|#x[0-9a-fA-F]+);)', '&amp;', tail)
        tail = tail.replace("<", "&lt;")
        result.append(tail)

    # Закриваємо незакриті теги зі стеку
    while stack:
        unclosed = stack.pop()
        result.append(f"</{unclosed}>")

    clean = "".join(result)
    clean = re.sub(r"[ \t]+\n", "\n", clean)
    clean = re.sub(r"[ \t]{2,}", " ", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean.strip()



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