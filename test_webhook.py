import requests
import hmac
import hashlib
import time

url = 'http://127.0.0.1:5000/webhooks/mercadopago'
secret = '3f8ece8280ddb5546516a09babb4783ac1584fc6b60c0c4e29006adc6a1c9ad4'

data_id = '184005219581'
request_id = 'test-request-id'
ts = str(int(time.time()))

manifest = f'id:{data_id};request-id:{request_id};ts:{ts};'
computed = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()

headers = {
    'Content-Type': 'application/json',
    'x-signature': f'ts={ts},v1={computed}',
    'x-request-id': request_id
}

payload = {'type': 'payment', 'data': {'id': data_id}}

r = requests.post(url, json=payload, headers=headers)
print('Status:', r.status_code)