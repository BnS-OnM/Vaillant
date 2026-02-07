"""
EPB/Vaillant Installatievoorstel → Odoo Sales import
Improved version with proper legend parsing, main component extraction, and catalog matching.
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

# Default Belgian VAT rate for EPB items
DEFAULT_EPB_TAX_PERCENT = 21


def normalize_text(s: str) -> str:
    """Normalize text: lowercase, non-alnum -> space, collapse whitespace."""
    if not s:
        return ""
    s = str(s).lower()
    # Remove accents
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("\xa0", " ")
    s = re.sub(r'[^a-z0-9]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def collapse_text(s: str) -> str:
    """Collapse text: remove all spaces, dots, dashes, underscores, slashes."""
    if not s:
        return ""
    s = str(s).lower()
    s = re.sub(r'[\s\.\-_/,]+', '', s)
    return s


def parse_legend_blocks(text: str) -> List[str]:
    """
    Parse Legend/Legende section from Vaillant PDF.
    
    Improvements:
    - Find "Legend"/"Legende" section
    - Stop at "Line Legend" or end of segment
    - Ignore indicator-only lines (1a, 2d, etc.)
    - Ignore headings (heat generators, storages, controls, etc.)
    - Extract actual items (pumps, valves, vessels, etc.)
    """
    txt = text
    
    # Find legend section
    m = re.search(r"(^|\n)\s*(legend|legende)\s*[:\n]", txt, flags=re.IGNORECASE)
    if not m:
        return []
    
    start = m.end()
    segment = txt[start:]
    
    # Stop at "Line Legend" or other end markers
    stop_patterns = [
        r"\n\s*line\s+legend\s*\n",
        r"\n\s*(bijlage|appendix|notes?|opmerkingen|specificaties|schema)\s*\n",
        r"\n\s*totaal\s*\n",
        r"\n\s*subtotaal\s*\n",
    ]
    for pattern in stop_patterns:
        stop_match = re.search(pattern, segment, flags=re.IGNORECASE)
        if stop_match:
            segment = segment[:stop_match.start()]
            break
    
    # Split into lines and normalize
    lines = segment.splitlines()
    
    # Headings to ignore (case-insensitive)
    ignore_headings = {
        'heat generators', 'heating generators', 'generator',
        'storages', 'storage',
        'controls', 'control',
        'hydraulical units', 'hydraulic units', 'hydraulic',
        'pumps', 'pump',
        'functional valves', 'functional valve', 'valves', 'valve',
        'safety units', 'safety unit', 'safety',
        'further armatures', 'armatures', 'armature',
        'sensors', 'sensor',
        'vr10',
        'line legend',
        'legend',
        'legende',
    }
    
    items = []
    for line in lines:
        line = line.strip()
        if not line or len(line) < 3:
            continue
        
        # Skip page markers
        if re.match(r'^pagina\s+\d+', line, re.IGNORECASE):
            continue
        
        # Skip indicator-only lines (1a, 2d, 3b, etc.)
        if re.match(r'^\d+[a-z]+$', line, re.IGNORECASE):
            continue
        
        # Clean up bullet points and numbering first
        cleaned = re.sub(r'^[•\-\*\d]+[a-z]?[\)\.\-\s]+', '', line).strip()
        if not cleaned:
            continue
        
        # Normalize and check if it's a heading to ignore
        normalized = normalize_text(cleaned)
        if normalized in ignore_headings:
            continue
        
        # Skip very short normalized text
        if len(normalized) < 5:
            continue
        
        # This looks like a real item
        items.append(cleaned)
    
    # Deduplicate while preserving order
    seen = set()
    unique_items = []
    for item in items:
        normalized = normalize_text(item)
        if normalized not in seen:
            seen.add(normalized)
            unique_items.append(item)
    
    logger.info(f"Extracted {len(unique_items)} legend items from text")
    return unique_items


def extract_main_components(full_text: str) -> List[str]:
    """
    Extract main Vaillant components from the entire PDF text.
    
    Searches for:
    - aroTHERM Split plus VWL 8.2 AS
    - Hydraulic module VWL 8.2 IS
    - uniSTOR VIH RW
    - VP RW 45/2 B
    - VRC720, VR71, VR940
    
    Handles variants without spaces/dots/commas (VWL8.2AS, VWL 8,2 AS, etc.)
    """
    components = []
    
    # Define patterns for main components
    # Check more specific patterns first to avoid duplicates
    patterns = [
        ("aroTHERM Split plus VWL 8.2 AS", r'arotherm\s+split\s+plus\s+vwl\s*8[\.,]?\s*2\s*as'),
        ("Hydraulic module VWL 8.2 IS", r'hydraulic\s+module\s+vwl\s*8[\.,]?\s*2\s*is'),
        ("uniSTOR VIH RW", r'unistor\s+vih\s*rw'),
        ("VP RW 45/2 B", r'vp\s*rw\s*45\s*/?\s*2\s*b'),
        ("VRC720", r'vrc\s*720'),
        ("VR71", r'vr\s*71'),
        ("VR940", r'vr\s*940'),
        ("VWL 8.2 AS", r'\bvwl\s*8[\.,]?\s*2\s*as\b'),
        ("VWL 8.2 IS", r'\bvwl\s*8[\.,]?\s*2\s*is\b'),
        ("VIH RW", r'\bvih\s*rw\b'),
    ]
    
    normalized_text = normalize_text(full_text)
    
    found = set()
    
    for display_name, pattern in patterns:
        if re.search(pattern, normalized_text, re.IGNORECASE):
            # Use normalized display name as key to avoid duplicates
            key = normalize_text(display_name)
            if key not in found:
                found.add(key)
                components.append(display_name)
    
    logger.info(f"Extracted {len(components)} main components from PDF")
    return components


def extract_qty(item: str) -> Tuple[str, int]:
    """
    Extract quantity from an item label. Returns (clean_text, qty).
    
    Patterns:
    - "2x Item" -> ("Item", 2)
    - "Item x2" -> ("Item", 2)
    - "Item qty 2" -> ("Item", 2)
    - "Item (2 st)" -> ("Item", 2)
    - "Item - 2" -> ("Item", 2)
    """
    qty = 1
    s = item
    
    patterns = [
        r'(\d+)\s*[x×]\s*',  # "2x Item"
        r'\s*[x×]\s*(\d+)',  # "Item x2"
        r'\bqty\s*(\d+)\b',  # "qty 2"
        r'\((\d+)\s*(st|pcs|stuks?)\)',  # "(2 st)"
        r'[-–]\s*(\d+)\s*$',  # "Item - 2"
        r'\b(\d+)\s*(st|pcs|stuks?)\b',  # "2 stuks"
    ]
    
    for pat in patterns:
        m = re.search(pat, s, flags=re.IGNORECASE)
        if m:
            try:
                qty = int(m.group(1))
                # Remove the matched part
                s = (s[:m.start()] + s[m.end():]).strip(' -–,;')
                break
            except (ValueError, IndexError):
                pass
    
    return s.strip(), max(1, qty)


def match_item(label: str, catalog: List[Dict]) -> Optional[Dict]:
    """
    Match a PDF item label to a product in the catalog.
    
    Strategy:
    A) Keyword/model code matching (strongest) with NL/EN synonyms
    B) Token overlap scoring as fallback
    
    Returns the best matching catalog entry or None.
    """
    if not catalog:
        return None
    
    # Normalize the label
    label_norm = normalize_text(label)
    label_collapse = collapse_text(label)
    
    # Keyword mapping for strong matches
    # Maps normalized search terms to keywords that should match
    keyword_map = {
        # Main components
        'vwl 8.2 as': ['vwl 8 2 as', 'vwl8 2as', 'vwl82as', 'arotherm split plus'],
        'vwl 8.2 is': ['vwl 8 2 is', 'vwl8 2is', 'vwl82is'],
        'hydraulic module': ['hydraulic module', 'hydraulische module', 'vwl 8 2 is'],
        'vih rw': ['vih rw', 'vihrw', 'unistor'],
        'vp rw 45/2 b': ['vp rw 45 2 b', 'vprw45 2b', 'vprw452b'],
        'vrc720': ['vrc720', 'vrc 720'],
        'vr71': ['vr71', 'vr 71'],
        'vr940': ['vr940', 'vr 940'],
        'vr10': ['vr10', 'vr 10'],
        
        # Legend items - synonyms NL/EN
        'mixing valve': ['mixing valve', 'mengklep', '3 port mixing valve', '3 port'],
        'mengklep': ['mengklep', 'mixing valve', '3 port mixing valve'],
        'non-return valve': ['non return valve', 'keerklep', 'non return'],
        'keerklep': ['keerklep', 'non return valve'],
        'circulation pump': ['circulation pump', 'circulatiepomp', 'circulatie pomp'],
        'circulatiepomp': ['circulatiepomp', 'circulation pump'],
        'heating circuit pump': ['heating circuit pump', 'heating pump', 'circuit pump', 'verwarmingspomp'],
        'cooling circuit pump': ['cooling circuit pump', 'cooling pump', 'koelpomp'],
        'expansion vessel': ['expansion vessel', 'expansievat', 'expansion'],
        'expansievat': ['expansievat', 'expansion vessel'],
        'safety assembly': ['safety assembly', 'veiligheidsgroep', 'safety group'],
        'veiligheidsgroep': ['veiligheidsgroep', 'safety assembly'],
        'sensor': ['sensor', 'vr10', 'temperature sensor'],
    }
    
    # A) Try keyword matching
    best_match = None
    best_score = 0
    
    for prod in catalog:
        prod_norm = prod['_search']
        prod_collapse = prod['_search_collapse']
        
        # Check if any keyword matches
        for key, synonyms in keyword_map.items():
            if key in label_norm or key in label_collapse:
                # Check if product contains any of the synonyms
                for syn in synonyms:
                    syn_collapse = collapse_text(syn)
                    if syn in prod_norm or syn_collapse in prod_collapse:
                        # Strong match found
                        return prod
        
        # Also check collapsed codes directly (for things like VWL8.2AS)
        if label_collapse and len(label_collapse) >= 4:
            if label_collapse in prod_collapse or prod_collapse in label_collapse:
                # Code match
                return prod
    
    # B) Fallback: token overlap scoring
    label_tokens = set(label_norm.split())
    if not label_tokens:
        return None
    
    for prod in catalog:
        prod_tokens = set(prod['_search'].split())
        if not prod_tokens:
            continue
        
        # Calculate Jaccard similarity
        intersection = label_tokens & prod_tokens
        union = label_tokens | prod_tokens
        
        if union:
            score = len(intersection) / len(union)
            
            # Boost score if there's a meaningful overlap (at least 2 chars in common)
            if intersection and score > 0:
                # Check for meaningful token matches (not just single letters)
                meaningful = any(len(token) >= 2 for token in intersection)
                if meaningful and score > best_score:
                    best_score = score
                    best_match = prod
    
    # Only return match if score is decent
    if best_score >= 0.2:  # At least 20% overlap
        return best_match
    
    return None


def epb_pdf_to_xlsx(pdf_bytes: bytes) -> BytesIO:
    """
    Convert EPB/Vaillant installatievoorstel PDF to XLSX.
    Legacy wrapper for backward compatibility.
    """
    xlsx_file, _ = epb_pdf_to_xlsx_and_data(pdf_bytes, [], "")
    return xlsx_file


def epb_pdf_to_xlsx_and_data(
    pdf_bytes: bytes,
    catalog: List[Dict] = None,
    partner_id: str = ""
) -> Tuple[BytesIO, List[Dict]]:
    """
    Convert EPB/Vaillant installatievoorstel PDF to Odoo Sales XLSX with catalog matching.
    
    Args:
        pdf_bytes: PDF file content
        catalog: Product catalog from /import-products (List[Dict] with _search fields)
        partner_id: Partner ID for the order (optional)
    
    Returns:
        Tuple[BytesIO, List[Dict]]: XLSX file and list of order lines
    """
    if catalog is None:
        catalog = []
    
    # Extract text from PDF
    full_text_parts = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            full_text_parts.append(t)
    
    full_text = "\n".join(full_text_parts)
    
    # Extract legend items
    legend_items_raw: List[str] = []
    for chunk in full_text_parts:
        legend_items_raw.extend(parse_legend_blocks(chunk))
    
    # Extract main components
    main_components = extract_main_components(full_text)
    
    # Combine: main components first, then legend items
    all_items_raw = main_components + legend_items_raw
    
    # Deduplicate by normalized text while preserving order
    seen_normalized = set()
    deduplicated_items = []
    for item in all_items_raw:
        normalized = normalize_text(item)
        if normalized and normalized not in seen_normalized:
            seen_normalized.add(normalized)
            deduplicated_items.append(item)
    
    logger.info(f"Total items after combining: {len(deduplicated_items)} (main components: {len(main_components)}, legend: {len(legend_items_raw)})")
    
    # Extract quantities
    items_with_qty: List[Tuple[str, int]] = [extract_qty(item) for item in deduplicated_items]
    
    # Match to catalog and build unique product list
    matched_products = {}  # key: product name, value: (product_dict, total_qty)
    unmatched_labels = []
    
    for label, qty in items_with_qty:
        matched = match_item(label, catalog)
        
        if matched:
            prod_name = matched['name']
            if prod_name in matched_products:
                # Add to existing quantity
                existing_prod, existing_qty = matched_products[prod_name]
                matched_products[prod_name] = (existing_prod, existing_qty + qty)
            else:
                matched_products[prod_name] = (matched, qty)
        else:
            unmatched_labels.append(label)
    
    logger.info(f"Matched {len(matched_products)} products from catalog")
    if unmatched_labels:
        logger.warning(f"Unmatched labels ({len(unmatched_labels)}): {unmatched_labels}")
    
    # Build XLSX for Odoo Sales import
    wb = Workbook()
    ws = wb.active
    ws.title = "Odoo Sales Import"
    
    # Column headers (EXACTLY as specified)
    headers = [
        "Orderreferentie",
        "Partner ID",
        "Product",
        "Product omschrijving",
        "Aantal",
        "Prijs"
    ]
    ws.append(headers)
    
    # Prepare structured data for Odoo import (backward compatibility)
    lines_data = []
    
    # Add rows
    first_row = True
    for prod_name, (prod, total_qty) in matched_products.items():
        row = [
            "GPT-001" if first_row else "",  # Orderreferentie only on first row
            partner_id if first_row else "",  # Partner ID only on first row
            prod['name'],
            prod['description'],
            total_qty,
            prod['list_price']
        ]
        ws.append(row)
        
        # Also add to lines_data for backward compatibility
        lines_data.append({
            "product_code": prod.get('default_code', ''),
            "description": prod['description'],
            "quantity": total_qty,
            "unit_price": prod['list_price'],
            "tax_percent": DEFAULT_EPB_TAX_PERCENT
        })
        
        first_row = False
    
    # Save workbook
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    logger.info(f"Generated Odoo Sales XLSX with {len(matched_products)} product lines")
    
    return output, lines_data
