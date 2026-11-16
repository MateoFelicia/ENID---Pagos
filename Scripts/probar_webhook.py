"""Prueba manual: manda un webhook FIRMADO a tu servidor local.

Uso:
    python scripts/probar_webhook.py <payment_id> [http://127.0.0.1:5000]

Lee MP_WEBHOOK_SECRET del .env (nunca lo escribas en este archivo).
- Con un payment_id real de tu cuenta de prueba: la inscripción se acredita.
- Con uno inexistente: responde 500 (la firma fue válida, pero MP no conoce ese pago).
- Si responde 401: la firma no coincide, revisá MP_WEBHOOK_SECRET.
"""
import hashlib
import hmac
import os
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv()

secreto = os.getenv("MP_WEBHOOK_SECRET")
if not secreto:
    sys.exit("Falta MP_WEBHOOK_SECRET en el .env")
if len(sys.argv) < 2:
    sys.exit(__doc__)

data_id = sys.argv[1]
base = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:5000"
request_id = "prueba-manual"
ts = str(int(time.time() * 1000))  # Mercado Pago usa milisegundos

manifest = f"id:{data_id};request-id:{request_id};ts:{ts};"
firma = hmac.new(secreto.encode(), manifest.encode(), hashlib.sha256).hexdigest()

r = requests.post(
    f"{base}/webhooks/mercadopago",
    params={"data.id": data_id, "type": "payment"},
    json={"type": "payment", "data": {"id": data_id}},
    headers={"x-signature": f"ts={ts},v1={firma}", "x-request-id": request_id},
    timeout=30,
)
print("Respuesta:", r.status_code)
