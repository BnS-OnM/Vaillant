import os
import requests
import logging
from typing import List, Dict, Any, Optional

# Configure logging - basicConfig is idempotent and won't reconfigure if already set up
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

ODOO_URL = os.getenv("ODOO_URL")
ODOO_DB = os.getenv("ODOO_DB")
ODOO_USER = os.getenv("ODOO_USER")
ODOO_PASSWORD = os.getenv("ODOO_PASSWORD")

# Constants
LOG_DESCRIPTION_MAX_LENGTH = 50

def login():
    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "service": "common",
            "method": "login",
            "args": [ODOO_DB, ODOO_USER, ODOO_PASSWORD],
        },
        "id": 1,
    }
    r = requests.post(f"{ODOO_URL}/jsonrpc", json=payload)
    r.raise_for_status()
    return r.json()["result"]

def call(uid, model, method, args):
    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "service": "object",
            "method": "execute_kw",
            "args": [ODOO_DB, uid, ODOO_PASSWORD, model, method, args],
        },
        "id": 1,
    }
    r = requests.post(f"{ODOO_URL}/jsonrpc", json=payload)
    r.raise_for_status()
    return r.json()["result"]

def search_product_by_reference(uid: int, product_code: str) -> Optional[int]:
    """
    Search for a product in Odoo by its default_code (internal reference).
    
    Args:
        uid: Odoo user ID
        product_code: Product reference/code to search for
    
    Returns:
        product_id if found, None otherwise
    """
    try:
        # Search by default_code (internal reference)
        products = call(uid, "product.product", "search", [
            [["default_code", "=", product_code]]
        ])
        
        if products:
            logger.info(f"Product found for reference '{product_code}': product_id={products[0]}")
            return products[0]
        else:
            logger.warning(f"No product found for reference '{product_code}'")
            return None
    except Exception as e:
        logger.error(f"Error searching for product with reference '{product_code}': {str(e)}")
        return None


def create_product(uid: int, product_code: str, description: str, unit_price: float) -> Optional[int]:
    """
    DEPRECATED: This function is no longer used in the quotation flow.
    Products are not automatically created when importing quotations.
    Use the /import-products endpoint to explicitly import products into Odoo.
    
    Create a new product in Odoo with the given details.
    
    Args:
        uid: Odoo user ID
        product_code: Product reference/code (will be set as default_code)
        description: Product description (will be set as name)
        unit_price: Product unit price (will be set as list_price)
    
    Returns:
        product_id if created successfully, None otherwise
    """
    try:
        product_data = {
            "name": description,
            "default_code": product_code,
            "list_price": unit_price,
            "type": "product",  # Can be 'product', 'consu' (consumable), or 'service'
            "sale_ok": True,  # Can be sold
            "purchase_ok": False,  # Cannot be purchased (products from PDFs are sales-only)
        }
        
        product_id = call(uid, "product.product", "create", [product_data])
        logger.info(f"Created new product '{product_code}' with product_id={product_id}")
        return product_id
    except Exception as e:
        logger.error(f"Error creating product '{product_code}': {str(e)}")
        return None


def create_quotation(data):
    uid = login()

    partner_id = call(uid, "res.partner", "create", [{
        "name": data.customer.name,
        "email": data.customer.email,
    }])

    order_id = call(uid, "sale.order", "create", [{
        "partner_id": partner_id,
    }])

    for l in data.quotation.lines:
        call(uid, "sale.order.line", "create", [{
            "order_id": order_id,
            "name": l.description,
            "product_uom_qty": l.quantity,
            "price_unit": l.unit_price,
        }])

    return order_id


