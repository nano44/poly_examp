import asyncio
import os
import time
import orjson
import websockets
import csv 
from datetime import datetime 
from dotenv import load_dotenv

# --- IMPORT SHARED STORE ---
import examples.store_price as store_price

# Ensure environment variables are loaded
load_dotenv()

# --- GLOBAL STATE ---
POLY_MARKET_CACHE = {
    "UP": {"id": None},
    "DOWN": {"id": None},
}
NEEDS_NEW_IDS = False
CACHE_LOCK = asyncio.Lock()

# --- SPECIALIZED LATENCY TRACKERS ---
LAST_PRICE_CHANGE_TIME = 0.0 
LAST_TRADE_TIME = 0.0
LAST_LOGGED_BBO = {} 

# --- POLYMARKET HELPERS ---

def resolve_side_for_token(token_id: str) -> str | None:
    for label, entry in POLY_MARKET_CACHE.items():
        if entry["id"] == token_id:
            return label
    return None

def cache_has_ids() -> bool:
    return bool(POLY_MARKET_CACHE["UP"]["id"] and POLY_MARKET_CACHE["DOWN"]["id"])

async def refresh_market_ids() -> bool:
    global NEEDS_NEW_IDS
    file_path = "active_ids.json"
    if not os.path.exists(file_path):
        print(f"⏳ Waiting for {file_path} to exist...")
        return False

    try:
        with open(file_path, "r") as f:
            data = orjson.loads(f.read())
        up_id = data.get("UP")
        down_id = data.get("DOWN")

        if not up_id or not down_id: return False

        async with CACHE_LOCK:
            if POLY_MARKET_CACHE["UP"]["id"] != up_id:
                #(f"🔄 LOADED MARKET: {data.get('market', 'Unknown')} | UP: {up_id[:8]}... | DOWN: {down_id[:8]}...")
                POLY_MARKET_CACHE["UP"] = {"id": up_id}
                POLY_MARKET_CACHE["DOWN"] = {"id": down_id}
        NEEDS_NEW_IDS = False
        return True
    except Exception as e:
        print(f"❌ Error reading JSON: {e}")
        return False

# --- CORE WEBSOCKET LISTENER ---

