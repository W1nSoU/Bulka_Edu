"""
Groq AI Service для інтелектуального пошуку по навчальних матеріалах.
Підтримує ротацію між кількома API ключами при перевищенні лімітів.
"""

from typing import Optional, List
import httpx
import os
from bot.services.logger import get_logger
from bot.config import GROQ_API_KEY
from database.hr import is_developer_user

logger = get_logger()

# Groq API configuration
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.1-8b-instant"

# Підтримка кількох API ключів (розділені комою або окремі змінні)
def _load_api_keys() -> List[str]:
    """Завантажує всі доступні API ключі."""
    keys = []
    
    # Основний ключ з конфіга
    main_key = GROQ_API_KEY or os.getenv("GROQ_API_KEY", "")
    if main_key:
        # Підтримка кількох ключів через кому
        keys.extend([k.strip() for k in main_key.split(",") if k.strip()])
    
    # Додаткові ключі GROQ_API_KEY_1, GROQ_API_KEY_2, etc.
    for i in range(1, 10):
        extra_key = os.getenv(f"GROQ_API_KEY_{i}", "")
        if extra_key:
            keys.append(extra_key.strip())
    
    return keys


class GroqKeyManager:
    """Менеджер ротації API ключів."""
    
    def __init__(self):
        self._keys = _load_api_keys()
        self._current_index = 0
        self._failed_keys = set()  # Ключі що тимчасово не працюють
    
    @property
    def available_keys_count(self) -> int:
        return len(self._keys)
    
    def get_current_key(self) -> Optional[str]:
        """Повертає поточний активний ключ."""
        if not self._keys:
            return None
        
        # Шукаємо перший не-failed ключ
        for _ in range(len(self._keys)):
            key = self._keys[self._current_index]
            if key not in self._failed_keys:
                return key
            self._rotate()
        
        # Всі ключі failed — скидаємо і пробуємо знову
        self._failed_keys.clear()
        return self._keys[self._current_index] if self._keys else None
    
    def _rotate(self):
        """Перемикає на наступний ключ."""
        if self._keys:
            self._current_index = (self._current_index + 1) % len(self._keys)
    
    def mark_failed(self, key: str):
        """Позначає ключ як тимчасово недоступний."""
        self._failed_keys.add(key)
        self._rotate()
        logger.warning(f"Groq key marked as failed, rotating. Active keys: {len(self._keys) - len(self._failed_keys)}")
    
    def mark_success(self, key: str):
        """Позначає ключ як робочий."""
        self._failed_keys.discard(key)
    
    def reset_failed(self):
        """Скидає всі failed ключі."""
        self._failed_keys.clear()


# Глобальний менеджер ключів
_key_manager = GroqKeyManager()


