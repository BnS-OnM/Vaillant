import os
import requests
import logging
from typing import List, Dict, Any, Optional
from difflib import SequenceMatcher

# Configure logging - basicConfig is idempotent and won't reconfigure if already set up
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

ODOO_URL = os.getenv("ODOO_URL")
ODOO_DB = os.getenv("ODOO_DB")
ODOO_USER = os.getenv("ODOO_USER")
ODOO_PASSWORD = os.getenv("ODOO_PASSWORD")

# Constants
LOG_DESCRIPTION_MAX_LENGTH = 50
FUZZY_MATCH_THRESHOLD = 0.6  # Minimum similarity ratio for fuzzy matching (60%)
FUZZY_MATCH_WORD_OVERLAP_THRESHOLD = 0.5  # Minimum word overlap ratio
FUZZY_MATCH_RATIO_BOOST = 0.7  # Boosted ratio when word overlap is significant

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


def fuzzy_search_product_by_name(uid: int, product_name: str, threshold: float = FUZZY_MATCH_THRESHOLD) -> Optional[int]:
    """
    Search for a product in Odoo by fuzzy matching on the product name.
    Uses sequence matching to find similar product names.
    
    Args:
        uid: Odoo user ID
        product_name: Product name to search for
        threshold: Minimum similarity ratio (0.0 to 1.0) to consider a match. Default is FUZZY_MATCH_THRESHOLD
    
    Returns:
        product_id if found with similarity >= threshold, None otherwise
    """
    try:
        # Get all active products with their names
        # Note: For large databases, consider adding filters or pagination
        products = call(uid, "product.product", "search_read", [
            [["active", "=", True]],  # Only search active products
            ["id", "name", "default_code"],
            0,  # offset
            1000  # limit to first 1000 products for performance
        ])
        
        if not products:
            logger.warning("No products found in database for fuzzy matching")
            return None
        
        # Warn if we hit the limit, as there may be more products
        if len(products) >= 1000:
            logger.warning(f"Fuzzy search limited to first 1000 products. Database may contain more products that won't be considered for matching '{product_name}'.")
        
        # Normalize the search term
        normalized_search = product_name.lower().strip()
        
        # Find best match
        best_match = None
        best_ratio = 0.0
        
        for product in products:
            product_id = product["id"]
            product_db_name = (product.get("name") or "").lower().strip()
            
            # Calculate similarity ratio
            ratio = SequenceMatcher(None, normalized_search, product_db_name).ratio()
            
            # Also check if search terms are contained in product name (partial matching)
            search_words = set(normalized_search.split())
            product_words = set(product_db_name.split())
            common_words = search_words.intersection(product_words)
            
            # Boost ratio if significant words overlap
            if search_words and len(common_words) / len(search_words) > FUZZY_MATCH_WORD_OVERLAP_THRESHOLD:
                ratio = max(ratio, FUZZY_MATCH_RATIO_BOOST)
            
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = product
        
        if best_match and best_ratio >= threshold:
            logger.info(f"Fuzzy match found for '{product_name}': '{best_match['name']}' (similarity: {best_ratio:.2f}, product_id={best_match['id']})")
            return best_match["id"]
        else:
            logger.warning(f"No fuzzy match found for '{product_name}' (best match: {best_ratio:.2f}, threshold: {threshold})")
            return None
            
    except Exception as e:
        logger.error(f"Error in fuzzy search for product '{product_name}': {str(e)}")
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
    products_created = 0
    products_not_found = 0
    
    for line in lines:
        product_code = line.get("product_code", "")
        description = line.get("description", "")
        quantity = line.get("quantity", 1)
        unit_price = line.get("unit_price", 0.0)
        
        # Try to find the product by its reference code or by fuzzy name matching
        product_id = None
        
        if product_code:
            # FACQ products: search by product code
            product_id = search_product_by_reference(uid, product_code)
            
            if product_id:
                products_found += 1
        else:
            # EPB products (no product code): use fuzzy matching by name
            if description:
                product_id = fuzzy_search_product_by_name(uid, description, threshold=FUZZY_MATCH_THRESHOLD)
                
                if product_id:
                    products_found += 1
                else:
                    # No match found (0% match) - create new product
                    logger.info(f"No match found for EPB product '{description}' - creating new product")
                    try:
                        # Validate that we have a description before creating
                        if not description or len(description.strip()) < 2:
                            logger.warning(f"Description too short to create product: '{description}'")
                            product_id = None
                        else:
                            product_data = {
                                "name": description,
                                "list_price": unit_price,
                                "type": "product",  # Standard stockable product
                                "sale_ok": True,  # Can be sold
                                "purchase_ok": False,  # EPB products are sales-only
                            }
                            product_id = call(uid, "product.product", "create", [product_data])
                            logger.info(f"Created new product '{description}' with product_id={product_id}")
                            products_created += 1
                    except Exception as e:
                        logger.error(f"Failed to create product '{description}': {str(e)}")
                        product_id = None
        
        # Prepare order line data
        order_line_data = {
            "order_id": order_id,
            "product_uom_qty": quantity,
            "price_unit": unit_price,
        }
        
        if product_id:
            # Product found or created - create a product line
            order_line_data["product_id"] = product_id
            # Let Odoo auto-fill the description from the product record
            if product_code:
                logger.info(f"Creating product line for '{product_code}' with product_id={product_id}")
            else:
                logger.info(f"Creating product line for '{description[:LOG_DESCRIPTION_MAX_LENGTH]}...' with product_id={product_id}")
        else:
            # Product not found and creation failed - create a description line
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
            logger.error(f"Failed to create order line for product '{product_code or (description or '')[:30]}': {str(e)}")
            raise

    logger.info(f"Quotation created successfully: {products_found} products found, {products_created} products created, {products_not_found} description lines created")
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
