import os
import requests
import logging
from typing import List, Dict, Any, Optional, Tuple
from difflib import SequenceMatcher

from app.constants import MIN_FUZZY_MATCH_THRESHOLD

# Configure logging - basicConfig is idempotent and won't reconfigure if already set up
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

ODOO_URL = os.getenv("ODOO_URL")
ODOO_DB = os.getenv("ODOO_DB")
ODOO_USER = os.getenv("ODOO_USER")
ODOO_PASSWORD = os.getenv("ODOO_PASSWORD")

# Constants
LOG_DESCRIPTION_MAX_LENGTH = 50

def normalize_text_for_matching(s: str) -> str:
    """Normaliseer tekst voor product matching."""
    if s is None:
        return ""
    import unicodedata
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("\xa0", " ")
    import re
    s = re.sub(r"\s+", " ", s).strip()
    return s.lower()

def calculate_text_similarity(text1: str, text2: str) -> float:
    """
    Bereken similariteit tussen twee teksten (0.0 - 1.0).
    Gebruikt SequenceMatcher voor fuzzy matching.
    """
    # Normaliseer beide teksten
    norm1 = normalize_text_for_matching(text1)
    norm2 = normalize_text_for_matching(text2)
    
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


def search_product_by_fuzzy_name(uid: int, product_name: str, min_similarity: float = MIN_FUZZY_MATCH_THRESHOLD) -> Optional[Tuple[int, str, float]]:
    """
    Search for a product in Odoo by fuzzy matching the product name.
    
    Note: This function retrieves all products for fuzzy matching. For large catalogs (>1000 products),
    consider implementing pagination or caching strategies to improve performance.
    
    Args:
        uid: Odoo user ID
        product_name: Product name to search for
        min_similarity: Minimum similarity threshold (0.0 - 1.0)
    
    Returns:
        Tuple of (product_id, matched_name, similarity_score) if found with sufficient similarity, None otherwise
    """
    try:
        # Search all products - get name and id
        # TODO: For large catalogs, consider implementing pagination or caching
        products = call(uid, "product.product", "search_read", [
            [],  # No domain filter - search all products
            ["id", "name"]  # Fields to retrieve
        ])
        
        if not products:
            logger.warning(f"No products found in database for fuzzy matching")
            return None
        
        best_match = None
        best_similarity = 0.0
        
        # Find best matching product
        for product in products:
            similarity = calculate_text_similarity(product_name, product["name"])
            
            if similarity > best_similarity:
                best_similarity = similarity
                best_match = product
        
        if best_similarity >= min_similarity:
            logger.info(f"Fuzzy match found for '{product_name}': product '{best_match['name']}' (ID: {best_match['id']}, similarity: {best_similarity:.2f})")
            return (best_match["id"], best_match["name"], best_similarity)
        else:
            logger.info(f"No fuzzy match found for '{product_name}' (best similarity: {best_similarity:.2f}, threshold: {min_similarity})")
            return None
            
    except Exception as e:
        logger.error(f"Error during fuzzy product search for '{product_name}': {str(e)}")
        return None


def create_product(uid: int, product_code: str, description: str, unit_price: float) -> Optional[int]:
    """
    Create a new product in Odoo with the given details.
    Used for EPB products when there's 0% matching with existing products.
    
    Args:
        uid: Odoo user ID
        product_code: Product reference/code (will be set as default_code, can be empty for EPB products)
        description: Product description (will be set as name)
        unit_price: Product unit price (will be set as list_price)
    
    Returns:
        product_id if created successfully, None otherwise
    """
    try:
        product_data = {
            "name": description,
            "list_price": unit_price,
            "type": "product",  # Can be 'product', 'consu' (consumable), or 'service'
            "sale_ok": True,  # Can be sold
            "purchase_ok": False,  # Cannot be purchased (products from PDFs are sales-only)
        }
        
        # Only set default_code if product_code is provided
        if product_code:
            product_data["default_code"] = product_code
        
        product_id = call(uid, "product.product", "create", [product_data])
        logger.info(f"Created new product '{description}' (code: '{product_code}') with product_id={product_id}")
        return product_id
    except Exception as e:
        logger.error(f"Error creating product '{description}': {str(e)}")
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
    customer_email: Optional[str] = None,
    enable_fuzzy_matching: bool = False,
    auto_create_products: bool = False
):
    """
    Create a quotation in Odoo from XLSX parsed data
    
    Args:
        lines: List of line items with product_code, description, quantity, unit_price, tax_percent
        customer_name: Name of the customer
        customer_email: Email of the customer (optional)
        enable_fuzzy_matching: Enable fuzzy matching for products without codes (EPB products)
        auto_create_products: Automatically create products when 0% match (for EPB products)
    
    Returns:
        order_id: The ID of the created sale order in Odoo
    """
    if not ODOO_URL or not ODOO_DB or not ODOO_USER or not ODOO_PASSWORD:
        raise ValueError("Odoo configuration not set. Please set ODOO_URL, ODOO_DB, ODOO_USER, and ODOO_PASSWORD environment variables.")
    
    uid = login()
    logger.info(f"Creating quotation for customer: {customer_name} (fuzzy_matching={enable_fuzzy_matching}, auto_create={auto_create_products})")

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
    products_fuzzy_matched = 0
    products_created = 0
    products_not_found = 0
    
    for line in lines:
        product_code = line.get("product_code", "")
        description = line.get("description", "")
        quantity = line.get("quantity", 1)
        unit_price = line.get("unit_price", 0.0)
        
        # Try to find the product by its reference code
        product_id = None
        fuzzy_matched_name = None
        
        if product_code:
            # Try exact match by product code
            product_id = search_product_by_reference(uid, product_code)
            
            if product_id:
                products_found += 1
        elif enable_fuzzy_matching and description:
            # No product code - try fuzzy matching by name (for EPB products)
            fuzzy_result = search_product_by_fuzzy_name(uid, description)
            
            if fuzzy_result:
                product_id, fuzzy_matched_name, similarity = fuzzy_result
                products_fuzzy_matched += 1
                logger.info(f"Using fuzzy matched product: '{fuzzy_matched_name}' (similarity: {similarity:.2f})")
            elif auto_create_products:
                # 0% match - create new product
                product_id = create_product(uid, "", description, unit_price)
                if product_id:
                    products_created += 1
                    logger.info(f"Created new product for '{description}' (0% match)")
        
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
            if fuzzy_matched_name:
                logger.info(f"Creating product line with fuzzy matched product '{fuzzy_matched_name}' (ID: {product_id})")
            else:
                logger.info(f"Creating product line for product_id={product_id}")
        else:
            # Product not found - create a description line
            if product_code:
                order_line_data["name"] = f"[{product_code}] {description}"
                logger.warning(f"Product '{product_code}' not found in database - creating description line")
            else:
                order_line_data["name"] = description
                truncated_desc = description[:LOG_DESCRIPTION_MAX_LENGTH] + ('...' if len(description) > LOG_DESCRIPTION_MAX_LENGTH else '')
                logger.warning(f"No product code provided and no match found - creating description line: {truncated_desc}")
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
            logger.error(f"Failed to create order line for product '{product_code or description}': {str(e)}")
            raise

    logger.info(f"Quotation created successfully: {products_found} exact matches, {products_fuzzy_matched} fuzzy matches, {products_created} created, {products_not_found} description lines")
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
