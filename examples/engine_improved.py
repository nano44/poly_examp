import sys
import os

# 1. Path Fix (Ensures we can import local files if running from root)
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import asyncio
import math
import csv
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
from transmission import (
    ShadowStrategy,
    get_current_window_open,
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
    expected_header = [
        "Timestamp",
        "Side",
        "Entry",
        "Spread",
        "Volatility",
        "Velocity",
        "Gear",
        "PredJump",
        "OrderID",
    ] + [f"Tick_{i}" for i in range(1, TICKS_TO_CAPTURE + 1)]
    
    needs_rewrite = False

    # 1. Check if file exists
    if not os.path.exists(CSV_FILE):
        needs_rewrite = True
    else:
        # 2. If it exists, peek at the first row
        try:
            with open(CSV_FILE, "r", newline="") as f:
                reader = csv.reader(f)
                existing_header = next(reader)
                
                # 3. If headers don't match exactly, we need to rewrite
                if existing_header != expected_header:
                    print(f"⚠️ CSV Schema changed. Overwriting {CSV_FILE}...")
                    needs_rewrite = True
        except StopIteration:
            # File exists but is empty
            needs_rewrite = True
        except Exception as e:
            print(f"⚠️ Error reading CSV ({e}). Re-initializing...")
            needs_rewrite = True

    # 4. Write the new header if needed
    if needs_rewrite:
        with open(CSV_FILE, "w", newline="") as f:
            csv.writer(f).writerow(expected_header)

            
def calculate_size(price: float) -> float:
    dist = abs(price - BINANCE_REF_PRICE) if BINANCE_REF_PRICE else abs(price)
    size = MAX_SIZE * math.exp(-(dist**2) / (2 * SIZE_SIGMA**2))
    return max(MIN_SIZE, size)

async def get_binance_ref_price(session: aiohttp.ClientSession) -> float:
    if BINANCE_REF_PRICE_OVERRIDE:
        return float(BINANCE_REF_PRICE_OVERRIDE)
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
        for trade in TRACKED_TRADES.copy():
            side = trade["side"]
            if side not in POLY_MARKET_CACHE:
                continue
            current_price = POLY_MARKET_CACHE[side]["ask"]
            trade["ticks"].append(current_price)
            if len(trade["ticks"]) >= TICKS_TO_CAPTURE:
                row = [
                    trade["timestamp"],
                    trade["side"],
                    trade["entry"],
                    trade.get("spread", 0.0),
                    trade.get("volatility", 0.0),
                    trade.get("velocity", 0.0),
                    trade.get("gear", 0.0),
                    trade.get("predicted_jump", 0.0),
                    trade.get("order_id"),
                ] + trade["ticks"][:TICKS_TO_CAPTURE]
                
                with open(CSV_FILE, "a", newline="") as f:
                    csv.writer(f).writerow(row)
                TRACKED_TRADES.remove(trade)

        await asyncio.sleep(BOOK_REFRESH_S)


# --- EXECUTION LOGIC (CALLBACK) ---
async def execute_trade(direction: str, mid_price: float, velocity: float, gear: float, predicted_jump: float, time_left: float, volatility: float) -> None:
    global NEEDS_NEW_IDS
    
    side_label = "UP" if direction == "UP" else "DOWN"
    print(f"⚡ SIGNAL: {direction} | Ref Price: ${mid_price:.2f} | Vel: {velocity:.2f}")

    if client is None:
        print("❌ Client not initialized")
        return

    async with CACHE_LOCK:
        target = POLY_MARKET_CACHE[side_label].copy()

    # --- PRE-FLIGHT ---
    if not target["id"]: return
    if time.time() - target["last_updated"] >= DATA_STALENESS_S:
        print("❌ Stale Polymarket book")
        return
    if target["spread"] >= SPREAD_THRESHOLD:
        print(f"❌ Spread too high: {target['spread']}")
        return

    # Real Price for CSV
    real_market_price = float(f"{target['ask']:.2f}")
    if real_market_price <= 0: real_market_price = 0.01

    if real_market_price < 0.15: 
        print(f"⚠️ Market Price {real_market_price} too low.")
        return
    if real_market_price > 0.85:
        print(f"⚠️ Market Price {real_market_price} too expensive.")
        return

    spread_logged = round(target["spread"] / 2, 3)

    # --- HARDCODED EXECUTION ---
    execution_price = 0.90

    # --- SIZE ALIGNMENT ---
    # Logic: Round UP to nearest 0.10 step to ensure Price(0.9)*Size = 2 decimal places
    min_notional = 1.00
    raw_shares = min_notional / execution_price
    safe_step = 0.10
    valid_size = math.ceil(raw_shares / safe_step) * safe_step
    valid_size = float(f"{valid_size:.2f}")

    if DRY_RUN_MODE:
        cost = valid_size * execution_price
        print(f"🔧 DRY RUN: BUY {side_label} {valid_size} @ ${execution_price} (Cost: ${cost:.3f})")
        return

    # --- EXECUTE ---
    try:
        total_cost = valid_size * execution_price
        print(f"⏳ SENDING: {side_label} {valid_size} @ ${execution_price} (Cost: ${total_cost:.2f})...")
        
        order_args = OrderArgs(
            price=execution_price, size=valid_size, side=BUY, token_id=target["id"]
        )
        
        signed_order = await asyncio.to_thread(client.create_order, order_args)
        resp = await asyncio.to_thread(client.post_order, signed_order, OrderType.FAK)
        order_id = resp.get("orderID") if isinstance(resp, dict) else resp
        print(f"✅ FILLED: {order_id}")
        
        TRACKED_TRADES.append({
            "timestamp": time.time(),
            "side": side_label,
            "entry": real_market_price,
            "spread": spread_logged,
            "volatility": round(volatility, 2),
            "velocity": round(velocity, 2),
            "gear": round(gear, 5),
            "predicted_jump": round(predicted_jump, 4),
            "order_id": order_id,
            "ticks": [],
        })

    except PolyApiException as e:
        if "no orders found to match" in str(e):
             print(f"❌ REJECTED (No Match).")
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
                    strategy.on_market_data(mid)
        except Exception as e:
            print(f"Stream Error: {e}")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 10)

