import asyncio
import websockets
import json

# Configuration
TARGET_SYMBOL = "btcusdt"  # Change this to 'ethusdt' or 'solusdt' as needed

async def listen():
    url = "wss://ws-live-data.polymarket.com"
    
    async with websockets.connect(url) as websocket:
        print(f"Connected. Subscribing to ALL, filtering locally for '{TARGET_SYMBOL}'...")
        
        # We use the "No Filter" subscription because it is 100% reliable
        subscribe_message = {
            "action": "subscribe",
            "subscriptions": [
                {
                    "topic": "crypto_prices",
                    "type": "update"
                }
            ]
        }
        
        await websocket.send(json.dumps(subscribe_message))
        print("Listening...")

        while True:
            try:
                response = await websocket.recv()
                if not response: continue
                
                data = json.loads(response)
                msg_type = data.get("type")
                payload = data.get("payload", {})

                # 1. Handle Live Updates
                if msg_type == "update":
                    # CLIENT-SIDE FILTERING
                    # We check the symbol here instead of asking the server to do it
                    if payload.get("symbol") == TARGET_SYMBOL:
                        price = payload.get("value")
                        ts = payload.get("timestamp")
                        print(f"MATCH: {TARGET_SYMBOL} price is ${price}")

                # 2. Handle History (Optional)
                elif msg_type == "subscribe":
                    print("Received history batch (skipping...)")

            except Exception as e:
                print(f"Error: {e}")
                break

if __name__ == "__main__":
    try:
        asyncio.run(listen())
    except KeyboardInterrupt:
        print("\nStopped.")