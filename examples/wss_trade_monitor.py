import asyncio
import json
import time
import websockets
from typing import Dict, List, Optional

class PolymarketLatencyMonitor:
    def __init__(self, api_key: str, api_secret: str, passphrase: str, markets: Optional[List[str]] = None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.markets = markets or []
        self.pending_orders: Dict[str, float] = {}   
        self.orphaned_matches: Dict[str, float] = {} 
        self.running = False

    async def start(self):
        """Starts the background listener task."""
        self.running = True
        asyncio.create_task(self._listen())
        print("✅ Latency Monitor: Background Task Started")

    def mark_sent(self, order_id: str, t_sent: float):
        """
        Call this immediately after you get an order ID from the REST API.
        """
        # Normalize to lowercase to ensure matching works
        order_id = order_id.lower()
        
        # print(f"👀 Monitor watching for: {order_id[:8]}...") # Optional Debug
        
        if order_id in self.orphaned_matches: 
            match_time = self.orphaned_matches.pop(order_id)
            self._finalize(order_id, t_sent, match_time, source="Orphan (WS First)")
        else:
            self.pending_orders[order_id] = t_sent

    async def _listen(self):
        uri = "wss://ws-subscriptions-clob.polymarket.com/ws/user"
        
        while self.running:
            try:
                # Ping settings help keep the connection alive on AWS
                async with websockets.connect(
                    uri, 
                    ping_interval=10, 
                    ping_timeout=20, 
                    max_queue=1000
                ) as ws:
                    
                    sub_msg = {
                        "markets": self.markets, 
                        "type": "user",
                        "auth": {
                            "apiKey": self.api_key,
                            "secret": self.api_secret,
                            "passphrase": self.passphrase
                        }
                    }
                    
                    await ws.send(json.dumps(sub_msg))
                    print(f"✅ Latency Monitor: Subscribed to User Channel")
                    
                    async for msg in ws:
                        data = json.loads(msg)
                        
                        # --- CASE 1: Single Dictionary (The Fix) ---
                        if isinstance(data, dict):
                            # Check for Trade Event
                            if data.get("event_type") == "trade":
                                self._handle_trade(data)
                            # Check for Error
                            elif data.get("type") == "error":
                                print(f"⚠️ WS Error Response: {data.get('message')}")

                        # --- CASE 2: List of Events (Batch) ---
                        elif isinstance(data, list):
                            for event in data:
                                if isinstance(event, dict) and event.get("event_type") == "trade":
                                    self._handle_trade(event)

            except Exception as e:
                print(f"⚠️ Latency Monitor Disconnected: {e}. Retrying in 2s...")
                await asyncio.sleep(2)

    def _handle_trade(self, event):
        # Extract IDs (Lowercase for safety)
        taker_oid = event.get("taker_order_id", "").lower()
        maker_orders = event.get("maker_orders", [])
        
        # Extract Server Timestamp
        # 'matchtime' is the engine execution time (preferred), fallback to 'timestamp'
        raw_ts = float(event.get("matchtime") or event.get("timestamp") or 0)
        
        if raw_ts == 0: return

        # Normalize: If > 10 billion, it's ms. Convert to seconds.
        match_time = raw_ts / 1000.0 if raw_ts > 10_000_000_000 else raw_ts

        # 1. Check Taker ID
        if taker_oid in self.pending_orders:
            t_sent = self.pending_orders.pop(taker_oid)
            self._finalize(taker_oid, t_sent, match_time, source="Standard")
            return
        
        # 2. Check Maker IDs (just in case)
        for maker_order in maker_orders:
            maker_oid = maker_order.get("order_id", "").lower()
            if maker_oid in self.pending_orders:
                t_sent = self.pending_orders.pop(maker_oid)
                self._finalize(maker_oid, t_sent, match_time, source="Standard (Maker)")
                return

        # 3. Store as Orphan (WS arrived before REST return)
        if taker_oid:
             self.orphaned_matches[taker_oid] = match_time 

    def _finalize(self, oid, sent, matched, source):
        # Calculate Latency in Milliseconds
        latency_ms = (matched - sent) * 1000.0
        

        print(f"🎯 \033[92mMATCH CONFIRMED\033[0m [{oid[:8]}...]")
        print(f"   Sent (Local):   {sent:.4f}")
        print(f"   Matched (Poly): {matched:.4f}")
        print(f"   \033[1mLatency:        {latency_ms:.2f} ms\033[0m  (via {source})")
        print("----------------------------------------------------\n")