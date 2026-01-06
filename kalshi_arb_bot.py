import requests
import time
import os

# ==================== CONFIGURATION ====================
# LIVE MODE - REAL MONEY!
BASE_URL = "https://trading-api.kalshi.com/trade-api/v2"

# Use environment variables (set these in Render dashboard!)
EMAIL = os.getenv("KALSHI_EMAIL")
PASSWORD = os.getenv("KALSHI_PASSWORD")

THRESHOLD = 1.0        # Minimum guaranteed profit in cents (e.g., 1¢+ after fees)
COUNT = 1              # Start with 1 contract only!
CHECK_INTERVAL = 60    # Check every 60 seconds
# ======================================================

def login():
    url = f"{BASE_URL}/login"
    payload = {"email": EMAIL, "password": PASSWORD}
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        print("✅ Logged in to LIVE Kalshi account")
        return response.json()["token"]
    else:
        raise Exception(f"Login failed: {response.status_code} {response.text}")

def has_open_positions(token):
    """Returns True if you have any open positions"""
    url = f"{BASE_URL}/portfolio/positions"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        positions = resp.json().get("positions", [])
        open_pos = [p for p in positions if p["quantity"] > 0]
        if open_pos:
            print(f"⏳ Holding {len(open_pos)} position(s) — waiting for settlement")
        return len(open_pos) > 0
    else:
        print("Could not check positions")
        return False

def find_best_arb(token):
    url = f"{BASE_URL}/markets?status=open&limit=1000"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        return None

    best = None
    best_profit = 0

    for m in resp.json()["markets"]:
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

def execute_arb(token, action, ticker, price1, price2):
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{BASE_URL}/orders"

    # Order 1: Yes side
    p1 = {"ticker": ticker, "action": action, "type": "limit", "count": COUNT, "side": "yes"}
    p1["yes_price" if action == "buy" else "no_price"] = price1  # buy yes at ask, sell yes at bid

    # Order 2: No side
    p2 = {"ticker": ticker, "action": action, "type": "limit", "count": COUNT, "side": "no"}
    p2["no_price" if action == "buy" else "yes_price"] = price2

    print(f"🚀 EXECUTING {action.upper()} ARB on {ticker} — Expected profit: {best_profit}¢")

    # Place orders quickly
    r1 = requests.post(url, headers=headers, json=p1)
    time.sleep(0.3)
    r2 = requests.post(url, headers=headers, json=p2)

    print("Order 1 (YES):", "SUCCESS" if r1.status_code == 200 else f"FAIL {r1.text}")
    print("Order 2 (NO): ", "SUCCESS" if r2.status_code == 200 else f"FAIL {r2.text}")

# ==================== MAIN LOOP ====================
if not EMAIL or not PASSWORD:
    raise ValueError("You MUST set KALSHI_EMAIL and KALSHI_PASSWORD in environment variables!")

print("🔴 LIVE KALSHI ARB BOT STARTED — ONE POSITION ONLY")
token = login()

while True:
    try:
        if has_open_positions(token):
            time.sleep(CHECK_INTERVAL)
            continue

        opp = find_best_arb(token)
        if opp:
            action, ticker, p1, p2, best_profit = opp
            print(f"💰 BEST ARB FOUND: {ticker} → {action.upper()} → +{best_profit}¢ profit")
            execute_arb(token, action, ticker, p1, p2)
        else:
            print("😴 No arbitrage opportunities above threshold")

        print(f"Next check in {CHECK_INTERVAL}s...\n")
        time.sleep(CHECK_INTERVAL)

    except Exception as e:
        print(f"❌ ERROR: {e}")
        time.sleep(30)
        try:
            token = login()
        except:
            print("Re-login failed — waiting")
            time.sleep(60)
