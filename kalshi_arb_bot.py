import requests
import time
import os

# ==================== CONFIGURATION ====================
DEMO_MODE = True  # Set False for live (your risk!)
BASE_URL = "https://demo-api.kalshi.co/trade-api/v2" if DEMO_MODE else "https://trading-api.kalshi.com/trade-api/v2"

EMAIL = os.getenv("KALSHI_EMAIL")
PASSWORD = os.getenv("KALSHI_PASSWORD")

THRESHOLD = 1.5      # Min profit % (1.5 cents = 1.5% guaranteed)
COUNT = 1            # 1 contract only
CHECK_INTERVAL = 60  # Check every minute
# ======================================================

def login():
    url = f"{BASE_URL}/login"
    payload = {"email": EMAIL, "password": PASSWORD}
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        print("✅ Login OK")
        return response.json()["token"]
    raise Exception(f"Login failed: {response.text}")

def get_positions(token):
    """Check if we have ANY open positions"""
    url = f"{BASE_URL}/portfolio/positions"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        positions = response.json().get("positions", [])
        return len(positions) > 0
    return False

def get_best_arb(token):
    """Find BEST arbitrage opportunity"""
    url = f"{BASE_URL}/markets?status=open&limit=1000"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        return None
    
    best_opp = None
    best_profit = 0
    
    for market in response.json()["markets"]:
        ticker = market["ticker"]
        yes_ask = market.get("yes_ask")
        no_ask = market.get("no_ask")
        yes_bid = market.get("yes_bid")
        no_bid = market.get("no_bid")
        
        # Buy Arb: Buy yes + buy no < 100
        if yes_ask and no_ask and yes_ask + no_ask < 100:
            profit = 100 - (yes_ask + no_ask)
            if profit > best_profit and profit >= THRESHOLD:
                best_opp = ("buy", ticker, yes_ask, no_ask, profit)
                best_profit = profit
        
        # Sell Arb: Sell yes + sell no > 100  
        if yes_bid and no_bid and yes_bid + no_bid > 100:
            profit = (yes_bid + no_bid) - 100
            if profit > best_profit and profit >= THRESHOLD:
                best_opp = ("sell", ticker, yes_bid, no_bid, profit)
                best_profit = profit
    
    return best_opp

def place_arb_orders(token, action, ticker, price_yes, price_no):
    """Place paired arbitrage orders"""
    headers = {"Authorization": f"Bearer {token}"}
    
    # Yes order
    yes_payload = {
        "ticker": ticker, "action": action, "type": "limit", 
        "count": COUNT, "side": "yes"
    }
    if action == "buy":
        yes_payload["yes_price"] = price_yes
    else:
        yes_payload["no_price"] = price_yes  # sell yes at bid
    
    # No order  
    no_payload = {
        "ticker": ticker, "action": action, "type": "limit", 
        "count": COUNT, "side": "no"
    }
    if action == "buy":
        no_payload["no_price"] = price_no
    else:
        no_payload["yes_price"] = price_no  # sell no at bid
    
    # Place orders
    requests.post(f"{BASE_URL}/orders", headers=headers, json=yes_payload)
    time.sleep(0.5)
    requests.post(f"{BASE_URL}/orders", headers=headers, json=no_payload)
    print(f"🎯 ARB TRADE: {action.upper()} {COUNT}x {ticker} (profit: {price_yes + price_no - 100 if action=='sell' else 100 - (price_yes + price_no):.1f}¢)")

# ==================== MAIN BOT ====================
if not EMAIL or not PASSWORD:
    raise ValueError("Set KALSHI_EMAIL and KALSHI_PASSWORD env vars!")

print("🚀 Product Bot Started - ONE POSITION ONLY")
token = login()

while True:
    try:
        # SAFETY CHECK: Any open positions?
        if get_positions(token):
            print("⏳ Holding position... waiting to close")
        else:
            # Find best arb
            opp = get_best_arb(token)
            if opp:
                action, ticker, p1, p2, profit = opp
                print(f"💰 BEST ARB: {ticker} | Profit: {profit}¢ | {action.upper()}")
                place_arb_orders(token, action, ticker, p1, p2)
            else:
                print("😴 No good arbs found")
        
        print(f"Sleeping {CHECK_INTERVAL}s... " + time.strftime('%H:%M:%S'))
        time.sleep(CHECK_INTERVAL)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        time.sleep(30)
        token = login()
