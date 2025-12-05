import os
import time
from dotenv import load_dotenv
from eth_utils import keccak
from py_clob_client.clob_types import OrderArgs
from py_clob_client.order_builder.constants import BUY
from eth_account import Account
from eth_account.messages import encode_typed_data

# --- IMPORT YOUR LATEST SIGNER ---
# Ensure this matches your filename (e.g. fast_signer.py)
from examples.sign_order import FastPolymarketSigner 

# 1. Load your Env
load_dotenv()
KEY = os.getenv("PK")
FUNDER = os.getenv("FUNDER")
SIGNATURE_TYPE = int(os.getenv("SIGNATURE_TYPE", 1))

# 2. Setup
print(f"--- SETUP ---")
print(f"Initializing Signer with Key: {KEY[:6]}... (Type: {SIGNATURE_TYPE})")
signer = FastPolymarketSigner(KEY, funder=FUNDER, signature_type=SIGNATURE_TYPE)

dummy_token = "5808926526685869403816172658828366964966779344465420364234026601438903332832"
args = OrderArgs(price=0.5, size=10.0, side=BUY, token_id=dummy_token)

print(f"Maker Address:  {signer.maker_address}")
print(f"Signer Address: {signer.signer_address}")

# 3. FAST PATH CALCULATION (Manual Byte Packing)
# We replicate the exact logic inside FastPolymarketSigner.sign_order
salt = int(time.time() * 1000)
maker_amount = int(args.size * args.price * 1_000_000)
taker_amount = int(args.size * 1_000_000)

# NOTE: The new signer uses pre-padded '_word' attributes, not '_bytes'
encoded_data = (
    signer.order_type_hash +
    salt.to_bytes(32, 'big') +
    signer._maker_word +    # <--- Updated to match new class
    signer._signer_word +   # <--- Updated to match new class
    signer._zero_word +     # <--- Updated to match new class
    int(args.token_id).to_bytes(32, 'big') +
    maker_amount.to_bytes(32, 'big') +
    taker_amount.to_bytes(32, 'big') +
    (0).to_bytes(32, 'big') + # expiration
    (0).to_bytes(32, 'big') + # nonce
    (0).to_bytes(32, 'big') + # feeRate
    (0).to_bytes(32, 'big') + # side (BUY = 0)
    int(signer.signature_type).to_bytes(32, 'big')
)

# EIP-712 Final Hash
fast_digest = keccak(b'\x19\x01' + signer.domain_separator + keccak(encoded_data))

# 4. SLOW PATH CALCULATION (Official Library Reference)
# We reconstruct the dictionary exactly as standard tools expect
data = {
    "types": {
        "EIP712Domain": [
            {"name": "name", "type": "string"},
            {"name": "version", "type": "string"},
            {"name": "chainId", "type": "uint256"},
            {"name": "verifyingContract", "type": "address"},
        ],
        "Order": [
            {"name": "salt", "type": "uint256"},
            {"name": "maker", "type": "address"},
            {"name": "signer", "type": "address"},
            {"name": "taker", "type": "address"},
            {"name": "tokenId", "type": "uint256"},
            {"name": "makerAmount", "type": "uint256"},
            {"name": "takerAmount", "type": "uint256"},
            {"name": "expiration", "type": "uint256"},
            {"name": "nonce", "type": "uint256"},
            {"name": "feeRate", "type": "uint256"},
            {"name": "side", "type": "uint8"},
            {"name": "signatureType", "type": "uint8"},
        ],
    },
    "domain": {
        "name": "Polymarket CTF Exchange",
        "version": "1",
        "chainId": 137,
        "verifyingContract": "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E",
    },
    "primaryType": "Order",
    "message": {
        "salt": salt,
        "maker": signer.maker_address,
        "signer": signer.signer_address,
        "taker": "0x0000000000000000000000000000000000000000",
        "tokenId": int(dummy_token),
        "makerAmount": maker_amount,
        "takerAmount": taker_amount,
        "expiration": 0,
        "nonce": 0,
        "feeRate": 0,
        "side": 0,
        "signatureType": signer.signature_type,
    },
}

slow_message = encode_typed_data(full_message=data)
slow_digest = slow_message.header + slow_message.body

print("-" * 60)
print(f"FAST DIGEST: {fast_digest.hex()}")
print(f"SLOW DIGEST: {slow_digest.hex()}")
print("-" * 60)

if fast_digest == slow_digest:
    print("\n✅ HASH VERIFIED: The C-optimized logic perfectly matches the Standard Library.")
else:
    print("\n❌ MISMATCH: The hashing logic differs.")
    print("Check: 1. Constants (ChainID/Contract), 2. Type definitions, 3. Address padding.")