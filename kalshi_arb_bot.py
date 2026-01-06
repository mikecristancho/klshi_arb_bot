import requests
import time
import os

# ==================== CONFIGURATION ====================
# LIVE MODE - NEW ENDPOINT AFTER MIGRATION
BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

# Environment variables (set in Render)
EMAIL = os.getenv("KALSHI_EMAIL")
PASSWORD = os.getenv("KALSHI_PASSWORD")

THRESHOLD = 1.0        # Min profit in cents
COUNT = 1              # Keep small!
CHECK_INTERVAL = 60
# ======================================================

def login():
    url = f"{BASE_URL}/login"
    payload = {"email": EMAIL, "password": PASSWORD}
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        print("✅ Logged in to LIVE Kalshi (new endpoint)")
        return response.json()["token"]
    else:
        raise Exception(f"Login failed: {response.status_code} {response.text}")

def has_open_positions(token):
    url = f"{BASE_URL}/portfolio/positions"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        positions = resp.json().get("positions", [])
        open_pos = [p for p in positions if p.get("quantity", 0) > 0]
        if open_pos:
            print(f"⏳ Holding {len(open_pos)} open position(s)")
        return len(open_pos) > 0
    else:
        print(f"Position check failed: {resp.text}")
        return False

def find_best_arb(token):
    url = f"{BASE_URL}/markets?status=open&limit=1000"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        print(f"Markets fetch failed: {resp.text}")
        return None

    best = None
    best_profit = 0

    for m in resp.json()["markets"]:
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

def execute_arb(token, action, ticker, price1, price2, profit):
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{BASE_URL}/orders"

    # Yes side
    p1 = {"ticker": ticker, "action": action, "type": "limit", "count": COUNT, "side": "yes"}
    p1["yes_price" if action == "buy" else "no_price"] = price1

    # No side
    p2 = {"ticker": ticker, "action": action, "type": "limit", "count": COUNT, "side": "no"}
    p2["no_price" if action == "buy" else "yes_price"] = price2

    print(f"🚀 EXECUTING {action.upper()} ARB on {ticker} — +{profit}¢ profit")

    r1 = requests.post(url, headers=headers, json=p1)
    time.sleep(0.3)
    r2 = requests.post(url, headers=headers, json=p2)

    print("YES order:", "OK" if r1.status_code == 200 else f"FAIL {r1.text}")
    print("NO order: ", "OK" if r2.status_code == 200 else f"FAIL {r2.text}")

# ==================== MAIN LOOP ====================
if not EMAIL or not PASSWORD:
    raise ValueError("Set KALSHI_EMAIL and KALSHI_PASSWORD env vars!")

print("🔴 LIVE KALSHI ARB BOT (One Position Only) - NEW ENDPOINT")
token = login()

while True:
    try:
        if has_open_positions(token):
            time.sleep(CHECK_INTERVAL)
            continue

        opp = find_best_arb(token)
        if opp:
            action, ticker, p1, p2, profit = opp
            print(f"💰 BEST ARB: {ticker} → {action.upper()} → +{profit}¢")
            execute_arb(token, action, ticker, p1, p2, profit)
        else:
            print("😴 No arbs found above threshold")

        time.sleep(CHECK_INTERVAL)

    except Exception as e:
        print(f"❌ ERROR: {e}")
        time.sleep(30)
        try:
            token = login()
        except:
            time.sleep(60)
