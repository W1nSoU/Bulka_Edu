from __future__ import annotations
import re
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass


@dataclass
class ParsedQuestion:
    question_idx: int
    text: str
    question_type: str  # 'choice' | 'multi_choice' | 'text'
    options: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question_idx": self.question_idx,
            "text": self.text,
            "question_type": self.question_type,
            "options": self.options
        }

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def keys(self):
        return ["question_idx", "text", "question_type", "options"]

    def items(self):
        return self.to_dict().items()

    def values(self):
        return self.to_dict().values()


class SurveyParser:
    """Парсер для структурованих шаблонів корпоративних опитувань BULKA."""

    QUESTION_HEADER_PATTERN = re.compile(r"^\s*(\d+)[\.\)]\s*(.+)$")
    OPTION_PATTERN = re.compile(r"^\s*([а-яА-Яa-zA-ZіїєґІЇЄҐ])[\.\)]\s*(.+)$")
    FREE_TEXT_MARKERS = [
        "(вільна відповідь)",
        "(вільна)",
        "(розгорнута відповідь)",
        "(текстова відповідь)",
        "(текст)"
    ]
    MULTI_CHOICE_MARKERS = [
        "(кілька варіантів)",
        "(вибір кількох варіантів)",
        "(мультивибір)",
        "(множинний вибір)",
        "(можна кілька)",
    ]
    MAX_MULTI_CHOICE_OPTIONS = 45

    @staticmethod
    def _strip_markers(text: str, markers: List[str]) -> str:
        """Видаляє службові маркери типу питання без урахування регістру."""
        cleaned = text
        for marker in markers:
            cleaned = re.sub(re.escape(marker), "", cleaned, flags=re.IGNORECASE)
        return re.sub(r"\s{2,}", " ", cleaned).strip()

    @classmethod
    def parse_template(cls, text: str) -> Tuple[Optional[List[ParsedQuestion]], Optional[str]]:
        """
        Парсить вхідний текст шаблону опитування.
        Повертає (список_ParsedQuestion, None) у разі успіху,
        або (None, текст_помилки) у разі некоректного формату.
        """
        if not text or not text.strip():
            return None, "Текст опитування порожній. Будь ласка, заповніть шаблон за інструкцією."

        lines = [line.strip() for line in text.strip().splitlines()]
        
        raw_blocks: List[Dict[str, Any]] = []
        current_block: Optional[Dict[str, Any]] = None

        for line in lines:
            if not line:
                continue

            q_match = cls.QUESTION_HEADER_PATTERN.match(line)
            if q_match:
                if current_block:
                    raw_blocks.append(current_block)
                q_num = int(q_match.group(1))
                q_text = q_match.group(2).strip()
                current_block = {
                    "num": q_num,
                    "text": q_text,
                    "options": []
                }
                continue

            opt_match = cls.OPTION_PATTERN.match(line)
            if opt_match and current_block is not None:
                opt_letter = opt_match.group(1).lower()
                opt_text = opt_match.group(2).strip()
                current_block["options"].append(f"{opt_letter}. {opt_text}")
                continue

            # Якщо це додатковий рядок тексту питання або варіанту
            if current_block is not None:
                if not current_block["options"]:
                    current_block["text"] += f" {line}"
                else:
                    current_block["options"][-1] += f" {line}"

        if current_block:
            raw_blocks.append(current_block)

        if not raw_blocks:
            return None, (
                "❌ <b>Помилка формату шаблону:</b> не вдалося розпізнати жодного питання.\n\n"
                "Кожне питання повинно починатися з номера з крапкою (наприклад: <code>1. Ваше питання</code>)."
            )

        parsed_questions: List[ParsedQuestion] = []
        for idx, block in enumerate(raw_blocks, start=1):
            q_text = block["text"]
            options = block["options"]
            q_lower = q_text.lower()

            # Перевіряємо тип питання за маркерами
            is_free_text = any(marker in q_lower for marker in cls.FREE_TEXT_MARKERS)
            is_multi_choice = any(marker in q_lower for marker in cls.MULTI_CHOICE_MARKERS)

            if is_free_text and is_multi_choice:
                return None, (
                    f"❌ <b>Помилка у питанні №{block['num']}:</b>\n"
                    f"«{block['text']}»\n\n"
                    "Не можна одночасно позначати питання як вільну відповідь і вибір кількох варіантів."
                )

            # Очищуємо маркери з відображуваного тексту питання
            clean_text = cls._strip_markers(q_text, cls.FREE_TEXT_MARKERS + cls.MULTI_CHOICE_MARKERS)

            if is_free_text or not options:
                # Якщо явно вказано вільну відповідь або немає варіантів
                if is_free_text:
                    parsed_questions.append(ParsedQuestion(
                        question_idx=idx,
                        text=clean_text or q_text,
                        question_type="text",
                        options=[]
                    ))
                elif is_multi_choice:
                    return None, (
                        f"❌ <b>Помилка у питанні №{block['num']}:</b>\n"
                        f"«{block['text']}»\n\n"
                        "Для питання з вибором кількох варіантів потрібно додати щонайменше 2 варіанти "
                        "(наприклад: <code>а. Варіант 1</code>, <code>б. Варіант 2</code>)."
                    )
                else:
                    return None, (
                        f"❌ <b>Помилка у питанні №{block['num']}:</b>\n"
                        f"«{block['text']}»\n\n"
                        f"Не знайдено варіантів відповідей. Якщо це відкрите питання, "
                        f"додайте в кінці помітку <code>(вільна відповідь)</code>. "
                        f"Якщо з вибором — додайте варіанти (наприклад: <code>а. Варіант 1</code>, <code>б. Варіант 2</code>)."
                    )
            else:
                if len(options) < 2:
                    return None, (
                        f"❌ <b>Помилка у питанні №{block['num']}:</b>\n"
                        f"«{block['text']}»\n\n"
                        f"Знайдено лише {len(options)} варіант відповіді. Для вибору потрібно щонайменше 2 варіанти (а. та б.)."
                    )
                if is_multi_choice and len(options) > cls.MAX_MULTI_CHOICE_OPTIONS:
                    return None, (
                        f"❌ <b>Помилка у питанні №{block['num']}:</b>\n"
                        f"«{block['text']}»\n\n"
                        f"Знайдено {len(options)} варіантів. Для мультивибору підтримується не більше {cls.MAX_MULTI_CHOICE_OPTIONS} варіантів."
                    )
                parsed_questions.append(ParsedQuestion(
                    question_idx=idx,
                    text=clean_text or q_text,
                    question_type="multi_choice" if is_multi_choice else "choice",
                    options=options
                ))

        return parsed_questions, None
