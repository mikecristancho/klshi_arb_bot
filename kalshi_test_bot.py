import requests
import time
import os
import json
import base64
from datetime import datetime, timezone
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

# ==================== CONFIGURATION ====================
TEST_MODE = True

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

ACCESS_KEY = os.getenv("KALSHI_ACCESS_KEY")
PRIVATE_KEY_PEM = os.getenv("KALSHI_PRIVATE_KEY")

THRESHOLD = 1.0
COUNT = 1
CHECK_INTERVAL = 30

TEST_TICKER = "TRUMPWIN-28"  # Verify this is a current open market
# ======================================================

print("BOT STARTUP - DEBUG ACTIVE")
print(f"ACCESS_KEY: {'Set' if ACCESS_KEY else 'MISSING'}")
print(f"PRIVATE_KEY length: {len(PRIVATE_KEY_PEM) if PRIVATE_KEY_PEM else 'MISSING'}")

try:
    private_key = serialization.load_pem_private_key(PRIVATE_KEY_PEM.encode(), password=None)
    print("Private key loaded OK")
except Exception as e:
    print(f"KEY LOAD ERROR: {e}")
    raise

def canonical_json(body):
    if not body:
        return ""
    return json.dumps(body, separators=(',', ':'), sort_keys=True)

def sign_request(method, path, body=None):
    now = datetime.now(timezone.utc)
    timestamp_ms = str(int(now.timestamp() * 1000))
    body_str = canonical_json(body)
    payload = timestamp_ms + method.upper() + path + body_str
    print(f"Payload for signing: {payload[:100]}...")  # Debug
    signature = private_key.sign(
        payload.encode(),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256()
    )
    sig_b64 = base64.b64encode(signature).decode()
    return timestamp_ms, sig_b64

def kalshi_request(method, endpoint, json_body=None):
    url = BASE_URL + endpoint
    timestamp, signature = sign_request(method, endpoint, json_body)
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
            print(f"Error body: {resp.text}")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"REQUEST FAILED: {e}")
        raise

# Functions same as before, using /portfolio/orders
# ... (has_open_positions, find_best_arb, execute_arb with /portfolio/orders)

def execute_test_trade():
    print("TEST MODE - Dummy YES buy at 1 cent")
    test_payload = {
        "ticker": TEST_TICKER,
        "action": "buy",
        "type": "limit",
        "count": 1,
        "side": "yes",
        "yes_price": 1
    }
    kalshi_request("POST", "/portfolio/orders", test_payload)
    print("Test order submitted - check Kalshi app")

print("STARTUP COMPLETE")

if TEST_MODE:
    execute_test_trade()
    print("Test order submitted! Check your Kalshi account → Orders tab (cancel the test order if it appears)")
    print("Once test works, set TEST_MODE = False and redeploy for full arbitrage mode")
else:
    print("FULL ARB MODE ACTIVE - Scanning every 30 seconds")
    while True:
        try:
            print(f"\n🔍 SCAN START {time.strftime('%H:%M:%S')}")
            if has_open_positions():
                print("Position open - waiting for settlement")
                time.sleep(CHECK_INTERVAL)
                continue

            opp = find_best_arb()
            if opp:
                action, ticker, p1, p2, profit = opp
                print(f"💰 ARB FOUND: {ticker} | {action.upper()} | +{profit}¢ profit")
                execute_arb(action, ticker, p1, p2, profit)
            else:
                print("😴 No arbitrage opportunity found this cycle")

            print(f"Next scan in {CHECK_INTERVAL} seconds...")
            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            print(f"❌ LOOP ERROR: {e}")
            time.sleep(60)
