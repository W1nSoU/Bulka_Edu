from __future__ import annotations

import io
import re
from typing import Optional

import docx
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph


def sanitize_instruction_filename(topic_title: Optional[str], inst_id: Optional[int] = None) -> str:
    """Формує безпечну назву .docx файлу інструкції на основі назви теми."""
    raw = (topic_title or "").strip()
    cleaned = re.sub(r'[\\/*?:"<>|\r\n\t]+', "", raw)
    cleaned = re.sub(r"[^\w\s\-'.а-яА-ЯіїєґІЇЄҐ]", "", cleaned, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._ ")
    if not cleaned:
        cleaned = f"instruction_{inst_id or 'doc'}"
    return f"{cleaned[:80]}.docx"


def generate_instruction_template_docx(topic_title: Optional[str] = None) -> io.BytesIO:
    """
    Генерує структурований Word-шаблон (.docx) інструкції BULKA
    для заповнення адміністратором та подальшої індексації в ШІ.
    """
    doc = docx.Document()
    title_label = (topic_title or "").strip() or "[Вкажіть назву теми]"

    doc.add_heading(f"ІНСТРУКЦІЯ BULKA: {title_label}", level=0)
    intro = doc.add_paragraph(
        "Цей шаблон створено для стандартизованого оформлення корпоративних інструкцій "
        "мережі BULKA. Заповніть розділи нижче — система автоматично проіндексує весь текст "
        "та таблиці для пошуку через ШІ-радника."
    )
    intro.italic = True

    doc.add_heading("1. Загальні положення та призначення", level=1)
    doc.add_paragraph(
        "Коротко опишіть, кого стосується ця інструкція, коли вона застосовується та яка її головна мета."
    )

    doc.add_heading("2. Основні правила та стандарти", level=1)
    doc.add_paragraph("Ключове правило або обов'язкова вимога №1.", style="List Bullet")
    doc.add_paragraph("Ключове правило або обов'язкова вимога №2.", style="List Bullet")
    doc.add_paragraph("Винятки або особливі умови.", style="List Bullet")

    doc.add_heading("3. Покроковий алгоритм дій", level=1)
    doc.add_paragraph("Крок 1: Підготовка / перевірка вихідних даних.", style="List Number")
    doc.add_paragraph("Крок 2: Виконання основної процедури.", style="List Number")
    doc.add_paragraph("Крок 3: Контроль результату / звітність.", style="List Number")

    doc.add_heading("4. Важливі застереження та типові помилки", level=1)
    table = doc.add_table(rows=3, cols=2)
    table.style = "Table Grid"
    hdr_cells = table.rows[0].cells
    hdr_cells[0].text = "Ситуація / Проблема"
    hdr_cells[1].text = "Правильна дія співробітника"

    table.rows[1].cells[0].text = "Приклад: виявлено невідповідність або брак"
    table.rows[1].cells[1].text = "Зафіксувати фото, повідомити керівника магазину та оформити акт."
    table.rows[2].cells[0].text = "Приклад: нестандартне звернення клієнта"
    table.rows[2].cells[1].text = "Діяти згідно зі стандартом сервісу та звернутися до адміністратора."

    doc.add_heading("5. Часті запитання (FAQ)", level=1)
    doc.add_paragraph("Питання: Що робити у спірній ситуації?")
    doc.add_paragraph("Відповідь: Вкажіть конкретну відповідь або відповідального.")

    stream = io.BytesIO()
    doc.save(stream)
    stream.seek(0)
    return stream


def extract_text_from_docx_bytes(file_bytes: bytes) -> str:
    """
    Витягує чистий текст із .docx файлу (усі абзаци та рядки таблиць у порядку слідування)
    для подальшого розбиття на чанки та пошуку ШІ.
    """
    if not file_bytes:
        raise ValueError("Файл порожній.")

    try:
        document = docx.Document(io.BytesIO(file_bytes))
    except Exception as exc:
        raise ValueError(f"Не вдалося прочитати .docx файл: {exc}") from exc

    blocks: list[str] = []
    body = document.element.body
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            para = Paragraph(child, document)
            txt = (para.text or "").strip()
            if txt:
                blocks.append(txt)
        elif isinstance(child, CT_Tbl):
            tbl = Table(child, document)
            for row in tbl.rows:
                row_cells = [re.sub(r"\s+", " ", (c.text or "").strip()) for c in row.cells]
                # Прибираємо дублікати від об'єднаних сусідніх клітинок
                unique_cells: list[str] = []
                for val in row_cells:
                    if val and (not unique_cells or unique_cells[-1] != val):
                        unique_cells.append(val)
                if unique_cells:
                    blocks.append(" | ".join(unique_cells))

    # Також перевіряємо текст у колонтитулах не потрібно, бо це декорація;
    # але якщо body дав 0 блоків, перевіримо document.paragraphs як fallback
    if not blocks:
        for p in document.paragraphs:
            txt = (p.text or "").strip()
            if txt:
                blocks.append(txt)

    extracted = "\n\n".join(blocks).strip()
    if not extracted:
        raise ValueError("Документ не містить текстового вмісту.")
    return extracted
