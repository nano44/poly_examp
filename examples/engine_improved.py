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
from sign_order import FastPolymarketSigner

# --- 1. IMPORT SHARED STORE (Global Variables) ---
import examples.store_price as store_price

# --- 2. IMPORT WEBSOCKET LISTENER (Background Task) ---
# This assumes you renamed 'test_websocket.py' to 'poly_cache.py'
from examples.poly_cache import websocket_listener 

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
SPREAD_THRESHOLD = 0.02
FAIR_VALUE_EPS = 0.02
DATA_STALENESS_S = 2.0
BOOK_REFRESH_S = 0.2
DRY_RUN_MODE = False
BINANCE_STREAM = os.getenv("BINANCE_STREAM", "btcusdt@bookTicker")
BINANCE_REF_PRICE_OVERRIDE = os.getenv("BINANCE_REF_PRICE_OVERRIDE")
TICKS_TO_CAPTURE = 8
CSV_FILE = "trade_analytics_temp.csv"

# Global State (IDs are still managed locally for Execution)
POLY_MARKET_CACHE = {
    "UP": {"id": None},
    "DOWN": {"id": None},
}
NEEDS_NEW_IDS = False
CACHE_LOCK = asyncio.Lock()
client: ClobClient | None = None
signer: FastPolymarketSigner | None = None
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

    if not os.path.exists(CSV_FILE):
        needs_rewrite = True
    else:
        try:
            with open(CSV_FILE, "r", newline="") as f:
                reader = csv.reader(f)
                try:
                    existing_header = next(reader)
                    if existing_header != expected_header:
                        print(f"⚠️ CSV Schema changed. Overwriting {CSV_FILE}...")
                        needs_rewrite = True
                except StopIteration:
                    needs_rewrite = True
        except Exception as e:
            print(f"⚠️ Error reading CSV ({e}). Re-initializing...")
            needs_rewrite = True

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


# --- POLYMARKET ID MANAGEMENT ---
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
                print(f"🔄 LOADED NEW MARKET (Engine): {data.get('market', 'Unknown')}")
                POLY_MARKET_CACHE["UP"] = {"id": up_id}
                POLY_MARKET_CACHE["DOWN"] = {"id": down_id}
        NEEDS_NEW_IDS = False
        return True
    except Exception as e:
        print(f"❌ Error reading JSON: {e}")
        return False

async def polymarket_csv_logger_loop():
    """
    Background task to update CSV ticks.
    Since we don't have a polling loop anymore, we need a dedicated loop 
    to periodically update the 'ticks' for tracked trades from the store.
    """
    while True:
        await asyncio.sleep(0.2) # Update ticks every 200ms
        
        if not TRACKED_TRADES: continue
        
        # Read current prices from the Shared Store
        current_up = store_price.UP_askprice
        current_down = store_price.DOWN_askprice
        
        for trade in TRACKED_TRADES.copy():
            side = trade["side"]
            
            # Get current price based on side
            curr_price = current_up if side == "UP" else current_down
            
            if curr_price <= 0: continue # Don't log zeros
            
            trade["ticks"].append(curr_price)
            
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
                
                try:
                    with open(CSV_FILE, "a", newline="") as f:
                        csv.writer(f).writerow(row)
                except Exception as e:
                    print(f"CSV Error: {e}")
                    
                TRACKED_TRADES.remove(trade)


