"""Printable report cards (PDF), drawn from the same data as the JSON report card.

One card per A4 page; a whole class prints as one document. Drafts carry a DRAFT watermark.
The bundled DejaVu font covers names in Yoruba, Igbo and other Latin scripts (ẹ, ọ, ṣ, ń...),
which the PDF standard fonts can't print.
"""

from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

FONTS = Path(__file__).parent / "fonts"
REGULAR, BOLD = "YapSans", "YapSans-Bold"
INK = colors.HexColor("#1f2933")
MUTED = colors.HexColor("#616e7c")
RULE = colors.HexColor("#cbd2d9")
SHADE = colors.HexColor("#f0f4f8")
MARGIN = 14 * mm
WIDTH = A4[0] - 2 * MARGIN


def _register_fonts():
    if REGULAR not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(REGULAR, FONTS / "DejaVuSansCondensed.ttf"))
        pdfmetrics.registerFont(TTFont(BOLD, FONTS / "DejaVuSansCondensed-Bold.ttf"))
        pdfmetrics.registerFontFamily(REGULAR, normal=REGULAR, bold=BOLD)


def _style(name, size=9, bold=False, color=INK, **extra):
    return ParagraphStyle(
        name,
        fontName=BOLD if bold else REGULAR,
        fontSize=size,
        leading=size * 1.3,
        textColor=color,
        **extra,
    )


TITLE = _style("title", 15, bold=True, alignment=TA_CENTER)
SUBTITLE = _style("subtitle", 10, color=MUTED, alignment=TA_CENTER)
HEADING = _style("heading", 10, bold=True, spaceBefore=4, spaceAfter=2)
BODY = _style("body", 9)
SMALL = _style("small", 7.5, color=MUTED)
CELL = _style("cell", 8)
CELL_BOLD = _style("cell-bold", 8, bold=True)
HEAD = _style("head", 7, bold=True, alignment=TA_CENTER)
HEAD_LEFT = _style("head-left", 7, bold=True)


def num(value):
    """12.00 -> "12", 12.50 -> "12.5", None -> "–"."""
    if value is None or value == "":
        return "–"
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return str(value)
    text = f"{number:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def ordinal(n):
    if n is None:
        return "–"
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def text(value, style=BODY):
    return Paragraph(escape(str(value or "")), style)


def _details(card):
    student = card["student"]
    rows = [
        ["Student", student["name"], "Class", card["classroom"]["name"]],
        [
            "Admission no.",
            student.get("admission_number") or "–",
            "Term",
            f"{card['term']['name']}, {card['session']}",
        ],
    ]
    if card.get("form_teacher"):
        rows.append(["Form teacher", card["form_teacher"], "", ""])
    data = [
        [text(a, SMALL), text(b, CELL_BOLD), text(c, SMALL), text(d, CELL_BOLD)]
        for a, b, c, d in rows
    ]
    table = Table(data, colWidths=[24 * mm, 66 * mm, 16 * mm, WIDTH - 106 * mm])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 0.5, RULE),
                ("BACKGROUND", (0, 0), (-1, -1), SHADE),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _subjects(card):
    subjects = card["subjects"]
    components = (
        [(s["component"], s.get("max_score")) for s in subjects[0]["scores"]] if subjects else []
    )
    show_position = card.get("show_position")
    use_gpa = card.get("use_gpa")
    head = ["Subject"]
    head += [f"{name}\n({num(top)})" if top is not None else name for name, top in components]
    head += ["Total", "Grade", "Remark"]
    if use_gpa:
        head.append("GP")
    if show_position:
        head.append("Pos.")
    head += ["Class\navg", "High", "Low"]

    rows = [
        [
            Paragraph(escape(h).replace("\n", "<br/>"), HEAD_LEFT if i == 0 else HEAD)
            for i, h in enumerate(head)
        ]
    ]
    for line in subjects:
        row = [text(line["subject"], CELL)]
        row += [num(s["value"]) for s in line["scores"]]
        row += [num(line["total"]), line["grade"] or "–", text(line["remark"], CELL)]
        if use_gpa:
            row.append(num(line.get("grade_point")))
        if show_position:
            row.append(ordinal(line.get("position")))
        row += [num(line["class_average"]), num(line["class_highest"]), num(line["class_lowest"])]
        rows.append(row)
    if len(rows) == 1:
        rows.append([text("No scores yet.", CELL)] + [""] * (len(head) - 1))

    remark = 22 * mm
    numbers = len(head) - 2  # every column but subject and remark
    # 12.5mm fits "Total", "Grade", "Project" unbroken; many components squeeze them so the
    # table still fits the page, keeping 32mm for subject names
    fixed = min(12.5 * mm, (WIDTH - remark - 32 * mm) / numbers)
    subject_width = WIDTH - remark - fixed * numbers
    widths = [subject_width] + [fixed] * len(components) + [fixed, fixed, remark]
    widths += [fixed] * (len(head) - len(widths))
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), REGULAR, 8),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND", (0, 0), (-1, 0), SHADE),
                ("GRID", (0, 0), (-1, -1), 0.4, RULE),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafbfc")]),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _summary(card):
    summary = card["summary"]
    cells = [
        ("Subjects", str(summary.get("subjects_count") or 0)),
        ("Total", num(summary.get("total"))),
        ("Average", num(summary.get("average"))),
    ]
    if card.get("use_gpa"):
        cells.append(("GPA", num(summary.get("gpa"))))
    if card.get("show_position") and summary.get("position"):
        cells.append(("Position", f"{ordinal(summary['position'])} of {summary.get('out_of')}"))
    attendance = card.get("attendance")
    if attendance:
        cells.append(("Days present", f"{attendance['present']} / {attendance['days_open']}"))
    data = [
        [text(label, SMALL) for label, _ in cells],
        [text(value, _style("big", 11 if len(cells) < 6 else 10, bold=True)) for _, value in cells],
    ]
    table = Table(data, colWidths=[WIDTH / len(cells)] * len(cells))
    table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.5, RULE),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _comments(card):
    comments = card.get("comments") or {}
    parts = []
    for label, key in (
        ("Form teacher's comment", "form_teacher"),
        ("Principal's comment", "principal"),
    ):
        parts.append(text(label, HEADING))
        parts.append(text(comments.get(key) or "–"))
    return KeepTogether(parts)


