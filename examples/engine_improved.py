import asyncio
import math
import csv
import os
import time
import aiohttp
import orjson
import websockets
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, BookParams, OrderArgs, OrderType
from py_clob_client.constants import POLYGON
from py_clob_client.exceptions import PolyApiException
from py_clob_client.order_builder.constants import BUY

# IMPORT LOCAL LOGIC
from examples.transmission import (
    ShadowStrategy,
    get_current_window_open,
    calculate_transmission_coefficient,
    DEFAULT_VOLATILITY,
    DEFAULT_WINDOW
)

load_dotenv()

# --- CONFIG ---
MAX_SIZE = 1.5
MIN_SIZE = 1.0
SIZE_SIGMA = 50.0  
SPREAD_THRESHOLD = 0.03
FAIR_VALUE_EPS = 0.02
DATA_STALENESS_S = 2.0
BOOK_REFRESH_S = 0.2
DRY_RUN_MODE = False
BINANCE_STREAM = os.getenv("BINANCE_STREAM", "btcusdt@bookTicker")
BINANCE_REF_PRICE_OVERRIDE = os.getenv("BINANCE_REF_PRICE_OVERRIDE")
TICKS_TO_CAPTURE = 8
CSV_FILE = "trade_analytics_temp.csv"

# Global State
POLY_MARKET_CACHE = {
    "UP": {"id": None, "bid": 0.0, "ask": 0.0, "spread": 0.0, "last_updated": 0.0},
    "DOWN": {"id": None, "bid": 0.0, "ask": 0.0, "spread": 0.0, "last_updated": 0.0},
}
NEEDS_NEW_IDS = False
CACHE_LOCK = asyncio.Lock()
client: ClobClient | None = None
BINANCE_REF_PRICE = 0.0
TRACKED_TRADES: list[dict] = []


# --- ANALYTICS HELPERS ---
def init_csv() -> None:
    expected_header = ["Timestamp", "Side", "Entry", "Spread", "Velocity", "OrderID"] + [
        f"Tick_{i}" for i in range(1, TICKS_TO_CAPTURE + 1)
    ]
    needs_header = not os.path.exists(CSV_FILE)
    if needs_header:
        with open(CSV_FILE, "w", newline="") as f:
            csv.writer(f).writerow(expected_header)

def calculate_size(price: float) -> float:
    dist = abs(price - BINANCE_REF_PRICE) if BINANCE_REF_PRICE else abs(price)
    size = MAX_SIZE * math.exp(-(dist**2) / (2 * SIZE_SIGMA**2))
    return max(MIN_SIZE, size)

async def get_binance_ref_price(session: aiohttp.ClientSession) -> float:
    if BINANCE_REF_PRICE_OVERRIDE:
        return float(BINANCE_REF_PRICE_OVERRIDE)
    # Re-use the one from transmission logic if we want, or simple implementation here
    # Since we have get_current_window_open in transmission, we can rely on that logic there,
    # but for simple sizing reference, we do a quick check here.
    try:
        url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=15m&limit=1"
        async with session.get(url, timeout=5) as resp:
            data = await resp.json(loads=orjson.loads)
            return float(data[0][1])
    except Exception as e:
        print(f"⚠️ Failed to fetch ref price: {e}")
        return 0.0


# --- POLYMARKET LOGIC ---
async def refresh_market_ids() -> bool:
    global NEEDS_NEW_IDS
    file_path = "active_ids.json"
    if not os.path.exists(file_path):
        return False

    try:
        with open(file_path, "r") as f:
            data = orjson.loads(f.read())

        up_id = data.get("UP")
        down_id = data.get("DOWN")

        if not up_id or not down_id: return False

        async with CACHE_LOCK:
            if POLY_MARKET_CACHE["UP"]["id"] != up_id:
                print(f"🔄 LOADED NEW MARKET: {data.get('market', 'Unknown')}")
                POLY_MARKET_CACHE["UP"] = {"id": up_id, "bid": 0.0, "ask": 0.0, "spread": 0.0, "last_updated": 0.0}
                POLY_MARKET_CACHE["DOWN"] = {"id": down_id, "bid": 0.0, "ask": 0.0, "spread": 0.0, "last_updated": 0.0}
        NEEDS_NEW_IDS = False
        return True
    except Exception as e:
        print(f"❌ Error reading JSON: {e}")
        return False

def resolve_side_for_token(token_id: str) -> str | None:
    for label, entry in POLY_MARKET_CACHE.items():
        if entry["id"] == token_id:
            return label
    return None

async def polymarket_data_stream(poly_client: ClobClient) -> None:
    global NEEDS_NEW_IDS
    while True:
        if poly_client is None:
            await asyncio.sleep(1)
            continue
        if NEEDS_NEW_IDS or not POLY_MARKET_CACHE["UP"]["id"]:
            await refresh_market_ids()
            await asyncio.sleep(1)
            continue

        try:
            params = [
                BookParams(token_id=POLY_MARKET_CACHE["UP"]["id"]),
                BookParams(token_id=POLY_MARKET_CACHE["DOWN"]["id"]),
            ]
            books = await asyncio.to_thread(poly_client.get_order_books, params)
        except Exception:
            await asyncio.sleep(BOOK_REFRESH_S)
            continue

        now = time.time()
        async with CACHE_LOCK:
            for book in books:
                label = resolve_side_for_token(book.asset_id)
                if not label: continue

                has_bids = len(book.bids) > 0
                has_asks = len(book.asks) > 0
                best_bid = float(book.bids[-1].price) if has_bids else 0.0
                best_ask = float(book.asks[-1].price) if has_asks else 0.0
                spread = round(best_ask - best_bid, 3) if (has_bids and has_asks) else 999.0

                POLY_MARKET_CACHE[label].update({
                    "id": book.asset_id, "bid": best_bid, "ask": best_ask,
                    "spread": spread, "last_updated": now
                })
        
        # CSV Logging for Active Trades
        # ... (Existing CSV logic kept abbreviated for clarity) ...
        
        await asyncio.sleep(BOOK_REFRESH_S)


