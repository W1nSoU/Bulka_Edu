from __future__ import annotations

import io
import re
import zipfile
from typing import Optional
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as xml_escape

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _w(tag: str) -> str:
    return f"{{{WORD_NS}}}{tag}"


def sanitize_instruction_filename(topic_title: Optional[str], inst_id: Optional[int] = None) -> str:
    """Формує безпечну назву .docx файлу інструкції на основі назви теми."""
    raw = (topic_title or "").strip()
    cleaned = re.sub(r'[\\/*?:"<>|\r\n\t]+', "", raw)
    cleaned = re.sub(r"[^\w\s\-'.а-яА-ЯіїєґІЇЄҐ]", "", cleaned, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._ ")
    if not cleaned:
        cleaned = f"instruction_{inst_id or 'doc'}"
    return f"{cleaned[:80]}.docx"


def _build_template_sections(topic_title: Optional[str] = None) -> dict:
    title_label = (topic_title or "").strip() or "[Вкажіть назву теми]"
    return {
        "title": f"ІНСТРУКЦІЯ BULKA: {title_label}",
        "intro": (
            "Цей шаблон створено для стандартизованого оформлення корпоративних інструкцій "
            "мережі BULKA. Заповніть розділи нижче — система автоматично проіндексує весь текст "
            "та таблиці для пошуку через ШІ-радника."
        ),
        "sections": [
            (
                "1. Загальні положення та призначення",
                [
                    (
                        None,
                        "Коротко опишіть, кого стосується ця інструкція, коли вона застосовується та яка її головна мета.",
                    )
                ],
            ),
            (
                "2. Основні правила та стандарти",
                [
                    ("List Bullet", "Ключове правило або обов'язкова вимога №1."),
                    ("List Bullet", "Ключове правило або обов'язкова вимога №2."),
                    ("List Bullet", "Винятки або особливі умови."),
                ],
            ),
            (
                "3. Покроковий алгоритм дій",
                [
                    ("List Number", "Крок 1: Підготовка / перевірка вихідних даних."),
                    ("List Number", "Крок 2: Виконання основної процедури."),
                    ("List Number", "Крок 3: Контроль результату / звітність."),
                ],
            ),
        ],
        "table_heading": "4. Важливі застереження та типові помилки",
        "table_rows": [
            ("Ситуація / Проблема", "Правильна дія співробітника"),
            (
                "Приклад: виявлено невідповідність або брак",
                "Зафіксувати фото, повідомити керівника магазину та оформити акт.",
            ),
            (
                "Приклад: нестандартне звернення клієнта",
                "Діяти згідно зі стандартом сервісу та звернутися до адміністратора.",
            ),
        ],
        "faq_heading": "5. Часті запитання (FAQ)",
        "faq_paragraphs": [
            "Питання: Що робити у спірній ситуації?",
            "Відповідь: Вкажіть конкретну відповідь або відповідального.",
        ],
    }


def _generate_instruction_template_docx_stdlib(topic_title: Optional[str] = None) -> io.BytesIO:
    """Генерує валідний .docx файл без зовнішніх бібліотек через zipfile + XML."""
    data = _build_template_sections(topic_title)

    def _p_xml(text: str, style_id: Optional[str] = None, italic: bool = False) -> str:
        ppr = f'<w:pPr><w:pStyle w:val="{xml_escape(style_id)}"/></w:pPr>' if style_id else ""
        rpr = "<w:rPr><w:i/></w:rPr>" if italic else ""
        return f'<w:p>{ppr}<w:r>{rpr}<w:t xml:space="preserve">{xml_escape(text)}</w:t></w:r></w:p>'

    body_parts: list[str] = [
        _p_xml(data["title"], style_id="Title"),
        _p_xml(data["intro"], italic=True),
    ]
    for heading, paras in data["sections"]:
        body_parts.append(_p_xml(heading, style_id="Heading1"))
        for style_name, txt in paras:
            prefix = "• " if style_name == "List Bullet" else ""
            body_parts.append(_p_xml(f"{prefix}{txt}"))

    body_parts.append(_p_xml(data["table_heading"], style_id="Heading1"))
    rows_xml: list[str] = []
    for c0, c1 in data["table_rows"]:
        rows_xml.append(
            "<w:tr>"
            f"<w:tc>{_p_xml(c0)}</w:tc>"
            f"<w:tc>{_p_xml(c1)}</w:tc>"
            "</w:tr>"
        )
    body_parts.append(
        "<w:tbl>"
        "<w:tblPr>"
        '<w:tblBorders>'
        '<w:top w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        '<w:left w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        '<w:right w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        '</w:tblBorders>'
        "</w:tblPr>"
        '<w:tblGrid><w:gridCol w:w="4500"/><w:gridCol w:w="4500"/></w:tblGrid>'
        + "".join(rows_xml)
        + "</w:tbl>"
    )

    body_parts.append(_p_xml(data["faq_heading"], style_id="Heading1"))
    for p_txt in data["faq_paragraphs"]:
        body_parts.append(_p_xml(p_txt))

    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{WORD_NS}">'
        "<w:body>"
        + "".join(body_parts)
        + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>'
        "</w:body>"
        "</w:document>"
    )

    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )

    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )

    doc_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
        "</Relationships>"
    )

    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:styles xmlns:w="{WORD_NS}">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/>'
        '<w:rPr><w:b/><w:sz w:val="36"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>'
        '<w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>'
        "</w:styles>"
    )

    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml.encode("utf-8"))
        zf.writestr("_rels/.rels", rels_xml.encode("utf-8"))
        zf.writestr("word/_rels/document.xml.rels", doc_rels_xml.encode("utf-8"))
        zf.writestr("word/styles.xml", styles_xml.encode("utf-8"))
        zf.writestr("word/document.xml", document_xml.encode("utf-8"))
    stream.seek(0)
    return stream


