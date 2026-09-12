"""
OpenAI GPT service для AI-наставника навчальної платформи BULKA.

Завантажує ВСІ матеріали ролі як контекст і надає цілісні відповіді
на питання стажерів та працівників.
"""

from __future__ import annotations

import os
import json
from typing import Optional, List
from bot.services.logger import get_logger

logger = get_logger()

_client = None


def _get_api_key() -> str:
    # Спочатку з config, потім напряму з env
    try:
        from bot.config import OPENAI_API_KEY
        if OPENAI_API_KEY:
            return OPENAI_API_KEY
    except ImportError:
        pass
    return os.getenv("OPENAI_API_KEY", "")


def is_openai_configured() -> bool:
    """Перевіряє чи налаштований OpenAI API ключ."""
    return bool(_get_api_key())


def get_client():
    """Повертає AsyncOpenAI клієнт (lazy init)."""
    global _client
    key = _get_api_key()
    if not key:
        return None
    if _client is None:
        try:
            from openai import AsyncOpenAI
            _client = AsyncOpenAI(api_key=key)
            logger.info("OpenAI client initialized successfully")
        except ImportError:
            logger.error("openai package not installed. Run: pip install openai")
            return None
    return _client


import asyncio


async def generate_material_summary(
    content: str,
    role: str = "",
    day: int = 1,
    title: str = ""
) -> Optional[str]:
    """
    Генерує короткий, але інформативний зміст/паспорт матеріалу для семантичного індексу.
    Використовує gpt-4o-mini.
    """
    client = get_client()
    if not client or not content or len(content.strip()) < 20:
        return None

    # Якщо контент нереально довгий (понад 100k символів), беремо до 80k символів
    trimmed_content = content[:80000]

    system_prompt = (
        "Ти — експерт-методист навчальних програм компанії BULKA.\n"
        "Твоє завдання — уважно прочитати наданий навчальний матеріал і скласти детальний, "
        "але компактний список тем, процесів, правил, чек-листів та інструкцій, які в ньому розглядаються.\n\n"
        "Вимоги до опису:\n"
        "• Виділи 4-8 головних блоків/тем\n"
        "• Вкажи конкретні терміни, процедури та обов'язки (наприклад: відкриття зміни, прийом товару, касова дисципліна, санітарні норми)\n"
        "• Коротко перелічи, на які практичні питання працівника цей матеріал дає відповідь\n"
        "• Обсяг: приблизно 100-200 слів. Формат: чіткі тези (буліти)\n"
        "• Мова: українська"
    )

    user_prompt = (
        f"Посада: {role}\n"
        f"День навчання: {day}\n"
        f"Попередня назва: {title}\n\n"
        f"Текст навчального матеріалу:\n{trimmed_content}"
    )

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2,
            max_tokens=400,
            timeout=30.0,
        )
        summary = response.choices[0].message.content
        return summary.strip() if summary else None
    except Exception as e:
        logger.error(f"Error generating material summary (role={role}, day={day}): {e}")
        return None


async def backfill_materials_summaries_background():
    """
    Безпечний фоновий процес:
    Знаходить усі матеріали без `summary` і генерує їх по черзі з паузами.
    Не блокує запуск бота, не перевантажує OpenAI API.
    """
    if not is_openai_configured():
        logger.info("[AI Summary Worker] OpenAI key not configured yet, backfill skipped.")
        return

    from database.materials import get_materials_without_summary, update_material_summary

    try:
        missing = await get_materials_without_summary()
        if not missing:
            logger.info("[AI Summary Worker] Всі матеріали вже мають актуальні summary ✅")
            return

        total = len(missing)
        logger.info(f"[AI Summary Worker] Знайдено {total} матеріалів без summary. Починаю чергову генерацію...")

        for idx, mat in enumerate(missing, 1):
            mat_id = mat.get("id")
            role = mat.get("role", "")
            day = mat.get("day", 1)
            title = mat.get("title") or ""
            content = mat.get("content") or ""

            logger.info(f"[AI Summary Worker] ({idx}/{total}) Генерація summary: ID={mat_id}, Роль='{role}', День={day}...")
            summary = await generate_material_summary(content=content, role=role, day=day, title=title)

            if summary:
                await update_material_summary(mat_id, summary)
                logger.info(f"[AI Summary Worker] ({idx}/{total}) Успішно збережено summary для ID={mat_id}")
            else:
                logger.warning(f"[AI Summary Worker] ({idx}/{total}) Не вдалося згенерувати summary для ID={mat_id}")

            # Пауза 1 секунда між матеріалами, щоб не перевищити Rate Limits
            await asyncio.sleep(1.0)

        logger.info("[AI Summary Worker] Почергова генерація summary успішно завершена! 🎉")

    except asyncio.CancelledError:
        logger.info("[AI Summary Worker] Фонова генерація summary зупинена.")
    except Exception as e:
        logger.error(f"[AI Summary Worker] Помилка у фоновому процесі генерації summary: {e}", exc_info=True)


