from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

DEFAULT_PAGE_SIZE = 2000


def split_text(text: str, page_size: int = DEFAULT_PAGE_SIZE) -> list[str]:
    """
    Splits a long text into pages of a specified size, trying to preserve paragraphs and sentences.
    """
    if len(text) <= page_size:
        return [text]

    pages = []
    current_page = ""
    paragraphs = text.split('\n\n')

    for paragraph in paragraphs:
        if not paragraph:
            continue

        # If the whole paragraph is too big, split it by sentences.
        if len(paragraph) > page_size:
            sentences = paragraph.split('. ')
            for sentence in sentences:
                if len(current_page) + len(sentence) + 2 > page_size:
                    pages.append(current_page.strip())
                    current_page = ""
                current_page += sentence + '. '
            continue

        # If adding the next paragraph overflows the page
        if len(current_page) + len(paragraph) + 2 > page_size:
            pages.append(current_page.strip())
            current_page = ""

        current_page += paragraph + "\n\n"

    if current_page:
        pages.append(current_page.strip())

    return pages


