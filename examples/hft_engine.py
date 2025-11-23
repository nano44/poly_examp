import asyncio
import math
import time
from collections import deque

import orjson
import requests
import websockets

# Targeting params
MAX_SIZE = 10.0
MIN_SIZE = 1.0
SIZE_SIGMA = 50.0  # standard deviation for Gaussian decay
BINANCE_REF_PRICE = 0.0


class MarketState:
    """Holds recent mid-prices with timestamps for velocity calc."""

    def __init__(self, maxlen: int = 20) -> None:
        self._prices = deque(maxlen=maxlen)  # (timestamp, price)
        self._lock = asyncio.Lock()

    async def update(self, price: float, ts: float) -> None:
        async with self._lock:
            self._prices.append((ts, price))

    async def velocity(self, window_s: float = 1.0) -> float:
        async with self._lock:
            if len(self._prices) < 2:
                return 0.0
            now = self._prices[-1][0]
            oldest_t, oldest_p = self._prices[0]
            # find the oldest point within the window
            for t, p in reversed(self._prices):
                if now - t <= window_s:
                    oldest_t, oldest_p = t, p
                else:
                    break
            newest_t, newest_p = self._prices[-1]
            dt = newest_t - oldest_t
            if dt <= 0:
                return 0.0
            return (newest_p - oldest_p) / dt


def calculate_obi(bid_qty: float, ask_qty: float) -> float:
    denom = bid_qty + ask_qty
    if denom == 0:
        return 0.0
    return (bid_qty - ask_qty) / denom


def calculate_size(price: float) -> float:
    dist = abs(price - BINANCE_REF_PRICE) if BINANCE_REF_PRICE else abs(price)
    size = MAX_SIZE * math.exp(-(dist**2) / (2 * SIZE_SIGMA**2))
    return max(MIN_SIZE, size)


def get_binance_candle_open() -> float:
    """
    Fetches the open price of the latest 15m BTCUSDT candle.
    BLOCKS until successful. Do not start without this.
    """
    url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=15m&limit=1"
    while True:
        try:
            resp = requests.get(url, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            if data and isinstance(data, list):
                return float(data[0][1])
        except Exception as e:
            print(f"⚠️ Failed to fetch reference price: {e}. Retrying in 2s...")
            time.sleep(2)


async def market_data_listener(state: MarketState) -> None:
    url = "wss://stream.binance.com:9443/ws/btcusdt@bookTicker"
    backoff = 1
    # FIX: Add Cooldown State
    last_trigger_time = 0.0
    COOLDOWN_SECONDS = 5.0

    while True:
        try:
            async with websockets.connect(
                url,
                ping_interval=15,
                ping_timeout=15,
                max_queue=1,
            ) as ws:
                backoff = 1
                print("⚡ Connected to Binance...")
                async for msg in ws:
                    data = orjson.loads(msg)
                    bid = float(data["b"])
                    ask = float(data["a"])
                    bid_qty = float(data["B"])
                    ask_qty = float(data["A"])
                    mid = (bid + ask) / 2.0
                    ts = time.time()
                    await state.update(mid, ts)

                    # FIX: Don't calculate logic on EVERY tick (too fast)
                    # Only check logic if cooldown has passed
                    if ts - last_trigger_time < COOLDOWN_SECONDS:
                        continue

                    vel = await state.velocity(window_s=1.0)
                    obi = calculate_obi(bid_qty, ask_qty)
                    size = calculate_size(mid)

                    if vel > 25.0 and obi > 0.6:
                        print(
                            f"🚨 BUY SIGNAL | Vel: {vel:.2f} | Size: {size:.2f} | OBI: {obi:.2f}"
                        )
                        last_trigger_time = ts  # Reset Cooldown
                        # TODO: place order here
                    elif vel < -25.0 and obi < -0.6:
                        print(
                            f"🚨 SELL SIGNAL | Vel: {vel:.2f} | Size: {size:.2f} | OBI: {obi:.2f}"
                        )
                        last_trigger_time = ts  # Reset Cooldown
                        # TODO: place order here
        except Exception as e:
            print(f"MD connection error: {e} | reconnecting in {backoff}s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


async def main() -> None:
    global BINANCE_REF_PRICE
    BINANCE_REF_PRICE = get_binance_candle_open()
    print(f"✅ Reference Price set to: ${BINANCE_REF_PRICE:,.2f}")

    state = MarketState(maxlen=20)
    await market_data_listener(state)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
