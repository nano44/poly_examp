import time
import os
from eth_utils import keccak, to_checksum_address, to_canonical_address
from coincurve import PrivateKey
from eth_account import Account
from eth_account.messages import encode_typed_data
from py_clob_client.clob_types import OrderArgs

# --- Constants ---
CHAIN_ID = 137
# Default to CTF Exchange, but allow override via Env for NegRisk markets
EXCHANGE_CONTRACT = os.getenv("EXCHANGE_CONTRACT", "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E")

class PolySignedOrder:
    def __init__(self, data):
        self._data = data
    def dict(self):
        return self._data
    def __getattr__(self, name):
        return self._data.get(name)
    def __setattr__(self, name, value):
        if name == "_data":
            super().__setattr__(name, value)
        else:
            if hasattr(value, "value"): value = value.value
            self._data[name] = value

class FastPolymarketSigner:
    def __init__(self, private_key_hex: str, funder: str = None, signature_type: int = 0):
        if private_key_hex.startswith("0x"):
            private_key_hex = private_key_hex[2:]
        
        # 1. Setup Keys
        self._private_key = PrivateKey.from_hex(private_key_hex)
        
        # Derive Address from PubKey (Coincurve -> Keccak -> Address)
        pub_key_bytes = self._private_key.public_key.format(compressed=False)[1:]
        self.signer_address = to_checksum_address(keccak(pub_key_bytes)[-20:])
        self.maker_address = to_checksum_address(funder) if funder else self.signer_address
        self.signature_type = signature_type

        # 2. Pre-compute Domain Separator
        domain_type_hash = keccak(text="EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)")
        name_hash = keccak(text="Polymarket CTF Exchange")
        version_hash = keccak(text="1")
        
        self.domain_separator = keccak(
            domain_type_hash +
            name_hash +
            version_hash +
            CHAIN_ID.to_bytes(32, 'big') +
            to_canonical_address(EXCHANGE_CONTRACT).rjust(32, b'\0')
        )

        # 3. CRITICAL FIX: Changed feeRate -> feeRateBps
        # This matches the Solidity struct exactly.
        self.order_type_hash = keccak(text="Order(uint256 salt,address maker,address signer,address taker,uint256 tokenId,uint256 makerAmount,uint256 takerAmount,uint256 expiration,uint256 nonce,uint256 feeRateBps,uint8 side,uint8 signatureType)")

        # Pre-pack Addresses
        self._maker_word = to_canonical_address(self.maker_address).rjust(32, b'\0')
        self._signer_word = to_canonical_address(self.signer_address).rjust(32, b'\0')
        self._zero_word = bytes(32) # Taker (0x0)

        # 4. Verify compatibility on startup
        self._verify_compatibility()

    def _verify_compatibility(self):
        """Checks if our Fast Hash matches the Official Hash (checking feeRateBps fix)."""
        print("🔍 Verifying Cryptographic Compatibility...")
        dummy_args = OrderArgs(price=0.5, size=1.0, side="BUY", token_id="123456789")
        
        # Fast Path
        fast_payload = self.sign_order(dummy_args)
        
        # Slow Path (Reference)
        maker_amt = int(dummy_args.size * dummy_args.price * 1_000_000)
        taker_amt = int(dummy_args.size * 1_000_000)
        
        structured_data = {
            "types": {
                "EIP712Domain": [{"name": "name", "type": "string"}, {"name": "version", "type": "string"}, {"name": "chainId", "type": "uint256"}, {"name": "verifyingContract", "type": "address"}],
                # CRITICAL FIX: feeRate -> feeRateBps here too
                "Order": [{"name": "salt", "type": "uint256"}, {"name": "maker", "type": "address"}, {"name": "signer", "type": "address"}, {"name": "taker", "type": "address"}, {"name": "tokenId", "type": "uint256"}, {"name": "makerAmount", "type": "uint256"}, {"name": "takerAmount", "type": "uint256"}, {"name": "expiration", "type": "uint256"}, {"name": "nonce", "type": "uint256"}, {"name": "feeRateBps", "type": "uint256"}, {"name": "side", "type": "uint8"}, {"name": "signatureType", "type": "uint8"}]
            },
            "domain": {"name": "Polymarket CTF Exchange", "version": "1", "chainId": CHAIN_ID, "verifyingContract": EXCHANGE_CONTRACT},
            "primaryType": "Order",
            "message": {
                "salt": fast_payload.salt,
                "maker": self.maker_address, "signer": self.signer_address, "taker": "0x0000000000000000000000000000000000000000",
                "tokenId": 123456789, "makerAmount": maker_amt, "takerAmount": taker_amt,
                "expiration": 0, "nonce": 0, 
                "feeRateBps": 0, # Changed from feeRate
                "side": 0, "signatureType": self.signature_type
            }
        }
        
        signable = encode_typed_data(full_message=structured_data)
        
        # Recover address from Fast Signature using Slow Logic
        recover_addr = Account.recover_message(signable, signature=fast_payload.signature)
        
        if recover_addr != self.signer_address:
            print(f"❌ MISMATCH DETAIL: Fast Sig: {fast_payload.signature}")
            raise RuntimeError(f"❌ CRITICAL: Hash mismatch! likely feeRate vs feeRateBps issue. Expected {self.signer_address}, Got {recover_addr}")
        print("✅ FastSigner is verified and 100% compatible.")

    def sign_order(self, order_args: OrderArgs):
        # 1. Parse Args
        token_id_int = int(order_args.token_id)
        
        if order_args.side == 0 or str(order_args.side).upper() == "BUY":
            side_int = 0
            side_str = "BUY"
            maker_amount = int(order_args.size * order_args.price * 1_000_000)
            taker_amount = int(order_args.size * 1_000_000)
        else:
            side_int = 1
            side_str = "SELL"
            maker_amount = int(order_args.size * 1_000_000)
            taker_amount = int(order_args.size * order_args.price * 1_000_000)

        salt = int(time.time() * 1000)
        
        # 2. Manual Packing
        encoded_data = (
            self.order_type_hash +
            salt.to_bytes(32, 'big') +
            self._maker_word +
            self._signer_word +
            self._zero_word +
            token_id_int.to_bytes(32, 'big') +
            maker_amount.to_bytes(32, 'big') +
            taker_amount.to_bytes(32, 'big') +
            (0).to_bytes(32, 'big') + # expiration
            (0).to_bytes(32, 'big') + # nonce
            (0).to_bytes(32, 'big') + # feeRateBps (matches hash position)
            side_int.to_bytes(32, 'big') +
            self.signature_type.to_bytes(32, 'big')
        )
        
        # 3. Hashing
        digest = keccak(b'\x19\x01' + self.domain_separator + keccak(encoded_data))
        
        # 4. Signing
        signature_bytes = self._private_key.sign_recoverable(digest, hasher=None)
        
        # 5. V-Value Fix
        sig_mutable = bytearray(signature_bytes)
        if sig_mutable[64] < 27:
            sig_mutable[64] += 27
            
        final_sig = "0x" + sig_mutable.hex()

        # 6. Return Wrapper
        return PolySignedOrder({
            "salt": salt,
            "maker": self.maker_address,
            "signer": self.signer_address,
            "taker": "0x0000000000000000000000000000000000000000",
            "tokenId": str(order_args.token_id),
            "makerAmount": str(maker_amount),
            "takerAmount": str(taker_amount),
            "expiration": "0",
            "nonce": "0",
            "feeRateBps": "0", # Matches API expectation
            "side": side_str,
            "signatureType": self.signature_type,
            "signature": final_sig
        })