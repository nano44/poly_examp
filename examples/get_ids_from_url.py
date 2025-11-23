import json
import requests

# PASTE YOUR URL HERE
TARGET_URL = "https://polymarket.com/event/btc-updown-15m-1763918100?tid=1763918302937"


def check_clob_status(token_id: str) -> bool:
    """
    Ping the CLOB book endpoint to see if the orderbook exists.
    Returns True if ACTIVE (200), False otherwise.
    """
    if not token_id or token_id == "NOT_FOUND":
        return False
    try:
        resp = requests.get(f"https://clob.polymarket.com/book?token_id={token_id}", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


def fetch_ids_from_url():
    try:
        # 1. Parse Slug
        if "event/" not in TARGET_URL:
            print("❌ Invalid URL. Must contain '/event/'")
            return
        slug = TARGET_URL.split("event/")[1].split("?")[0]
        print(f"🔍 Analyzing Event Slug: '{slug}'...")

        # 2. Fetch Data from Gamma API
        url = f"https://gamma-api.polymarket.com/events?slug={slug}"
        resp = requests.get(url, timeout=10).json()

        if not resp:
            print("❌ API returned no data.")
            return

        event = resp[0] if isinstance(resp, list) else resp
        print(f"✅ Found Event: {event.get('title')}")

        markets = event.get("markets", [])
        print(f"📊 Found {len(markets)} market(s) in this event.")

        for m in markets:
            print(f"\n📌 Market: {m.get('question')}")

            clob_ids = m.get("clobTokenIds", [])
            if isinstance(clob_ids, str):
                try:
                    clob_ids = json.loads(clob_ids)
                except Exception:
                    pass

            tokens_meta = m.get("tokens", [])
            if not clob_ids and tokens_meta:
                clob_ids = [t.get("token_id") or t.get("id") for t in tokens_meta]

            if not clob_ids:
                print("   ❌ No Token IDs found for this market.")
                continue

            print(f"   (Found {len(clob_ids)} tokens. Verifying status...)")
            print("-" * 80)

            for idx, token_id in enumerate(clob_ids):
                if not token_id:
                    continue
                outcome_label = "Unknown"
                if idx < len(tokens_meta):
                    outcome_label = tokens_meta[idx].get("outcome", "Unknown")

                is_active = check_clob_status(token_id)
                status_label = "✅ ACTIVE" if is_active else "❌ DEAD (404)"

                print(f'Outcome: {outcome_label:<20} | ID: {token_id} | Status: {status_label}')

            print("-" * 80)

    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    fetch_ids_from_url()
