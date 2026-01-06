import requests
import time
import os
import json
import base64
from datetime import datetime, timezone
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

print("BOT STARTING - DEBUG MODE ACTIVE")

# ==================== CONFIGURATION ====================
BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

ACCESS_KEY = os.getenv("KALSHI_ACCESS_KEY")
PRIVATE_KEY_PEM = os.getenv("KALSHI_PRIVATE_KEY")

print(f"ACCESS_KEY loaded: {'YES' if ACCESS_KEY else 'NO/MISSING'}")
print(f"PRIVATE_KEY_PEM length: {len(PRIVATE_KEY_PEM) if PRIVATE_KEY_PEM else 'MISSING'} chars")

THRESHOLD = 1.0
COUNT = 1
CHECK_INTERVAL = 30
# ======================================================

# Load private key with debug
try:
    if not PRIVATE_KEY_PEM:
        raise ValueError("KALSHI_PRIVATE_KEY is empty or missing!")
    if not PRIVATE_KEY_PEM.startswith('-----BEGIN RSA PRIVATE KEY-----'):
        raise ValueError("Private key does not start with expected header!")
    private_key = serialization.load_pem_private_key(
        PRIVATE_KEY_PEM.encode('utf-8'), password=None
    )
    print("Private key loaded SUCCESSFULLY")
except Exception as e:
    print(f"CRITICAL ERROR loading private key: {str(e)}")
    raise  # Exit early to show in logs

def sign_request(method, path):
    # FIXED: No body in payload (Kalshi docs examples for GET/POST omit it)
    now = datetime.now(timezone.utc)
    timestamp_ms = str(int(now.timestamp() * 1000))
    payload = timestamp_ms + method.upper() + path
    print(f"Signing payload: {payload[:50]}...")  # Debug snippet
    signature = private_key.sign(
        payload.encode(),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256()
    )
    sig_b64 = base64.b64encode(signature).decode()
    return timestamp_ms, sig_b64

def kalshi_request(method, endpoint, json_body=None):
    if not ACCESS_KEY:
        raise ValueError("KALSHI_ACCESS_KEY missing!")
    url = BASE_URL + endpoint
    body_str = json.dumps(json_body) if json_body else ""
    timestamp, signature = sign_request(method, endpoint)  # No body_str
    
    headers = {
        "KALSHI-ACCESS-KEY": ACCESS_KEY,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "Content-Type": "application/json"
    }
    
    try:
        if method == "GET":
            resp = requests.get(url, headers=headers, timeout=10)
        elif method == "POST":
            resp = requests.post(url, headers=headers, json=json_body, timeout=10)
        print(f"{method} {endpoint} status: {resp.status_code}")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"API ERROR {method} {endpoint}: {str(e)} | Response: {getattr(e.response, 'text', 'No response')}")
        raise

# BOT FUNCTIONS (same as before, with try/except)
def has_open_positions():
    try:
        data = kalshi_request("GET", "/portfolio/positions")
        positions = data.get("positions", [])
        open_pos = [p for p in positions if p.get("quantity", 0) > 0]
        if open_pos:
            print(f"⏳ HOLDING {len(open_pos)} position(s)")
        return len(open_pos) > 0
    except Exception as e:
        print(f"Positions check failed: {e}")
        return False

def find_best_arb():
    try:
        data = kalshi_request("GET", "/markets?status=open&limit=1000")
        # ... (rest of arb logic same)
        best = None
        best_profit = 0
        for m in data["markets"]:
            t = m["ticker"]
            ya = m.get("yes_ask")
            na = m.get("no_ask")
            yb = m.get("yes_bid")
            nb = m.get("no_bid")
            if ya and na and ya + na < 100:
                profit = 100 - (ya + na)
                if profit > best_profit and profit >= THRESHOLD:
                    best = ("buy", t, ya, na, profit)
                    best_profit = profit
            if yb and nb and yb + nb > 100:
                profit = (yb + nb) - 100
                if profit > best_profit and profit >= THRESHOLD:
                    best = ("sell", t, yb, nb, profit)
                    best_profit = profit
        return best
    except Exception as e:
        print(f"Markets fetch failed: {e}")
        return None

def execute_arb(action, ticker, price1, price2, profit):
    print(f"EXECUTING {action.upper()} ARB on {ticker} — +{profit}¢")
    # ... (order placement same, with prints)

# MAIN
print("🔴 LIVE KALSHI ARB BOT STARTED — DEBUG VERSION")
print("If you see this, startup succeeded!\n")

while True:
    try:
        print(f"SCAN START {time.strftime('%H:%M:%S')}")
        if has_open_positions():
            print("Has positions - skipping")
        else:
            opp = find_best_arb()
            if opp:
                print("ARB FOUND!")
            else:
                print("No arb this cycle")
        print(f"Next in {CHECK_INTERVAL}s\n")
        time.sleep(CHECK_INTERVAL)
    except Exception as e:
        print(f"MAIN LOOP ERROR: {e}")
        time.sleep(60)
