import os

from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds

# PASTE YOUR LIVE TOKEN ID HERE (UP or DOWN token)
LIVE_TOKEN_ID = "72247127858101293756743562676945901963630969280187987932370111719068543181084"


def get_live_spread() -> None:
    load_dotenv()

    host = os.getenv("CLOB_API_URL", "https://clob.polymarket.com")
    key = os.getenv("PK")
    chain_id = 137  # Polygon mainnet

    creds = ApiCreds(
        api_key=os.getenv("CLOB_API_KEY"),
        api_secret=os.getenv("CLOB_SECRET"),
        api_passphrase=os.getenv("CLOB_PASS_PHRASE"),
    )

    client = ClobClient(host, key=key, chain_id=chain_id, creds=creds)

    print(f"Checking spread for: {LIVE_TOKEN_ID[:15]}...")
    try:
        resp = client.get_spread(LIVE_TOKEN_ID)
        best_bid = float(resp.get("bestBidPrice", 0.0))
        best_ask = float(resp.get("bestAskPrice", 0.0))
        spread = best_ask - best_bid
        print(f"✅ Success: Bid: {best_bid:.4f}, Ask: {best_ask:.4f}")
        print(f"   Calculated Spread: {spread:.4f}")
    except Exception as e:
        print(f"❌ Error during spread check: {e}")


if __name__ == "__main__":
    get_live_spread()
