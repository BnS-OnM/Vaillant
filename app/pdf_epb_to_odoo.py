"""
EPB Installatievoorstel → Odoo Sales import
Gebaseerd op ChatGPT's legende-matching code
"""
import re
import unicodedata
from typing import List, Tuple, Dict, Optional
from io import BytesIO
import logging

import pdfplumber
from openpyxl import Workbook

# Configure logging
logger = logging.getLogger(__name__)

# Default Belgian VAT rate for EPB items (can be overridden)
DEFAULT_EPB_TAX_PERCENT = 21

# Regex pattern for number+letter indicators (e.g., 1a, 2a, 3a)
# Made more flexible to match optional codes
LEGEND_INDICATOR_PATTERN = r"^(\d+[a-z]+)[\s\.\)\-:,]+"

# Product-related keywords to identify valid legend items (English and Dutch)
PRODUCT_KEYWORDS = [
    # English
    'pump', 'valve', 'vessel', 'sensor', 'module', 'cylinder', 'heat', 'cooling',
    'circuit', 'expansion', 'safety', 'assembly', 'non-return', 'mixing', 'circulation',
    'heating', 'potable', 'water', 'domestic', 'hot', 'boiler', 'split', 'plus',
    'hydraulic', 'vaillant', 'arotherm', 'unistor', 'vrc', 'vr', 'vp', 'vw',
    # Dutch
    'pomp', 'klep', 'vat', 'sensor', 'module', 'cilinder', 'warmte', 'koeling',
    'circuit', 'expansie', 'veiligheid', 'mengklep', 'circulatie',
    'verwarming', 'drink', 'water', 'huishoudelijk', 'warm', 'ketel', 'split',
    'hydraulisch',
]

# Noise patterns to filter out (schema elements, coordinates, short codes)
NOISE_PATTERNS = [
    r'^[a-z]$',  # Single letters: a, b, c, etc.
    r'^\d{1,3}$',  # Short numbers: 1, 23, 032, etc.
    r'^\d+m$',  # Distance markers: 3m, 5m, etc.
    r'^(mod|bus|pe|rf|af|dhw|l1|l2|l3|s1|s2|s3)$',  # Technical abbreviations (exact match)
    r'^\d+v~?$',  # Voltage: 230v~, 12v, etc.
    r'^[\d\s]+$',  # Only digits and spaces: "1 2 1 2"
    r'^(bus\s+mod|mod\s+a|mod\s+bus)$',  # Bus/module combinations
    r'^[a-z]+\d+:\d+$',  # Codes with colons: vrc720:8
]

