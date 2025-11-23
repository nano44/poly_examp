import asyncio
import math
import os
import time
from collections import deque

import orjson
import requests
import websockets
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL

# Targeting params
MAX_SIZE = 10.0
MIN_SIZE = 1.0
SIZE_SIGMA = 50.0  # standard deviation for Gaussian decay
BINANCE_REF_PRICE = 0.0
DRY_RUN_MODE = True
client: ClobClient | None = None
TOKEN_ID_UP = "10334449752454341374581636586903032507606859851381275260687240460182698532134"
TOKEN_ID_DOWN = "52024715793975710673607861457473968911870695482055079725273269515884399987454"


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
                            f"🚨 BULL SIGNAL! Vel: {vel:.2f} | Size: {size:.2f} | OBI: {obi:.2f}"
                        )
                        last_trigger_time = ts  # Reset Cooldown
                        await execute_trade("BULL", size)
                    elif vel < -25.0 and obi < -0.6:
                        print(
                            f"🚨 BEAR SIGNAL! Vel: {vel:.2f} | Size: {size:.2f} | OBI: {obi:.2f}"
                        )
                        last_trigger_time = ts  # Reset Cooldown
                        await execute_trade("BEAR", size)
        except Exception as e:
            print(f"MD connection error: {e} | reconnecting in {backoff}s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


async def execute_trade(signal_type, size: float) -> None:
    if client is None:
        print("❌ Client not initialized")
        return

    target_token_id = TOKEN_ID_UP if signal_type == "BULL" else TOKEN_ID_DOWN
    side = BUY  # we always buy the respective token

    # Step 1: Connectivity check (orderbook)
    try:
        ob = await asyncio.to_thread(client.get_order_book, target_token_id)
    except Exception as e:
        print(f"❌ ABORT: Failed to fetch orderbook: {e}")
        return

    # Step 2: Spread guard
    try:
        # Polymarket library returns lists of OrderSummary objects
        best_bid = float(ob.bids[0].price) if ob.bids else 0.0
        best_ask = float(ob.asks[0].price) if ob.asks else 0.0
    except Exception:
        print("❌ ABORT: Invalid orderbook data")
        return

    spread = best_ask - best_bid
    if spread > 0.03:
        print(f"❌ ABORT: Spread too wide ({spread:.4f})")
        return

    price = best_ask  # taking liquidity on chosen side
    if DRY_RUN_MODE:
        direction = "UP" if target_token_id == TOKEN_ID_UP else "DOWN"
        print(
            f"🔧 DRY RUN: Would have BOUGHT {direction} ({size:.2f} shares) @ ${price:.4f}"
        )
        return

    try:
        order_args = OrderArgs(
            price=price,
            size=size,
            side=side,
            token_id=target_token_id,
        )
        signed = client.create_order(order_args)
        resp = client.post_order(signed, OrderType.IOC)
        direction = "UP" if target_token_id == TOKEN_ID_UP else "DOWN"
        print(f"✅ Sent BUY {direction} | OrderID: {resp.get('orderID', resp)}")
    except Exception as e:
        print(f"❌ Order error: {e}")


async def main() -> None:
    global BINANCE_REF_PRICE, client, TOKEN_ID_UP, TOKEN_ID_DOWN
    load_dotenv()
    BINANCE_REF_PRICE = get_binance_candle_open()
    print(f"✅ Reference Price set to: ${BINANCE_REF_PRICE:,.2f}")

    client = ClobClient(
        os.getenv("CLOB_API_URL") or "https://clob.polymarket.com",
        key=os.getenv("PK"),
        chain_id=int(os.getenv("CHAIN_ID", "137")),
        signature_type=int(os.getenv("SIGNATURE_TYPE", "1")),
        funder=os.getenv("FUNDER"),
        creds=None,
    )
    api_key = os.getenv("CLOB_API_KEY")
    api_secret = os.getenv("CLOB_SECRET")
    api_passphrase = os.getenv("CLOB_PASS_PHRASE")
    if api_key and api_secret and api_passphrase:
        from py_clob_client.clob_types import ApiCreds

        client.set_api_creds(
            ApiCreds(
                api_key=api_key,
                api_secret=api_secret,
                api_passphrase=api_passphrase,
            )
        )
        print("✅ Polymarket client initialized with API creds")
    else:
        print("ℹ️ Polymarket client initialized without API creds (read-only)")

    state = MarketState(maxlen=20)
    await market_data_listener(state)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