def build_course_outline(all_materials: list[dict]) -> str:
    """
    Створює зміст курсу. Якщо для дня є згенероване `summary` — використовує його!
    Це забезпечує надточний роутинг питань стажера до потрібного дня.
    """
    days_dict: dict[int, list[dict]] = {}
    for m in all_materials:
        day = m.get("day", 1)
        days_dict.setdefault(day, []).append(m)

    outline_lines = []
    for day in sorted(days_dict.keys()):
        mats = days_dict[day]
        outline_lines.append(f"📅 День {day}:")
        
        # Перевіряємо, чи є хоча б одне summary для цього дня
        summaries = [m.get("summary") for m in mats if m.get("summary")]
        if summaries:
            for s in summaries:
                outline_lines.append(f"{s}\n")
        else:
            # Fallback: якщо summary ще не готове, беремо заголовки
            for m in mats:
                title = (m.get("title") or "").strip()
                if not title:
                    content = (m.get("content") or "").strip()
                    title = content.split("\n")[0][:80] if content else "Без назви"
                outline_lines.append(f"  • {title}")

    return "\n".join(outline_lines)


async def route_question_to_days(
    question: str,
    course_outline: str,
    user_id: int | None = None
) -> List[int]:
    """
    КРОК 1: Визначає, в яких саме днях навчання міститься відповідь на питання.
    Швидкий запит до gpt-4o-mini (JSON response).
    """
    client = get_client()
    if not client or not course_outline:
        return []

    system_prompt = (
        "Ти — інтелектуальний диспетчер навчальної програми компанії BULKA.\n"
        "Твоє завдання — проаналізувати зміст навчального курсу за днями і визначити, "
        "в яких саме днях міститься відповідь на питання працівника.\n\n"
        f"Зміст навчального курсу:\n{course_outline}\n\n"
        "Правила:\n"
        "1. Обери від 1 до 2 найбільш релевантних днів (наприклад, [1] або [2, 3]).\n"
        "2. Якщо питання загальне по всій компанії чи правилах — можеш повернути до 3 днів.\n"
        "3. Відповідай ТІЛЬКИ у форматі валідного JSON об'єкта: {\"days\": [номер_дня_1, номер_дня_2]}"
    )

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Питання працівника: {question}"}
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=150,
            timeout=10.0,
        )
        data = json.loads(response.choices[0].message.content or "{}")
        days = data.get("days", [])
        if isinstance(days, list) and all(isinstance(d, int) for d in days):
            logger.info(f"AI Router: Question routed to days {days} for user={user_id}")
            return days
    except Exception as e:
        logger.warning(f"AI Router step failed (fallback will be used): {e}")

    return []


