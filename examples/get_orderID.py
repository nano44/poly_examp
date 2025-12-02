import os
import sys
from functools import lru_cache
from pprint import pprint

from dotenv import load_dotenv

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
from py_clob_client.constants import AMOY

load_dotenv()


@lru_cache(maxsize=1)
def _get_client() -> ClobClient:
    """Build and cache a ClobClient using environment variables."""
    host = os.getenv("CLOB_API_URL", "https://clob.polymarket.com")
    key = os.getenv("PK")
    chain_id = int(os.getenv("CHAIN_ID", str(AMOY)))

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

    return ClobClient(host, key=key, chain_id=chain_id, creds=creds)


def get_order_by_id(order_id: str):
    """Fetch a single order by ID."""
    if not order_id:
        raise ValueError("order_id is required")
    client = _get_client()
    return client.get_order(order_id)


def main(order_id: str) -> None:
    order = get_order_by_id(order_id)
    print(order)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python examples/get_orderID.py <order_id>")
        raise SystemExit(1)
    main(sys.argv[1])
