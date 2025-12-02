import asyncio
import os
from pprint import pprint
from functools import lru_cache
from dotenv import load_dotenv

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
from py_clob_client.constants import POLYGON 

# Load environment variables from .env file
load_dotenv()

# --- Configuration ---
# 40 is the requested limit
TRADE_LIMIT = 5 
# Get the user address from environment variables
USER_ADDRESS = os.getenv("FUNDER") 

# --- CONSOLIDATED CLIENT CONFIGURATION ---
# The get_authenticated_client function has been moved here
@lru_cache(maxsize=1)
def get_authenticated_client() -> ClobClient:
    """
    Builds and caches a ClobClient using environment variables for authentication.
    """
    host = os.getenv("CLOB_API_URL", "https://clob.polymarket.com")
    key = os.getenv("PK")
    funder = os.getenv("FUNDER")
    # Assuming POLYGON (137) as default, adjust if necessary
    chain_id = int(os.getenv("CHAIN_ID", str(POLYGON))) 

    api_key = os.getenv("CLOB_API_KEY")
    api_secret = os.getenv("CLOB_SECRET")
    api_passphrase = os.getenv("CLOB_PASS_PHRASE")
    
    creds = None
    if api_key and api_secret and api_passphrase:
        creds = ApiCreds(
            api_key=api_key,
            api_secret=api_secret,
            api_passphrase=api_passphrase,
        )
    else:
        print("⚠️ Warning: API credentials (KEY/SECRET/PASS_PHRASE) missing. Read-only client initialized.")

    return ClobClient(
        host, 
        key=key, 
        chain_id=chain_id, 
        funder=funder, 
        creds=creds
    )
# --- END CONSOLIDATED CLIENT CONFIGURATION ---


async def fetch_user_trades() -> None:
    if not USER_ADDRESS:
        print("❌ Error: The 'FUNDER' environment variable is not set. Cannot determine user address.")
        return

    try:
        client = get_authenticated_client()

        print(f"⏳ Fetching last {TRADE_LIMIT} trades for user: {USER_ADDRESS}...")

        trades = await asyncio.to_thread(client.get_trades)
        trades = trades[:TRADE_LIMIT]

        if not trades:
            print("\n✅ Success, but no trades found matching the criteria.")
            return

        print(f"\n✅ Successfully retrieved {len(trades)} trades (most recent first):")

        # 🔹 Only keep order_id, price, size
        simplified_trades = [
            {
                "order_id": t.get("taker_order_id"),
                "price": t.get("price"),
                "size": round(float(t.get("size")), 2) if t.get("size") is not None else None,
            }
            for t in trades
        ]

        for st in simplified_trades:
            print(
                f"Order ID: {st['order_id']} | "
                f"Price: {st['price']} | "
                f"Size: {st['size']}"
            )

    except Exception as e:
        print(f"\n❌ An error occurred during trade fetching: {e}")
        print("Ensure CLOB_API_KEY, CLOB_SECRET, CLOB_PASS_PHRASE, and PK are set correctly.")
        

if __name__ == "__main__":
    try:
        # We run the async function
        asyncio.run(fetch_user_trades())
    except KeyboardInterrupt:
        print("\nScript interrupted.")
