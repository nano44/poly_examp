import os

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, BalanceAllowanceParams, AssetType
from dotenv import load_dotenv
from py_clob_client.constants import POLYGON  # switch to AMOY if using testnet

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

    collateral = client.get_balance_allowance(
        params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
    )
    print(collateral)

    yes = client.get_balance_allowance(
        params=BalanceAllowanceParams(
            asset_type=AssetType.CONDITIONAL,
            token_id="52114319501245915516055106046884209969926127482827954674443846427813813222426",
        )
    )
    print(yes)

    no = client.get_balance_allowance(
        params=BalanceAllowanceParams(
            asset_type=AssetType.CONDITIONAL,
            token_id="71321045679252212594626385532706912750332728571942532289631379312455583992563",
        )
    )
    print(no)


main()
