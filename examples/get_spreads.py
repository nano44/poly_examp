import os
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BookParams


def fetch_spreads(token_ids: list[str]):
    host = os.getenv("CLOB_API_URL", "https://clob.polymarket.com")
    client = ClobClient(host)

    params = [BookParams(token_id=tid) for tid in token_ids]
    return client.get_spreads(params=params)


def main():
    # Default token IDs; replace as needed
    token_id1 = "50820207232450388163157348495823669746288401214699605911449943572987282317202"
    token_id2 = "58582488809451453627603572935939478499122520279747056470613726400534133629224"
    resp = fetch_spreads([token_id1, token_id2])
    print(resp)
    print("Done!")


if __name__ == "__main__":
    main()
