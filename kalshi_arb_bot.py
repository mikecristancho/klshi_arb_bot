import requests
import time
import os
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
import base64
import json
from datetime import datetime

# ==================== CONFIGURATION ====================
BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

# Set in Render environment variables
ACCESS_KEY = os.getenv("KALSHI_ACCESS_KEY")      # Your public Access Key
PRIVATE_KEY_PEM = os.getenv("KALSHI_PRIVATE_KEY") # Full PEM private key as string (multi-line ok)

THRESHOLD = 1.0
COUNT = 1
CHECK_INTERVAL = 60
# ======================================================

def load_private_key():
    if not PRIVATE_KEY_PEM:
        raise ValueError("Set KALSHI_PRIVATE_KEY env var with your full PEM key")
    return serialization.load_pem_private_key(PRIVATE_KEY_PEM.encode(), password=None)

private_key = load_private_key()

def sign_request(method, path, body=""):
    timestamp = str(int(datetime.utcnow().timestamp() * 1000))
    payload = timestamp + method.upper() + path + body
    signature = private_key.sign(
        payload.encode(),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256()
    )
    sig_b64 = base64.b64encode(signature).decode()
    return timestamp, sig_b64

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
    
    if resp.status_code != 200:
        raise Exception(f"{method} {endpoint} failed: {resp.status_code} {resp.text}")
    return resp.json()

# ==================== BOT FUNCTIONS ====================
def has_open_positions():
    data = kalshi_request("GET", "/portfolio/positions")
    positions = data.get("positions", [])
    open_pos = [p for p in positions if p.get("quantity", 0) > 0]
    if open_pos:
        print(f"⏳ Holding {len(open_pos)} position(s)")
    return len(open_pos) > 0

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

def execute_arb(action, ticker, price1, price2, profit):
    print(f"🚀 EXECUTING {action.upper()} ARB on {ticker} — +{profit}¢ profit")
    
    # Yes order
    yes_payload = {"ticker": ticker, "action": action, "type": "limit", "count": COUNT, "side": "yes"}
    yes_payload["yes_price" if action == "buy" else "no_price"] = price1
    kalshi_request("POST", "/orders", yes_payload)
    
    time.sleep(0.3)
    
    # No order
    no_payload = {"ticker": ticker, "action": action, "type": "limit", "count": COUNT, "side": "no"}
    no_payload["no_price" if action == "buy" else "yes_price"] = price2
    kalshi_request("POST", "/orders", no_payload)
    
    print("Orders placed!")

# ==================== MAIN LOOP ====================
if not ACCESS_KEY:
    raise ValueError("Set KALSHI_ACCESS_KEY and KALSHI_PRIVATE_KEY env vars!")

print("🔴 LIVE KALSHI ARB BOT (One Position Only) - API KEY AUTH")
print("Authenticated successfully")

while True:
    try:
        if has_open_positions():
            time.sleep(CHECK_INTERVAL)
            continue
        
        opp = find_best_arb()
        if opp:
            action, ticker, p1, p2, profit = opp
            print(f"💰 BEST ARB: {ticker} → +{profit}¢")
            execute_arb(action, ticker, p1, p2, profit)
        else:
            print("😴 No arbs found")
        
        time.sleep(CHECK_INTERVAL)
    
    except Exception as e:
        print(f"❌ ERROR: {e}")
        time.sleep(60)
