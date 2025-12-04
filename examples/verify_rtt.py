import asyncio
import time
import orjson
import websockets

# Use a specific asset
TEST_ASSET_ID = "84517093281453194504195657774426519876996049904556962453977063633430553967768"
URI = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

async def verify_true_latency_with_drain():
    print(f"🧹 STARTING BUFFER-DRAIN LATENCY TEST")
    print(f"    We will empty the queue before every ping.\n")

    async with websockets.connect(URI) as websocket:
        # Subscribe once
        msg = {"type": "market", "assets_ids": [TEST_ASSET_ID]}
        await websocket.send(orjson.dumps(msg).decode())
        print("✅ Connected & Subscribed. Stabilizing...")
        await asyncio.sleep(2)

        for i in range(100):
            # --- STEP 1: DRAIN THE BUFFER ---
            # Read everything currently in memory until the queue is empty
            while True:
                try:
                    # Try to read with a tiny timeout (0.001s)
                    # If there is data, we throw it away.
                    # If no data, it raises TimeoutError, and we proceed.
                    await asyncio.wait_for(websocket.recv(), timeout=0.001)
                except asyncio.TimeoutError:
                    break # Queue is empty!

            # --- STEP 2: SEND APPLICATION PING ---
            # We resend the sub message just to force a reply
            t0 = time.perf_counter()
            await websocket.send(orjson.dumps(msg).decode())
            
            # --- STEP 3: WAIT FOR NEW DATA ---
            # This MUST come from the network because we just emptied the queue
            await websocket.recv()
            t1 = time.perf_counter()
            
            rtt = (t1 - t0) * 1000
            print(f"   Run {i+1}: Real RTT = {rtt:.2f}ms")
            
            await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(verify_true_latency_with_drain())
    except KeyboardInterrupt:
        pass