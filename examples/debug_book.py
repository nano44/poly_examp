import requests

# The IDs your bot is currently using (update as needed)
UP_ID = "51246029821095321025101528579801436697613413457040588756195921550858692320775"
DOWN_ID = "30952632199510210582669872465499230674506268186076755831868961179548730516152"


def inspect(label: str, token_id: str) -> None:
    print(f"\n🔍 Inspecting {label} ({token_id[:15]}...):")
    url = f"https://clob.polymarket.com/book?token_id={token_id}"
    try:
        resp = requests.get(url, timeout=5).json()
        bids = resp.get("bids", [])
        asks = resp.get("asks", [])

        if not bids and not asks:
            print("   ❌ ORDER BOOK IS EMPTY!")
        else:
            top_bid = bids[0]["price"] if bids else "None"
            top_ask = asks[0]["price"] if asks else "None"
            print("   ✅ Liquidity Found!")
            print(f"      Best Bid: {top_bid}")
            print(f"      Best Ask: {top_ask}")
            if bids and asks:
                spread = float(top_ask) - float(top_bid)
                print(f"      Spread: {spread:.4f}")
    except Exception as e:
        print(f"   ⚠️ Error: {e}")


if __name__ == "__main__":
    inspect("UP Token", UP_ID)
    inspect("DOWN Token", DOWN_ID)
