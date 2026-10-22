from taxrag.models import Block
from taxrag.parse.pdf import _classify


def _b(text, size=10.0, bold=False, italic=False):
    return Block(page=1, text=text, font_size=size, bold=bold, italic=italic)


def test_marker_attaches_to_paragraph_not_heading():
    blocks = [
        _b("Enter the total of your wages. " * 5),
        _b("CAUTION!", size=5.4, bold=True),
        _b("Line 1a", size=14.0, bold=True),
        _b("If you received a pension from a nonqualified plan do not include it here.", italic=True),
        _b("Total Amount From Form(s) W-2, Box 1", size=12.0, bold=True),
        _b("• Dividends you received as a nominee."),
    ]
    _classify(blocks)
    kinds = [b.kind for b in blocks]
    assert kinds == ["para", "line_heading", "caution", "heading", "bullet"]
    assert blocks[1].line_ref == "1a" and blocks[3].level == 2
