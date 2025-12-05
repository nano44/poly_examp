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
        
        # Maps OrderID -> Local Send Timestamp
        self.pending_orders: Dict[str, float] = {}   
        
        # Maps OrderID -> First Server Timestamp (Arrival/Placement)
        self.server_acks: Dict[str, float] = {}
        
        # Maps OrderID -> Match Timestamp (Execution)
        self.orphaned_matches: Dict[str, float] = {} 
        
        self.running = False

    async def start(self):
        """Starts the background listener task."""
        self.running = True
        asyncio.create_task(self._listen())
        print("✅ Latency Monitor: Background Task Started")

    def mark_sent(self, order_id: str, t_sent: float):
        order_id = order_id.lower()
        
        # Check if we already have server data waiting (Race condition)
        if order_id in self.orphaned_matches: 
            match_time = self.orphaned_matches.pop(order_id)
            ack_time = self.server_acks.pop(order_id, match_time) # Default to match time if no ack
            self._finalize(order_id, t_sent, ack_time, match_time, source="Orphan (WS First)")
        else:
            self.pending_orders[order_id] = t_sent

    async def _listen(self):
        uri = "wss://ws-subscriptions-clob.polymarket.com/ws/user"
        
        while self.running:
            try:
                async with websockets.connect(uri, ping_interval=10, ping_timeout=20, max_queue=1000) as ws:
                    sub_msg = {
                        "markets": self.markets, 
                        "type": "user",
                        "auth": {
                            "apiKey": self.api_key, "secret": self.api_secret, "passphrase": self.passphrase
                        }
                    }
                    await ws.send(json.dumps(sub_msg))
                    print(f"✅ Latency Monitor: Subscribed to User Channel")
                    
                    async for msg in ws:
                        data = json.loads(msg)
                        
                        # Handle Dict (Single) or List (Batch)
                        if isinstance(data, dict):
                            self._route_event(data)
                        elif isinstance(data, list):
                            for event in data:
                                if isinstance(event, dict):
                                    self._route_event(event)

            except Exception as e:
                print(f"⚠️ Latency Monitor Disconnected: {e}. Retrying in 2s...")
                await asyncio.sleep(2)

    def _route_event(self, event):
        etype = event.get("event_type")
        
        # 1. ORDER EVENT (Arrival/Placement)
        if etype == "order" and event.get("type") == "PLACEMENT":
            self._handle_placement(event)
            
        # 2. TRADE EVENT (Execution)
        elif etype == "trade":
            self._handle_trade(event)
            
        # 3. ERROR
        elif event.get("type") == "error":
             print(f"⚠️ WS Error Response: {event.get('message')}")

    def _handle_placement(self, event):
        """Records the moment the server accepted the order."""
        oid = event.get("id", "").lower() # Note: In order events, ID is 'id', not 'taker_order_id'
        if not oid: return

        raw_ts = float(event.get("timestamp") or 0)
        ack_time = raw_ts / 1000.0 if raw_ts > 10_000_000_000 else raw_ts
        
        # Store this as the "Server Arrival Time"
        self.server_acks[oid] = ack_time

    def _handle_trade(self, event):
        """Records the moment the server executed the trade."""
        taker_oid = event.get("taker_order_id", "").lower()
        
        raw_ts = float(event.get("matchtime") or event.get("timestamp") or 0)
        match_time = raw_ts / 1000.0 if raw_ts > 10_000_000_000 else raw_ts

        # If we sent this order, we can now finalize the report
        if taker_oid in self.pending_orders:
            t_sent = self.pending_orders.pop(taker_oid)
            # Retrieve the ACK time (Arrival) if we captured it earlier
            ack_time = self.server_acks.pop(taker_oid, match_time) 
            self._finalize(taker_oid, t_sent, ack_time, match_time, source="Standard")
        else:
            # Save for later
            self.orphaned_matches[taker_oid] = match_time

    def _finalize(self, oid, sent, ack, matched, source):
        # Calc 1: Network Latency (Sent -> Server Ack)
        net_latency = (ack - sent) * 1000.0
        
        # Calc 2: Engine Latency (Server Ack -> Matched)
        engine_latency = (matched - ack) * 1000.0
        
        # Calc 3: Total
        total_latency = (matched - sent) * 1000.0
        

        print(f"🎯 \033[92mDETAILED LATENCY REPORT\033[0m [{oid[:8]}...]")
        print(f"   1. Sent (Local):   {sent:.4f}")
        print(f"   2. Arrived (Poly): {ack:.4f}  (Network: {net_latency:.2f}ms)")
        print(f"   3. Matched (Poly): {matched:.4f}  (Engine:  {engine_latency:.2f}ms)")
        print(f"   ====================================================")
        print(f"   \033[1mTOTAL LATENCY:     {total_latency:.2f} ms\033[0m")
        print("----------------------------------------------------\n")