# --- EXECUTION LOGIC (CALLBACK) ---
async def execute_trade(direction: str, mid_price: float, velocity: float, gear: float, predicted_jump: float, time_left: float, volatility: float) -> None:
    global NEEDS_NEW_IDS
    time_start = time.time()
    
    side_label = "UP" if direction == "UP" else "DOWN"
    
    loop_start = time.time()

    # 1. READ FROM SHARED STORE (Instant Data)
    if side_label == "UP":
        market_price = store_price.UP_askprice
        spread = store_price.spread_up
        token_id = POLY_MARKET_CACHE["UP"].get("id")
    else:
        market_price = store_price.DOWN_askprice
        spread = store_price.spread_down
        token_id = POLY_MARKET_CACHE["DOWN"].get("id")

    print(f"⚡ SIGNAL: {direction} | Market Price: ${market_price:.2f} | Spread: {spread:.3f}")

    
    if signer is None:
        print("❌ CRITICAL: Signer is not initialized!")
        return
    
    
    if client is None:
        print("❌ Client not initialized")
        return

    # --- PRE-FLIGHT CHECKS ---
    if not token_id:
        # Try one quick refresh if IDs are missing
        await refresh_market_ids() 
        token_id = POLY_MARKET_CACHE[side_label].get("id")
        if not token_id: return

    # Check validity of Store Data
    if market_price <= 0:
        print(f"⚠️ Store price is 0. Waiting for Websocket data...")
        return

    if spread >= SPREAD_THRESHOLD:
        print(f"❌ Spread too high: {spread:.3f}")
        return

    # Real Price for CSV is the price we see NOW in the store
    real_market_price = market_price

    if real_market_price < 0.15: 
        print(f"⚠️ Market Price {real_market_price} too low.")
        return
    if real_market_price > 0.85:
        print(f"⚠️ Market Price {real_market_price} too expensive.")
        return

    # --- HARDCODED EXECUTION (Market Order Logic) ---
    # We pay up to 0.90 to ensure fill, but 'real_market_price' is what we expect to pay
    execution_price = market_price + 0.02

    # --- SIZE ALIGNMENT ---
    # Choose a size step so price * size always has <= 2 decimals.
    # With price in cents (p), size in cents (s), we need p * s % 100 == 0.
    price_cents = int(round(execution_price * 100))
    min_notional = 1.00
    raw_shares = min_notional / execution_price

    step_cents = 100 // math.gcd(price_cents, 100)  # smallest size (in cents) that keeps p*s divisible by 100
    raw_size_cents = raw_shares * 100
    valid_size_cents = math.ceil(raw_size_cents / step_cents) * step_cents
    valid_size = valid_size_cents / 100.0

    if DRY_RUN_MODE:
        cost = valid_size * execution_price
        print(f"🔧 DRY RUN: BUY {side_label} {valid_size} @ ${execution_price} (Cost: ${cost:.3f})")
        return

    # --- EXECUTE ---
    try:
        total_cost = valid_size * execution_price
        print(f"⏳ SENDING: {side_label} {valid_size} @ ${execution_price} (Cost: ${total_cost:.2f})...")
        
        order_args = OrderArgs(
            price=execution_price, size=valid_size, side=BUY, token_id=token_id
        )

        signed_payload = signer.sign_order(order_args)
        
        post_loop = time.time()
        #print(f"⏱️ Order signed in {(post_loop - loop_start)*1000:.1f}ms. Posting to API...")
        print(f"Order process took {(post_loop - time_start)*1000:.1f}ms.")
        time_order_sent = time.time()
        resp = await asyncio.to_thread(client.post_order, signed_payload, OrderType.FAK)

        post_send = time.time()
        print(f"⏱️ Order posted & signed in {(post_send - loop_start)*1000:.1f}ms.")
        order_id = resp.get("orderID") if isinstance(resp, dict) else resp
        print(f"✅ FILLED: {order_id}")
        
        TRACKED_TRADES.append({
            "timestamp": time.time(),
            "side": side_label,
            "entry": real_market_price,
            "spread": spread,
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
    global BINANCE_REF_PRICE, client, signer

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

    # 3. Start Websocket Cache (Background)
    # This runs the listener which updates store_price.py in real-time
    print("🔌 Launching internal Websocket Cache...")
    asyncio.create_task(websocket_listener())
    
    # 4. Start CSV Logger (Background)
    # Since we removed the data stream loop, we need this to log ticks
    asyncio.create_task(polymarket_csv_logger_loop())


    # Wait for websocket to warm up
    await asyncio.sleep(2)

    signer = FastPolymarketSigner(private_key_hex=key, funder=funder, signature_type=sig_type)
    print(f"✅ Fast Signer Initialized (Maker: {signer.maker_address}, Type: {signer.signature_type})")

    # 5. Initialize Strategy
    strategy = ShadowStrategy(
        strike_price=strike_price,
        expiry_timestamp=expiry_timestamp,
        volatility=DEFAULT_VOLATILITY, 
        velocity_window=DEFAULT_WINDOW, 
        on_trigger_callback=execute_trade,
    )

    # 6. Run Tasks
    await market_data_listener(strategy)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
