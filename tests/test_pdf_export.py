from reportlab.lib.enums import TA_CENTER

from app.pdf_export import _styles


def test_pdf_center_style_uses_reportlab_alignment_constant() -> None:
    assert _styles("Helvetica")["center"].alignment == TA_CENTER