# --- EXECUTION LOGIC (CALLBACK) ---
async def execute_trade(direction: str, mid_price: float, velocity: float, gear: float, predicted_jump: float, time_left: float) -> None:
    """
    This function is called by the Strategy class when a signal fires.
    """
    global NEEDS_NEW_IDS
    
    print(f"⚡ SIGNAL RECEIVED: {direction} | Vel: {velocity:.2f} | Jump: {predicted_jump*100:.2f}¢")

    if client is None:
        print("❌ Client not initialized")
        return

    side_label = "UP" if direction == "UP" else "DOWN"
    
    # Calculate Size
    size = calculate_size(mid_price)

    async with CACHE_LOCK:
        target = POLY_MARKET_CACHE[side_label].copy()
        other = POLY_MARKET_CACHE["DOWN" if side_label == "UP" else "UP"].copy()

    # Pre-flight Checks
    if not target["id"]: return
    if time.time() - target["last_updated"] >= DATA_STALENESS_S:
        print("❌ Stale Polymarket book")
        return
    if target["spread"] >= SPREAD_THRESHOLD:
        print(f"❌ Spread too high: {target['spread']}")
        return

    # Price Calculation
    price = float(f"{target['ask']:.2f}")
    if price <= 0: price = 0.01

    # Filters
    if price < 0.15 or price > 0.85:
        print(f"⚠️ Price {price} out of tradeable bounds.")
        return

    # Size Rounding
    price_cents = int(round(price * 100))
    step_size_cents = 100 // math.gcd(price_cents, 100)
    step_size = step_size_cents / 100.0
    valid_size = math.ceil(size / step_size) * step_size
    valid_size = float(f"{valid_size:.2f}")

    if DRY_RUN_MODE:
        print(f"🔧 DRY RUN: BUY {side_label} {valid_size} @ {price}")
        return

    # EXECUTE
    try:
        print(f"⏳ BUYING {side_label} {valid_size} @ {price}...")
        order_args = OrderArgs(price=price, size=valid_size, side=BUY, token_id=target["id"])
        
        # Sign and Post
        signed_order = await asyncio.to_thread(client.create_order, order_args)
        resp = await asyncio.to_thread(client.post_order, signed_order, OrderType.FAK)
        
        order_id = resp.get("orderID") if isinstance(resp, dict) else resp
        print(f"✅ FILLED: {order_id}")
        
        # Log to Tracker
        TRACKED_TRADES.append({
            "timestamp": time.time(), "side": side_label, "entry": price,
            "spread": target["spread"], "velocity": velocity, "order_id": order_id, "ticks": []
        })

    except PolyApiException as e:
        if "no orders found to match" in str(e):
             print(f"❌ REJECTED (No Match). Price likely moved.")
        else:
             print(f"❌ API Error: {e}")
    except Exception as e:
        print(f"❌ Unexpected Error: {e}")


# --- MAIN ENTRY POINT ---
async def market_data_listener(strategy: ShadowStrategy) -> None:
    url = f"wss://stream.binance.com/ws/{BINANCE_STREAM}"
    backoff = 1
    while True:
        try:
            async with websockets.connect(url, max_queue=1) as ws:
                print("⚡ Binance Stream Connected")
                backoff = 1
                async for msg in ws:
                    data = orjson.loads(msg)
                    mid = (float(data["b"]) + float(data["a"])) / 2.0
                    
                    # Pass data to strategy. If strategy triggers, it calls execute_trade
                    strategy.on_market_data(mid)
                    
        except Exception as e:
            print(f"Stream Error: {e}")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 10)

async def main() -> None:
    global BINANCE_REF_PRICE, client

    # 1. Setup Client
    host = os.getenv("CLOB_API_URL") or "https://clob.polymarket.com"
    key = os.getenv("PK")
    creds = ApiCreds(
        api_key=os.getenv("CLOB_API_KEY"),
        api_secret=os.getenv("CLOB_SECRET"),
        api_passphrase=os.getenv("CLOB_PASS_PHRASE")
    )
    client = ClobClient(
        host, key=key, chain_id=int(os.getenv("CHAIN_ID", 137)), creds=creds
    )
    print("✅ Polymarket Client Initialized")

    init_csv()

    # 2. Setup Reference Data
    async with aiohttp.ClientSession(json_serialize=orjson.dumps) as session:
        BINANCE_REF_PRICE = await get_binance_ref_price(session)
        print(f"✅ Reference Price: ${BINANCE_REF_PRICE}")
        
        # Get Strike/Expiry from our Transmission Logic
        strike_price, expiry_timestamp = await get_current_window_open(session)

    await refresh_market_ids()

    # 3. Initialize Strategy with the Callback
    strategy = ShadowStrategy(
        strike_price=strike_price,
        expiry_timestamp=expiry_timestamp,
        volatility=DEFAULT_VOLATILITY,
        velocity_window=DEFAULT_WINDOW,
        on_trigger_callback=execute_trade  # <--- Linking the callback here
    )

    # 4. Run Tasks
    asyncio.create_task(polymarket_data_stream(client))
    await market_data_listener(strategy)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass