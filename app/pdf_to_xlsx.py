import pdfplumber
from openpyxl import Workbook
import re
from io import BytesIO
from typing import Tuple, List, Dict, Any

ARTICLE_REGEX = re.compile(
    r"^(\*?\d{5,6})\s+(\d+)\s+(.*?)\s+([\d,.]+)\s+([\d,.]+)$"
)

def facq_pdf_to_xlsx(pdf_bytes: bytes) -> BytesIO:
    """Convert FACQ PDF to XLSX file only (backward compatible)"""
    xlsx_file, _ = facq_pdf_to_xlsx_and_data(pdf_bytes)
    return xlsx_file


def facq_pdf_to_xlsx_and_data(pdf_bytes: bytes) -> Tuple[BytesIO, List[Dict[str, Any]]]:
    """Convert FACQ PDF to XLSX file and structured data"""
    wb = Workbook()
    ws = wb.active
    ws.title = "FACQ"

    ws.append([
        "ArtikelNr",
        "Omschrijving",
        "Hoeveelheid",
        "Eenheid",
        "Eenheidsprijs",
        "Bedrag",
        "BTW"
    ])

    lines_data = []

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue

            for line in text.splitlines():
                line = line.strip()

                if (
                    not line
                    or "taks recupel" in line.lower()
                    or line.startswith(("OPTIE", "VARIANTE"))
                ):
                    continue

                match = ARTICLE_REGEX.match(line)
                if not match:
                    continue

                artikel, qty, desc, unit_price, amount = match.groups()

                artikel_clean = artikel.replace("*", "")
                desc_clean = desc.strip()
                qty_int = int(qty)
                unit_price_float = float(unit_price.replace(",", "."))
                amount_float = float(amount.replace(",", "."))

                ws.append([
                    artikel_clean,
                    desc_clean,
                    qty_int,
                    "st",
                    unit_price_float,
                    amount_float,
                    21
                ])

                lines_data.append({
                    "product_code": artikel_clean,
                    "description": desc_clean,
                    "quantity": qty_int,
                    "unit_price": unit_price_float,
                    "tax_percent": 21
                })

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output, lines_data
