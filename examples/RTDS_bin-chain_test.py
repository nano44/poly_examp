import asyncio
import websockets
import json
import os
import time

# -----------------------------------------------------------------------------
# CONFIGURATION
# -----------------------------------------------------------------------------
# Triggers a timer when Binance moves this % away from the last known Chainlink price
DEVIATION_THRESHOLD_PERCENT = 0.1 

# Throttling: Only print Binance updates if price moves by more than this $ amount
# (Prevents your terminal from freezing due to speed)
PRINT_THRESHOLD_USD = 5.0

try:
    import orjson as json_parser
except ImportError:
    import json as json_parser

BINANCE_STREAM = os.getenv("BINANCE_STREAM", "btcusdt@bookTicker")
CHAINLINK_TARGET_SYMBOL = "btc/usd" # Polymarket uses this format for Chainlink

# -----------------------------------------------------------------------------
# STRATEGY: COMPARE & TIME
# -----------------------------------------------------------------------------
class DeviationStrategy:
    def __init__(self):
        self.last_chainlink_price = None
        self.current_binance_price = 0
        
        # Trigger Logic
        self.waiting_for_trigger = False
        self.trigger_start_time = 0
        
        # Throttling Logic (for printing)
        self.last_print_price = 0

    def on_binance_data(self, price):
        self.current_binance_price = price
        
        # We need a baseline Chainlink price to compare against
        if self.last_chainlink_price is None:
            return

        # 1. Calculate Deviation
        diff = price - self.last_chainlink_price
        deviation_pct = abs(diff) / self.last_chainlink_price * 100
        
        # 2. "Chatty" Print Logic
        # Print if price moved > $5 since last print OR if we are in a Trigger state
        if abs(price - self.last_print_price) > PRINT_THRESHOLD_USD:
            self.last_print_price = price
            # Use color to indicate direction relative to Chainlink
            direction = "⬆️" if diff > 0 else "⬇️"
            print(f"⚡ Binance: ${price:,.2f} ({direction} ${abs(diff):.2f} / {deviation_pct:.3f}%)")

        # 3. TRIGGER LOGIC (The Stop Watch)
        # If Binance pulls away significantly, start timing how long Chainlink takes to catch up
        if deviation_pct >= DEVIATION_THRESHOLD_PERCENT and not self.waiting_for_trigger:
            print(f"\n🚨 TRIGGER ACTIVATED! Deviation > {DEVIATION_THRESHOLD_PERCENT}%")
            print(f"   Binance (${price:,.2f}) is pulling away from Chainlink (${self.last_chainlink_price:,.2f})")
            print("   ⏱️  Timer Started...")
            self.waiting_for_trigger = True
            self.trigger_start_time = time.time()

    def on_chainlink_data(self, price, ts):
        now = time.time()
        self.last_chainlink_price = price
        
        # Formatting the output
        diff_vs_binance = 0
        if self.current_binance_price:
            diff_vs_binance = self.current_binance_price - price

        print(f"\n🔗 Chainlink Update: ${price:,.2f} | Current Binance Gap: ${diff_vs_binance:.2f}")

        # STOP THE TIMER
        if self.waiting_for_trigger:
            elapsed = now - self.trigger_start_time
            print(f"✅ CAUGHT UP! Chainlink reacted in {elapsed:.2f} seconds.")
            print("-" * 50 + "\n")
            self.waiting_for_trigger = False
        else:
            print("   (Routine update)")

strategy = DeviationStrategy()

# -----------------------------------------------------------------------------
# TASK 1: BINANCE CONNECTION
# -----------------------------------------------------------------------------
async def run_binance():
    url = f"wss://stream.binance.com/ws/{BINANCE_STREAM}"
    backoff = 1
    print(f"--- Connecting to Binance ({BINANCE_STREAM}) ---")
    
    while True:
        try:
            async with websockets.connect(url, max_queue=1) as ws:
                print("⚡ Binance Connected")
                backoff = 1
                async for msg in ws:
                    data = json_parser.loads(msg)
                    # Calculate Mid Price
                    mid = (float(data["b"]) + float(data["a"])) / 2.0
                    strategy.on_binance_data(mid)
        except Exception as e:
            print(f"⚡ Binance Error: {e}")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 10)

# -----------------------------------------------------------------------------
# TASK 2: POLYMARKET CHAINLINK CONNECTION
# -----------------------------------------------------------------------------
async def run_chainlink():
    url = "wss://ws-live-data.polymarket.com"
    backoff = 1
    print(f"--- Connecting to Polymarket Oracle Feed ---")

    while True:
        try:
            async with websockets.connect(url) as ws:
                print("🔷 Polymarket Oracle Connected")
                backoff = 1
                
                # Subscribe to Chainlink topic
                sub_msg = {
                    "action": "subscribe", 
                    "subscriptions": [{"topic": "crypto_prices_chainlink", "type": "update"}]
                }
                await ws.send(json.dumps(sub_msg))

                while True:
                    response = await ws.recv()
                    if not response: continue
                    
                    data = json.loads(response)
                    
                    # Check for correct topic and type
                    if data.get("topic") == "crypto_prices_chainlink" and data.get("type") == "update":
                        payload = data.get("payload", {})
                        
                        # Filter for BTC/USD
                        if payload.get("symbol") == CHAINLINK_TARGET_SYMBOL:
                            price = payload.get("value")
                            ts = payload.get("timestamp")
                            strategy.on_chainlink_data(price, ts)

        except Exception as e:
            print(f"🔷 Poly Error: {e}")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 10)

# -----------------------------------------------------------------------------
# MAIN LOOP
# -----------------------------------------------------------------------------
async def main():
    await asyncio.gather(run_binance(), run_chainlink())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped by user.")