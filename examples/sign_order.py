import time
from eth_utils import keccak, to_checksum_address
from coincurve import PrivateKey
from py_clob_client.clob_types import OrderArgs

# --- Constants ---
CHAIN_ID = 137
EXCHANGE_CONTRACT = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E" 

class FastPolymarketSigner:
    def __init__(self, private_key_hex: str, funder: str = None):
        # 1. Setup Keys
        if private_key_hex.startswith("0x"):
            private_key_hex = private_key_hex[2:]
        
        self._private_key = PrivateKey.from_hex(private_key_hex)
        self.signer_address = to_checksum_address(self._private_key.public_key.format(compressed=False).hex()[-40:])
        
        # 2. Handle Proxy/Funder Logic
        # If funder is provided, Maker = Funder, Signer = EOA.
        # If no funder, Maker = EOA, Signer = EOA.
        self.maker_address = to_checksum_address(funder) if funder else self.signer_address

        # 3. Pre-compute Domain Separator
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

        # 4. Pre-compute Order Type Hash
        self.order_type_hash = keccak(text="Order(uint256 salt,address maker,address signer,address taker,uint256 tokenId,uint256 makerAmount,uint256 takerAmount,uint256 expiration,uint256 nonce,uint256 feeRate,uint8 side,uint8 signatureType)")

        # Pre-encode addresses to bytes
        self._maker_bytes = bytes.fromhex(self.maker_address[2:].rjust(64, '0'))
        self._signer_bytes = bytes.fromhex(self.signer_address[2:].rjust(64, '0'))
        self._zero_bytes = bytes.fromhex("0000000000000000000000000000000000000000".rjust(64, '0'))

    def sign_order(self, order_args: OrderArgs):
        salt = int(time.time() * 1000) 
        
        # Handle Side (Supports Integers 0/1 or Strings "BUY"/"SELL")
        s = order_args.side
        if s == 0 or s == "BUY": 
            side_int = 0
            # Buying: Maker pays USDC, Taker gives Token
            maker_amount = int(order_args.size * order_args.price * 1_000_000)
            taker_amount = int(order_args.size * 1_000_000)
        else:
            side_int = 1
            # Selling: Maker pays Token, Taker gives USDC
            maker_amount = int(order_args.size * 1_000_000)
            taker_amount = int(order_args.size * order_args.price * 1_000_000)

        nonce = 0 
        
        # Pack Struct
        encoded_data = (
            self.order_type_hash +
            salt.to_bytes(32, 'big') +
            self._maker_bytes +    # Use Proxy if set
            self._signer_bytes +   # Use EOA
            self._zero_bytes +
            int(order_args.token_id).to_bytes(32, 'big') +
            maker_amount.to_bytes(32, 'big') +
            taker_amount.to_bytes(32, 'big') +
            int(0).to_bytes(32, 'big') +
            int(nonce).to_bytes(32, 'big') +
            int(0).to_bytes(32, 'big') +
            int(side_int).to_bytes(32, 'big') +
            int(0).to_bytes(32, 'big') 
        )
        
        digest = keccak(b'\x19\x01' + self.domain_separator + keccak(encoded_data))
        signature = self._private_key.sign_recoverable(digest, hasher=None)
        
        return {
            "order": {
                "salt": salt,
                "maker": self.maker_address,
                "signer": self.signer_address,
                "taker": "0x0000000000000000000000000000000000000000",
                "tokenId": order_args.token_id,
                "makerAmount": str(maker_amount),
                "takerAmount": str(taker_amount),
                "expiration": "0",
                "nonce": str(nonce),
                "feeRateBps": "0",
                "side": "0" if side_int == 0 else "1",
                "signatureType": "0"
            },
            "owner": self.maker_address, # Owner is the Proxy
            "orderType": "GTC", # Will be overridden by client.post_order arg
            "signature": "0x" + signature.hex()
        }