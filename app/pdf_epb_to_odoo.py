"""
EPB Installatievoorstel → Odoo Sales import
Gebaseerd op ChatGPT's legende-matching code
"""
import re
import unicodedata
from typing import List, Tuple, Dict
from io import BytesIO
import logging

import pdfplumber
from openpyxl import Workbook

# Configure logging
logger = logging.getLogger(__name__)

# Default Belgian VAT rate for EPB items (can be overridden)
DEFAULT_EPB_TAX_PERCENT = 21

def normalize_text(s: str) -> str:
    """Normaliseer tekst voor betere matching."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s.lower()

def parse_legend_blocks(text: str) -> List[str]:
    """Zoek sectie 'Legende' en pak regels tot volgende sectie."""
    txt = text
    m = re.search(r"(^|\n)\s*legende\s*[:\n]", txt, flags=re.IGNORECASE)
    if not m:
        return []
    
    start = m.end()
    segment = txt[start:]
    
    # Stop bij volgende sectie
    stop_match = re.search(
        r"\n\s*(bijlage|appendix|notes?|opmerkingen|specificaties|schema|totaal|subtotaal)\s*\n",
        segment,
        flags=re.IGNORECASE
    )
    if stop_match:
        segment = segment[:stop_match.start()]
    
    # Splitsen en filteren
    lines = [normalize_text(l) for l in segment.splitlines()]
    lines = [l for l in lines if l and not l.startswith("pagina ") and len(l) >= 2]
    
    # Items herkennen
    item_like = []
    for l in lines:
        if re.search(r"^[•\-\*\d]+[\)\.\-\s]", l) or re.search(r"[a-z0-9]{2,}", l):
            l2 = re.sub(r"^(•|\-|\*|\d+[\)\.\-\s])+", "", l).strip()
            if l2:
                item_like.append(l2)
    
    # Deduplicatie
    seen = set()
    unique_items = []
    for l in item_like:
        if l not in seen:
            seen.add(l)
            unique_items.append(l)
    
    return unique_items

def extract_qty(item: str) -> Tuple[str, int]:
    """Haal aantal uit een item-regel. Retourneert (clean_text, qty)."""
    qty = 1
    s = item
    patterns = [
        r"\b(\d+)\s*[x×]\b",
        r"\b[x×]\s*(\d+)\b",
        r"\bqty\s*(\d+)\b",
        r"\((\d+)\s*(st|pcs|stuks?)\)",
        r"[-–]\s*(\d+)\b$",
        r"\b(\d+)\s*(st|pcs|stuks?)\b",
    ]
    for pat in patterns:
        m = re.search(pat, s, flags=re.IGNORECASE)
        if m:
            try:
                qty = int(m.group(1))
                s = (s[:m.start()] + s[m.end():]).strip(' -–,;')
                break
            except Exception:
                pass
    return s.strip(), max(1, qty)

def epb_pdf_to_xlsx(pdf_bytes: bytes) -> BytesIO:
    """
    Converteer EPB/installatievoorstel PDF naar XLSX met legende items.
    """
    xlsx_file, _ = epb_pdf_to_xlsx_and_data(pdf_bytes)
    return xlsx_file


def epb_pdf_to_xlsx_and_data(pdf_bytes: bytes) -> Tuple[BytesIO, List[Dict]]:
    """
    Converteer EPB/installatievoorstel PDF naar XLSX met legende items en gestructureerde data.
    
    Returns:
        Tuple[BytesIO, List[Dict]]: XLSX file en lijst van orderregels
    """
    # Extract text
    full_text = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            full_text.append(t)
    
    # Extract legende items
    legend_items_raw: List[str] = []
    for chunk in full_text:
        legend_items_raw.extend(parse_legend_blocks(chunk))
    
    # Fallback: als geen legende gevonden, gebruik alle lijnen
    if not legend_items_raw:
        print("DEBUG: Geen legende sectie gevonden, gebruik alle regels")
        for t in full_text:
            lines = [normalize_text(l) for l in t.splitlines() if l.strip()]
            legend_items_raw.extend(lines)
        legend_items_raw = list(dict.fromkeys(legend_items_raw))
    
    # Extract qty
    legend_items: List[Tuple[str, int]] = [extract_qty(it) for it in legend_items_raw]
    
    print(f"DEBUG: Gevonden {len(legend_items)} legende items")
    
    # Bouw XLSX
    wb = Workbook()
    ws = wb.active
    ws.title = "EPB Items"
    
    ws.append([
        "Item Beschrijving",
        "Aantal",
        "Opmerkingen"
    ])
    
    # Prepare structured data for Odoo import
    lines_data = []
    
    for description, qty in legend_items:
        ws.append([
            description,
            qty,
            "Te matchen met product"
        ])
        
        # Add to structured data (no product_code for EPB items, no price)
        lines_data.append({
            "product_code": "",  # EPB items don't have product codes
            "description": description,
            "quantity": qty,
            "unit_price": 0.0,  # No price information in EPB PDFs
            "tax_percent": DEFAULT_EPB_TAX_PERCENT
        })
    
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    print(f"DEBUG: EPB XLSX gegenereerd met {len(legend_items)} items")
    return output, lines_data
