import asyncio
import os
import time
import orjson
import websockets
from dotenv import load_dotenv

# Ensure environment variables are loaded
load_dotenv()

# --- GLOBAL STATE (Minimal required to function) ---
POLY_MARKET_CACHE = {
    "UP": {"id": None, "bid": 0.0, "ask": 0.0, "spread": 0.0, "last_updated": 0.0},
    "DOWN": {"id": None, "bid": 0.0, "ask": 0.0, "spread": 0.0, "last_updated": 0.0},
}
NEEDS_NEW_IDS = False
CACHE_LOCK = asyncio.Lock()
LAST_MSG_TIME = 0.0

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
    global NEEDS_NEW_IDS, LAST_MSG_TIME
    # Using the path confirmed by the previous example code
    uri = "wss://ws-subscriptions-clob.polymarket.com/ws/market" 
    
    print("\n--- Polymarket Websocket Tester ---")
    
    while True:
        # Wait until we have valid IDs before attempting connection
        while NEEDS_NEW_IDS or not cache_has_ids():
            await refresh_market_ids()
            await asyncio.sleep(1)

        token_ids = [POLY_MARKET_CACHE["UP"]["id"], POLY_MARKET_CACHE["DOWN"]["id"]]
        
        try:
            connect_start = time.time()
            async with websockets.connect(uri, ping_interval=20, ping_timeout=20) as websocket:
                connect_end = time.time()
                print(f"\n✅ WS Connected. Latency: {(connect_end - connect_start) * 1000:.1f}ms")
                
                # 1. Subscribe to the market channel
                sub_msg = {"type": "market", "assets_ids": token_ids}
                await websocket.send(orjson.dumps(sub_msg).decode())
                print(f"📡 Subscribed to {len(token_ids)} assets. Waiting for stream...")

# 2. Listen for messages
                async for raw_msg in websocket:
                    if NEEDS_NEW_IDS:
                        print("🔄 IDs changed. Reconnecting WS...")
                        break
                    
                    data = orjson.loads(raw_msg)
                    
                    # Handle single message or batched list
                    messages = data if isinstance(data, list) else [data]
                    
                    for message in messages:
                        # 3. Time Delta Analysis
                        current_time = time.time()
                        time_delta_ms = 0
                        if LAST_MSG_TIME != 0.0:
                            time_delta_ms = (current_time - LAST_MSG_TIME) * 1000
                        LAST_MSG_TIME = current_time
                        
# --- PRICE DATA EXTRACTION ---
                        event_type = message.get("event_type", "Unknown")
                        asset_id = message.get("asset_id") or "N/A"
                        price_info = ""

                        # --- FIX: Skip the initial book snapshot ---
                        if event_type == 'book':
                            # We receive this, but we don't need to process or print it for latency testing.
                            continue 
                        # ---------------------------------------------
                        
                        if event_type == 'price_change':
                            changes = message.get('price_changes', [])
                            if changes:
                                # Price changes often contain BBO updates directly in the first item
                                change = changes[0]
                                asset_id = change.get("asset_id", asset_id)
                                bid = change.get("best_bid", "N/A")
                                ask = change.get("best_ask", "N/A")
                                price_info = f"BBO: {bid:<6} | {ask:<6}"

                        elif event_type == 'last_trade_price':
                            price = message.get('price', 'N/A')
                            side = message.get('side', 'N/A')
                            price_info = f"TRADE @ {price:<6} ({side})"

                        # 4. Print results
                        print(
                            f"[{time_delta_ms:.1f}ms] | EVENT: {event_type:<18} | ID: {asset_id[:8]}... | {price_info}"
                        )
                                                
                                                
        except Exception as e:
            # Note: The 'Task was destroyed' errors are cosmetic due to KeyboardInterrupt 
            # while websockets is cleaning up. The core error is handled here.
            print(f"⚠️ WS Connection or Loop Error: {e}. Retrying in 2s...")
            await asyncio.sleep(2)


if __name__ == "__main__":
    try:
        asyncio.run(websocket_listener())
    except KeyboardInterrupt:
        print("\n🛑 Tester stopped.")