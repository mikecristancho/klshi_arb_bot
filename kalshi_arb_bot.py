import requests
import time
import os
import json
import base64
from datetime import datetime, timezone
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

# ==================== CONFIGURATION ====================
BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

ACCESS_KEY = os.getenv("KALSHI_ACCESS_KEY")
PRIVATE_KEY_PEM = os.getenv("KALSHI_PRIVATE_KEY")

THRESHOLD = 1.0
COUNT = 1
CHECK_INTERVAL = 30
# ======================================================

def load_private_key():
    if not PRIVATE_KEY_PEM:
        print("ERROR: KALSHI_PRIVATE_KEY env var missing!")
        raise ValueError("Missing private key")
    try:
        return serialization.load_pem_private_key(PRIVATE_KEY_PEM.encode(), password=None)
    except Exception as e:
        print(f"ERROR loading private key: {e}")
        raise

private_key = load_private_key()

def sign_request(method, path, body=""):
    # FIXED: Omit body from payload (per Kalshi docs/examples for standard requests)
    now = datetime.now(timezone.utc)
    timestamp_ms = str(int(now.timestamp() * 1000))
    payload = timestamp_ms + method.upper() + path  # No + body here!
    signature = private_key.sign(
        payload.encode(),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256()
    )
    sig_b64 = base64.b64encode(signature).decode()
    return timestamp_ms, sig_b64

def kalshi_request(method, endpoint, json_body=None):
    if not ACCESS_KEY:
        raise ValueError("KALSHI_ACCESS_KEY env var missing!")
        
    url = BASE_URL + endpoint
    body_str = json.dumps(json_body) if json_body else ""
    timestamp, signature = sign_request(method, endpoint, body_str)  # Keep body for signing if needed (safe fallback)
    
    headers = {
        "KALSHI-ACCESS-KEY": ACCESS_KEY,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "Content-Type": "application/json"
    }
    
    try:
        if method == "GET":
            resp = requests.get(url, headers=headers)
        elif method == "POST":
            resp = requests.post(url, headers=headers, json=json_body)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"API REQUEST FAILED: {method} {endpoint} - {e} | Response: {getattr(e.response, 'text', '')}")
        raise

# Rest of functions unchanged...
def has_open_positions():
    try:
        data = kalshi_request("GET", "/portfolio/positions")
        positions = data.get("positions", [])
        open_pos = [p for p in positions if p.get("quantity", 0) > 0]
        if open_pos:
            print(f"⏳ HOLDING {len(open_pos)} open position(s)")
        return len(open_pos) > 0
    except:
        print("Failed to check positions - assuming none")
        return False

def find_best_arb():
    try:
        data = kalshi_request("GET", "/markets?status=open&limit=1000")
    except:
        print("Failed to fetch markets")
        return None
        
    best = None
    best_profit = 0

    for m in data["markets"]:
        t = m["ticker"]
        ya = m.get("yes_ask")
        na = m.get("no_ask")
        yb = m.get("yes_bid")
        nb = m.get("no_bid")

        if ya is not None and na is not None and ya + na < 100:
            profit = 100 - (ya + na)
            if profit > best_profit and profit >= THRESHOLD:
                best = ("buy", t, ya, na, profit)
                best_profit = profit

        if yb is not None and nb is not None and yb + nb > 100:
            profit = (yb + nb) - 100
            if profit > best_profit and profit >= THRESHOLD:
                best = ("sell", t, yb, nb, profit)
                best_profit = profit

    return best

def execute_arb(action, ticker, price1, price2, profit):
    print(f"🚀 EXECUTING {action.upper()} ARB on {ticker} — +{profit}¢ profit")

    yes_payload = {"ticker": ticker, "action": action, "type": "limit", "count": COUNT, "side": "yes"}
    yes_payload["yes_price" if action == "buy" else "no_price"] = price1
    kalshi_request("POST", "/orders", yes_payload)

    time.sleep(0.3)

    no_payload = {"ticker": ticker, "action": action, "type": "limit", "count": COUNT, "side": "no"}
    no_payload["no_price" if action == "buy" else "yes_price"] = price2
    kalshi_request("POST", "/orders", no_payload)

    print("✅ Orders placed!")

# ==================== MAIN LOOP ====================
print("🔴 LIVE KALSHI ARB BOT STARTED — One Position Only")
print("Authenticated with API key — scanning every 30s\n")

while True:
    try:
        print(f"🔍 Scanning markets... ({time.strftime('%H:%M:%S')})")

        if has_open_positions():
            time.sleep(CHECK_INTERVAL)
            continue

        opp = find_best_arb()
        if opp:
            action, ticker, p1, p2, profit = opp
            print(f"💰 ARB FOUND: {ticker} → +{profit}¢")
            execute_arb(action, ticker, p1, p2, profit)
        else:
            print("😴 No arbs found")

        print(f"Next scan in {CHECK_INTERVAL}s...\n")
        time.sleep(CHECK_INTERVAL)

    except Exception as e:
        print(f"❌ LOOP ERROR: {e}\nWaiting 60s...")
        time.sleep(60)
