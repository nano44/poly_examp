import asyncio
import websockets
import json
import os
import time
from collections import deque

# -----------------------------------------------------------------------------
# CONFIGURATION
# -----------------------------------------------------------------------------
try:
    import orjson as json_parser
except ImportError:
    import json as json_parser

BINANCE_STREAM = os.getenv("BINANCE_STREAM", "btcusdt@bookTicker")
POLY_TARGET_SYMBOL = "btcusdt" 

# -----------------------------------------------------------------------------
# LATENCY MEASUREMENT STRATEGY
# -----------------------------------------------------------------------------
class LatencyStrategy:
    def __init__(self):
        # Stores the time we first saw a specific price on Binance
        # Key: Price (rounded to 2 decimals), Value: Local Timestamp
        self.binance_memory = {}
        self.latest_binance_price = 0
        self.latest_binance_time = 0

    def on_binance_data(self, price):
        now = time.time()
        
        # Round to 2 decimals because Polymarket data is less precise
        rounded_price = round(price, 1)
        
        # Save the FIRST time we see this price level
        if rounded_price not in self.binance_memory:
            self.binance_memory[rounded_price] = now
            
            # Maintenance: Keep memory small (remove old prices)
            if len(self.binance_memory) > 1000:
                # Remove 100 oldest items roughly (casting to list is expensive but fine here)
                keys = list(self.binance_memory.keys())[:100]
                for k in keys: del self.binance_memory[k]

        self.latest_binance_price = price
        self.latest_binance_time = now
        
        # Optional: Print every 50th tick just to show it's alive
        # print(f"⚡ Binance Live: {price:.2f}")

    def on_poly_data(self, poly_price):
        now = time.time()
        
        # Round Poly to match our map keys
        rounded_poly = round(poly_price, 1)
        
        # 1. Check if we saw this price on Binance already
        if rounded_poly in self.binance_memory:
            first_seen = self.binance_memory[rounded_poly]
            lag_seconds = now - first_seen
            lag_ms = lag_seconds * 1000
            
            # Color code the output
            if lag_ms > 1000:
                status = "🔴 MASSIVE LAG"
            elif lag_ms > 200:
                status = "🟠 SLOW"
            elif lag_ms > 50:
                status = "🟡 DELAYED"
            else:
                status = "🟢 FAST"

            print(f"{status}: Poly just showed {rounded_poly}. Binance had this {lag_ms:.1f}ms ago.")
            
        else:
            # This happens if Poly price is actually AHEAD of Binance (Rare) 
            # or if Binance jumped over this price without stopping
            diff = poly_price - self.latest_binance_price
            print(f"⚪ NEW/UNMATCHED: Poly: {poly_price} | Binance is at {self.latest_binance_price:.2f} (Diff: {diff:.2f})")

strategy = LatencyStrategy()

# -----------------------------------------------------------------------------
# TASK 1: BINANCE STREAM
# -----------------------------------------------------------------------------
async def run_binance():
    url = f"wss://stream.binance.com/ws/{BINANCE_STREAM}"
    backoff = 1
    print(f"--- Starting Binance Stream ({BINANCE_STREAM}) ---")
    
    while True:
        try:
            async with websockets.connect(url, max_queue=1) as ws:
                print("⚡ Binance Connected")
                backoff = 1
                async for msg in ws:
                    data = json_parser.loads(msg)
                    # Mid Price Calculation: (Bid + Ask) / 2
                    mid = (float(data["b"]) + float(data["a"])) / 2.0
                    strategy.on_binance_data(mid)
                    
        except Exception as e:
            print(f"⚡ Binance Error: {e}")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 10)

# -----------------------------------------------------------------------------
# TASK 2: POLYMARKET STREAM
# -----------------------------------------------------------------------------
async def run_polymarket():
    url = "wss://ws-live-data.polymarket.com"
    backoff = 1
    print(f"--- Starting Polymarket Stream ---")

    while True:
        try:
            async with websockets.connect(url) as ws:
                print("🔷 Polymarket Connected")
                backoff = 1
                
                # "Firehose" Subscription (Safest method)
                sub_msg = {"action": "subscribe", "subscriptions": [{"topic": "crypto_prices", "type": "update"}]}
                await ws.send(json.dumps(sub_msg))

                while True:
                    response = await ws.recv()
                    if not response: continue
                    
                    data = json.loads(response)
                    
                    if data.get("type") == "update":
                        payload = data.get("payload", {})
                        # Filter only for BTCUSDT
                        if payload.get("symbol") == POLY_TARGET_SYMBOL:
                            price = payload.get("value")
                            strategy.on_poly_data(price)

        except Exception as e:
            print(f"🔷 Poly Error: {e}")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 10)

# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
async def main():
    await asyncio.gather(run_binance(), run_polymarket())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped by user.")