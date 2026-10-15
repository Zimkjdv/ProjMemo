"""Real PDF parsing, rasterization and glyph geometry, deliberately not a visual oracle."""

from io import BytesIO
from contextlib import closing

from pypdf import PdfReader
import pypdfium2 as pdfium
from reportlab.lib.units import mm


def audit_pdf(content, output=None):
    assert content.startswith(b"%PDF-")
    reader = PdfReader(BytesIO(content), strict=True)
    assert not reader.is_encrypted
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert "\ufffd" not in text and "\x00" not in text
    assert not any(ord(char) == 127 or ord(char) < 32 and char not in "\r\n\t" for char in text)
    pages = []
    with pdfium.PdfDocument(content) as document:
        assert len(document) == len(reader.pages)
        for index, page in enumerate(document):
            try:
                width, height = page.get_size()
                with closing(page.get_textpage()) as textpage:
                    for char_index in range(textpage.count_chars()):
                        if textpage.get_text_range(char_index, 1).isspace():
                            continue
                        left, bottom, right, top = textpage.get_charbox(char_index)
                        if right <= left or top <= bottom:
                            continue
                        assert left >= 18 * mm - 1 and right <= width - 18 * mm + 1, (index + 1, left, right)
                        assert bottom >= 8 * mm and top <= height - 8 * mm, (index + 1, bottom, top)
                bitmap = page.render(scale=1.25)
                try:
                    image = bitmap.to_pil()
                    extrema = image.convert("L").getextrema()
                    assert extrema[0] < 100 and extrema[1] == 255  # Not blank or wholly black.
                    if output:
                        image.save(output / f"page-{index+1:03}.png")
                finally:
                    bitmap.close()
                pages.append(dict(number=index+1, width=width, height=height))
            finally:
                page.close()
    return text, pages