async def websocket_listener() -> None:
    global NEEDS_NEW_IDS, LAST_PRICE_CHANGE_TIME, LAST_TRADE_TIME
    
    # Define CSV file and header
    CSV_LOG_FILE = "websocket_log.csv"
    HEADER = ["Time_ms", "Timestamp_UTC", "Event", "Asset_ID", "Bid", "Ask", "Trade_Price", "Trade_Side"]
    
    if not os.path.exists(CSV_LOG_FILE):
        with open(CSV_LOG_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(HEADER)

    uri = "wss://ws-subscriptions-clob.polymarket.com/ws/market" 
    #print("\n--- Polymarket Websocket Tester & Updater ---")
    
    while True:
        while NEEDS_NEW_IDS or not cache_has_ids():
            await refresh_market_ids()
            await asyncio.sleep(1)

        token_ids = [POLY_MARKET_CACHE["UP"]["id"], POLY_MARKET_CACHE["DOWN"]["id"]]
        
        try:
            connect_start = time.time()
            async with websockets.connect(uri, ping_interval=20, ping_timeout=20) as websocket:
                connect_end = time.time()
                print(f"\n✅ WS Connected. Latency: {(connect_end - connect_start) * 1000:.1f}ms")
                
                sub_msg = {"type": "market", "assets_ids": token_ids}
                await websocket.send(orjson.dumps(sub_msg).decode())
                #print(f"📡 Subscribed. Updating store_price and logging to {CSV_LOG_FILE}...")

                with open(CSV_LOG_FILE, 'a', newline='') as csvfile: 
                    csv_writer = csv.writer(csvfile)

                    async for raw_msg in websocket:
                        if NEEDS_NEW_IDS:
                            print("🔄 IDs changed. Reconnecting WS...")
                            break
                        
                        data = orjson.loads(raw_msg)
                        messages = data if isinstance(data, list) else [data]
                        
                        for message in messages:
                            current_time = time.time()
                            
                            # Init trackers
                            if LAST_PRICE_CHANGE_TIME == 0.0: LAST_PRICE_CHANGE_TIME = current_time
                            if LAST_TRADE_TIME == 0.0: LAST_TRADE_TIME = current_time
                            
                            time_since_last_event = 0.0
                            
                            event_type = message.get("event_type", "Unknown")
                            bid, ask, trade_price, trade_side = 'N/A', 'N/A', 'N/A', 'N/A'
                            price_info_print = ""
                            should_log_now = False
                            asset_id = message.get("asset_id") 
                            
                            # --- 1. HANDLE PRICE UPDATES (BBO) ---
                            # This is the authoritative source for "Current Price"
                            if event_type == 'price_change':
                                changes = message.get('price_changes', [])
                                if not changes: continue
                                
                                first_change = changes[0]
                                asset_id = first_change.get("asset_id", asset_id) 
                                
                                raw_bid = first_change.get("best_bid")
                                raw_ask = first_change.get("best_ask")
                                
                                current_bid = float(raw_bid) if raw_bid and raw_bid != 'N/A' else None
                                current_ask = float(raw_ask) if raw_ask and raw_ask != 'N/A' else None
                                
                                # >>> UPDATE SHARED STORE (Strictly from price_change) <<<
                                side = resolve_side_for_token(asset_id)
                                if side:
                                    if current_ask is not None:
                                        if side == "UP": store_price.UP_askprice = current_ask
                                        elif side == "DOWN": store_price.DOWN_askprice = current_ask
                                    
                                    if current_bid is not None:
                                        if side == "UP": store_price.UP_bidprice = current_bid
                                        elif side == "DOWN": store_price.DOWN_bidprice = current_bid
                                    
                                    store_price.update_spreads()
                                # >>> END UPDATE <<<

                                # --- Logging Filter Logic (0.01 Check) ---
                                asset_key = asset_id if asset_id else "N/A"
                                if asset_key not in LAST_LOGGED_BBO:
                                    LAST_LOGGED_BBO[asset_key] = {'bid': current_bid, 'ask': current_ask}
                                    if current_bid is not None and current_ask is not None: should_log_now = True
                                else:
                                    last_bid = LAST_LOGGED_BBO[asset_key]['bid']
                                    last_ask = LAST_LOGGED_BBO[asset_key]['ask']
                                    if (current_bid is not None and last_bid is not None and abs(current_bid - last_bid) >= 0.01) or \
                                       (current_ask is not None and last_ask is not None and abs(current_ask - last_ask) >= 0.01):
                                        should_log_now = True
                                
                                if should_log_now:
                                    time_since_last_event = current_time - LAST_PRICE_CHANGE_TIME
                                    LAST_PRICE_CHANGE_TIME = current_time 
                                    bid, ask = raw_bid, raw_ask 
                                    LAST_LOGGED_BBO[asset_key]['bid'] = current_bid
                                    LAST_LOGGED_BBO[asset_key]['ask'] = current_ask
                                    price_info_print = f"BBO: {bid:<6} | {ask:<6}"
                                else:
                                    continue

                            # --- 2. HANDLE TRADE UPDATES (EXECUTIONS) ---
                            # Only for logging/velocity tracking. DO NOT update BBO store.
                            elif event_type == 'last_trade_price':
                                should_log_now = True
                                time_since_last_event = current_time - LAST_TRADE_TIME
                                LAST_TRADE_TIME = current_time
                                
                                trade_price_val = message.get('price')
                                trade_price = trade_price_val
                                trade_side = message.get('side', trade_side)
                                price_info_print = f"TRADE @ {trade_price:<6} ({trade_side})"
                                
                                # --- REMOVED STORE UPDATE LOGIC HERE TO PREVENT STALE PRICES ---
                            
                            elif event_type == 'book':
                                continue

                            # --- Final Write Check ---
                            if asset_id != "N/A" and should_log_now:
                                time_delta_ms_print = time_since_last_event * 1000
                                row = [
                                    f"{time_delta_ms_print:.3f}", 
                                    datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f"),
                                    event_type,
                                    asset_id,
                                    bid, ask, trade_price, trade_side,
                                ]
                                csv_writer.writerow(row)
                                
                                # Updated print to show full Bid/Ask context
                                store_status = (
                                    f"STORE: UP(A:{store_price.UP_askprice} B:{store_price.UP_bidprice} S:{store_price.spread_up}) | "
                                    f"DOWN(A:{store_price.DOWN_askprice} B:{store_price.DOWN_bidprice} S:{store_price.spread_down})"
                                )
                                
                                #print(f"[{time_delta_ms_print:.1f}ms] | EVENT: {event_type:<18} | {price_info_print:<20} | {store_status}")
                                                            
        except Exception as e:
            print(f"⚠️ WS Connection or Loop Error: {e}. Retrying in 2s...")
            await asyncio.sleep(2)

if __name__ == "__main__":
    try:
        asyncio.run(websocket_listener())
    except KeyboardInterrupt:
        print("\n🛑 Tester stopped.")