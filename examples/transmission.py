import asyncio
import math
import os
import time
from collections import deque
from typing import Optional

import aiohttp
import orjson
import websockets
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
# 1. Connectivity
BINANCE_SYMBOL = os.getenv("BINANCE_SYMBOL", "BTCUSDT")
BINANCE_STREAM = os.getenv("BINANCE_STREAM", "btcusdt@bookTicker")

# 2. Math & Physics
VOLATILITY_ASSUMPTION = 0.60  # 60% Annualized Volatility
MAX_SENSITIVITY_CAP = 0.05    # Max prob change per $1 move (Safety Clamp)

# 3. Signal Tuning
VELOCITY_WINDOW = 1.0  # Look back 1.0 seconds for price changes

# Constants
SECONDS_IN_YEAR = 31_536_000.0
ONE_OVER_SQRT_2PI = 1.0 / math.sqrt(2 * math.pi)


def calculate_transmission_coefficient(spot_price, strike_price, time_to_expiry_sec, annual_volatility):
    if time_to_expiry_sec < 2: return 0.0
    t_years = time_to_expiry_sec / SECONDS_IN_YEAR
    std_dev_move = spot_price * annual_volatility * math.sqrt(t_years)
    if std_dev_move < 1e-6: return 0.0
    z_score = (spot_price - strike_price) / std_dev_move
    pdf_height = ONE_OVER_SQRT_2PI * math.exp(-0.5 * z_score**2)
    return min((pdf_height / std_dev_move), MAX_SENSITIVITY_CAP)

class ShadowStrategy:
    def __init__(self, strike_price: float, expiry_timestamp: float, volatility: float, velocity_window: float):
        self.strike_price = strike_price
        self.expiry_timestamp = expiry_timestamp
        self.volatility = volatility
        self.velocity_window = velocity_window
        
        self.history = deque()
        self.last_heartbeat = 0.0
        
        # STATE MACHINE (Schmitt Trigger)
        # Prevents flickering: Fire High, Reset Low.
        self.is_in_swing = False 

    def on_market_data(self, mid_price: float):
        now = time.time()
        time_left = self.expiry_timestamp - now
        
        # 1. Update Sliding Window
        self.history.append((now, mid_price))
        
        # Efficiently prune old data (keep exactly 0.5s of history)
        while self.history and (now - self.history[0][0] > self.velocity_window):
            self.history.popleft()
            
        if not self.history: return

        # 2. Calculate Cumulative Impulse
        # This captures the total energy of the move over the last 0.5s.
        price_n_sec_ago = self.history[0][1]
        spot_velocity = mid_price - price_n_sec_ago

        gear_ratio = calculate_transmission_coefficient(
            mid_price, self.strike_price, time_left, self.volatility
        )
        
        predicted_jump = spot_velocity * gear_ratio
        
        # --- THE TRIGGER LOGIC ---
        
        # ENTRY_THRESHOLD: 0.02 (2 cents)
        # This requires a significant move to fire.
        ENTRY_THRESHOLD = 0.02
        
        # RESET_THRESHOLD: 0.005 (0.5 cents)
        # We don't unlock until the market is calm.
        RESET_THRESHOLD = 0.005 

        if not self.is_in_swing:
            # STATE: READY -> Check for Fire
            if abs(predicted_jump) > ENTRY_THRESHOLD:
                direction = "🟩 UP" if predicted_jump > 0 else "🟥 DOWN"
                jump_cents = abs(predicted_jump) * 100
                
                print(f"🚀 EXECUTE | T-{time_left:4.1f}s | "
                      f"Vel(0.5s): {spot_velocity:+.2f} | "
                      f"Gear: {gear_ratio:.5f} | "
                      f"👉 {direction} {jump_cents:.2f}¢")
                
                self.is_in_swing = True
                # TODO: execute_trade() goes here.

        else:
            # STATE: IN SWING -> Check for Reset
            if abs(predicted_jump) < RESET_THRESHOLD:
                if self.is_in_swing:
                    print(f"♻️ RELOAD | Swing over.")
                self.is_in_swing = False
        
        # Heartbeat visualization
        if now - self.last_heartbeat > 5.0:
            print(f"💓 Alive | T-{time_left:.0f}s | Gear: {gear_ratio:.6f}")
            self.last_heartbeat = now
    

async def get_current_window_open(session: aiohttp.ClientSession) -> tuple[float, float]:
    """
    Fetches the Binance Open price for the current 15m window.
    """
    now = time.time()
    window_duration = 900
    window_start_epoch = (math.floor(now / window_duration) * window_duration)
    expiry_epoch = window_start_epoch + window_duration
    
    start_ms = int(window_start_epoch * 1000)
    
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": BINANCE_SYMBOL,
        "interval": "15m",
        "startTime": start_ms,
        "limit": 1
    }
    
    print(f"⏳ Fetching Binance Open for window starting: {window_start_epoch}...")
    
    async with session.get(url, params=params, timeout=10) as resp:
        if resp.status != 200:
            raise ValueError(f"Binance API Error: {await resp.text()}")
            
        data = await resp.json(loads=orjson.loads)
        
        if not data:
            print("⚠️ Candle not ready, retrying...")
            await asyncio.sleep(1)
            return await get_current_window_open(session)
            
        strike_price = float(data[0][1])
        return strike_price, expiry_epoch


async def market_data_listener(callback):
    url = f"wss://stream.binance.com/ws/{BINANCE_STREAM}"
    while True:
        try:
            async with websockets.connect(url, max_queue=1) as ws:
                print("⚡ Stream Connected.")
                async for msg in ws:
                    data = orjson.loads(msg)
                    bid = float(data['b'])
                    ask = float(data['a'])
                    mid = (bid + ask) / 2.0
                    callback(mid)
        except Exception as e:
            print(f"⚠️ Stream Error: {e}. Reconnecting in 2s...")
            await asyncio.sleep(2)


async def main():
    async with aiohttp.ClientSession() as session:
        try:
            strike_price, expiry_timestamp = await get_current_window_open(session)
        except Exception as e:
            print(f"❌ Critical Init Error: {e}")
            return

        strategy = ShadowStrategy(
            strike_price=strike_price,
            expiry_timestamp=expiry_timestamp,
            volatility=VOLATILITY_ASSUMPTION,
            velocity_window=VELOCITY_WINDOW
        )
        
        await market_data_listener(strategy.on_market_data)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped.")