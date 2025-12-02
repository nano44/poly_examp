import os
import time
import hmac
import hashlib
import json
import base64
import asyncio
import aiohttp
from typing import Optional, Dict

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType
from py_clob_client.constants import POLYGON
from py_clob_client.order_builder.constants import BUY, SELL

# Base URLs / creds from env
CLOB_API_URL = os.getenv("CLOB_API_URL", "https://clob.polymarket.com")
API_KEY = os.getenv("CLOB_API_KEY", "your-api-key-uuid")
API_SECRET = os.getenv("CLOB_SECRET", "your-api-secret-base64")
API_PASSPHRASE = os.getenv("CLOB_PASS_PHRASE", "your-api-passphrase")
PK = os.getenv("PK")
SIG_TYPE = int(os.getenv("SIGNATURE_TYPE", "1"))
FUNDER = os.getenv("FUNDER")
CHAIN_ID = int(os.getenv("CHAIN_ID", str(POLYGON)))


class TradingBot:
    def __init__(self) -> None:
        self.session: Optional[aiohttp.ClientSession] = None
        self.nonce_lock = asyncio.Lock()
        self.token_ids: Dict[str, str] = {}
        self.api_key, self.secret_bytes, self.api_passphrase = self._load_credentials()
        self.client: Optional[ClobClient] = self._init_client()

    async def start_session(self) -> None:
        if not self.session:
            connector = aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)
            self.session = aiohttp.ClientSession(connector=connector)

    async def close_session(self) -> None:
        if self.session:
            await self.session.close()

    @staticmethod
    def _load_credentials() -> tuple[str, bytes, str]:
        if "your-api-key-uuid" in API_KEY:
            raise ValueError("CLOB_API_KEY is not set.")
        if "your-api-secret-base64" in API_SECRET:
            raise ValueError("CLOB_SECRET is not set.")
        if "your-api-passphrase" in API_PASSPHRASE:
            raise ValueError("CLOB_PASS_PHRASE is not set.")

        padded_secret = API_SECRET
        missing = len(API_SECRET) % 4
        if missing:
            padded_secret += "=" * (4 - missing)

        try:
            secret_bytes = base64.b64decode(padded_secret, validate=True)
        except Exception as err:
            raise ValueError("Invalid CLOB_SECRET; must be base64 encoded.") from err

        return API_KEY, secret_bytes, API_PASSPHRASE

    def _init_client(self) -> Optional[ClobClient]:
        creds = None
        if API_KEY and API_SECRET and API_PASSPHRASE:
            creds = ApiCreds(
                api_key=API_KEY,
                api_secret=API_SECRET,
                api_passphrase=API_PASSPHRASE,
            )

        client = ClobClient(
            CLOB_API_URL,
            key=PK,
            chain_id=CHAIN_ID,
            signature_type=SIG_TYPE,
            funder=FUNDER,
            creds=creds,
        )

        if creds:
            print("✅ Polymarket client initialized with API creds")
        else:
            print("ℹ️ Polymarket client initialized without API creds (read-only)")
        return client

    def load_token_ids(self, path: str = "active_ids.json") -> Dict[str, str]:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Token ID file not found: {path}")

        with open(path, "r") as f:
            data = json.load(f)

        ids: Dict[str, str] = {}
        for key in ("UP", "DOWN"):
            if key in data and data[key]:
                ids[key] = str(data[key])

        if not ids:
            raise ValueError(f"No token IDs found in {path}")

        self.token_ids = ids
        print(f"🔑 Loaded token IDs: {self.token_ids}")
        return ids

    def _generate_signature(self, timestamp: int, method: str, request_path: str, body_json: str = "") -> str:
        message = f"{timestamp}{method}{request_path}{body_json}"
        signature = hmac.new(
            self.secret_bytes,
            message.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(signature).decode("utf-8")

    async def _execute_with_client(self, token_id: str, side: str, price: float, size: float) -> bool:
        if not self.client or not self.client.signer:
            return False
        side_const = BUY if side.upper() == "BUY" else SELL
        order_args = OrderArgs(
            price=price,
            size=size,
            side=side_const,
            token_id=token_id,
        )
        try:
            signed_order = await asyncio.to_thread(self.client.create_order, order_args)
            resp = await asyncio.to_thread(self.client.post_order, signed_order, OrderType.FAK)
            order_id = resp.get("orderID") if isinstance(resp, dict) else resp
            print(f"✅ EXECUTION SUCCESS: {order_id}")
            return True
        except Exception as e:
            print(f"❌ Client order failed: {e}")
            return False

    async def execute_trade(self, token_id: str, side: str, price: float, size: float) -> bool:
        if not self.session:
            await self.start_session()

        max_size = 500
        if size > max_size:
            print(f"⚠️ Risk Check: Size {size} exceeds max {max_size}. Clipping.")
            size = max_size

        # Try via SDK client first if signer available
        if await self._execute_with_client(token_id, side, price, size):
            return True

        # Manual REST fallback using API creds
        endpoint = "/order"
        method = "POST"
        payload = {
            "token_id": token_id,
            "price": f"{price:.2f}",
            "side": side.upper(),
            "size": f"{size:.2f}",
            "type": "FOK",
        }
        body_json = json.dumps(payload)

        timestamp = int(time.time() * 1000)
        signature = self._generate_signature(timestamp, method, endpoint, body_json)

        headers = {
            "Content-Type": "application/json",
            "POLY_API_KEY": self.api_key,
            "POLY_SIGNATURE": signature,
            "POLY_TIMESTAMP": str(timestamp),
            "POLY_PASSPHRASE": self.api_passphrase,
        }

        try:
            async with self.session.post(
                CLOB_API_URL + endpoint,
                data=body_json,
                headers=headers,
            ) as response:
                resp_text = await response.text()

                if response.status == 200:
                    data = json.loads(resp_text)
                    print(f"✅ FILLED: {side} {size} @ {price} | ID: {data.get('orderID')}")
                    return True
                else:
                    print(f"❌ FAIL [{response.status}]: {resp_text}")
                    return False
        except Exception as e:
            print(f"🔥 NETWORK ERROR: {e}")
            return False


async def main() -> None:
    bot = TradingBot()
    try:
        token_ids = bot.load_token_ids("active_ids.json")
        sample_token_id = token_ids.get("UP") or next(iter(token_ids.values()))
        await bot.execute_trade(
            token_id=sample_token_id,
            side="BUY",
            price=0.65,
            size=1.0,
        )
    finally:
        await bot.close_session()


if __name__ == "__main__":
    asyncio.run(main())
