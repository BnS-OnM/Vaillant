import pdfplumber
from openpyxl import Workbook
import re
from io import BytesIO

ARTICLE_REGEX = re.compile(
    r"^(\*?\d{5,6})\s+(\d+)\s+(.*?)\s+([\d,.]+)\s+([\d,.]+)$"
)

def facq_pdf_to_xlsx(pdf_bytes: bytes) -> BytesIO:
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

                ws.append([
                    artikel.replace("*", ""),
                    desc.strip(),
                    int(qty),
                    "st",
                    float(unit_price.replace(",", ".")),
                    float(amount.replace(",", ".")),
                    21
                ])

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output