def create_quotation_from_xlsx_data(
    lines: List[Dict[str, Any]],
    customer_name: str = "FACQ Customer",
    customer_email: Optional[str] = None
):
    """
    Create a quotation in Odoo from XLSX parsed data
    
    Args:
        lines: List of line items with product_code, description, quantity, unit_price, tax_percent
        customer_name: Name of the customer
        customer_email: Email of the customer (optional)
    
    Returns:
        order_id: The ID of the created sale order in Odoo
    """
    if not ODOO_URL or not ODOO_DB or not ODOO_USER or not ODOO_PASSWORD:
        raise ValueError("Odoo configuration not set. Please set ODOO_URL, ODOO_DB, ODOO_USER, and ODOO_PASSWORD environment variables.")
    
    uid = login()
    logger.info(f"Creating quotation for customer: {customer_name}")

    # Search for existing customer by name or email, or create new one
    search_domain = []
    if customer_email:
        search_domain = ["|", ["name", "=", customer_name], ["email", "=", customer_email]]
    else:
        search_domain = [["name", "=", customer_name]]
    
    existing_partners = call(uid, "res.partner", "search", [search_domain])
    
    if existing_partners:
        partner_id = existing_partners[0]
        logger.info(f"Using existing customer with ID: {partner_id}")
    else:
        partner_id = call(uid, "res.partner", "create", [{
            "name": customer_name,
            "email": customer_email,
        }])
        logger.info(f"Created new customer with ID: {partner_id}")

    # Create sale order
    order_id = call(uid, "sale.order", "create", [{
        "partner_id": partner_id,
    }])
    logger.info(f"Created sale order with ID: {order_id}")

    # Add order lines
    products_found = 0
    products_not_found = 0
    
    for line in lines:
        product_code = line.get("product_code", "")
        description = line.get("description", "")
        quantity = line.get("quantity", 1)
        unit_price = line.get("unit_price", 0.0)
        
        # Try to find the product by its reference code
        product_id = None
        if product_code:
            product_id = search_product_by_reference(uid, product_code)
            
            if product_id:
                products_found += 1
            # If not found, product_id stays None and will create description line
        
        # Prepare order line data
        order_line_data = {
            "order_id": order_id,
            "product_uom_qty": quantity,
            "price_unit": unit_price,
        }
        
        if product_id:
            # Product found - create a product line
            order_line_data["product_id"] = product_id
            # Let Odoo auto-fill the description from the product record
            logger.info(f"Creating product line for '{product_code}' with product_id={product_id}")
        else:
            # Product not found - create a description line
            if product_code:
                order_line_data["name"] = f"[{product_code}] {description}"
                logger.warning(f"Product '{product_code}' not found in database - creating description line")
            else:
                order_line_data["name"] = description
                truncated_desc = description[:LOG_DESCRIPTION_MAX_LENGTH] + ('...' if len(description) > LOG_DESCRIPTION_MAX_LENGTH else '')
                logger.warning(f"No product code provided - creating description line: {truncated_desc}")
            products_not_found += 1
        
        # TODO: Add tax handling for production environments
        # Tax handling in Odoo requires finding the tax record by rate
        # The tax_percent field is preserved in the XLSX but not automatically applied
        # Example implementation:
        #   tax_percent = line.get("tax_percent", 0)
        #   if tax_percent:
        #       taxes = call(uid, "account.tax", "search", [
        #           [["amount", "=", tax_percent], ["type_tax_use", "=", "sale"]]
        #       ])
        #       if taxes:
        #           order_line_data["tax_id"] = [(6, 0, taxes)]
        
        try:
            call(uid, "sale.order.line", "create", [order_line_data])
        except Exception as e:
            logger.error(f"Failed to create order line for product '{product_code}': {str(e)}")
            raise

    logger.info(f"Quotation created successfully: {products_found} products found, {products_not_found} description lines created")
    return order_id


def import_products_from_data(products_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Import products into Odoo from parsed Excel data.
    
    For each product:
    - Search if product with same default_code already exists
    - If exists: update the product
    - If not exists: create new product
    
    Args:
        products_data: List of product dictionaries with fields like default_code, name, list_price, etc.
    
    Returns:
        Dictionary with import statistics (created, updated, errors)
    """
    if not ODOO_URL or not ODOO_DB or not ODOO_USER or not ODOO_PASSWORD:
        raise ValueError("Odoo configuration not set. Please set ODOO_URL, ODOO_DB, ODOO_USER, and ODOO_PASSWORD environment variables.")
    
    uid = login()
    logger.info(f"Starting product import: {len(products_data)} products to process")
    
    stats = {
        'created': 0,
        'updated': 0,
        'skipped': 0,
        'errors': 0,
        'error_details': []
    }
    
    for product in products_data:
        default_code = product.get('default_code')
        if not default_code:
            logger.warning(f"Skipping product without default_code: {product}")
            stats['skipped'] += 1
            continue
        
        try:
            # Search for existing product by default_code
            existing_products = call(uid, "product.template", "search", [
                [["default_code", "=", default_code]]
            ])
            
            # Prepare product data for Odoo
            product_data = {
                'default_code': default_code,
                'name': product.get('name', default_code),
            }
            
            # Add optional fields if present
            if 'list_price' in product:
                product_data['list_price'] = float(product['list_price'])
            if 'standard_price' in product:
                product_data['standard_price'] = float(product['standard_price'])
            if 'type' in product:
                product_data['type'] = product['type']
            
            if existing_products:
                # Update existing product
                product_id = existing_products[0]
                call(uid, "product.template", "write", [[product_id], product_data])
                logger.info(f"Updated product '{default_code}' (ID: {product_id})")
                stats['updated'] += 1
            else:
                # Create new product
                product_id = call(uid, "product.template", "create", [product_data])
                logger.info(f"Created product '{default_code}' (ID: {product_id})")
                stats['created'] += 1
                
        except Exception as e:
            error_msg = f"Error processing product '{default_code}': {str(e)}"
            logger.error(error_msg)
            stats['errors'] += 1
            stats['error_details'].append(error_msg)
    
    logger.info(f"Product import completed: {stats['created']} created, {stats['updated']} updated, {stats['skipped']} skipped, {stats['errors']} errors")
    return stats
