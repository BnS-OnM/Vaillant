"""
Detecteer type PDF: FACQ offerte of EPB installatievoorstel
"""
import pdfplumber
from io import BytesIO
from enum import Enum

class PDFType(Enum):
    FACQ_OFFERTE = "facq_offerte"
    EPB_VOORSTEL = "epb_voorstel"
    UNKNOWN = "unknown"

def detect_pdf_type(pdf_bytes: bytes) -> PDFType:
    """
    Detecteer welk type PDF dit is o.b.v. content.
    
    FACQ Offerte kenmerken:
    - Bevat vaak: "FACQ", artikelnummers (5-6 cijfers), prijzen, hoeveelheden
    - Tabelvorm met kolommen
    
    EPB Voorstel kenmerken:
    - Bevat: "legende", "installatievoorstel", "EPB"
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
                return PDFType.UNKNOWN
            
            # EPB indicators
            epb_indicators = ["legende", "installatievoorstel", "epb", "energieprestatie"]
            epb_score = sum(1 for indicator in epb_indicators if indicator in text)
            
            # FACQ indicators
            facq_indicators = ["facq", "artikelnr", "eenheidsprijs", "btw"]
            facq_score = sum(1 for indicator in facq_indicators if indicator in text)
            
            # Check voor tabelvorm (veel getallen + prijzen)
            import re
            price_patterns = len(re.findall(r'\d+[.,]\d{2}', text))
            article_patterns = len(re.findall(r'\b\d{5,6}\b', text))
            
            print(f"DEBUG: EPB score={epb_score}, FACQ score={facq_score}, prices={price_patterns}, articles={article_patterns}")
            
            # Beslissingslogica
            if epb_score >= 2:
                return PDFType.EPB_VOORSTEL
            elif facq_score >= 2 or (price_patterns > 10 and article_patterns > 5):
                return PDFType.FACQ_OFFERTE
            else:
                # Heuristiek: als veel nummers/prijzen → FACQ, anders EPB
                if price_patterns > 5:
                    return PDFType.FACQ_OFFERTE
                else:
                    return PDFType.EPB_VOORSTEL
                    
    except Exception as e:
        print(f"Error detecting PDF type: {e}")
        return PDFType.UNKNOWN