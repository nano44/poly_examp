import os

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs
from dotenv import load_dotenv
from py_clob_client.constants import POLYGON  # use AMOY for testnet

from py_clob_client.order_builder.constants import BUY


load_dotenv()


def main():
    host = os.getenv("CLOB_API_URL") or "https://clob.polymarket.com"
    key = os.getenv("PK")
    sig_type = int(os.getenv("SIGNATURE_TYPE", "1"))  # 1 for email/Magic proxy
    funder = os.getenv("FUNDER")
    creds = ApiCreds(
        api_key=os.getenv("CLOB_API_KEY"),
        api_secret=os.getenv("CLOB_SECRET"),
        api_passphrase=os.getenv("CLOB_PASS_PHRASE"),
    )
    chain_id = POLYGON
    client = ClobClient(
        host,
        key=key,
        chain_id=chain_id,
        signature_type=sig_type,
        funder=funder,
        creds=creds,
    )

    # Create and sign a tiny limit order: buy 0.01 YES @ $0.01
    order_args = OrderArgs(
        price=0.01,
        size=0.01,
        side=BUY,
        token_id="73470541315377973562501025254719659796416871135081220986683321361000395461644",
    )
    signed_order = client.create_order(order_args)
    resp = client.post_order(signed_order)
    print(resp)
    print("Done!")


main()
