# FACQ Converter Odoo

Convert FACQ PDF invoices to XLSX format and optionally import them as quotations into Odoo.
Also supports direct import of products and sale orders from Excel files.

## Features

- **PDF to XLSX Conversion**: Upload a FACQ PDF and download it as an Excel file
- **Odoo Integration**: Automatically import the converted data as a new quotation in Odoo's sales module
- **Excel Import**: Import products and sale orders directly from Excel files to Odoo
- **Product Linking**: Automatically link sale order lines to existing products in Odoo by product code
- **Multiple workflows**:
  1. Download XLSX only (original functionality)
  2. Download XLSX + Import to Odoo (new functionality)
  3. Import products from Excel to Odoo
  4. Import sale orders from Excel to Odoo with automatic product linking

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

### PDF Conversion
- `GET /` - Web interface
- `POST /upload-xlsx` - Upload PDF, download XLSX
- `POST /upload-and-import` - Upload PDF, download XLSX, and import to Odoo

### Excel Import (New)
- `POST /import-products` - Import products from Excel file (Product (product.template).xlsx format)
- `POST /import-sale-order` - Import sale order from Excel file (Verkooporder (sale.order).xlsx format)

### Other
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

## Excel Import Usage

### Importing Products

Import products from an Excel file with the following structure:

**Product (product.template).xlsx format:**
- Column headers: `ArtikelNr`, `Naam`, `Verkoopprijs`, `Kostprijs`, `Type`
- Example:
  ```
  ArtikelNr | Naam              | Verkoopprijs | Kostprijs | Type
  12345     | Product A - Kraan | 150.50       | 100.00    | product
  67890     | Product B - Wasbak| 250.00       | 180.00    | product
  ```

**API Call:**
```bash
curl -X POST "http://localhost:8000/import-products" \
  -F "file=@Product (product.template).xlsx"
```

### Importing Sale Orders

Import sale orders from an Excel file with the following structure:

**Verkooporder (sale.order).xlsx format:**
- Column headers: `ArtikelNr`, `Omschrijving`, `Hoeveelheid`, `Eenheidsprijs`, `Bedrag`, `BTW`
- Example:
  ```
  ArtikelNr | Omschrijving      | Hoeveelheid | Eenheidsprijs | Bedrag | BTW
  12345     | Product A - Kraan | 2           | 150.50        | 301.00 | 21
  67890     | Product B - Wasbak| 1           | 250.00        | 250.00 | 21
  ```

**API Call:**
```bash
curl -X POST "http://localhost:8000/import-sale-order" \
  -F "file=@Verkooporder (sale.order).xlsx" \
  -F "customer_name=Test Customer" \
  -F "customer_email=test@example.com"
```

**Product Linking:**
- Sale order lines will automatically be linked to existing products in Odoo based on the `ArtikelNr` (product code)
- If a product with the matching `default_code` is found, a product line is created with the `product_id` set
- If no matching product is found, a description-only line is created with the product code and description
- This ensures proper product tracking and inventory management in Odoo
