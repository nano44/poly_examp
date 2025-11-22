"""
Example: construct a ClobClient with signature_type pulled from env.

Required env:
  - PK: your private key (hex)

Optional env:
  - CLOB_API_URL: override host (default https://clob.polymarket.com)
  - SIGNATURE_TYPE: 0 (EOA), 1 (email/Magic), 2 (proxy contract). Default 1.
  - FUNDER: funded address if different from PK's address (proxy/email wallets)
  - CLOB_API_KEY / CLOB_SECRET / CLOB_PASS_PHRASE: set to enable Level 2 calls
"""

import os
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON  # use AMOY for testnet
from py_clob_client.clob_types import ApiCreds


def build_client():
    load_dotenv()
    host = os.getenv("CLOB_API_URL") or "https://clob.polymarket.com"
    key = os.getenv("PK")
    if not key:
        raise SystemExit("PK env var required")

    # default to signature_type=1 for email/Magic; set SIGNATURE_TYPE=0 for EOA
    sig_type = int(os.getenv("SIGNATURE_TYPE", "1"))
    funder = os.getenv("FUNDER")

    client = ClobClient(
        host,
        key=key,
        chain_id=POLYGON,
        signature_type=sig_type,
        funder=funder,
    )

    if os.getenv("CLOB_API_KEY"):
        client.set_api_creds(
            ApiCreds(
                api_key=os.getenv("CLOB_API_KEY"),
                api_secret=os.getenv("CLOB_SECRET"),
                api_passphrase=os.getenv("CLOB_PASS_PHRASE"),
            )
        )
    return client


def main():
    client = build_client()
    print("Client constructed. Address:", client.get_address())
    # Example call (requires network access):
    # print("Server time:", client.get_server_time())


if __name__ == "__main__":
    main()
