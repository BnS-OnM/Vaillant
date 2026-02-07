"""
Module for importing data from Excel files to Odoo.
Handles Product (product.template) and Sale Order (sale.order) Excel files.
"""
import openpyxl
from io import BytesIO
from typing import List, Dict, Any, Optional
import logging
import re

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Constants
DEFAULT_VAT_PERCENT = 21  # Default VAT rate for Belgium


def normalize_text(s: str) -> str:
    """Normalize text: lowercase, non-alnum -> space, collapse whitespace."""
    if not s:
        return ""
    s = str(s).lower()
    s = re.sub(r'[^a-z0-9]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def collapse_text(s: str) -> str:
    """Collapse text: remove all spaces, dots, dashes, underscores, slashes."""
    if not s:
        return ""
    s = str(s).lower()
    s = re.sub(r'[\s\.\-_/]+', '', s)
    return s


def build_catalog_from_products(products_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Build a searchable catalog from product data.
    
    Args:
        products_data: List of product dictionaries with fields like name, description, list_price, default_code
    
    Returns:
        List of catalog entries with normalized search fields:
        - name: product name
        - description: product description (fallback to name if not available)
        - list_price: price (default 0.0)
        - default_code: internal reference (default "")
        - _search: normalized "name description default_code" for matching
        - _search_collapse: collapsed version without spaces/dots/dashes for code matching
    """
    catalog = []
    
    for prod in products_data:
        # Extract fields with fallbacks
        name = str(prod.get('name', '')).strip()
        if not name:
            name = str(prod.get('default_code', 'Product')).strip()
        
        description = str(prod.get('description', '')).strip()
        if not description:
            description = name
        
        try:
            list_price = float(prod.get('list_price', 0.0))
        except (ValueError, TypeError):
            list_price = 0.0
        
        default_code = str(prod.get('default_code', '')).strip()
        
        # Build search fields
        search_parts = [name, description, default_code]
        search_text = ' '.join(p for p in search_parts if p)
        
        catalog_entry = {
            'name': name,
            'description': description,
            'list_price': list_price,
            'default_code': default_code,
            '_search': normalize_text(search_text),
            '_search_collapse': collapse_text(search_text)
        }
        
        catalog.append(catalog_entry)
    
    logger.info(f"Built catalog with {len(catalog)} entries")
    return catalog


def parse_product_xlsx(xlsx_bytes: bytes) -> List[Dict[str, Any]]:
    """
    Parse Product (product.template).xlsx file to extract product data.
    
    Flexible column detection:
    - name: name / Product / Naam (fallback: first column)
    - description: description / omschrijving / beschrijving (fallback: name)
    - list_price: list_price (prefer exact), or first column with "prijs"
    - default_code: default_code / internal reference / SKU / ArtikelNr (optional)
    
    Args:
        xlsx_bytes: Bytes content of the Excel file
    
    Returns:
        List of product dictionaries with keys matching Odoo product.template fields
    """
    products = []
    
    try:
        wb = openpyxl.load_workbook(BytesIO(xlsx_bytes), data_only=True)
        ws = wb.active
        
        # Get headers from first row
        headers = []
        for cell in ws[1]:
            headers.append(cell.value)
        
        logger.info(f"Product Excel headers: {headers}")
        
        # Map common Excel column names to Odoo field names
        field_mapping = {
            # default_code (internal reference)
            'artikelnr': 'default_code',
            'artikel': 'default_code',
            'default_code': 'default_code',
            'internal reference': 'default_code',
            'sku': 'default_code',
            'code': 'default_code',
            
            # name
            'naam': 'name',
            'name': 'name',
            'product name': 'name',
            'product': 'name',
            'productnaam': 'name',
            
            # description
            'description': 'description',
            'omschrijving': 'description',
            'beschrijving': 'description',
            
            # list_price
            'verkoopprijs': 'list_price',
            'sales price': 'list_price',
            'list_price': 'list_price',
            'listprice': 'list_price',
            'prijs': 'list_price',
            'price': 'list_price',
            
            # standard_price
            'kostprijs': 'standard_price',
            'cost': 'standard_price',
            'standard_price': 'standard_price',
            
            # type
            'type': 'type',
            'product type': 'type',
        }
        
        # Create column index mapping
        column_mapping = {}
        for idx, header in enumerate(headers):
            if header:
                header_lower = str(header).lower().strip()
                if header_lower in field_mapping:
                    field_name = field_mapping[header_lower]
                    # Prefer exact match for list_price, but allow any column with "prijs"
                    if field_name not in column_mapping or field_name == 'list_price':
                        column_mapping[field_name] = idx
        
        # Fallback: if no name column found, use first column
        if 'name' not in column_mapping and headers:
            column_mapping['name'] = 0
            logger.info("No name column detected, using first column as name")
        
        logger.info(f"Column mapping: {column_mapping}")
        
        # Parse data rows (skip header)
        for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            # Skip empty rows
            if not any(row):
                continue
            
            product = {}
            
            # Extract mapped fields
            for field_name, col_idx in column_mapping.items():
                if col_idx < len(row):
                    value = row[col_idx]
                    if value is not None:
                        product[field_name] = value
            
            # Skip if no name
            if 'name' not in product or not product['name']:
                logger.warning(f"Skipping row {row_idx}: No name found")
                continue
            
            # Ensure description is set (use name if not available)
            if 'description' not in product or not product['description']:
                product['description'] = product['name']
            
            # Ensure default_code is set (can be empty string)
            if 'default_code' not in product:
                product['default_code'] = ""
            
            # Ensure list_price is a number
            if 'list_price' in product:
                try:
                    product['list_price'] = float(product['list_price'])
                except (ValueError, TypeError):
                    product['list_price'] = 0.0
            else:
                product['list_price'] = 0.0
            
            products.append(product)
        
        logger.info(f"Parsed {len(products)} products from Excel file")
        
    except Exception as e:
        logger.error(f"Error parsing product Excel file: {str(e)}")
        raise
    
    return products


def parse_sale_order_xlsx(xlsx_bytes: bytes) -> Dict[str, Any]:
    """
    Parse Verkooporder (sale.order).xlsx file to extract sale order data.
    
    Expected structure:
    - Order header information (partner, date, etc.)
    - Order lines with product codes, descriptions, quantities, prices
    
    Args:
        xlsx_bytes: Bytes content of the Excel file
    
    Returns:
        Dictionary with order header data and list of order lines
    """
    order_data = {
        'lines': []
    }
    
    try:
        wb = openpyxl.load_workbook(BytesIO(xlsx_bytes), data_only=True)
        ws = wb.active
        
        # Get headers from first row
        headers = []
        for cell in ws[1]:
            headers.append(cell.value)
        
        logger.info(f"Sale Order Excel headers: {headers}")
        
        # Map common Excel column names to order line fields
        field_mapping = {
            'artikelnr': 'product_code',
            'artikel': 'product_code',
            'default_code': 'product_code',
            'product code': 'product_code',
            'omschrijving': 'description',
            'description': 'description',
            'name': 'description',
            'hoeveelheid': 'quantity',
            'quantity': 'quantity',
            'qty': 'quantity',
            'eenheidsprijs': 'unit_price',
            'unit price': 'unit_price',
            'price unit': 'unit_price',
            'price_unit': 'unit_price',
            'btw': 'tax_percent',
            'tax': 'tax_percent',
            'vat': 'tax_percent',
        }
        
        # Create column index mapping
        column_mapping = {}
        for idx, header in enumerate(headers):
            if header:
                header_lower = str(header).lower().strip()
                if header_lower in field_mapping:
                    column_mapping[field_mapping[header_lower]] = idx
        
        logger.info(f"Column mapping: {column_mapping}")
        
        # Parse data rows (skip header)
        for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            # Skip empty rows
            if not any(row):
                continue
            
            line = {}
            
            # Extract mapped fields
            for field_name, col_idx in column_mapping.items():
                if col_idx < len(row):
                    value = row[col_idx]
                    if value is not None:
                        line[field_name] = value
            
            # Skip if no description and no product code
            if 'description' not in line and 'product_code' not in line:
                logger.warning(f"Skipping row {row_idx}: No description or product code")
                continue
            
            # Ensure description is set
            if 'description' not in line or not line['description']:
                line['description'] = line.get('product_code', 'Product')
            
            # Convert types and set defaults
            try:
                line['quantity'] = int(line['quantity']) if line.get('quantity') else 1
                line['unit_price'] = float(line['unit_price']) if line.get('unit_price') else 0.0
                line['tax_percent'] = int(line['tax_percent']) if line.get('tax_percent') else DEFAULT_VAT_PERCENT
            except (ValueError, TypeError) as e:
                logger.warning(f"Error converting values in row {row_idx}: {e}")
                continue
            
            order_data['lines'].append(line)
        
        logger.info(f"Parsed {len(order_data['lines'])} order lines from Excel file")
        
    except Exception as e:
        logger.error(f"Error parsing sale order Excel file: {str(e)}")
        raise
    
    return order_data
