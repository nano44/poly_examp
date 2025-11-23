import os
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BookParams


def main():
    host = os.getenv("CLOB_API_URL", "https://clob.polymarket.com")
    client = ClobClient(host)

    resp = client.get_spreads(
        params=[
            BookParams(
                token_id="30781390935964643809169938652265452487584631554843464153358559865968760704577"
            ),
            BookParams(
                token_id="72247127858101293756743562676945901963630969280187987932370111719068543181084"
            ),
        ]
    )
    print(resp)
    print("Done!")


main()
