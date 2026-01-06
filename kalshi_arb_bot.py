import requests
import time
import os

# ==================== CONFIGURATION ====================
DEMO_MODE = True  # Set to False ONLY when ready for live trading (use real money at your own risk!)

BASE_URL = "https://demo-api.kalshi.com/trade-api/v2" if DEMO_MODE else "https://trading-api.kalshi.com/trade-api/v2"

# Use environment variables for security (recommended!)
EMAIL = os.getenv("KALSHI_EMAIL")      # e.g., "you@example.com"
PASSWORD = os.getenv("KALSHI_PASSWORD")  # your Kalshi password

# If not using env vars, uncomment and fill below (less secure):
# EMAIL = "your_email@example.com"
# PASSWORD = "your_password"

THRESHOLD = 2          # Minimum profit in cents to trigger a trade (covers fees/slippage)
COUNT = 1              # Number of contracts per side (keep small, especially testing!)
CHECK_INTERVAL = 30    # Seconds between full market scans
# ======================================================

def login():
    url = f"{BASE_URL}/login"
    payload = {"email": EMAIL, "password": PASSWORD}
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        token = response.json()["token"]
        print("Login successful!")
        return token
    else:
        raise Exception(f"Login failed: {response.status_code} - {response.text}")

def get_open_markets(token):
    url = f"{BASE_URL}/markets?status=open&limit=500"  # Kalshi usually has <500 open markets
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()["markets"]
    else:
        raise Exception(f"Failed to fetch markets: {response.text}")

def place_order(token, ticker, action, side, price_cents, count):
    url = f"{BASE_URL}/orders"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "ticker": ticker,
        "action": action,      # "buy" or "sell"
        "type": "limit",
        "count": count,
        "side": side           # "yes" or "no"
    }
    if side == "yes":
        payload["yes_price"] = price_cents
    else:
        payload["no_price"] = price_cents

    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        print(f"SUCCESS: {action.upper()} {count} {side.upper()} contract(s) on {ticker} at {price_cents} cents")
    else:
        print(f"Order failed on {ticker}: {response.status_code} - {response.text}")

# ==================== MAIN LOOP ====================
if not EMAIL or not PASSWORD:
    raise ValueError("Please set KALSHI_EMAIL and KALSHI_PASSWORD environment variables!")

token = login()

while True:
    try:
        print(f"\nScanning markets... ({time.strftime('%Y-%m-%d %H:%M:%S')})")
        markets = get_open_markets(token)

        for market in markets:
            ticker = market["ticker"]
            yes_ask = market.get("yes_ask")
            no_ask = market.get("no_ask")
            yes_bid = market.get("yes_bid")
            no_bid = market.get("no_bid")

            # Buy arbitrage: yes_ask + no_ask < 100 - THRESHOLD
            if yes_ask and no_ask and (yes_ask + no_ask) < (100 - THRESHOLD):
                profit = 100 - (yes_ask + no_ask)
                print(f"BUY ARB FOUND on {ticker}: Profit {profit} cents")
                place_order(token, ticker, "buy", "yes", yes_ask, COUNT)
                place_order(token, ticker, "buy", "no", no_ask, COUNT)

            # Sell arbitrage: yes_bid + no_bid > 100 + THRESHOLD
            if yes_bid and no_bid and (yes_bid + no_bid) > (100 + THRESHOLD):
                profit = (yes_bid + no_bid) - 100
                print(f"SELL ARB FOUND on {ticker}: Profit {profit} cents")
                place_order(token, ticker, "sell", "yes", yes_bid, COUNT)
                place_order(token, ticker, "sell", "no", no_bid, COUNT)

        print(f"Scan complete. Sleeping {CHECK_INTERVAL} seconds...\n")

    except Exception as e:
        print(f"Error: {e}")
        print("Attempting to re-login...")
        try:
            token = login()
        except:
            print("Re-login failed. Waiting before retry...")
    
    time.sleep(CHECK_INTERVAL)