async def ask_gpt_tutor(
    question: str,
    all_materials: list[dict],
    role: str,
    user_id: int | None = None,
) -> Optional[str]:
    """
    2-Step GPT Router:
    Крок 1: Визначаємо релевантні дні за легким змістом курсу.
    Крок 2: Завантажуємо повні тексти цих днів і формуємо відповідь від BULKA радника.
    """
    client = get_client()
    if not client:
        logger.warning("OpenAI not configured — skipping GPT tutor call")
        return None

    if not all_materials:
        logger.warning(f"No materials provided for role '{role}', cannot answer")
        return None

    # --- КРОК 1: Автономний роутинг ---
    course_outline = build_course_outline(all_materials)
    target_days = await route_question_to_days(question, course_outline, user_id=user_id)

    # Відбираємо матеріали: якщо роутер обрав дні — беремо тільки їх, інакше всі (або перші доступні)
    if target_days:
        selected_materials = [m for m in all_materials if m.get("day") in target_days]
        if not selected_materials:
            selected_materials = all_materials
    else:
        selected_materials = all_materials

    # Збираємо контекст відібраних матеріалів
    context_parts = []
    for m in selected_materials:
        day = m.get("day", "?")
        title = (m.get("title") or "").strip()
        content = (m.get("content") or "").strip()
        if not content:
            continue
        header = f"📅 День {day}" + (f": {title}" if title else "")
        context_parts.append(f"{header}\n{content}")

    if not context_parts:
        logger.warning(f"All selected materials for role '{role}' have empty content")
        return None

    context = "\n\n---\n\n".join(context_parts)

    system_prompt = (
        "Ти — BULKA радник 🥐, інтелектуальний помічник навчальної платформи мережі BULKA.\n"
        "Твоя задача — чітко, структуровано та доброзичливо відповідати на питання стажерів і працівників "
        "на основі офіційних навчальних матеріалів компанії.\n\n"
        "Правила відповідей:\n"
        "• Відповідай по суті, професійно та зрозуміло, як досвідчений наставник.\n"
        "• Обов'язково вказуй, до якого дня навчання або теми відноситься інформація (наприклад: «Згідно з матеріалами Дня 2...»).\n"
        "• Якщо інформації немає в наданих матеріалах — прямо скажи: «У навчальній програмі немає цієї інформації. Будь ласка, зверніться до свого керівника або наставника.»\n"
        "• Не вигадуй стандартів чи регламентів, яких немає в тексті.\n"
        "• Відповідай українською мовою з охайним форматуванням (списки, пункти).\n\n"
        f"Навчальні матеріали для посади «{role}»:\n\n"
        f"{context}"
    )

    logger.info(
        f"GPT tutor call: user={user_id}, role='{role}', "
        f"materials={len(context_parts)}, context_len={len(context)}, "
        f"question='{question[:80]}...'"
    )

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
            max_tokens=1200,
            temperature=0.3,
        )
        answer = response.choices[0].message.content
        usage = response.usage
        logger.info(
            f"GPT tutor success: user={user_id}, "
            f"prompt_tokens={usage.prompt_tokens}, "
            f"completion_tokens={usage.completion_tokens}, "
            f"total_tokens={usage.total_tokens}"
        )
        return answer

    except Exception as e:
        logger.error(f"OpenAI GPT tutor error (user={user_id}): {e}")
        return None


async def improve_news_text_with_gpt(original_text: str) -> Optional[str]:
    """
    Покращує текст корпоративної новини мережі BULKA за допомогою gpt-4o-mini:
    - Зберігає фактологічну суть, дати та деталі.
    - Робить текст мотивуючим, доброзичливим, легкочитним та структурованим.
    - Додає доречні емодзі та форматує за допомогою валідного Telegram HTML (<b>, <i>).
    - Не додає зайвих коментарів і не додає хештеги.
    """
    client = get_client()
    if not client or not original_text:
        return None

    system_prompt = (
        "Ти — професійний корпоративний редактор та копірайтер мережі пекарень BULKA.\n"
        "Твоє завдання — вдосконалити текст новини/оголошення для внутрішньої розсилки співробітникам компанії.\n\n"
        "Правила редагування:\n"
        "1. Збережи абсолютно всі факти, дати, цифри, терміни та суть оригінального повідомлення.\n"
        "2. Зроби формулювання чіткими, приємними, надихаючими та структурованими (використовуй абзаци або пункти списку).\n"
        "3. Додай доречні емодзі для візуальних акцентів (🍞, 🥐, ✨, 📢, 💡, 📍 тощо).\n"
        "4. Використовуй тільки валідні Telegram HTML-теги: <b>жирний</b>, <i>курсив</i>, <code>код</code>. Не використовуй Markdown (** або *).\n"
        "5. НЕ додавай жодних хештегів (вони прикріплюються системою автоматично).\n"
        "6. Відповідай ВИКЛЮЧНО готовим покращеним текстом публікації. Без жодних вступів на зразок 'Ось покращений варіант:' чи коментарів у кінці."
    )

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": original_text}
            ],
            temperature=0.7,
            max_tokens=1000,
            timeout=25.0
        )
        improved = response.choices[0].message.content
        if improved:
            return improved.strip()
    except Exception as e:
        logger.error(f"Error improving news text with GPT: {e}")

    return None

