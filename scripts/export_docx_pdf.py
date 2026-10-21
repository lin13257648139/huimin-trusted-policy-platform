from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, PageBreak, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.platypus import Paragraph as PdfParagraph

GREEN = colors.HexColor("#075F50")
INK = colors.HexColor("#17342E")
MUTED = colors.HexColor("#66766F")
LINE = colors.HexColor("#D6E0DC")
PALE = colors.HexColor("#F6F9F7")


def _fonts() -> tuple[str, str]:
    regular = Path(r"C:\Windows\Fonts\simsun.ttc")
    bold = Path(r"C:\Windows\Fonts\simhei.ttf")
    pdfmetrics.registerFont(TTFont("CN", str(regular), subfontIndex=0))
    pdfmetrics.registerFont(TTFont("CN-Bold", str(bold)))
    return "CN", "CN-Bold"


def _styles() -> dict[str, ParagraphStyle]:
    regular, bold = _fonts()
    base = getSampleStyleSheet()
    return {
        "Normal": ParagraphStyle(
            "CN-Normal",
            parent=base["BodyText"],
            fontName=regular,
            fontSize=9.5,
            leading=15.5,
            textColor=INK,
            spaceAfter=5,
            alignment=TA_LEFT,
            wordWrap="CJK",
        ),
        "Title": ParagraphStyle(
            "CN-Title",
            parent=base["Title"],
            fontName=bold,
            fontSize=26,
            leading=36,
            textColor=GREEN,
            alignment=TA_CENTER,
            spaceBefore=1.4 * cm,
            spaceAfter=16,
            wordWrap="CJK",
        ),
        "Subtitle": ParagraphStyle(
            "CN-Subtitle",
            parent=base["BodyText"],
            fontName=regular,
            fontSize=12,
            leading=20,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceAfter=10,
            wordWrap="CJK",
        ),
        "Heading 1": ParagraphStyle(
            "CN-H1",
            parent=base["Heading1"],
            fontName=bold,
            fontSize=18,
            leading=26,
            textColor=INK,
            spaceBefore=10,
            spaceAfter=9,
            wordWrap="CJK",
        ),
        "Heading 2": ParagraphStyle(
            "CN-H2",
            parent=base["Heading2"],
            fontName=bold,
            fontSize=13,
            leading=20,
            textColor=GREEN,
            spaceBefore=8,
            spaceAfter=6,
            wordWrap="CJK",
        ),
        "Heading 3": ParagraphStyle(
            "CN-H3",
            parent=base["Heading3"],
            fontName=bold,
            fontSize=10.5,
            leading=17,
            textColor=INK,
            spaceBefore=5,
            spaceAfter=4,
            wordWrap="CJK",
        ),
        "Table": ParagraphStyle(
            "CN-Table",
            parent=base["BodyText"],
            fontName=regular,
            fontSize=8.2,
            leading=12.5,
            textColor=INK,
            wordWrap="CJK",
        ),
        "TableHead": ParagraphStyle(
            "CN-TableHead",
            parent=base["BodyText"],
            fontName=bold,
            fontSize=8.2,
            leading=12.5,
            textColor=colors.white,
            wordWrap="CJK",
        ),
    }


def _paragraph_text(paragraph: Paragraph) -> str:
    return "".join(node.text or "" for node in paragraph._p.xpath(".//w:t")).strip()


def _paragraph_images(paragraph: Paragraph) -> list[bytes]:
    images: list[bytes] = []
    for blip in paragraph._p.xpath(".//a:blip"):
        rel_id = blip.get(qn("r:embed"))
        if rel_id and rel_id in paragraph.part.related_parts:
            images.append(paragraph.part.related_parts[rel_id].blob)
    return images


def _image_flowable(blob: bytes) -> Image:
    image = Image(BytesIO(blob))
    max_width = 17.0 * cm
    max_height = 16.8 * cm
    scale = min(max_width / image.imageWidth, max_height / image.imageHeight, 1.0)
    image.drawWidth = image.imageWidth * scale
    image.drawHeight = image.imageHeight * scale
    image.hAlign = "CENTER"
    return image


def _pdf_table(table: DocxTable, styles: dict[str, ParagraphStyle]) -> Table:
    rows: list[list[PdfParagraph]] = []
    for row_index, row in enumerate(table.rows):
        style = styles["TableHead"] if row_index == 0 else styles["Table"]
        rows.append(
            [
                PdfParagraph(
                    "<br/>".join(part.strip() for part in cell.text.splitlines() if part.strip())
                    or " ",
                    style,
                )
                for cell in row.cells
            ]
        )
    columns = max((len(row) for row in rows), default=1)
    result = Table(rows, colWidths=[17.0 * cm / columns] * columns, repeatRows=1, hAlign="LEFT")
    result.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), GREEN),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.45, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
            ]
        )
    )
    return result


def export(input_path: Path, output_path: Path) -> None:
    document = Document(input_path)
    styles = _styles()
    story: list[object] = []
    for element in document.element.body.iterchildren():
        if element.tag == qn("w:p"):
            paragraph = Paragraph(element, document)
            text = _paragraph_text(paragraph)
            for blob in _paragraph_images(paragraph):
                story.extend([_image_flowable(blob), Spacer(1, 0.25 * cm)])
            if text:
                style_name = paragraph.style.name if paragraph.style is not None else "Normal"
                style = styles.get(style_name, styles["Normal"])
                story.append(PdfParagraph(text.replace("&", "&amp;"), style))
            if paragraph._p.xpath('.//w:br[@w:type="page"]'):
                story.append(PageBreak())
        elif element.tag == qn("w:tbl"):
            story.extend([_pdf_table(DocxTable(element, document), styles), Spacer(1, 0.28 * cm)])

    short_title = input_path.stem.split("-")[-1]

    def footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.line(2.0 * cm, 1.35 * cm, 19.0 * cm, 1.35 * cm)
        canvas.setFont("CN", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(2.0 * cm, 1.0 * cm, f"惠民智导 v2.0.0 · {short_title}")
        canvas.drawRightString(19.0 * cm, 1.0 * cm, str(doc.page))
        canvas.restoreState()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=2.0 * cm,
        rightMargin=2.0 * cm,
        topMargin=1.7 * cm,
        bottomMargin=1.7 * cm,
        title=short_title,
        author="策马奔腾队",
    )
    pdf.build(story, onFirstPage=footer, onLaterPages=footer)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render project DOCX to a self-contained PDF.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    export(args.input.resolve(), args.output.resolve())
    print(f"DOCX_PDF_OK {args.output.resolve()}")


if __name__ == "__main__":
    main()
