from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY

host: str = "https://clob.polymarket.com"
key: str = "0x57af57c5dcc9bced35981134ab62ea0259646f3e82b6d37ec106098539dc174f"  # This is your Private Key. Export from reveal.polymarket.com or from your Web3 Application
chain_id: int = 137  # No need to adjust this
POLYMARKET_PROXY_ADDRESS: str = "0xc2f1c1793bD724D7cbeee28F3deE8Ef85E530E5F"  # This is the address you deposit/send USDC to to FUND your Polymarket account.

# Select ONE of the following initialization options to match your login method.

# Initialization of a client using a Polymarket Proxy associated with an Email/Magic account.
client = ClobClient(host, key=key, chain_id=chain_id, signature_type=1, funder=POLYMARKET_PROXY_ADDRESS)

# Initialization of a client using a Polymarket Proxy associated with a Browser Wallet (Metamask, Coinbase Wallet, etc).
# client = ClobClient(host, key=key, chain_id=chain_id, signature_type=2, funder=POLYMARKET_PROXY_ADDRESS)

# Initialization of a client that trades directly from an EOA.
#client = ClobClient(host, key=key, chain_id=chain_id)

# Create API creds (builder flow)
client.set_api_creds(client.create_or_derive_api_creds())

# Create and sign a limit order buying 5 YES tokens for $0.01 each
# Refer to the Markets API documentation to locate a tokenID: https://docs.polymarket.com/developers/gamma-markets-api/get-markets
order_args = OrderArgs(
    price=0.01,
    size=5.0,
    side=BUY,
    token_id="104147082097316656098112191698157534543200412073151339023506196167615561102864",  # Token ID you want to purchase goes here.
)
signed_order = client.create_order(order_args)

# GTC (Good-Till-Cancelled) Order
resp = client.post_order(signed_order, OrderType.GTC)
print(resp)