def normalize_text(s: str) -> str:
    """Normaliseer tekst voor betere matching."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s.lower()


def is_valid_legend_item(text: str) -> bool:
    """
    Filter ruis zoals schema-elementen, coördinaten, korte codes.
    
    Returns:
        True if the item is valid (product name), False if it's noise
    """
    if not text or len(text) < 3:
        return False
    
    # Check against noise patterns
    text_lower = text.lower().strip()
    for pattern in NOISE_PATTERNS:
        if re.match(pattern, text_lower, re.IGNORECASE):
            logger.debug(f"Filtered out noise (pattern match): '{text}'")
            return False
    
    # Filter out items that are just 1-2 letters followed by digits (but allow vr, vp, vw with digits)
    if re.match(r'^[a-z]{1,2}\d+$', text_lower) and not text_lower[:2] in ['vr', 'vp', 'vw']:
        logger.debug(f"Filtered out noise (short code): '{text}'")
        return False
    
    # Too short items are likely noise
    if len(text_lower) < 5:
        # Allow short items only if they contain product keywords or are Vaillant codes
        has_keyword = any(keyword in text_lower for keyword in PRODUCT_KEYWORDS)
        if not has_keyword:
            logger.debug(f"Filtered out noise (too short): '{text}'")
            return False
    
    # Items should have at least 2 words OR contain a product keyword
    words = text_lower.split()
    if len(words) >= 2:
        # For multi-word items, check that they're not generic descriptions
        # Filter out generic phrases like "additional information here"
        generic_words = ['additional', 'information', 'here', 'some', 'footer', 'text', 'page', 'document']
        if any(word in generic_words for word in words):
            # Only keep if it also has product keywords
            has_keyword = any(keyword in text_lower for keyword in PRODUCT_KEYWORDS)
            if not has_keyword:
                logger.debug(f"Filtered out noise (generic text): '{text}'")
                return False
        return True
    
    # Single word items must contain a product keyword
    has_keyword = any(keyword in text_lower for keyword in PRODUCT_KEYWORDS)
    if not has_keyword:
        logger.debug(f"Filtered out noise (single word, no keyword): '{text}'")
        return False
    
    return True

def parse_legend_blocks(text: str) -> List[str]:
    """
    Zoek sectie 'Legende' (Nederlands) of 'Legend' (Engels) en pak regels met 
    optionele nummer+letter indicator (1a, 2a, 3a, etc.) of standalone productnamen.
    Strip de indicator en behoud alleen de productnaam.
    """
    txt = text
    
    # Multi-language support: search for both "legend" and "legende"
    m = re.search(r"(^|\n)\s*(legend|legende)\s*[:\n]", txt, flags=re.IGNORECASE)
    if not m:
        return []
    
    # Detect language
    legend_keyword = m.group(2).lower()
    language = "English" if legend_keyword == "legend" else "Dutch"
    logger.info(f"Found 'legend' section in PDF (language: {language})")
    
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
    
    # Items herkennen met optionele nummer+letter indicator (1a, 2a, 3a, etc.)
    # Ook standalone productnamen zonder code
    item_like = []
    
    for l in lines:
        # Try to extract item with number+letter indicator
        match = re.match(LEGEND_INDICATOR_PATTERN, l, re.IGNORECASE)
        if match:
            # Strip de indicator en behoud de rest als productnaam
            product_name = l[match.end():].strip()
            if product_name and is_valid_legend_item(product_name):
                item_like.append(product_name)
                logger.debug(f"Extracted legend item with indicator '{match.group(1)}': {product_name}")
        else:
            # No indicator pattern found, check if the whole line is a valid product
            # This handles standalone product names without codes
            if is_valid_legend_item(l):
                item_like.append(l)
                logger.debug(f"Extracted standalone legend item: {l}")
    
    # Deduplicatie
    seen = set()
    unique_items = []
    for l in item_like:
        if l not in seen:
            seen.add(l)
            unique_items.append(l)
    
    logger.info(f"Final: {len(unique_items)} valid items extracted from legend")
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


def fuzzy_match_legend_items(
    legend_items: List[str],
    uid: int,
    threshold: float = 0.6
) -> List[Dict]:
    """
    Match legende items met Odoo productcatalogus via fuzzy matching.
    
    Args:
        legend_items: Lijst van rauwe items uit PDF
        uid: Odoo user ID voor database access
        threshold: Minimum similarity (0.0-1.0), default 0.6
    
    Returns:
        Lijst van matched items met product_id en confidence score
        Format: [{"description": str, "product_id": int|None, "confidence": float}, ...]
    """
    from app.odoo import fuzzy_search_product_by_name
    
    matched_items = []
    
    for item in legend_items:
        try:
            # Try fuzzy matching with Odoo catalog
            product_id = fuzzy_search_product_by_name(uid, item, threshold=threshold)
            
            if product_id:
                # Match found - we'll get the confidence from the logs
                # The fuzzy_search_product_by_name logs the similarity ratio
                matched_items.append({
                    "description": item,
                    "product_id": product_id,
                    "confidence": threshold,  # Minimum confidence (actual is >= this)
                })
                logger.info(f"Fuzzy match: '{item}' → product_id={product_id}")
            else:
                # No match found - keep as description-only
                matched_items.append({
                    "description": item,
                    "product_id": None,
                    "confidence": 0.0,
                })
                logger.debug(f"No match found for: '{item}'")
                
        except Exception as e:
            logger.error(f"Error fuzzy matching '{item}': {str(e)}")
            # On error, keep as description-only
            matched_items.append({
                "description": item,
                "product_id": None,
                "confidence": 0.0,
            })
    
    logger.info(f"Fuzzy matching complete: {sum(1 for m in matched_items if m['product_id'])} of {len(matched_items)} items matched")
    return matched_items

def epb_pdf_to_xlsx(pdf_bytes: bytes) -> BytesIO:
    """
    Converteer EPB/installatievoorstel PDF naar XLSX met legende items.
    Backward compatible version without uid parameter.
    """
    xlsx_file, _ = epb_pdf_to_xlsx_and_data(pdf_bytes, uid=None)
    return xlsx_file


def epb_pdf_to_xlsx_and_data(
    pdf_bytes: bytes,
    uid: Optional[int] = None
) -> Tuple[BytesIO, List[Dict]]:
    """
    Converteer EPB/installatievoorstel PDF naar XLSX met legende items en gestructureerde data.
    
    Args:
        pdf_bytes: PDF file bytes
        uid: Optional Odoo user ID for fuzzy matching with product catalog
    
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
    
    # Fallback: als geen legende gevonden, gebruik keyword extraction (not all lines)
    if not legend_items_raw:
        logger.warning("No legend section found, using keyword-based extraction")
        for t in full_text:
            lines = [normalize_text(l) for l in t.splitlines() if l.strip()]
            # Only keep lines that look like valid products
            for line in lines:
                if is_valid_legend_item(line):
                    legend_items_raw.append(line)
        legend_items_raw = list(dict.fromkeys(legend_items_raw))
        logger.info(f"Fallback extraction found {len(legend_items_raw)} potential items")
    
    # Extract qty from items
    legend_items: List[Tuple[str, int]] = [extract_qty(it) for it in legend_items_raw]
    
    logger.info(f"Extracted {len(legend_items)} legend items (before fuzzy matching)")
    
    # Fuzzy matching with Odoo catalog if uid is provided
    matched_items = []
    if uid is not None:
        logger.info("Fuzzy matching enabled (uid provided)")
        # Get just the descriptions for fuzzy matching
        descriptions = [desc for desc, qty in legend_items]
        matched_results = fuzzy_match_legend_items(descriptions, uid)
        
        # Combine with quantities
        for (desc, qty), match_result in zip(legend_items, matched_results):
            matched_items.append({
                "description": desc,
                "quantity": qty,
                "product_id": match_result.get("product_id"),
                "confidence": match_result.get("confidence", 0.0),
            })
    else:
        logger.info("Fuzzy matching disabled (no uid provided)")
        # No fuzzy matching - use descriptions as-is
        for desc, qty in legend_items:
            matched_items.append({
                "description": desc,
                "quantity": qty,
                "product_id": None,
                "confidence": 0.0,
            })
    
    # Bouw XLSX
    wb = Workbook()
    ws = wb.active
    ws.title = "EPB Items"
    
    # Add headers with optional Product ID and Match Confidence columns
    if uid is not None:
        ws.append([
            "Item Beschrijving",
            "Aantal",
            "Product ID",
            "Match Confidence",
            "Opmerkingen"
        ])
    else:
        ws.append([
            "Item Beschrijving",
            "Aantal",
            "Opmerkingen"
        ])
    
    # Prepare structured data for Odoo import
    lines_data = []
    
    for item in matched_items:
        description = item["description"]
        qty = item["quantity"]
        product_id = item.get("product_id")
        confidence = item.get("confidence", 0.0)
        
        # Add to XLSX
        if uid is not None:
            ws.append([
                description,
                qty,
                product_id or "",
                f"{confidence:.2f}" if confidence > 0 else "",
                "Matched" if product_id else "Te matchen met product"
            ])
        else:
            ws.append([
                description,
                qty,
                "Te matchen met product"
            ])
        
        # Add to structured data
        lines_data.append({
            "product_code": "",  # EPB items don't have product codes
            "description": description,
            "quantity": qty,
            "unit_price": 0.0,  # No price information in EPB PDFs
            "tax_percent": DEFAULT_EPB_TAX_PERCENT,
            "product_id": product_id,  # Include product_id if matched
        })
    
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    logger.info(f"EPB XLSX generated with {len(matched_items)} items")
    return output, lines_data
