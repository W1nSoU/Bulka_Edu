"""
OpenAI GPT service для AI-наставника навчальної платформи BULKA.

Завантажує ВСІ матеріали ролі як контекст і надає цілісні відповіді
на питання стажерів та працівників.
"""

from __future__ import annotations

import asyncio
import html
import json
import os
import re
from typing import List, Optional

from bot.services.logger import get_logger
from bot.utils.message_utils import sanitize_telegram_html
from database import DB_PATH

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


NO_ANSWER_MARKER = "__NO_ANSWER_IN_MATERIALS__"
NETWORK_FALLBACK_NOTE = (
    "<i>ℹ️ У матеріалах твоєї посади відповіді не знайдено, "
    "тому я перевірив інструкції всієї мережі:</i>\n\n"
)


def _format_gpt_telegram_html(raw_text: str) -> str:
    """Converts any leftover Markdown bolding/headings and sanitizes output for Telegram HTML."""
    text = (raw_text or "").strip()
    text = re.sub(r"(?m)^#{1,6}\s+(.+)$", r"<b>\1</b>", text)
    text = re.sub(r"\*\*([^\n*]+?)\*\*", r"<b>\1</b>", text)
    return sanitize_telegram_html(text)


def _format_extractive_fallback(
    question: str,
    results: list[dict],
    used_network_fallback: bool = False,
    max_items: int = 8,
) -> str:
    """Formats clean chunk excerpts when OpenAI chat completion is unavailable."""
    safe_q = html.escape((question or "").strip())
    lines: list[str] = [
        f"🔎 <b>Результати пошуку за запитом «{safe_q}»</b>",
        "<i>BULKA радник тимчасово недоступний. Показую знайдені фрагменти з інструкцій:</i>",
        "",
    ]
    if used_network_fallback:
        lines.append(NETWORK_FALLBACK_NOTE.strip())
        lines.append("")

    for idx, item in enumerate(results[:max_items], 1):
        label = html.escape(item.get("sources_label") or "Інструкція")
        excerpt = (item.get("excerpt") or "").strip()
        if len(excerpt) > 450:
            excerpt = excerpt[:449].rstrip() + "…"
        lines.append(f"{idx}. <b>{label}</b>")
        if excerpt:
            lines.append(f"   {html.escape(excerpt)}")
        lines.append("")

    return sanitize_telegram_html("\n".join(lines).strip())


def _build_chunks_context(results: list[dict]) -> str:
    blocks: list[str] = []
    for idx, item in enumerate(results, 1):
        label = item.get("sources_label") or "Загальні матеріали"
        excerpt = (item.get("excerpt") or "").strip()
        if excerpt:
            blocks.append(f"[Джерело {idx}: {label}]\n{excerpt}")
    return "\n\n---\n\n".join(blocks)


