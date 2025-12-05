import sys
import os

# 1. Path Fix: Ensure we can import 'sign_order' from the current or parent directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
# If sign_order is one level up, uncomment this:
# sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import time
import json
import websockets
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY

# IMPORT YOUR CUSTOM SIGNER
from sign_order import FastPolymarketSigner

load_dotenv()

# --- CONFIGURATION ---
TOKEN_ID = "15890227592210907756319279312361426008421148618679272278455310642619948758578" 
SAFE_PRICE = 0.02  

HOST = "https://clob.polymarket.com"
KEY = os.getenv("PK")
FUNDER = os.getenv("FUNDER")
CHAIN_ID = 137
SIG_TYPE = int(os.getenv("SIGNATURE_TYPE", 1))

CREDS = ApiCreds(
    api_key=os.getenv("CLOB_API_KEY"),
    api_secret=os.getenv("CLOB_SECRET"),
    api_passphrase=os.getenv("CLOB_PASS_PHRASE")
)

# 1. Initialize Client (Connection Pooling)
client = ClobClient(
    HOST, 
    key=KEY, 
    chain_id=CHAIN_ID, 
    funder=FUNDER, 
    creds=CREDS,
    signature_type=SIG_TYPE
)

# 2. Initialize Your Fast Signer (Matches your Engine Logic)
signer = FastPolymarketSigner(
    private_key_hex=KEY,
    funder=FUNDER,
    signature_type=SIG_TYPE
)

async def monitor_latency():
    """Listens for the 'Order Placed' event to capture Server Ack time."""
    uri = "wss://ws-subscriptions-clob.polymarket.com/ws/user"
    
    # FIX: Use correct attribute names for Auth
    auth = {
        "apiKey": CREDS.api_key, 
        "secret": CREDS.api_secret, 
        "passphrase": CREDS.api_passphrase 
    }
    
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"markets": [], "type": "user", "auth": auth}))
        print("   ✅ WS Monitor Connected.")
        
        async for msg in ws:
            data = json.loads(msg)
            events = data if isinstance(data, list) else [data]
            
            for event in events:
                if isinstance(event, dict) and event.get("event_type") == "order":
                    if event.get("type") == "PLACEMENT":
                        oid = event.get("id")
                        raw_ts = float(event.get("timestamp"))
                        server_time = raw_ts / 1000.0 if raw_ts > 10_000_000_000 else raw_ts
                        return oid, server_time

async def run_test(order_type, type_name):
    print(f"\n🧪 Testing {type_name} Latency...")
    
    monitor_task = asyncio.create_task(monitor_latency())
    await asyncio.sleep(1) 
    
    # 1. Prepare Order Args
    order_args = OrderArgs(price=0.70, size=2, side=BUY, token_id=TOKEN_ID)
    
    # 2. Sign using YOUR Signer (The feedback's crucial fix)
    signed_order = signer.sign_order(order_args)
    
    # 3. Send
    t_start = time.time()
    print(f"   🚀 Sending at: {t_start:.4f}")
    
    try:
        # Pass the pre-signed order directly to post_order
        resp = await asyncio.to_thread(client.post_order, signed_order, order_type)
        
        # Check basic success
        if isinstance(resp, dict) and not resp.get("success", False) and not resp.get("orderID"):
             # Sometimes FAK returns error if no match, which is fine, but let's log it
             pass 

        t_rest_ack = time.time()
        print(f"   ↩️ REST Returned: {(t_rest_ack - t_start)*1000:.1f}ms (Round-Trip)")
        
        try:
            oid, server_ts = await asyncio.wait_for(monitor_task, timeout=5.0)
            
            latency = (server_ts - t_start) * 1000.0
            print(f"   📉 {type_name} SERVER ARRIVAL LATENCY: {latency:.2f} ms")
            
            if order_type == OrderType.GTC:
                await asyncio.to_thread(client.cancel, oid)
                print("   🗑️ GTC Order Cancelled.")
                
        except asyncio.TimeoutError:
            print("   ⚠️ WS Monitor Timed out (FAK might not emit placement event on immediate fail).")
            
    except Exception as e:
        print(f"   ⚠️ Request Error (Normal for FAK no-match): {e}")

async def main():
    print("========================================")
    print("🏁 STARTING LATENCY DIAGNOSTICS")
    print("========================================\n")

    # --- STEP 1: WARM-UP ---
    print("🔥 PHASE 1: WARMING UP CONNECTION...")
    try:
        t_warm_start = time.time()
        await asyncio.to_thread(client.get_markets, next_cursor="") 
        print(f"   ✅ Warm-up complete in {(time.time() - t_warm_start)*1000:.1f}ms")
    except Exception as e:
        print(f"   ⚠️ Warm-up failed: {e}")

    # --- STEP 2: TEST GTC ---
    print("\n----------------------------------------")
    print("🏁 PHASE 2: GTC ORDERS (Limit Orders)")
    for i in range(3):
        await run_test(OrderType.GTC, f"GTC #{i+1}")
        await asyncio.sleep(0.5)
        
    # --- STEP 3: TEST FAK ---
    print("\n----------------------------------------")
    print("🏁 PHASE 3: FAK ORDERS (Fill-And-Kill)")
    for i in range(3):
        await run_test(OrderType.FAK, f"FAK #{i+1}")
        await asyncio.sleep(0.5)

if __name__ == "__main__":
    if TOKEN_ID == "YOUR_TOKEN_ID_HERE":
        print("❌ ERROR: Please edit the script and set a valid TOKEN_ID first.")
    else:
        asyncio.run(main())