# FACQ Converter Odoo

Convert FACQ PDF invoices to XLSX format and optionally import them as quotations into Odoo.

## Features

- **PDF to XLSX Conversion**: Upload a FACQ PDF and download it as an Excel file
- **Odoo Integration**: Automatically import the converted data as a new quotation in Odoo's sales module
- **Two workflows**:
  1. Download XLSX only (original functionality)
  2. Download XLSX + Import to Odoo (new functionality)

## Setup

### Environment Variables

For Odoo integration, set the following environment variables:

```bash
# Required for Odoo integration
ODOO_URL=https://your-odoo-instance.com
ODOO_DB=your-database-name
ODOO_USER=your-username
ODOO_PASSWORD=your-password

# Optional: Default customer name when not specified in the form
DEFAULT_CUSTOMER_NAME=FACQ Customer
```

### Run with Docker

```bash
docker build -t facq-converter .
docker run -p 8000:8000 \
  -e ODOO_URL=https://your-odoo-instance.com \
  -e ODOO_DB=your-db \
  -e ODOO_USER=your-user \
  -e ODOO_PASSWORD=your-password \
  facq-converter
```

### Run locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## API Endpoints

- `GET /` - Web interface
- `POST /upload-xlsx` - Upload PDF, download XLSX
- `POST /upload-and-import` - Upload PDF, download XLSX, and import to Odoo
- `GET /health` - Health check

## Usage

1. Navigate to `http://localhost:8000`
2. Choose one of two options:
   - **Download XLSX alleen**: Just convert and download the Excel file
   - **Upload en importeer in Odoo**: Convert, download, AND create a new quotation in Odoo
3. Fill in customer details (for Odoo import)
4. Upload your FACQ PDF file
5. Download the generated XLSX file

When using the Odoo import feature, a new quotation will be created in your Odoo sales module with:
- A new or existing customer record
- All product lines from the PDF
- Quantities and prices preserved