async def _synthesize_answer_from_chunks(
    question: str,
    results: list[dict],
    role_label: str,
    is_network_wide: bool,
    user_id: Optional[int] = None,
    client=None,
) -> tuple[Optional[str], bool]:
    """
    Calls gpt-4o-mini on retrieved chunks.

    Returns (answer_text_or_none, gpt_was_available).
    When GPT explicitly determines the excerpts do not answer the question, returns
    (NO_ANSWER_MARKER, True).
    """
    active_client = client if client is not None else get_client()
    if not active_client:
        return None, False

    context = _build_chunks_context(results)
    if not context:
        return NO_ANSWER_MARKER, True

    citation_rule = (
        "Обов'язково вказуй джерело у форматі [Посада, День X] для кожного факту або блоку."
        if is_network_wide
        else "Обов'язково вказуй, до якого дня відноситься інформація (наприклад: [День X])."
    )

    system_prompt = (
        "Ти — BULKA радник, інтелектуальний помічник навчальної платформи мережі пекарень BULKA.\n"
        "Твоє завдання — дати повну, точну та структуровану відповідь на запитання співробітника "
        "ВИКЛЮЧНО на основі наданих нижче фрагментів інструкцій.\n\n"
        "Правила відповідей:\n"
        "• Відповідай тільки фактами з наданих джерел, не вигадуй регламенти, яких немає в тексті.\n"
        "• Якщо в наданих фрагментах є кілька правил, умов або згадок по темі (наприклад, по всьому тексту чи кількох посадах) — "
        "обов'язково включи та узагальни ВСІ релевантні пункти, нічого не пропускаючи.\n"
        f"• {citation_rule}\n"
        "• Використовуй ТІЛЬКИ валідні Telegram HTML-теги: <b>жирний</b>, <i>курсив</i>, <code>код</code>, <blockquote>цитата</blockquote>. "
        "Категорично заборонено <ul>, <ol>, <li>, <p>, <br>, <h1>-<h6> та Markdown (** чи #). Для списків використовуй '• ' з нового рядка.\n"
        f"• Якщо у наданих фрагментах взагалі немає відповіді на це запитання, відповідай ОДНИМ точним рядком: {NO_ANSWER_MARKER}\n\n"
        f"Фрагменти інструкцій ({role_label}):\n\n"
        f"{context}"
    )

    logger.info(
        f"GPT tutor call: user={user_id}, scope='{role_label}', "
        f"chunks={len(results)}, context_len={len(context)}, "
        f"question='{question[:80]}...'"
    )

    try:
        response = await active_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
            max_tokens=1800,
            temperature=0.2,
            timeout=35.0,
        )
        raw_answer = (response.choices[0].message.content or "").strip()
        usage = getattr(response, "usage", None)
        if usage is not None:
            logger.info(
                f"GPT tutor success: user={user_id}, "
                f"prompt_tokens={usage.prompt_tokens}, "
                f"completion_tokens={usage.completion_tokens}, "
                f"total_tokens={usage.total_tokens}"
            )
        if not raw_answer or NO_ANSWER_MARKER in raw_answer:
            return NO_ANSWER_MARKER, True
        return _format_gpt_telegram_html(raw_answer), True
    except Exception as e:
        logger.error(f"OpenAI GPT tutor error (user={user_id}): {e}")
        return None, False


