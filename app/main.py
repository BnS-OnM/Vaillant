from fastapi import FastAPI, UploadFile, File, Request, Form
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
import os

from app.pdf_to_xlsx import facq_pdf_to_xlsx, facq_pdf_to_xlsx_and_data
from app.odoo import create_quotation_from_xlsx_data

app = FastAPI(title="FACQ PDF → XLSX Converter")

templates = Jinja2Templates(directory="app/templates")

# Configuration
DEFAULT_CUSTOMER_NAME = os.getenv("DEFAULT_CUSTOMER_NAME", "FACQ Customer")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """
    Homepage met uploadformulier
    """
    return templates.TemplateResponse(
        "index.html",
        {"request": request}
    )


@app.post("/upload-xlsx")
async def upload_pdf_to_xlsx(file: UploadFile = File(...)):
    """
    Upload FACQ PDF → download XLSX
    """
    if not file.filename.lower().endswith(".pdf"):
        return {"error": "Upload een PDF-bestand"}

    pdf_bytes = await file.read()

    try:
        xlsx_file = facq_pdf_to_xlsx(pdf_bytes)
    except Exception as e:
        return {
            "error": "Conversie mislukt",
            "detail": str(e)
        }

    return StreamingResponse(
        xlsx_file,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=facq_offerte.xlsx"
        }
    )


@app.post("/upload-and-import")
async def upload_pdf_and_import_to_odoo(
    file: UploadFile = File(...),
    customer_name: Optional[str] = Form(None),
    customer_email: Optional[str] = Form(None)
):
    """
    Upload FACQ PDF → create XLSX → import to Odoo as quotation
    """
    if not file.filename.lower().endswith(".pdf"):
        return JSONResponse(
            status_code=400,
            content={"error": "Upload een PDF-bestand"}
        )

    pdf_bytes = await file.read()

    try:
        xlsx_file, lines_data = facq_pdf_to_xlsx_and_data(pdf_bytes)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "error": "Conversie mislukt",
                "detail": str(e)
            }
        )

    # Import to Odoo if data was extracted
    odoo_order_id = None
    if lines_data:
        try:
            odoo_order_id = create_quotation_from_xlsx_data(
                lines=lines_data,
                customer_name=customer_name or DEFAULT_CUSTOMER_NAME,
                customer_email=customer_email
            )
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Odoo import mislukt",
                    "detail": str(e),
                    "xlsx_generated": True
                }
            )

    # Return XLSX file with headers indicating Odoo import success
    return StreamingResponse(
        xlsx_file,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=facq_offerte.xlsx",
            "X-Odoo-Order-Id": str(odoo_order_id) if odoo_order_id else "none",
            "X-Odoo-Import-Status": "success" if odoo_order_id else "failed"
        }
    )


@app.get("/health")
async def health():
    """
    Healthcheck voor Railway / Render
    """
    return {"status": "ok"}
