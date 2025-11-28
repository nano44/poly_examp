import os
from py_clob_client.client import ClobClient


def main():
    host = os.getenv("CLOB_API_URL", "https://clob.polymarket.com")
    client = ClobClient(host)

    orderbook = client.get_order_book(
        "44527960608459915204385410174103900772376741082547846811964179630682948263379"
    )
    print("orderbook", orderbook)

    hash = client.get_order_book_hash(orderbook)
    print("orderbook hash", hash)


main()
