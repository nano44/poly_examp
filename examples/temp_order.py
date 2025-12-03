import asyncio # <-- ADD THIS IMPORT
import os



from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, BookParams, OrderArgs, OrderType
from py_clob_client.constants import POLYGON
from py_clob_client.exceptions import PolyApiException
from py_clob_client.order_builder.constants import BUY



load_dotenv()

# --- Configuration Variables ---

### Initialization of a client... (Select one)


# ----------------------------------------------------------------------
# 🔑 FIX: DEFINE AN ASYNC MAIN FUNCTION
# ----------------------------------------------------------------------
async def main():
    # All synchronous setup can remain outside, but the execution must be here
    host = os.getenv("CLOB_API_URL") or "https://clob.polymarket.com"
    key = os.getenv("PK")
    sig_type = int(os.getenv("SIGNATURE_TYPE", "1"))
    funder = os.getenv("FUNDER")
    chain_id = int(os.getenv("CHAIN_ID", 137))

    creds = ApiCreds(
        api_key=os.getenv("CLOB_API_KEY"),
        api_secret=os.getenv("CLOB_SECRET"),
        api_passphrase=os.getenv("CLOB_PASS_PHRASE")
    )
    
    client = ClobClient(
        host, key=key, chain_id=chain_id, creds=creds,
        signature_type=sig_type, funder=funder
    )


    client.set_api_creds(client.create_or_derive_api_creds()) 

    order_args = OrderArgs(
        price=0.01,
        size=5.0,
        side=BUY,
        token_id="20441796210794588021098066329856766888214628355195643405096685703780376832726", 
    )
    
    # NOW the 'await' is inside an 'async def' function!
    # 👇 This line and the one below it MUST be indented inside main()
    signed_order = await asyncio.to_thread(client.create_order, order_args) 
    resp = await asyncio.to_thread(client.post_order, signed_order, OrderType.GTC) # Switched to GTC
    
    print(resp)

# ----------------------------------------------------------------------
# 🚀 FIX: EXECUTE THE ASYNC FUNCTION
# ----------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(main())