import asyncio
import time
import os
import sys

import orjson
import websockets

# Use a stream that includes "E" (event time), e.g. trade or aggTrade
BINANCE_STREAM = os.getenv("BINANCE_STREAM", "btcusdt@trade")
WS_URL = f"wss://stream.binance.com/ws/{BINANCE_STREAM}"

STATS_EVERY = 100


async def latency_tester():
    print(f"🔌 Connecting to Binance stream: {WS_URL}")
    backoff = 1
    latencies = []

    while True:
        try:
            async with websockets.connect(WS_URL, max_queue=1) as ws:
                print("⚡ Connected to Binance stream")
                backoff = 1
                msg_count = 0

                async for msg in ws:
                    recv_ts = time.time()  # local receive time (seconds)
                    data = orjson.loads(msg)

                    # trade / aggTrade style payloads contain "E" = event time (ms)
                    event_ts_ms = data.get("E")
                    if event_ts_ms is None:
                        # Safety: if this stream type doesn't have E, skip
                        continue

                    latency_ms = recv_ts * 1000.0 - event_ts_ms
                    latencies.append(latency_ms)
                    msg_count += 1

                    print(f"📡 Feed latency: {latency_ms:.1f} ms")

                    if msg_count % STATS_EVERY == 0:
                        lat_sorted = sorted(latencies)
                        n = len(lat_sorted)
                        avg = sum(lat_sorted) / n
                        p50 = lat_sorted[int(0.50 * (n - 1))]
                        p95 = lat_sorted[int(0.95 * (n - 1))]
                        p99 = lat_sorted[int(0.99 * (n - 1))]
                        print(
                            f"\n📊 Latency stats over {n} msgs:"
                            f"\n   min  = {lat_sorted[0]:.1f} ms"
                            f"\n   p50  = {p50:.1f} ms"
                            f"\n   p95  = {p95:.1f} ms"
                            f"\n   p99  = {p99:.1f} ms"
                            f"\n   max  = {lat_sorted[-1]:.1f} ms"
                            f"\n   avg  = {avg:.1f} ms\n"
                        )

        except asyncio.CancelledError:
            # Graceful exit
            print("🛑 Latency tester cancelled.")
            break
        except Exception as e:
            print(f"⚠️ Stream error: {e}. Reconnecting in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 10)


def main():
    try:
        asyncio.run(latency_tester())
    except KeyboardInterrupt:
        print("Exiting latency tester.")
        # Avoid noisy traceback on shutdown
        sys.exit(0)


if __name__ == "__main__":
    main()