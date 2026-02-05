from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app.pdf_to_xlsx import facq_pdf_to_xlsx

app = FastAPI(title="FACQ PDF → XLSX Converter")

templates = Jinja2Templates(directory="app/templates")


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


@app.get("/health")
async def health():
    """
    Healthcheck voor Railway / Render
    """
    return {"status": "ok"}
