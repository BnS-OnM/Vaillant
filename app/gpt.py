import os
import json
from openai import OpenAI
from app.schemas import GPTResponse

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """
Je converteert FACQ PDF offertes naar strikt JSON.
GEEN tekst, GEEN uitleg, GEEN markdown.

Schema:
{
  "customer": {"name": string, "email": string|null},
  "quotation": {
    "currency": "EUR",
    "lines": [
      {
        "product_code": string|null,
        "description": string,
        "quantity": number,
        "unit_price": number,
        "tax_percent": number
      }
    ]
  }
}
"""

def pdf_to_json(_: bytes) -> GPTResponse:
    response = client.responses.create(
        model="gpt-4.1-mini",
        input=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": "Parse deze FACQ PDF naar JSON."
            }
        ],
    )

    content = response.output_text
    data = json.loads(content)
    return GPTResponse(**data)
