import pdfplumber
from openpyxl import Workbook
import re
from io import BytesIO
from typing import Tuple, List, Dict, Any

ARTICLE_REGEX = re.compile(
    r"^(\*?\d{5,6})\s+(\d+)\s+(.*?)\s+([\d,.]+)\s+([\d,.]+)$"
)

def parse_european_number(value: str) -> float:
    """
    Parse European number format to float.
    European format uses dots as thousand separators and commas as decimal separators.
    Examples: '1.808,86' -> 1808.86, '123,45' -> 123.45, '1234' -> 1234.0
    
    Raises:
        ValueError: If the input cannot be converted to a float
    """
    if not value or not isinstance(value, str):
        raise ValueError(f"Invalid input: expected non-empty string, got {type(value).__name__}")
    
    # Remove dots (thousand separators)
    value = value.replace(".", "")
    # Replace comma with dot (decimal separator)
    value = value.replace(",", ".")
    
    try:
        return float(value)
    except ValueError as e:
        raise ValueError(f"Cannot convert '{value}' to float: {e}") from e

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
                unit_price_float = parse_european_number(unit_price)
                amount_float = parse_european_number(amount)

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
