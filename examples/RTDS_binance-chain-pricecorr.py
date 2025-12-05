import asyncio
import websockets
import json
import os
import time
import csv
import math
from collections import deque

# -----------------------------------------------------------------------------
# CONFIGURATION
# -----------------------------------------------------------------------------
# Trigger a "Jump Event" if Binance moves this % in under 5 seconds
JUMP_THRESHOLD_PERCENT = 0.1 
JUMP_WINDOW_SECONDS = 5.0

# How many ticks to keep for the rolling correlation calculation
CORRELATION_WINDOW = 1000 

try:
    import orjson as json_parser
except ImportError:
    import json as json_parser

BINANCE_STREAM = os.getenv("BINANCE_STREAM", "btcusdt@bookTicker")
CHAINLINK_TARGET_SYMBOL = "btc/usd"

# -----------------------------------------------------------------------------
# STATS ENGINE
# -----------------------------------------------------------------------------
class MarketLogger:
    def __init__(self):
        # CSV Logging
        self.csv_file = open('market_data.csv', 'w', newline='')
        self.writer = csv.writer(self.csv_file)
        self.writer.writerow(["timestamp", "source", "price", "binance_price_at_time"])
        
        # Real-time Stats
        self.binance_price = None
        self.chainlink_price = None
        
        # Correlation Data (Binance Price, Chainlink Price)
        self.history = deque(maxlen=CORRELATION_WINDOW)
        
        # Jump Detection
        self.binance_window = deque() # Stores (price, timestamp) for jump detection

    def log_binance(self, price):
        self.binance_price = price
        now = time.time()
        
        # 1. Log to CSV
        self.writer.writerow([now, "BINANCE", price, price])
        self.csv_file.flush() # Ensure data is saved immediately
        
        # 2. Update Correlation History (Pair with last known Chainlink)
        if self.chainlink_price:
            self.history.append((price, self.chainlink_price))
            
        # 3. Detect Jumps
        self.binance_window.append((price, now))
        # Remove old ticks (> 5 seconds ago)
        while self.binance_window and now - self.binance_window[0][1] > JUMP_WINDOW_SECONDS:
            self.binance_window.popleft()
            
        # Check delta in window
        if self.binance_window:
            oldest_price = self.binance_window[0][0]
            pct_change = abs(price - oldest_price) / oldest_price * 100
            
            if pct_change > JUMP_THRESHOLD_PERCENT:
                # We found a jump!
                return True, pct_change
        
        return False, 0.0

    def log_chainlink(self, price):
        self.chainlink_price = price
        now = time.time()
        
        # 1. Log to CSV
        self.writer.writerow([now, "CHAINLINK", price, self.binance_price])
        self.csv_file.flush()
        
        # 2. Update Correlation History
        if self.binance_price:
            self.history.append((self.binance_price, price))

    def get_correlation(self):
        # Calculate Pearson Correlation Coefficient manually
        if len(self.history) < 100: return 0.0
        
        n = len(self.history)
        sum_x = sum(x for x, y in self.history)
        sum_y = sum(y for x, y in self.history)
        sum_xy = sum(x*y for x, y in self.history)
        sum_x_sq = sum(x*x for x, y in self.history)
        sum_y_sq = sum(y*y for x, y in self.history)
        
        numerator = (n * sum_xy) - (sum_x * sum_y)
        denominator = math.sqrt((n * sum_x_sq - sum_x**2) * (n * sum_y_sq - sum_y**2))
        
        if denominator == 0: return 0.0
        return numerator / denominator

logger = MarketLogger()

# -----------------------------------------------------------------------------
# TASKS
# -----------------------------------------------------------------------------
async def run_binance():
    url = f"wss://stream.binance.com/ws/{BINANCE_STREAM}"
    print(f"--- Logging Binance ({BINANCE_STREAM}) ---")
    
    while True:
        try:
            async with websockets.connect(url, max_queue=1) as ws:
                async for msg in ws:
                    data = json_parser.loads(msg)
                    mid = (float(data["b"]) + float(data["a"])) / 2.0
                    
                    is_jump, magnitude = logger.log_binance(mid)
                    
                    if is_jump:
                        # Only print if it's a NEW jump (debounce slightly by checking console output frequency yourself or simplified here)
                        print(f"🚨 BINANCE JUMP: Moved {magnitude:.3f}% in 5s! Waiting for Chainlink...")

                    # Print Correlation every ~100 updates
                    if int(time.time()) % 10 == 0: # Every 10 seconds approx
                        corr = logger.get_correlation()
                        # \r overwrites the line for a cleaner dashboard effect
                        print(f"📊 Live Correlation (Last {CORRELATION_WINDOW} ticks): {corr:.4f}   |   Binance: ${mid:.2f}   ", end="\r")

        except Exception as e:
            print(f"Binance Error: {e}")
            await asyncio.sleep(1)

async def run_chainlink():
    url = "wss://ws-live-data.polymarket.com"
    print(f"--- Logging Chainlink ({CHAINLINK_TARGET_SYMBOL}) ---")

    while True:
        try:
            async with websockets.connect(url) as ws:
                sub_msg = {"action": "subscribe", "subscriptions": [{"topic": "crypto_prices_chainlink", "type": "update"}]}
                await ws.send(json.dumps(sub_msg))

                while True:
                    response = await ws.recv()
                    if not response: continue
                    data = json.loads(response)
                    
                    if data.get("type") == "update":
                        payload = data.get("payload", {})
                        if payload.get("symbol") == CHAINLINK_TARGET_SYMBOL:
                            price = payload.get("value")
                            ts = payload.get("timestamp")
                            
                            logger.log_chainlink(price)
                            
                            # Visual feedback
                            print(f"\n🔗 CHAINLINK UPDATE: ${price:.2f} (Recorded to CSV)")

        except Exception as e:
            print(f"Poly Error: {e}")
            await asyncio.sleep(1)

async def main():
    await asyncio.gather(run_binance(), run_chainlink())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nLogger stopped. Data saved to 'market_data.csv'.")