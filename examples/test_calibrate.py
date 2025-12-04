import asyncio
import os
import time
import orjson
import websockets
import statistics

# Using a popular market ID (Trump/Harris or similar) to ensure high traffic
# If this ID is inactive, replace it with any active ID from your active_ids.json
TEST_ASSET_ID = "61034468318337750752933170962983343104387885336208534678206636559613296076624"
URI = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

async def calibrate_via_websocket():
    print("📡 Connecting to WebSocket for High-Res Calibration...")
    print("   Collecting 50 samples to determine Baseline...")

    deltas = []
    
    try:
        async with websockets.connect(URI) as websocket:
            # Subscribe to something busy
            sub_msg = {"type": "market", "assets_ids": [TEST_ASSET_ID]}
            await websocket.send(orjson.dumps(sub_msg).decode())

            count = 0
            while count < 50:
                raw_msg = await websocket.recv()
                msg = orjson.loads(raw_msg)
                
                # We need data lists or single objects
                items = msg if isinstance(msg, list) else [msg]
                
                for item in items:
                    server_ts_raw = item.get("timestamp")
                    
                    if server_ts_raw:
                        # Capture arrival time immediately
                        local_ts_ms = time.time() * 1000
                        server_ts_ms = float(server_ts_raw)
                        
                        # Calculate Raw Delta
                        # This includes: Network Latency + Clock Offset
                        delta = local_ts_ms - server_ts_ms
                        
                        deltas.append(delta)
                        count += 1
                        print(f"   Sample {count}: {delta:.1f}ms")
                        
                        if count >= 50: break
                        
    except Exception as e:
        print(f"❌ Error: {e}")
        print("💡 Tip: Ensure TEST_ASSET_ID is valid and active.")
        return

    if not deltas:
        print("❌ No timestamped data received.")
        return

    # --- ANALYSIS ---
    # We want the MEDIAN (to ignore huge lag spikes)
    # We also look at the MINIMUM (Theoretical best-case latency)
    
    median_latency = statistics.median(deltas)
    min_latency = min(deltas)
    stdev = statistics.stdev(deltas)

    print("\n" + "="*40)
    print(f"📊 WEBSOCKET CALIBRATION RESULTS")
    print("="*40)
    print(f"🔹 Baseline (Median) Latency: {median_latency:.1f}ms")
    print(f"🔹 Best Case (Min) Latency:   {min_latency:.1f}ms")
    print(f"🔹 Jitter (Std Dev):          {stdev:.1f}ms")
    print("-" * 40)

    # INTERPRETATION
    # If the Baseline is roughly 10-100ms, your clock is fine.
    # If the Baseline is negative (e.g., -500ms), your clock is FAST.
    # If the Baseline is huge (e.g., +2000ms), your clock is SLOW.
    
    print("\n✅ RECOMMENDATION:")
    print("Use the 'Baseline Latency' as your 'Normal' state.")
    print("Set your 'Staleness Threshold' to: Baseline + 100ms")
    print("-" * 40)
    print(f"CLOCK_OFFSET_MS = 0  # No offset needed, trust the baseline")
    print(f"MAX_DATA_DELAY_MS = {median_latency + 100:.0f}  # The Guardrail")

if __name__ == "__main__":
    try:
        asyncio.run(calibrate_via_websocket())
    except KeyboardInterrupt:
        pass