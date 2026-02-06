"""
Detecteer type PDF: FACQ offerte of Vaillant installatievoorstel
"""
import pdfplumber
from io import BytesIO
from enum import Enum
import logging

# Configure logging
logger = logging.getLogger(__name__)

class PDFType(Enum):
    FACQ_OFFERTE = "facq_offerte"
    VAILLANT_VOORSTEL = "vaillant_voorstel"
    UNKNOWN = "unknown"

def detect_pdf_type(pdf_bytes: bytes) -> PDFType:
    """
    Detecteer welk type PDF dit is o.b.v. content.
    
    FACQ Offerte kenmerken:
    - Bevat vaak: "FACQ", artikelnummers (5-6 cijfers), prijzen, hoeveelheden
    - Tabelvorm met kolommen
    
    Vaillant installatievoorstel kenmerken:
    - Bevat: "legende", "installatievoorstel", "vaillant"
    - Meer tekstueel/beschrijvend
    """
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            # Pak eerste 2 pagina's voor analyse
            text = ""
            for page in pdf.pages[:2]:
                t = page.extract_text()
                if t:
                    text += t.lower()
            
            if not text:
                logger.warning("PDF has no extractable text - returning UNKNOWN")
                return PDFType.UNKNOWN
            
            # Vaillant installatievoorstel indicators
            vaillant_indicators = ["legende", "installatievoorstel", "vaillant", "energieprestatie"]
            vaillant_score = sum(1 for indicator in vaillant_indicators if indicator in text)
            
            # FACQ indicators
            facq_indicators = ["facq", "artikelnr", "eenheidsprijs", "btw"]
            facq_score = sum(1 for indicator in facq_indicators if indicator in text)
            
            # Check voor tabelvorm (veel getallen + prijzen)
            import re
            price_patterns = len(re.findall(r'\d+[.,]\d{2}', text))
            article_patterns = len(re.findall(r'\b\d{5,6}\b', text))
            
            logger.info(f"PDF detection scores - Vaillant: {vaillant_score}, FACQ: {facq_score}, prices: {price_patterns}, articles: {article_patterns}")
            
            # Beslissingslogica
            if vaillant_score >= 2:
                logger.info(f"Detected as Vaillant installatievoorstel (score: {vaillant_score})")
                return PDFType.VAILLANT_VOORSTEL
            elif facq_score >= 2 or (price_patterns > 10 and article_patterns > 5):
                logger.info(f"Detected as FACQ offerte (FACQ score: {facq_score}, prices: {price_patterns}, articles: {article_patterns})")
                return PDFType.FACQ_OFFERTE
            else:
                # Heuristiek: als veel nummers/prijzen → FACQ, anders Vaillant installatievoorstel
                if price_patterns > 5:
                    logger.info(f"Detected as FACQ offerte based on price patterns ({price_patterns} prices found)")
                    return PDFType.FACQ_OFFERTE
                else:
                    logger.info(f"Detected as Vaillant installatievoorstel by default (insufficient indicators for FACQ)")
                    return PDFType.VAILLANT_VOORSTEL
                    
    except Exception as e:
        logger.error(f"Error detecting PDF type: {e}", exc_info=True)
        return PDFType.UNKNOWN