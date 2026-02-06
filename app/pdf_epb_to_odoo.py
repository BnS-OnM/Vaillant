"""
EPB Installatievoorstel → Odoo Sales import
Gebaseerd op ChatGPT's legende-matching code
"""
import re
import unicodedata
from typing import List, Tuple, Dict, Optional
from io import BytesIO
import logging
from difflib import SequenceMatcher

import pdfplumber
from openpyxl import Workbook

# Configure logging
logger = logging.getLogger(__name__)

# Default Belgian VAT rate for EPB items (can be overridden)
DEFAULT_EPB_TAX_PERCENT = 21

# Minimum similarity threshold for fuzzy matching (0.0 to 1.0)
MIN_FUZZY_MATCH_THRESHOLD = 0.6

def normalize_text(s: str) -> str:
    """Normaliseer tekst voor betere matching."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s.lower()

def remove_designation_prefix(text: str) -> str:
    """
    Verwijder aanduiding prefix van productnaam (bijv. "1a", "2a", "3a").
    
    Voorbeelden:
    - "1a Warmtepomp" -> "Warmtepomp"
    - "2a Ventilatiesysteem" -> "Ventilatiesysteem"
    - "3a,4a Radiator" -> "Radiator"
    """
    # Pattern: cijfer gevolgd door letter(s), optioneel met komma en meer cijfer+letter combinaties
    # Voorbeelden: 1a, 2a, 3a, 1a,2a, 3a,4a
    pattern = r'^[\s]*(?:\d+[a-zA-Z]+[,\s]*)+[\s]*'
    cleaned = re.sub(pattern, '', text).strip()
    return cleaned

def calculate_similarity(text1: str, text2: str) -> float:
    """
    Bereken similariteit tussen twee teksten (0.0 - 1.0).
    Gebruikt SequenceMatcher voor fuzzy matching.
    """
    # Normaliseer beide teksten
    norm1 = normalize_text(text1)
    norm2 = normalize_text(text2)
    
    # Bereken exacte match
    if norm1 == norm2:
        return 1.0
    
    # Bereken sequentie similarity
    seq_similarity = SequenceMatcher(None, norm1, norm2).ratio()
    
    # Bereken ook word-based similarity (overeenkomstige woorden)
    words1 = set(norm1.split())
    words2 = set(norm2.split())
    
    if not words1 or not words2:
        return seq_similarity
    
    common_words = words1.intersection(words2)
    word_similarity = len(common_words) / max(len(words1), len(words2))
    
    # Gebruik het maximum van beide methodes
    return max(seq_similarity, word_similarity)

def parse_legend_blocks(text: str) -> List[str]:
    """
    Zoek sectie 'Legende' en pak regels met aanduiding prefix (bijv. 1a, 2a, 3a).
    Verwijder de aanduiding prefix van de productnamen.
    """
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
    
    # Items herkennen - Focus op regels met aanduiding prefix (cijfer + letter)
    item_like = []
    designation_pattern = re.compile(r'^\s*\d+[a-zA-Z]+')
    
    for l in lines:
        # Check of de regel begint met een aanduiding prefix (bijv. 1a, 2a, 3a)
        if designation_pattern.match(l):
            # Verwijder de aanduiding prefix
            cleaned = remove_designation_prefix(l)
            if cleaned and len(cleaned) >= 2:
                item_like.append(cleaned)
        # Fallback: herken ook andere list-achtige items als geen aanduiding gevonden
        elif re.search(r"^[•\-\*\d]+[\)\.\-\s]", l) or re.search(r"[a-z0-9]{2,}", l):
            l2 = re.sub(r"^(•|\-|\*|\d+[\)\.\-\s])+", "", l).strip()
            if l2 and len(l2) >= 2:
                item_like.append(l2)
    
    # Deduplicatie
    seen = set()
    unique_items = []
    for l in item_like:
        if l not in seen:
            seen.add(l)
            unique_items.append(l)
    
    logger.info(f"Parsed {len(unique_items)} items from legend (after removing designation prefixes)")
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
