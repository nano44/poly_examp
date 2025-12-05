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
POLY_TARGET_SYMBOL = "btcusdt"       # For the fast feed
CHAINLINK_TARGET_SYMBOL = "btc/usd"  # For the oracle feed (Note the slash!)

# -----------------------------------------------------------------------------
# LATENCY MEASUREMENT STRATEGY
# -----------------------------------------------------------------------------
class LatencyStrategy:
    def __init__(self):
        self.binance_memory = {}
        self.latest_binance_price = 0
        self.latest_binance_time = 0

    def on_binance_data(self, price):
        now = time.time()
        # Round to 1 decimal to be generous with matching
        rounded_price = round(price, 1)
        
        if rounded_price not in self.binance_memory:
            self.binance_memory[rounded_price] = now
            # Keep memory small
            if len(self.binance_memory) > 1000:
                keys = list(self.binance_memory.keys())[:100]
                for k in keys: del self.binance_memory[k]

        self.latest_binance_price = price
        self.latest_binance_time = now

    def on_poly_data(self, poly_price):
        now = time.time()
        rounded_poly = round(poly_price, 1)
        
        if rounded_poly in self.binance_memory:
            first_seen = self.binance_memory[rounded_poly]
            lag_ms = (now - first_seen) * 1000
            
            if lag_ms > 1000: status = "🔴 MASSIVE LAG"
            elif lag_ms > 200: status = "🟠 SLOW"
            elif lag_ms > 50: status = "🟡 DELAYED"
            else: status = "🟢 FAST"

            print(f"{status}: Poly Fast Feed: {rounded_poly}. Lag: {lag_ms:.1f}ms")
        else:
            diff = poly_price - self.latest_binance_price
            print(f"⚪ UNMATCHED: Poly: {poly_price} | Binance: {self.latest_binance_price:.2f}")

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
                    mid = (float(data["b"]) + float(data["a"])) / 2.0
                    strategy.on_binance_data(mid)
                    
        except Exception as e:
            print(f"⚡ Binance Error: {e}")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 10)

# -----------------------------------------------------------------------------
# TASK 2: POLYMARKET DUAL STREAM (Fast + Chainlink)
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
                
                # SUBSCRIBE TO BOTH TOPICS
                # We use the "No Filter" approach for both to ensure connection,
                # then we filter client-side.
                sub_msg = {
                    "action": "subscribe", 
                    "subscriptions": [
                        {"topic": "crypto_prices", "type": "update"},            # Fast Feed
                        {"topic": "crypto_prices_chainlink", "type": "update"}   # Chainlink Feed
                    ]
                }
                await ws.send(json.dumps(sub_msg))
                print("🔷 Subscribed to Fast Feed + Chainlink Feed")

                while True:
                    response = await ws.recv()
                    if not response: continue
                    
                    data = json.loads(response)
                    msg_type = data.get("type")
                    topic = data.get("topic")
                    payload = data.get("payload", {})

                    # 1. HANDLE FAST FEED (Binance Source)
                    if topic == "crypto_prices" and msg_type == "update":
                        if payload.get("symbol") == POLY_TARGET_SYMBOL:
                            price = payload.get("value")
                            strategy.on_poly_data(price)

                    # 2. HANDLE CHAINLINK FEED (Oracle Source)
                    elif topic == "crypto_prices_chainlink" and msg_type == "update":
                        # Client-side filter for btc/usd
                        if payload.get("symbol") == CHAINLINK_TARGET_SYMBOL:
                            price = payload.get("value")
                            ts = payload.get("timestamp")
                            print(f"🔗 CHAINLINK UPDATE: {price} (TS: {ts})")
                        
                        # Debug: Print ALL chainlink symbols just to see if it works
                        # else:
                        #    print(f"🔗 Ignored Chainlink: {payload.get('symbol')}")

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