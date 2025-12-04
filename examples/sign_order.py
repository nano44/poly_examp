import time
import asyncio
import os
from eth_utils import keccak, to_checksum_address
from coincurve import PrivateKey
from py_clob_client.clob_types import OrderArgs
from py_clob_client.constants import POLYGON

# --- Constants for Polymarket Polygon Mainnet ---
CHAIN_ID = 137
EXCHANGE_CONTRACT = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"  # CTF Exchange

class FastPolymarketSigner:
    def __init__(self, private_key_hex: str):
        # 1. Setup Keys using Coincurve (Fast C-binding)
        # Handle 0x prefix if present
        if private_key_hex.startswith("0x"):
            private_key_hex = private_key_hex[2:]
        
        self._private_key = PrivateKey.from_hex(private_key_hex)
        # Derive public address efficiently
        self.address = to_checksum_address(self._private_key.public_key.format(compressed=False).hex()[-40:])
        
        # 2. Pre-compute Domain Separator (Static)
        # EIP-712 Domain: name, version, chainId, verifyingContract
        domain_type_hash = keccak(text="EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)")
        name_hash = keccak(text="Polymarket CTF Exchange")
        version_hash = keccak(text="1")
        
        self.domain_separator = keccak(
            domain_type_hash +
            name_hash +
            version_hash +
            CHAIN_ID.to_bytes(32, 'big') +
            bytes.fromhex(EXCHANGE_CONTRACT[2:].rjust(64, '0'))
        )

        # 3. Pre-compute Order Type Hash (Static)
        # Note: 'feeRate' is the struct field name, even though API calls it 'feeRateBps'
        self.order_type_hash = keccak(text="Order(uint256 salt,address maker,address signer,address taker,uint256 tokenId,uint256 makerAmount,uint256 takerAmount,uint256 expiration,uint256 nonce,uint256 feeRate,uint8 side,uint8 signatureType)")

        # Pre-encoded address bytes (optimization)
        self._address_bytes = bytes.fromhex(self.address[2:].rjust(64, '0'))
        self._zero_bytes = bytes.fromhex("0000000000000000000000000000000000000000".rjust(64, '0'))

    def sign_order(self, order_args: OrderArgs):
        """
        Returns the payload dictionary expected by client.post_order
        """
        # Generate Salt (Unique entropy for this specific order)
        salt = int(time.time() * 1000) 
        
        # Maker/Taker Amount Logic (Both USDC and Tokens are 6 decimals)
        # BUY (Side 0): You pay USDC (Maker), You get Token (Taker)
        # SELL (Side 1): You pay Token (Maker), You get USDC (Taker)
        
        raw_price = float(order_args.price)
        raw_size = float(order_args.size)
        
        if order_args.side == "BUY": # "BUY" from OrderArgs enum often maps to string or object, check your specific enum usage
            side_int = 0
            # Maker = USDC = size * price
            maker_amount = int(raw_size * raw_price * 1_000_000)
            # Taker = Token = size
            taker_amount = int(raw_size * 1_000_000)
        else:
            side_int = 1
            # Maker = Token = size
            maker_amount = int(raw_size * 1_000_000)
            # Taker = USDC = size * price
            taker_amount = int(raw_size * raw_price * 1_000_000)

        # Nonce is used for batch cancellation. 0 is fine for HFT unless you need grouping.
        nonce = 0 
        
        # Pack the Order Struct (EIP-712)
        encoded_data = (
            self.order_type_hash +
            salt.to_bytes(32, 'big') +
            self._address_bytes +  # maker
            self._address_bytes +  # signer
            self._zero_bytes +     # taker (0x0 for public order)
            int(order_args.token_id).to_bytes(32, 'big') +
            maker_amount.to_bytes(32, 'big') +
            taker_amount.to_bytes(32, 'big') +
            int(0).to_bytes(32, 'big') + # expiration (0 = GTC)
            int(nonce).to_bytes(32, 'big') +
            int(0).to_bytes(32, 'big') + # feeRate (0)
            int(side_int).to_bytes(32, 'big') + # side
            int(0).to_bytes(32, 'big')    # signatureType (0 = EOA)
        )
        
        struct_hash = keccak(encoded_data)
        digest = keccak(b'\x19\x01' + self.domain_separator + struct_hash)
        
        # Sign (recoverable=True returns 65 bytes)
        signature = self._private_key.sign_recoverable(digest, hasher=None)
        
        # Return exact JSON payload structure for API
        return {
            "order": {
                "salt": salt,
                "maker": self.address,
                "signer": self.address,
                "taker": "0x0000000000000000000000000000000000000000",
                "tokenId": order_args.token_id,
                "makerAmount": str(maker_amount),
                "takerAmount": str(taker_amount),
                "expiration": "0",
                "nonce": str(nonce),
                "feeRateBps": "0", # API expects 'feeRateBps', Struct uses 'feeRate'
                "side": "0" if side_int == 0 else "1",
                "signatureType": "0"
            },
            "owner": self.address,
            "orderType": "GTC",
            "signature": "0x" + signature.hex()
        }