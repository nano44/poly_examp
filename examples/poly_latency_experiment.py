import sys
import os
import asyncio
import time
import json
import websockets
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY
from examples.sign_order import FastPolymarketSigner

# 1. Path Fix
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

load_dotenv()

# --- CONFIGURATION ---
TOKEN_ID = "7194396064974462717435510859272757538703420461935855103761678212914815664999" 
SAFE_PRICE = 0.02 # For GTC tests
FILL_PRICE = 0.70 # For FAK tests

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

# 1. Initialize Client
client = ClobClient(
    HOST, key=KEY, chain_id=CHAIN_ID, funder=FUNDER, creds=CREDS, signature_type=SIG_TYPE
)

# 2. Initialize Signer
signer = FastPolymarketSigner(
    private_key_hex=KEY, funder=FUNDER, signature_type=SIG_TYPE
)

class LatencyMonitor:
    def __init__(self):
        self.captured_events = [] # Store everything we see
        self.running = False
        self.task = None

    async def start(self):
        self.running = True
        self.captured_events = [] # Clear buffer
        self.task = asyncio.create_task(self._listen())
        await asyncio.sleep(1) # Warmup wait

    async def stop(self):
        self.running = False
        if self.task: self.task.cancel()

    async def _listen(self):
        uri = "wss://ws-subscriptions-clob.polymarket.com/ws/user"
        auth = {
            "apiKey": CREDS.api_key, 
            "secret": CREDS.api_secret, 
            "passphrase": CREDS.api_passphrase 
        }
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps({"markets": [], "type": "user", "auth": auth}))
            print("   ✅ WS Monitor Connected & Buffering...")
            
            async for msg in ws:
                data = json.loads(msg)
                events = data if isinstance(data, list) else [data]
                for event in events:
                    if isinstance(event, dict):
                        # Capture Time immediately
                        event['_local_recv_time'] = time.time()
                        self.captured_events.append(event)

    def find_order(self, order_id):
        """Look through the buffer for the specific Order ID"""
        target = order_id.lower()
        
        for event in self.captured_events:
            # Check 1: PLACEMENT (Resting)
            if event.get("event_type") == "order" and event.get("type") == "PLACEMENT":
                if event.get("id", "").lower() == target:
                    return self._extract_time(event)

            # Check 2: TRADE (Immediate Fill)
            if event.get("event_type") == "trade":
                if event.get("taker_order_id", "").lower() == target:
                    return self._extract_time(event)
        return None

    def _extract_time(self, event):
        raw_ts = float(event.get("matchtime") or event.get("timestamp") or 0)
        return raw_ts / 1000.0 if raw_ts > 10_000_000_000 else raw_ts

monitor = LatencyMonitor()

async def run_test(order_type, type_name, price):
    print(f"\n🧪 Testing {type_name} Latency...")
    
    # 1. Start Buffering BEFORE we send
    await monitor.start()
    
    order_args = OrderArgs(price=price, size=5.0, side=BUY, token_id=TOKEN_ID)
    signed_order = signer.sign_order(order_args)
    
    t_start = time.time()
    print(f"   🚀 Sending at: {t_start:.4f}")
    
    order_id = None
    try:
        resp = await asyncio.to_thread(client.post_order, signed_order, order_type)
        t_rest_ack = time.time()
        print(f"   ↩️ REST Returned: {(t_rest_ack - t_start)*1000:.1f}ms (Round-Trip)")
        
        if isinstance(resp, dict) and resp.get("orderID"):
            order_id = resp.get("orderID")
        
    except Exception as e:
        print(f"   ⚠️ Request Error: {e}")

    # 2. Look for the ID in the buffer
    if order_id:
        print(f"   🔎 Searching buffer for ID: {order_id}...")
        
        # Give WS a moment to catch up if REST was faster (unlikely)
        await asyncio.sleep(0.5) 
        
        server_ts = monitor.find_order(order_id)
        
        if server_ts:
            latency = (server_ts - t_start) * 1000.0
            print(f"   📉 {type_name} TRUE SERVER LATENCY: {latency:.2f} ms")
        else:
            print("   ⚠️ Event not found in WS buffer (Packet Loss?)")
            
        # Cleanup GTC
        if order_type == OrderType.GTC:
            try:
                await asyncio.to_thread(client.cancel, order_id)
                print("   🗑️ Order Cancelled.")
            except: pass
    else:
        print("   ❌ No Order ID returned, cannot verify latency.")

    await monitor.stop()

async def main():
    print("========================================")
    print("🏁 STARTING ROBUST LATENCY DIAGNOSTICS")
    print("========================================\n")

    # WARM UP
    try:
        await asyncio.to_thread(client.get_markets, next_cursor="") 
        print("   ✅ Warm-up complete")
    except: pass

    # PHASE 1: GTC (Passive)
    print("\n----------------------------------------")
    print("🏁 PHASE 1: GTC ORDERS (Passive/Resting)")
    for i in range(2):
        await run_test(OrderType.GTC, f"GTC #{i+1}", SAFE_PRICE)
        
    # PHASE 2: FAK (Aggressive)
    print("\n----------------------------------------")
    print("🏁 PHASE 2: FAK ORDERS (Aggressive/Matching)")
    # Note: Ensure you have >$1.50 USDC for this to work
    for i in range(2):
        await run_test(OrderType.FAK, f"FAK #{i+1}", FILL_PRICE)

if __name__ == "__main__":
    asyncio.run(main())