async def ask_groq(
    question: str,
    context: str,
    max_tokens: int = 1024,
    max_retries: int = 3,
) -> Optional[str]:
    """
    Надсилає питання до Groq API з контекстом навчальних матеріалів.
    Автоматично переключається на інший ключ при помилці.
    
    Args:
        question: Питання від користувача
        context: Текст навчальних матеріалів для контексту
        max_tokens: Максимальна довжина відповіді
        max_retries: Максимум спроб з різними ключами
    
    Returns:
        Відповідь від AI або None при помилці
    """
    system_prompt = """Ти — асистент навчальної платформи Булка для стажерів.
Твоя задача — відповідати на питання стажерів на основі наданих навчальних матеріалів.

ВАЖЛИВІ ПРАВИЛА:
1. Відповідай ТІЛЬКИ на основі наданого контексту
2. Шукай НАЙБІЛЬШ релевантну інформацію до конкретного питання
3. Ігноруй інформацію з контексту, яка не стосується питання
4. Якщо в контексті є кілька різних тем - фокусуйся на тій, що відповідає питанню
5. Структуруй відповідь логічно та зрозуміло
6. Відповідай українською мовою
7. Будь стислим, але інформативним
8. Використовуй дружній професійний тон
9. Якщо релевантної інформації справді немає - чітко про це скажи"""

    user_message = f"""Навчальні матеріали (кожен матеріал позначений [Матеріал X]):
---
{context[:20000]}
---

Питання стажера: {question}

Проаналізуй матеріали та дай КОНКРЕТНУ відповідь на питання. Використовуй ТІЛЬКИ ту інформацію з матеріалів, яка безпосередньо стосується питання. Ігноруй неRelевантну інформацію:"""

    for attempt in range(max_retries):
        api_key = _key_manager.get_current_key()
        if not api_key:
            logger.error("No Groq API keys available")
            return None
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    GROQ_API_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": GROQ_MODEL,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_message},
                        ],
                        "max_tokens": max_tokens,
                        "temperature": 0.3,
                    },
                )
                
                if response.status_code == 200:
                    _key_manager.mark_success(api_key)
                    data = response.json()
                    return data["choices"][0]["message"]["content"]
                
                elif response.status_code == 429:
                    # Rate limit - переключаємось на інший ключ
                    logger.warning(f"Groq rate limit hit, attempt {attempt + 1}/{max_retries}")
                    _key_manager.mark_failed(api_key)
                    continue
                
                elif response.status_code == 401:
                    # Invalid key - переключаємось
                    logger.error(f"Groq invalid API key")
                    _key_manager.mark_failed(api_key)
                    continue
                
                else:
                    logger.error(f"Groq API error: {response.status_code} - {response.text[:200]}")
                    return None
                    
        except httpx.TimeoutException:
            logger.warning(f"Groq timeout, attempt {attempt + 1}/{max_retries}")
            continue
        except Exception as e:
            logger.error(f"Groq API exception: {e}")
            return None
    
    logger.error("All Groq API attempts failed")
    return None


async def search_with_ai(
    question: str,
    context: str,
    user_role: Optional[str] = None,
    user_id: Optional[int] = None, # Add user_id for debugging
) -> str:
    """
    Виконує AI-пошук по навчальних матеріалах на основі наданого контексту.
    
    Args:
        question: Питання від користувача
        context: Сформований контекст з релевантних матеріалів
        user_role: Роль користувача
        user_id: ID користувача для перевірки, чи є він розробником
    
    Returns:
        Відповідь від AI або повідомлення про помилку
    """
    if not is_groq_configured():
        return (
            "⚠️ AI-пошук недоступний.\n\n"
            "Для активації встановіть GROQ_API_KEY в змінних середовища.\n"
            "Отримати безкоштовний ключ: https://console.groq.com"
        )
    
    if not context.strip():
        return "😿 Не знайдено жодних матеріалів для формування відповіді."
    
    # Викликаємо Groq API
    ai_response = await ask_groq(question, context)
    
    is_dev = await is_developer_user(user_id) if user_id else False

    if ai_response:
        keys_info = f" (ключів: {_key_manager.available_keys_count})" if _key_manager.available_keys_count > 1 else ""
        
        # DEBUG: Log context for developers (without showing in message)
        if is_dev:
            from bot.services.logger import get_logger
            logger = get_logger()
            material_count = context.count('[Матеріал ')
            logger.debug(f"AI search - materials in context: {material_count}, total length: {len(context)}")
            logger.debug(f"Context preview: {context[:500]}...")
            
        return f"🤖 <b>AI-відповідь{keys_info}:</b>\n\n{ai_response}"
    else:
        # If AI fails, log context for debugging
        if is_dev:
            from bot.services.logger import get_logger
            logger = get_logger()
            material_count = context.count('[Матеріал ')
            logger.debug(f"AI search failed - materials: {material_count}, context length: {len(context)}")
            logger.debug(f"Context preview: {context[:500]}...")
        
        return (
            "⚠️ Не вдалося отримати відповідь від AI.\n"
            "Спробуйте ще раз або використайте пошук за ключовими словами."
        )


def is_groq_configured() -> bool:
    """Перевіряє, чи налаштований Groq API."""
    return _key_manager.available_keys_count > 0


def get_groq_status() -> dict:
    """Повертає статус Groq API для Панелі Адміністратора."""
    return {
        "configured": is_groq_configured(),
        "total_keys": _key_manager.available_keys_count,
        "active_keys": _key_manager.available_keys_count - len(_key_manager._failed_keys),
        "failed_keys": len(_key_manager._failed_keys),
    }
