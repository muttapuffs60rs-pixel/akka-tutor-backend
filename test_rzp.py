import requests
import os
from dotenv import load_dotenv

load_dotenv()

key_id = os.getenv("RAZORPAY_KEY_ID")
key_secret = os.getenv("RAZORPAY_KEY_SECRET")

try:
    res = requests.post(
        "https://api.razorpay.com/v1/orders",
        auth=(key_id, key_secret),
        json={"amount": 4900, "currency": "INR", "receipt": "rcpt_1"},
        verify=False
    )
    print("STATUS:", res.status_code)
    print("BODY:", res.text)
except Exception as e:
    print("ERROR:", e)
