import requests
import time
import os
import json
import base64
from datetime import datetime, timezone
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

# ===================== CONFIGURATION ====================
BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

# Set these in Render.com environment variables
ACCESS_KEY = os.getenv("KALSHI_ACCESS_KEY")          # Your public Access Key
PRIVATE_KEY_PEM = os.getenv("KALSHI_PRIVATE_KEY")    # Full PEM private key (multi-line OK)

THRESHOLD = 1.0        # Minimum guaranteed profit in cents
COUNT = 1              # Number of contracts per side (keep small!)
CHECK_INTERVAL = 30    # Check every 30 seconds
# ======================================================

# Load private key once at startup
def load_private_key():
    if not PRIVATE_KEY_PEM:
        raise ValueError("KALSHI_PRIVATE_KEY environment variable is missing!")
    return serialization.load_pem_private_key(PRIVATE_KEY_PEM.encode(), password=None)

private_key = load_private_key()

# Sign request (RSA-PSS as required by Kalshi)
def sign_request(method, path, body=""):
    now = datetime.now(timezone.utc)
    timestamp_ms = str(int(now.timestamp() * 1000))
    payload = timestamp_ms + method.upper() + path + body
    signature = private_key.sign(
        payload.encode(),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256()
    )
    sig_b64 = base64.b64encode(signature).decode()
    return timestamp_ms, sig_b64

# Generic authenticated request
def kalshi_request(method, endpoint, json_body=None):
    url = BASE_URL + endpoint
    body_str = json.dumps(json_body) if json_body else ""
    timestamp, signature = sign_request(method, endpoint, body_str)

    headers = {
        "KALSHI-ACCESS-KEY": ACCESS_KEY,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "Content-Type": "application/json"
    }

    if method == "GET":
        resp = requests.get(url, headers=headers)
    elif method == "POST":
        resp = requests.post(url, headers=headers, json=json_body)
    else:
        raise ValueError("Unsupported method")

    if resp.status_code != 200:
        raise Exception(f"{method} {endpoint} failed ({resp.status_code}): {resp.text}")
    return resp.json()

# Check if we already have open positions
def has_open_positions():
    data = kalshi_request("GET", "/portfolio/positions")
    positions = data.get("positions", [])
    open_pos = [p for p in positions if p.get("quantity", 0) > 0]
    if open_pos:
        print(f"⏳ HOLDING {len(open_pos)} open position(s) — waiting for settlement")
        return True
    return False

# Scan markets for the best arbitrage opportunity
def find_best_arb():
    data = kalshi_request("GET", "/markets?status=open&limit=1000")
    best = None
    best_profit = 0

    for m in data["markets"]:
        t = m["ticker"]
        ya = m.get("yes_ask")
        na = m.get("no_ask")
        yb = m.get("yes_bid")
        nb = m.get("no_bid")

        # Buy both sides arb
        if ya is not None and na is not None and ya + na < 100:
            profit = 100 - (ya + na)
            if profit > best_profit and profit >= THRESHOLD:
                best = ("buy", t, ya, na, profit)
                best_profit = profit

        # Sell both sides arb
        if yb is not None and nb is not None and yb + nb > 100:
            profit = (yb + nb) - 100
            if profit > best_profit and profit >= THRESHOLD:
                best = ("sell", t, yb, nb, profit)
                best_profit = profit

    return best

# Execute the paired arbitrage orders
def execute_arb(action, ticker, price1, price2, profit):
    print(f"🚀 EXECUTING {action.upper()} ARB on {ticker} — Expected profit +{profit}¢")

    # Yes side
    yes_payload = {
        "ticker": ticker,
        "action": action,
        "type": "limit",
        "count": COUNT,
        "side": "yes"
    }
    yes_payload["yes_price" if action == "buy" else "no_price"] = price1
    kalshi_request("POST", "/orders", yes_payload)

    time.sleep(0.3)

    # No side
    no_payload = {
        "ticker": ticker,
        "action": action,
        "type": "limit",
        "count": COUNT,
        "side": "no"
    }
    no_payload["no_price" if action == "buy" else "yes_price"] = price2
    kalshi_request("POST", "/orders", no_payload)

    print("✅ Both orders placed successfully!")

# ==================== MAIN LOOP ====================
if not ACCESS_KEY:
    raise ValueError("KALSHI_ACCESS_KEY environment variable is missing!")

print("🔴 LIVE KALSHI ARB BOT STARTED — One Position Only")
print("Authenticated with API key — ready to scan every 30 seconds\n")

while True:
    try:
        print(f"🔍 Scanning all open markets... ({time.strftime('%H:%M:%S')})")

        if has_open_positions():
            time.sleep(CHECK_INTERVAL)
            continue

        opp = find_best_arb()

        if opp:
            action, ticker, p1, p2, profit = opp
            print(f"💰 BEST ARB FOUND: {ticker} → {action.upper()} → +{profit}¢ profit")
            execute_arb(action, ticker, p1, p2, profit)
        else:
            print("😴 No arbitrage opportunities above threshold — all quiet")

        print(f"Next scan in {CHECK_INTERVAL} seconds...\n")
        time.sleep(CHECK_INTERVAL)

    except Exception as e:
        print(f"❌ ERROR: {e}")
        print("Waiting 60 seconds before retry...\n")
        time.sleep(60)
