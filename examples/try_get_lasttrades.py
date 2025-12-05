import argparse
import asyncio
import os
from functools import lru_cache
from typing import List, Dict, Any, Optional
from datetime import datetime

from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
from py_clob_client.constants import POLYGON
from py_clob_client.clob_types import TradeParams

# Load environment variables from .env file
load_dotenv()

# --- Configuration ---
DEFAULT_TRADE_FETCH_LIMIT = 30  # how many recent trades to pull when filtering
USER_ADDRESS = os.getenv("FUNDER")


# --- CLIENT CONFIGURATION ---
@lru_cache(maxsize=1)
def get_authenticated_client() -> ClobClient:
    """
    Builds and caches a ClobClient using environment variables for authentication.
    """
    host = os.getenv("CLOB_API_URL", "https://clob.polymarket.com")
    key = os.getenv("PK")
    funder = os.getenv("FUNDER")
    chain_id = int(os.getenv("CHAIN_ID", str(POLYGON)))  # 137 by default

    api_key = os.getenv("CLOB_API_KEY")
    api_secret = os.getenv("CLOB_SECRET")
    api_passphrase = os.getenv("CLOB_PASS_PHRASE")

    creds: Optional[ApiCreds] = None
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
        creds=creds,
    )
# --- END CLIENT CONFIGURATION ---


async def _get_recent_trades(limit: int = DEFAULT_TRADE_FETCH_LIMIT) -> list[dict]:
    """
    Internal helper: fetches the most recent trades for the authenticated user.
    """
    if not USER_ADDRESS:
        raise RuntimeError("The 'FUNDER' environment variable is not set. Cannot determine user address.")

    client = get_authenticated_client()

    params = TradeParams(
        maker_address=USER_ADDRESS,
    )

    trades = await asyncio.to_thread(client.get_trades, params)
    
    # Slice locally in case the API returned more than requested
    return trades[:limit]

    
def _simplify_trade(trade: dict) -> dict:
    """
    Reduce a raw trade object to {order_id, price, size, timestamp}.
    """
    size_raw = trade.get("size")
    price_raw = trade.get("price")
    timestamp_raw = trade.get("match_time")
    print(f"Raw timestamp: {timestamp_raw}")

    # Polymarket usually returns timestamps as unix integers (seconds)
    # converting to readable format if present
    timestamp_val = None
    if timestamp_raw is not None:
        try:
            timestamp_val = int(timestamp_raw)
        except (ValueError, TypeError):
            timestamp_val = timestamp_raw

    return {
        "order_id": trade.get("taker_order_id"),
        "price": float(price_raw) if price_raw is not None else None,
        "size": round(float(size_raw), 2) if size_raw is not None else None,
        "timestamp": timestamp_val  # <--- ADDED FIELD
    }


async def get_trades_for_order_ids(
    order_ids: List[str],
    limit: int = DEFAULT_TRADE_FETCH_LIMIT,
) -> List[Dict[str, Any]]:
    """
    Public async function:
    - Fetches the last `limit` trades for the authenticated user
    - Filters them to only keep trades whose taker_order_id is in `order_ids`
    - Returns a list of {order_id, price, size, timestamp} dicts
    """
    if not order_ids:
        return []

    recent_trades = await _get_recent_trades(limit=limit)
    wanted_ids = set(order_ids)

    matched: List[Dict[str, Any]] = []
    for t in recent_trades:
        oid = t.get("taker_order_id")
        if oid in wanted_ids:
            matched.append(_simplify_trade(t))

    return matched


def _print_trades(trades: List[Dict[str, Any]], limit: int, order_ids: List[str]) -> None:
    if not trades:
        print(f"No matching trades found in the last {limit} trades.")
        return

    print(f"✅ Found {len(trades)} matching trades for {len(order_ids)} order IDs:\n")
    for t in trades:
        # Format timestamp to human-readable if it's an integer
        ts_display = t['timestamp']
        if isinstance(ts_display, (int, float)):
            ts_display = datetime.fromtimestamp(ts_display).strftime('%Y-%m-%d %H:%M:%S')
            
        print(f"Order ID: {t['order_id']} | Price: {t['price']} | Size: {t['size']} | Time: {ts_display}")


async def _cli_main(order_ids: List[str], limit: int) -> None:
    print(f"⏳ Fetching recent trades and matching {len(order_ids)} order IDs...")
    trades = await get_trades_for_order_ids(order_ids, limit=limit)
    print(trades)
    _print_trades(trades, limit, order_ids)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch recent trades and filter by order IDs.")
    parser.add_argument(
        "--order-ids",
        nargs="+",
        required=True,
        help="Order IDs to match against taker_order_id",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_TRADE_FETCH_LIMIT,
        help=f"How many recent trades to pull before filtering (default: {DEFAULT_TRADE_FETCH_LIMIT})",
    )
    args = parser.parse_args()

    try:
        asyncio.run(_cli_main(args.order_ids, args.limit))
    except KeyboardInterrupt:
        print("\nScript interrupted.")