def _scale(card):
    scale = card.get("grading_scale") or []
    if not scale:
        return Spacer(0, 0)
    bits = [
        (
            f"{band['label']} ≥ {num(band['min_score'])}"
            + (f" {band['remark']}" if band.get("remark") else "")
        ).replace(" ", "\u00a0")  # a band never breaks across lines
        for band in scale
    ]
    return text("Grades: " + " · ".join(bits), SMALL)


def _footer(card):
    if card.get("published") and card.get("published_at"):
        when = card["published_at"]
        when = when.strftime("%-d %B %Y") if hasattr(when, "strftime") else str(when)[:10]
        return text(f"Published on {when}.", SMALL)
    return text("Draft: not published. Marks may still change.", SMALL)


def _signatures():
    line = "_" * 28
    data = [
        [text(line, SMALL), "", text(line, SMALL)],
        [
            text("Form teacher's signature", SMALL),
            "",
            text("Principal's signature and stamp", SMALL),
        ],
    ]
    table = Table(data, colWidths=[WIDTH * 0.4, WIDTH * 0.2, WIDTH * 0.4])
    table.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 1)]))
    return table


def card_story(card):
    return [
        text(card["school"]["name"], TITLE),
        text("Report card", SUBTITLE),
        Spacer(0, 5 * mm),
        _details(card),
        Spacer(0, 5 * mm),
        _subjects(card),
        Spacer(0, 4 * mm),
        _summary(card),
        Spacer(0, 3 * mm),
        _comments(card),
        Spacer(0, 4 * mm),
        _scale(card),
        Spacer(0, 2 * mm),
        _footer(card),
        Spacer(0, 16 * mm),
        _signatures(),
    ]


def _watermark(canvas, doc):
    if not getattr(doc, "draft", False):
        return
    canvas.saveState()
    canvas.setFont(BOLD, 90)
    canvas.setFillColor(colors.Color(0.85, 0.2, 0.2, alpha=0.12))
    canvas.translate(A4[0] / 2, A4[1] / 2)
    canvas.rotate(40)
    canvas.drawCentredString(0, 0, "DRAFT")
    canvas.restoreState()


def render(cards, title="Report cards"):
    """PDF bytes for ``cards`` (report card dicts), one per page."""
    _register_fonts()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=title,
        author="YAP",
    )
    doc.draft = any(not card.get("published") for card in cards)
    story = []
    for i, card in enumerate(cards):
        if i:
            story.append(PageBreak())
        story.extend(card_story(card))
    if not story:
        story.append(text("No report cards."))
    doc.build(story, onFirstPage=_watermark, onLaterPages=_watermark)
    return buffer.getvalue()


def filename(*parts):
    """A safe download name, e.g. "Ada Obi - First Term 2025-2026.pdf"."""
    name = " - ".join(p for p in parts if p).replace("/", "-")
    keep = "".join(c for c in name if c.isalnum() or c in " -_.,'()")
    return f"{keep.strip() or 'report-card'}.pdf"
