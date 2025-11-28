import asyncio
import time

import orjson
import websockets


async def listen_trades():
    url = "wss://stream.binance.com/ws/btcusdt@aggTrade"
    async with websockets.connect(url) as ws:
        print(f"⚡ Connected to {url}")
        print("Waiting for trades...")

        start_time = time.time()
        count = 0

        async for msg in ws:
            data = orjson.loads(msg)
            price = float(data["p"])
            qty = float(data["q"])
            side = "SELL" if data["m"] else "BUY"
            if qty >= 0.1:  # Only print trades with quantity >= 0.5 BTC
                print(f"[{side}] {qty:.4f} BTC @ {price:.2f}")

            count += 1
            #if count >= 100:  # Stop after 100 trades
            #    break

        duration = time.time() - start_time
        print(
            f"\n⚡ Speed Test: {count} trades in {duration:.4f} seconds "
            f"({count/duration:.1f} trades/sec)"
        )


if __name__ == "__main__":
    asyncio.run(listen_trades())
