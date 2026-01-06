import requests
import time
import os
import json
import base64
from datetime import datetime, timezone
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

# ==================== CONFIGURATION ====================
TEST_MODE = True  # Keep True to test order placement; False for arb

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

ACCESS_KEY = os.getenv("KALSHI_ACCESS_KEY")
PRIVATE_KEY_PEM = os.getenv("KALSHI_PRIVATE_KEY")

THRESHOLD = 1.0
COUNT = 1
CHECK_INTERVAL = 30

TEST_TICKER = "TRUMPWIN-28"  # Change to a current open market ticker if needed
# ======================================================

print("BOT STARTUP - DEBUG ACTIVE")
print(f"ACCESS_KEY: {'Set' if ACCESS_KEY else 'MISSING'}")
print(f"PRIVATE_KEY_PEM length: {len(PRIVATE_KEY_PEM) if PRIVATE_KEY_PEM else 'MISSING'}")

try:
    private_key = serialization.load_pem_private_key(PRIVATE_KEY_PEM.encode(), password=None)
    print("Private key loaded OK")
except Exception as e:
    print(f"PRIVATE KEY LOAD FAILED: {e}")
    raise

def sign_request(method, path):
    now = datetime.now(timezone.utc)
    timestamp_ms = str(int(now.timestamp() * 1000))
    payload = timestamp_ms + method.upper() + path
    signature = private_key.sign(
        payload.encode(),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256()
    )
    sig_b64 = base64.b64encode(signature).decode()
    return timestamp_ms, sig_b64

def kalshi_request(method, endpoint, json_body=None):
    url = BASE_URL + endpoint
    timestamp, signature = sign_request(method, endpoint)
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
        print(f"{method} {endpoint} -> {resp.status_code}")
        if resp.status_code >= 400:
            print(f"Response body: {resp.text}")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"REQUEST FAILED: {e}")
        raise

def has_open_positions():
    try:
        data = kalshi_request("GET", "/portfolio/positions")
        positions = data.get("positions", [])
        open_pos = [p for p in positions if p.get("quantity", 0) > 0]
        if open_pos:
            print(f" HOLDING {len(open_pos)} positions")
        return len(open_pos) > 0
    except:
        print("Positions check failed")
        return False

def find_best_arb():
    try:
        data = kalshi_request("GET", "/markets?status=open&limit=1000")
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
    except:
        print("Markets fetch failed")
        return None

def execute_arb(action, ticker, price1, price2, profit):
    print(f"EXECUTING {action.upper()} ARB on {ticker} +{profit}¢")
    yes_payload = {"ticker": ticker, "action": action, "type": "limit", "count": COUNT, "side": "yes"}
    yes_payload["yes_price" if action == "buy" else "no_price"] = price1
    kalshi_request("POST", "/portfolio/orders", yes_payload)
    time.sleep(0.3)
    no_payload = {"ticker": ticker, "action": action, "type": "limit", "count": COUNT, "side": "no"}
    no_payload["no_price" if action == "buy" else "yes_price"] = price2
    kalshi_request("POST", "/portfolio/orders", no_payload)
    print("ARB orders placed!")

def execute_test_trade():
    print("TEST MODE - Placing dummy YES buy at 1 cent on " + TEST_TICKER)
    test_payload = {
        "ticker": TEST_TICKER,
        "action": "buy",
        "type": "limit",
        "count": 1,
        "side": "yes",
        "yes_price": 1  # Very low price - should not fill, no risk
    }
    kalshi_request("POST", "/portfolio/orders", test_payload)
    print("Test order submitted! Check Kalshi app → Portfolio → Orders (cancel if needed)")

print("STARTUP COMPLETE")

if TEST_MODE:
    execute_test_trade()
    print("Test done - set TEST_MODE = False and redeploy for arb mode")
else:
    while True:
        try:
            print(f"SCAN {time.strftime('%H:%M:%S')}")
            if has_open_positions():
                time.sleep(CHECK_INTERVAL)
                continue
            opp = find_best_arb()
            if opp:
                action, ticker, p1, p2, profit = opp
                execute_arb(action, ticker, p1, p2, profit)
            else:
                print("No arb found")
            time.sleep(CHECK_INTERVAL)
        except Exception as e:
            print(f"LOOP ERROR: {e}")
            time.sleep(60)