async def main() -> None:
    global BINANCE_REF_PRICE, client

    # 1. Setup Client with Funder Logic
    host = os.getenv("CLOB_API_URL") or "https://clob.polymarket.com"
    key = os.getenv("PK")
    sig_type = int(os.getenv("SIGNATURE_TYPE", "1"))
    funder = os.getenv("FUNDER")
    chain_id = int(os.getenv("CHAIN_ID", 137))

    creds = ApiCreds(
        api_key=os.getenv("CLOB_API_KEY"),
        api_secret=os.getenv("CLOB_SECRET"),
        api_passphrase=os.getenv("CLOB_PASS_PHRASE")
    )
    
    client = ClobClient(
        host, key=key, chain_id=chain_id, creds=creds,
        signature_type=sig_type, funder=funder
    )
    print(f"✅ Polymarket Client Initialized (Funder: {funder})")

    init_csv()

    # 2. Setup Reference Data
    async with aiohttp.ClientSession(json_serialize=orjson.dumps) as session:
        BINANCE_REF_PRICE = await get_binance_ref_price(session)
        print(f"✅ Reference Price: ${BINANCE_REF_PRICE}")
        strike_price, expiry_timestamp = await get_current_window_open(session)

    await refresh_market_ids()

    # 3. Initialize Strategy (Fixing Variable Names)
    strategy = ShadowStrategy(
        strike_price=strike_price,
        expiry_timestamp=expiry_timestamp,
        volatility=DEFAULT_VOLATILITY, # Fixed NameError
        velocity_window=DEFAULT_WINDOW, # Fixed NameError
        on_trigger_callback=execute_trade,
    )

    # 4. Run Tasks
    asyncio.create_task(polymarket_data_stream(client))
    await market_data_listener(strategy)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
