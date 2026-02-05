import os
import requests
from typing import List, Dict, Any, Optional

ODOO_URL = os.getenv("ODOO_URL")
ODOO_DB = os.getenv("ODOO_DB")
ODOO_USER = os.getenv("ODOO_USER")
ODOO_PASSWORD = os.getenv("ODOO_PASSWORD")

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

    # Search for existing customer by name or email, or create new one
    search_domain = []
    if customer_email:
        search_domain = ["|", ["name", "=", customer_name], ["email", "=", customer_email]]
    else:
        search_domain = [["name", "=", customer_name]]
    
    existing_partners = call(uid, "res.partner", "search", [search_domain])
    
    if existing_partners:
        partner_id = existing_partners[0]
    else:
        partner_id = call(uid, "res.partner", "create", [{
            "name": customer_name,
            "email": customer_email,
        }])

    # Create sale order
    order_id = call(uid, "sale.order", "create", [{
        "partner_id": partner_id,
    }])

    # Add order lines
    for line in lines:
        product_code = line.get("product_code", "")
        description = line.get("description", "")
        
        # Include product code in description if available
        if product_code:
            line_description = f"[{product_code}] {description}"
        else:
            line_description = description
        
        order_line_data = {
            "order_id": order_id,
            "name": line_description,
            "product_uom_qty": line.get("quantity", 1),
            "price_unit": line.get("unit_price", 0.0),
        }
        
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
        
        call(uid, "sale.order.line", "create", [order_line_data])

    return order_id
