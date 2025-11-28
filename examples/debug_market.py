import asyncio
import os
import pprint

import orjson
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BookParams

load_dotenv()


async def inspect_market():
    # 1. Load IDs from your JSON file
    try:
        with open("active_ids.json", "r") as f:
            data = orjson.loads(f.read())
            up_id = data.get("UP")
            down_id = data.get("DOWN")
            print(f"🔍 Inspecting Market: {data.get('market')}")
    except Exception:
        print("❌ Could not read active_ids.json. Run the helper script first.")
        return

    # 2. Initialize Client
    host = "https://clob.polymarket.com"
    key = os.getenv("PK")
    client = ClobClient(host, key=key, chain_id=137)

    print(f"\n{'='*60}")
    print(f"{'SIDE':<6} | {'SOURCE':<12} | {'PRICE / SPREAD':<20} | {'STATUS':<10}")
    print(f"{'-'*60}")

    # 3. Fetch Data for UP and DOWN
    for label, token_id in [("UP", up_id), ("DOWN", down_id)]:
        if not token_id:
            continue

        print(f"\n🔵 --- FETCHING DATA FOR {label} ({token_id}) ---")

        # A. Get the Book
        book_resp = await asyncio.to_thread(
            client.get_order_books, [BookParams(token_id=token_id)]
        )
        book = book_resp[0]

        # --- RAW BOOK PRINT ---
        print(f"\n📜 RAW ORDER BOOK RESPONSE ({label}):")
        try:
            pprint.pprint(book.__dict__)
        except Exception:
            print(book)
        print("-" * 30)

        # B. Get the "Real" Midpoint
        try:
            mid_resp = await asyncio.to_thread(client.get_midpoint, token_id)
            mid_price = float(mid_resp.get("mid") or 0.0)
            print(f"📜 RAW MIDPOINT RESPONSE ({label}):")
            pprint.pprint(mid_resp)
            print("-" * 30)
        except Exception as e:
            print(f"❌ Midpoint Error: {e}")
            mid_price = 0.0

        # C. Get Last Trade Price
        try:
            last_trade_resp = await asyncio.to_thread(
                client.get_last_trade_price, token_id
            )
            last_price = float(last_trade_resp.get("price") or 0.0)
            print(f"📜 RAW LAST TRADE RESPONSE ({label}):")
            pprint.pprint(last_trade_resp)
            print("-" * 30)
        except Exception as e:
            print(f"❌ Last Trade Error: {e}")
            last_price = 0.0

        # --- ANALYSIS ---
        best_bid = float(book.bids[0].price) if book.bids else 0.00
        best_ask = float(book.asks[0].price) if book.asks else 0.00
        spread = best_ask - best_bid

        is_ghost = (best_bid <= 0.01 and best_ask >= 0.99)

        print(f"\n📊 SUMMARY for {label}:")
        print(
            f"{label:<6} | {'OrderBook':<12} | {best_bid:.2f} / {best_ask:.2f} ({spread:.2f}) | "
            f"{'👻 GHOST' if is_ghost else '✅ ACTIVE'}"
        )
        print(
            f"{'':<6} | {'Midpoint':<12} | ${mid_price:.2f}               | "
            f"{'✅ MATCH' if abs(mid_price - best_bid) < 0.1 else '⚠️ DIFF'}"
        )
        print(
            f"{'':<6} | {'LastTrade':<12} | ${last_price:.2f}               |"
        )
        print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(inspect_market())