async def answer_remind_topic(
    question: str,
    role_filter: Optional[str] = None,
    user_id: Optional[int] = None,
    db_path: str = DB_PATH,
    client=None,
) -> dict:
    """
    2-Stage hybrid retrieval + GPT synthesis for 'Нагадати тему':
      - Global search (`role_filter is None`): searches all network chunks directly.
      - Role search (`role_filter` set):
          Stage 1 searches strictly role (+ 'ALL').
          Stage 2 searches across the whole network ONLY if Stage 1 has 0 chunks,
          no relevant matches, or GPT returns NO_ANSWER_MARKER.
    """
    from bot.services.semantic_search import hybrid_search_chunks

    clean_question = (question or "").strip()
    if not clean_question:
        return {
            "status": "not_found",
            "text": "",
            "used_network_fallback": False,
            "used_gpt": False,
            "matches": [],
        }

    # --- Global mode ("Всі посади") ---
    if not role_filter:
        global_res = await hybrid_search_chunks(
            query=clean_question,
            role_filter=None,
            scope="global",
            db_path=db_path,
            client=client,
        )
        if not global_res["results"] or not global_res["has_relevant_match"]:
            return {
                "status": "not_found",
                "text": "",
                "used_network_fallback": False,
                "used_gpt": False,
                "matches": [],
            }

        answer, gpt_ok = await _synthesize_answer_from_chunks(
            question=clean_question,
            results=global_res["results"],
            role_label="усіх посад мережі",
            is_network_wide=True,
            user_id=user_id,
            client=client,
        )
        if gpt_ok:
            if answer == NO_ANSWER_MARKER:
                return {
                    "status": "not_found",
                    "text": "",
                    "used_network_fallback": False,
                    "used_gpt": True,
                    "matches": [],
                }
            return {
                "status": "ok",
                "text": answer or "",
                "used_network_fallback": False,
                "used_gpt": True,
                "matches": global_res["results"],
            }

        return {
            "status": "fallback_lexical",
            "text": _format_extractive_fallback(clean_question, global_res["results"], used_network_fallback=False),
            "used_network_fallback": False,
            "used_gpt": False,
            "matches": global_res["results"],
        }

    # --- Stage 1: User's own role (+ 'ALL') ---
    stage1_res = await hybrid_search_chunks(
        query=clean_question,
        role_filter=role_filter,
        scope="role",
        db_path=db_path,
        client=client,
    )

    inspected_hashes: Optional[set[str]] = None
    if stage1_res["scoped_chunk_count"] > 0 and stage1_res["has_relevant_match"] and stage1_res["results"]:
        answer, gpt_ok = await _synthesize_answer_from_chunks(
            question=clean_question,
            results=stage1_res["results"],
            role_label=role_filter,
            is_network_wide=False,
            user_id=user_id,
            client=client,
        )
        if gpt_ok and answer and answer != NO_ANSWER_MARKER:
            return {
                "status": "ok",
                "text": answer,
                "used_network_fallback": False,
                "used_gpt": True,
                "matches": stage1_res["results"],
            }
        if not gpt_ok:
            return {
                "status": "fallback_lexical",
                "text": _format_extractive_fallback(clean_question, stage1_res["results"], used_network_fallback=False),
                "used_network_fallback": False,
                "used_gpt": False,
                "matches": stage1_res["results"],
            }
        # GPT inspected Stage 1 chunks and confirmed answer is absent there.
        inspected_hashes = {r["chunk_hash"] for r in stage1_res["results"]}

    # --- Stage 2: Cross-role network fallback ---
    stage2_res = await hybrid_search_chunks(
        query=clean_question,
        role_filter=None,
        scope="network_fallback",
        exclude_hashes=inspected_hashes,
        db_path=db_path,
        client=client,
    )
    if not stage2_res["results"] or not stage2_res["has_relevant_match"]:
        return {
            "status": "not_found",
            "text": "",
            "used_network_fallback": True,
            "used_gpt": False,
            "matches": [],
        }

    answer2, gpt2_ok = await _synthesize_answer_from_chunks(
        question=clean_question,
        results=stage2_res["results"],
        role_label="усієї мережі",
        is_network_wide=True,
        user_id=user_id,
        client=client,
    )
    if gpt2_ok:
        if answer2 == NO_ANSWER_MARKER or not answer2:
            return {
                "status": "not_found",
                "text": "",
                "used_network_fallback": True,
                "used_gpt": True,
                "matches": [],
            }
        return {
            "status": "ok",
            "text": f"{NETWORK_FALLBACK_NOTE}{answer2}",
            "used_network_fallback": True,
            "used_gpt": True,
            "matches": stage2_res["results"],
        }

    return {
        "status": "fallback_lexical",
        "text": _format_extractive_fallback(clean_question, stage2_res["results"], used_network_fallback=True),
        "used_network_fallback": True,
        "used_gpt": False,
        "matches": stage2_res["results"],
    }


async def ask_gpt_tutor(
    question: str,
    all_materials: list[dict],
    role: str,
    user_id: int | None = None,
) -> Optional[str]:
    """Compatibility wrapper delegating to 2-stage hybrid answer_remind_topic."""
    normalized_role = None if (not role or role == "загальна") else role
    res = await answer_remind_topic(question=question, role_filter=normalized_role, user_id=user_id)
    if res["status"] == "ok":
        return res["text"]
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
        "4. Використовуй тільки валідні Telegram HTML-теги: <b>жирний</b>, <i>курсив</i>, <code>код</code>. Категорично заборонено використовувати <ul>, <ol>, <li>, <p>, <br>, <h1>-<h6> або Markdown (** чи *). Для списків використовуй звичайні емодзі або текстовий буліт '• ' на новому рядку.\n"
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
            from bot.utils.message_utils import sanitize_telegram_html
            return sanitize_telegram_html(improved)
    except Exception as e:
        logger.error(f"Error improving news text with GPT: {e}")

    return None

