"""
Module for importing data from Excel files to Odoo.
Handles Product (product.template) and Sale Order (sale.order) Excel files.
"""
import openpyxl
from io import BytesIO
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Constants
DEFAULT_VAT_PERCENT = 21  # Default VAT rate for Belgium


def parse_product_xlsx(xlsx_bytes: bytes) -> List[Dict[str, Any]]:
    """
    Parse Product (product.template).xlsx file to extract product data.
    
    Expected columns:
    - default_code (Internal Reference / ArtikelNr)
    - name (Product Name)
    - list_price (Sales Price)
    - standard_price (Cost)
    - type (Product Type)
    - categ_id (Product Category)
    
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
            'artikelnr': 'default_code',
            'artikel': 'default_code',
            'default_code': 'default_code',
            'internal reference': 'default_code',
            'naam': 'name',
            'name': 'name',
            'product name': 'name',
            'verkoopprijs': 'list_price',
            'sales price': 'list_price',
            'list_price': 'list_price',
            'kostprijs': 'standard_price',
            'cost': 'standard_price',
            'standard_price': 'standard_price',
            'type': 'type',
            'product type': 'type',
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
            
            product = {}
            
            # Extract mapped fields
            for field_name, col_idx in column_mapping.items():
                if col_idx < len(row):
                    value = row[col_idx]
                    if value is not None:
                        product[field_name] = value
            
            # Skip if no default_code (required field)
            if 'default_code' not in product or not product['default_code']:
                logger.warning(f"Skipping row {row_idx}: No default_code found")
                continue
            
            # Ensure name is set (use default_code if not available)
            if 'name' not in product or not product['name']:
                product['name'] = product['default_code']
            
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
