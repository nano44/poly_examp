import asyncio
import datetime

import orjson
import websockets


def check_for_opportunity(price: float) -> None:
    """Placeholder for custom trading logic."""
    return


async def stream_book_ticker() -> None:
    url = "wss://stream.binance.com:9443/ws/btcusdt@bookTicker"
    backoff = 1
    while True:
        try:
            async with websockets.connect(
                url,
                ping_interval=15,
                ping_timeout=15,
                max_queue=1,
            ) as ws:
                backoff = 1  # reset backoff on successful connect
                print("Connected to Binance bookTicker stream")
                async for msg in ws:
                    data = orjson.loads(msg)
                    # bookTicker payloads omit event time; fall back to local receive time
                    event_time = data.get("E")
                    bid = float(data["b"])
                    ask = float(data["a"])
                    mid = (bid + ask) / 2.0
                    spread = ask - bid
                    local_time = int(datetime.datetime.utcnow().timestamp() * 1000)
                    latency = local_time - event_time if event_time is not None else 0
                    now = datetime.datetime.utcnow().strftime("%H:%M:%S.%f")[:-3]
                    print(
                        f"⚡ [{now}] BTC Mid-Price: ${mid:,.2f} | "
                        f"Spread: ${spread:,.2f} | Latency: {latency}ms"
                    )
                    check_for_opportunity(mid)
        except Exception as e:
            print(f"Connection error: {e}. Reconnecting in {backoff}s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


def main() -> None:
    try:
        asyncio.run(stream_book_ticker())
    except KeyboardInterrupt:
        # Graceful shutdown on Ctrl+C
        return


if __name__ == "__main__":
    main()