def generate_instruction_template_docx(topic_title: Optional[str] = None) -> io.BytesIO:
    """
    Генерує структурований Word-шаблон (.docx) інструкції BULKA
    для заповнення адміністратором та подальшої індексації в ШІ.
    """
    try:
        import docx
    except ImportError:
        return _generate_instruction_template_docx_stdlib(topic_title)

    data = _build_template_sections(topic_title)
    doc = docx.Document()

    doc.add_heading(data["title"], level=0)
    intro = doc.add_paragraph(data["intro"])
    intro.italic = True

    for heading, paras in data["sections"]:
        doc.add_heading(heading, level=1)
        for style_name, txt in paras:
            doc.add_paragraph(txt, style=style_name)

    doc.add_heading(data["table_heading"], level=1)
    table = doc.add_table(rows=len(data["table_rows"]), cols=2)
    table.style = "Table Grid"
    for r_idx, (c0, c1) in enumerate(data["table_rows"]):
        table.rows[r_idx].cells[0].text = c0
        table.rows[r_idx].cells[1].text = c1

    doc.add_heading(data["faq_heading"], level=1)
    for p_txt in data["faq_paragraphs"]:
        doc.add_paragraph(p_txt)

    stream = io.BytesIO()
    doc.save(stream)
    stream.seek(0)
    return stream


def _extract_paragraph_text_xml(p_elem: ET.Element) -> str:
    parts: list[str] = []
    t_tag = _w("t")
    tab_tag = _w("tab")
    br_tag = _w("br")
    cr_tag = _w("cr")
    for node in p_elem.iter():
        if node.tag == t_tag and node.text:
            parts.append(node.text)
        elif node.tag == tab_tag:
            parts.append("\t")
        elif node.tag in (br_tag, cr_tag):
            parts.append("\n")
    return "".join(parts).strip()


def _extract_text_from_docx_bytes_stdlib(file_bytes: bytes) -> str:
    """Витягує текст із .docx через стандартні zipfile + ElementTree (без python-docx)."""
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            xml_bytes = zf.read("word/document.xml")
    except Exception as exc:
        raise ValueError(f"Не вдалося прочитати .docx файл: {exc}") from exc

    try:
        root = ET.fromstring(xml_bytes)
    except Exception as exc:
        raise ValueError(f"Не вдалося прочитати .docx файл: {exc}") from exc

    p_tag = _w("p")
    tbl_tag = _w("tbl")
    tr_tag = _w("tr")
    tc_tag = _w("tc")
    body = root.find(_w("body"))

    blocks: list[str] = []
    if body is not None:
        for child in body:
            if child.tag == p_tag:
                txt = _extract_paragraph_text_xml(child)
                if txt:
                    blocks.append(txt)
            elif child.tag == tbl_tag:
                for row in child.findall(tr_tag):
                    row_cells: list[str] = []
                    for cell in row.findall(tc_tag):
                        cell_paras = [
                            _extract_paragraph_text_xml(p)
                            for p in cell.findall(f".//{p_tag}")
                        ]
                        cell_txt = re.sub(
                            r"\s+",
                            " ",
                            " ".join(p for p in cell_paras if p).strip(),
                        )
                        row_cells.append(cell_txt)
                    unique_cells: list[str] = []
                    for val in row_cells:
                        if val and (not unique_cells or unique_cells[-1] != val):
                            unique_cells.append(val)
                    if unique_cells:
                        blocks.append(" | ".join(unique_cells))

    if not blocks:
        for p in root.findall(f".//{p_tag}"):
            txt = _extract_paragraph_text_xml(p)
            if txt:
                blocks.append(txt)

    extracted = "\n\n".join(blocks).strip()
    if not extracted:
        raise ValueError("Документ не містить текстового вмісту.")
    return extracted


def extract_text_from_docx_bytes(file_bytes: bytes) -> str:
    """
    Витягує чистий текст із .docx файлу (усі абзаци та рядки таблиць у порядку слідування)
    для подальшого розбиття на чанки та пошуку ШІ.
    """
    if not file_bytes:
        raise ValueError("Файл порожній.")

    try:
        import docx
        from docx.oxml.table import CT_Tbl
        from docx.oxml.text.paragraph import CT_P
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError:
        return _extract_text_from_docx_bytes_stdlib(file_bytes)

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
                unique_cells: list[str] = []
                for val in row_cells:
                    if val and (not unique_cells or unique_cells[-1] != val):
                        unique_cells.append(val)
                if unique_cells:
                    blocks.append(" | ".join(unique_cells))

    if not blocks:
        for p in document.paragraphs:
            txt = (p.text or "").strip()
            if txt:
                blocks.append(txt)

    extracted = "\n\n".join(blocks).strip()
    if not extracted:
        raise ValueError("Документ не містить текстового вмісту.")
    return extracted
