import asyncio
import os
import time
import orjson
import websockets
from datetime import datetime 
from dotenv import load_dotenv

# Ensure environment variables are loaded
load_dotenv()

# --- GLOBAL STATE ---
POLY_MARKET_CACHE = {
    "UP": {"id": None, "bid": 0.0, "ask": 0.0, "spread": 0.0, "last_updated": 0.0},
    "DOWN": {"id": None, "bid": 0.0, "ask": 0.0, "spread": 0.0, "last_updated": 0.0},
}
NEEDS_NEW_IDS = False
CACHE_LOCK = asyncio.Lock()
# --- SPECIALIZED LATENCY TRACKERS ---
LAST_PRICE_CHANGE_TIME = 0.0 
LAST_TRADE_TIME = 0.0
# --- END SPECIALIZED TRACKERS ---
LAST_LOGGED_BBO = {} # Key: Asset_ID, Value: {'bid': float, 'ask': float}

# --- POLYMARKET HELPERS ---

def cache_has_ids() -> bool:
    return bool(POLY_MARKET_CACHE["UP"]["id"] and POLY_MARKET_CACHE["DOWN"]["id"])

async def refresh_market_ids() -> bool:
    """Reads IDs from active_ids.json (required for subscription)."""
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
                print(f"🔄 LOADED MARKET: {data.get('market', 'Unknown')} | UP: {up_id[:8]}... | DOWN: {down_id[:8]}...")
                POLY_MARKET_CACHE["UP"] = {"id": up_id, "bid": 0.0, "ask": 0.0, "spread": 0.0, "last_updated": 0.0}
                POLY_MARKET_CACHE["DOWN"] = {"id": down_id, "bid": 0.0, "ask": 0.0, "spread": 0.0, "last_updated": 0.0}
        NEEDS_NEW_IDS = False
        return True
    except Exception as e:
        print(f"❌ Error reading JSON: {e}")
        return False

# --- CORE WEBSOCKET LISTENER ---

async def websocket_listener() -> None:
    global NEEDS_NEW_IDS, LAST_PRICE_CHANGE_TIME, LAST_TRADE_TIME
    
    uri = "wss://ws-subscriptions-clob.polymarket.com/ws/market" 
    print("\n--- Polymarket Websocket Tester ---")
    
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
                print(f"📡 Subscribed to {len(token_ids)} assets. Logging to console...")

                async for raw_msg in websocket:
                    if NEEDS_NEW_IDS:
                        print("🔄 IDs changed. Reconnecting WS...")
                        break
                    
                    data = orjson.loads(raw_msg)
                    messages = data if isinstance(data, list) else [data]
                    
                    for message in messages:
                        current_time = time.time()
                        
                        # --- Initialize specialized trackers on first run ---
                        if LAST_PRICE_CHANGE_TIME == 0.0:
                            LAST_PRICE_CHANGE_TIME = current_time
                        if LAST_TRADE_TIME == 0.0:
                            LAST_TRADE_TIME = current_time
                        
                        time_since_last_event = 0.0
                        
                        # --- Data Initialization ---
                        event_type = message.get("event_type", "Unknown")
                        bid, ask, trade_price, trade_side = 'N/A', 'N/A', 'N/A', 'N/A'
                        price_info_print = ""
                        should_log_now = False
                        asset_id = message.get("asset_id") 
                        
                        # --- Logic based on Event Type ---

                        if event_type == 'price_change':
                            changes = message.get('price_changes', [])
                            if not changes: continue
                            
                            first_change = changes[0]
                            asset_id = first_change.get("asset_id", asset_id) 
                            
                            raw_bid = first_change.get("best_bid")
                            raw_ask = first_change.get("best_ask")
                            
                            current_bid = float(raw_bid) if raw_bid and raw_bid != 'N/A' else None
                            current_ask = float(raw_ask) if raw_ask and raw_ask != 'N/A' else None
                            
                            # --- 1. APPLY FILTER LOGIC ---
                            asset_key = asset_id if asset_id else "N/A"
                            
                            if asset_key not in LAST_LOGGED_BBO:
                                # Initialization: Log the very first BBO received
                                LAST_LOGGED_BBO[asset_key] = {'bid': current_bid, 'ask': current_ask}
                                if current_bid is not None and current_ask is not None: should_log_now = True
                            else:
                                # Check for 0.01 (1 cent) change in either Bid or Ask
                                last_bid = LAST_LOGGED_BBO[asset_key]['bid']
                                last_ask = LAST_LOGGED_BBO[asset_key]['ask']
                                
                                if (current_bid is not None and last_bid is not None and abs(current_bid - last_bid) >= 0.01) or \
                                   (current_ask is not None and last_ask is not None and abs(current_ask - last_ask) >= 0.01):
                                    should_log_now = True
                            
                            # Update cache and prepare data IF we decided to log
                            if should_log_now:
                                # --- TRACKING: TIME SINCE LAST PRICE CHANGE ---
                                time_since_last_event = current_time - LAST_PRICE_CHANGE_TIME
                                LAST_PRICE_CHANGE_TIME = current_time # Update tracker
                                
                                bid, ask = raw_bid, raw_ask 
                                LAST_LOGGED_BBO[asset_key]['bid'] = current_bid
                                LAST_LOGGED_BBO[asset_key]['ask'] = current_ask
                                price_info_print = f"BBO: {bid:<6} | {ask:<6}"
                            else:
                                continue # Skip printing if no relevant price change

                        elif event_type == 'last_trade_price':
                            # --- TRACKING: TIME SINCE LAST TRADE ---
                            should_log_now = True
                            time_since_last_event = current_time - LAST_TRADE_TIME
                            LAST_TRADE_TIME = current_time # Update tracker
                            
                            trade_price = message.get('price', trade_price)
                            trade_side = message.get('side', trade_side)
                            price_info_print = f"TRADE @ {trade_price:<6} ({trade_side})"
                        
                        elif event_type == 'book':
                            continue # Skip logging book snapshot

                        # --- Final Write Check ---
                        if asset_id != "N/A" and should_log_now:
                            time_delta_ms_print = time_since_last_event * 1000
                            
                            # Print results to console
                            print(f"[{time_delta_ms_print:.1f}ms] | EVENT: {event_type:<18} | ID: {asset_id[:8]}... | {price_info_print}")
                                                            
        except Exception as e:
            print(f"⚠️ WS Connection or Loop Error: {e}. Retrying in 2s...")
            await asyncio.sleep(2)

# --- ENTRY POINT ---
if __name__ == "__main__":
    try:
        asyncio.run(websocket_listener())
    except KeyboardInterrupt:
        print("\n🛑 Tester stopped.")
