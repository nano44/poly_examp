import os
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BookParams


def main():
    host = os.getenv("CLOB_API_URL", "https://clob.polymarket.com")
    client = ClobClient(host)

    resp = client.get_prices(
        params=[
            BookParams(
                token_id="44527960608459915204385410174103900772376741082547846811964179630682948263379",
                side="BUY",
            ),
            BookParams(
                token_id="44527960608459915204385410174103900772376741082547846811964179630682948263379",
                side="SELL",
            ),
            BookParams(
                token_id="56297617931546527767294349494591959172101397323020328846651582318666139280906",
                side="BUY",
            ),
            BookParams(
                token_id="56297617931546527767294349494591959172101397323020328846651582318666139280906",
                side="SELL",
            ),
        ]
    )
    print(resp)
    print("Done!")


main()
