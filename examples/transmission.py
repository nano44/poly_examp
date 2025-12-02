import math
import time
import asyncio
import aiohttp
import orjson
import os
from collections import deque
from dotenv import load_dotenv

load_dotenv()

SECONDS_IN_YEAR = 31_536_000.0
ONE_OVER_SQRT_2PI = 1.0 / math.sqrt(2 * math.pi)
MAX_SENSITIVITY_CAP = 0.05

# Defaults if not provided
DEFAULT_VOLATILITY = 0.60
DEFAULT_WINDOW = 1.0
BINANCE_SYMBOL = os.getenv("BINANCE_SYMBOL", "BTCUSDT")

def calculate_transmission_coefficient(spot_price, strike_price, time_to_expiry_sec, annual_volatility):
    if time_to_expiry_sec < 2: return 0.0
    t_years = time_to_expiry_sec / SECONDS_IN_YEAR
    std_dev_move = spot_price * annual_volatility * math.sqrt(t_years)
    
    if std_dev_move < 1e-6: return 0.0
    
    z_score = (spot_price - strike_price) / std_dev_move
    pdf_height = ONE_OVER_SQRT_2PI * math.exp(-0.5 * z_score**2)
    
    return min((pdf_height / std_dev_move), MAX_SENSITIVITY_CAP)

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

class ShadowStrategy:
    """
    Pure logic class. 
    It ingests price data and calls 'on_trigger_callback' when a signal is found.
    """
    def __init__(
        self, 
        strike_price: float, 
        expiry_timestamp: float, 
        volatility: float, 
        velocity_window: float,
        on_trigger_callback=None  # This is the bridge to the main bot
    ):
        self.strike_price = strike_price
        self.expiry_timestamp = expiry_timestamp
        self.volatility = volatility
        self.velocity_window = velocity_window
        self.callback = on_trigger_callback
        
        self.history = deque()
        self.is_in_swing = False 
        self.last_heartbeat = 0.0

    def on_market_data(self, mid_price: float):
        now = time.time()
        time_left = self.expiry_timestamp - now
        
        # 1. Update Sliding Window
        self.history.append((now, mid_price))
        
        # Prune old data
        while self.history and (now - self.history[0][0] > self.velocity_window):
            self.history.popleft()
            
        if not self.history: return

        # 2. Calculate Math
        price_n_sec_ago = self.history[0][1]
        spot_velocity = mid_price - price_n_sec_ago

        gear_ratio = calculate_transmission_coefficient(
            mid_price, self.strike_price, time_left, self.volatility
        )
        
        predicted_jump = spot_velocity * gear_ratio
        
        # 3. Thresholds
        ENTRY_THRESHOLD = 0.02
        RESET_THRESHOLD = 0.005 

        # 4. State Machine Logic
        if not self.is_in_swing:
            if abs(predicted_jump) > ENTRY_THRESHOLD:
                direction = "UP" if predicted_jump > 0 else "DOWN"
                self.is_in_swing = True
                
                # --- FIRE SIGNAL ---
                if self.callback:
                    # We use create_task because the callback (execute_trade) is async
                    # but this function is sync.
                    asyncio.create_task(
                        self.callback(
                            direction=direction, 
                            mid_price=mid_price, 
                            velocity=spot_velocity, 
                            gear=gear_ratio, 
                            predicted_jump=predicted_jump, 
                            time_left=time_left
                        )
                    )
        else:
            if abs(predicted_jump) < RESET_THRESHOLD:
                self.is_in_swing = False