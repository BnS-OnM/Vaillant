import pdfplumber
from openpyxl import Workbook
import re
from io import BytesIO
from typing import Tuple, List, Dict, Any

ARTICLE_REGEX = re.compile(
    r"^(\*?\d{5,6})\s+(\d+)\s+(.*?)\s+([\d,.]+)\s+([\d,.]+)$"
)

# Regex voor legende producten (alleen artikelnummer en omschrijving)
LEGEND_PRODUCT_REGEX = re.compile(
    r"^(\*?\d{5,6})\s+(.+)$"
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

def is_valid_product_line(line: str) -> bool:
    """
    Controleer of een regel een geldige productlijn is.
    Filtert tussenregels zoals headers, totalen, subtitels, etc.
    """
    line_lower = line.lower()
    
    # Skip lege regels
    if not line.strip():
        return False
    
    # Skip bekende tussenregels
    skip_patterns = [
        "taks recupel",
        "totaal",
        "subtotaal",
        "bedrag",
        "korting",
        "levering",
        "verzending",
        "btw",
        "inclusief",
        "exclusief",
    ]
    
    for pattern in skip_patterns:
        if pattern in line_lower:
            return False
    
    # Skip regels die beginnen met bepaalde prefixes
    if line.startswith(("OPTIE", "VARIANTE", "Pagina", "Datum", "Klant")):
        return False
    
    return True

def extract_legend_products(text: str) -> List[str]:
    """
    Extract producten uit de legende sectie van de PDF.
    Zoekt naar sectie met "legende" of "legenda" en haalt artikelnummers eruit.
    """
    legend_products = []
    lines = text.splitlines()
    in_legend_section = False
    
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        line_lower = line_stripped.lower()
        
        # Detecteer start van legende sectie
        if "legende" in line_lower or "legenda" in line_lower:
            in_legend_section = True
            continue
        
        # Stop met legende sectie bij bepaalde markers
        if in_legend_section:
            # Stop als we een nieuwe sectie tegenkomen
            if line_lower.startswith(("totaal", "subtotaal", "optie", "variante")):
                in_legend_section = False
                continue
            
            # Probeer artikelnummer te matchen in legende
            match = LEGEND_PRODUCT_REGEX.match(line_stripped)
            if match:
                artikel = match.group(1).replace("*", "")
                legend_products.append(artikel)
    
    return legend_products

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
    all_legend_products = []

    # Eerste pass: verzamel alle legende producten
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            
            legend_products = extract_legend_products(text)
            all_legend_products.extend(legend_products)

    # Tweede pass: match producten (inclusief legende producten)
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue

            for line in text.splitlines():
                line = line.strip()

                # Valideer of dit een geldige productlijn is
                if not is_valid_product_line(line):
                    continue

                match = ARTICLE_REGEX.match(line)
                if not match:
                    continue

                artikel, qty, desc, unit_price, amount = match.groups()
                artikel_clean = artikel.replace("*", "")
                
                # Extra check: als dit artikel in de legende staat, OF
                # als het een standaard productlijn is, dan opnemen
                # (Legende producten hebben prioriteit voor matching)
                
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
                    "tax_percent": 21,
                    "from_legend": artikel_clean in all_legend_products  # Markeer of het uit legende komt
                })

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output, lines_data
