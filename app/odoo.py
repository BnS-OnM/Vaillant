import os
import requests

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
