import json
import requests

# PASTE YOUR URL HERE
TARGET_URL = "https://polymarket.com/event/btc-updown-15m-1763915400?tid=1763915409194"


def check_clob_status(token_id: str) -> bool:
    """
    Ping the CLOB book endpoint to see if the orderbook exists.
    Returns True if ACTIVE (200), False otherwise.
    """
    if not token_id or token_id == "NOT_FOUND":
        return False
    try:
        resp = requests.get(f"https://clob.polymarket.com/book?token_id={token_id}", timeout=5)
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

        # 2. Fetch Data from Gamma
        url = f"https://gamma-api.polymarket.com/events?slug={slug}"
        resp = requests.get(url, timeout=5).json()

        if not resp:
            print("❌ API returned no data.")
            return

        event = resp[0] if isinstance(resp, list) else resp
        print(f"✅ Found Event: {event.get('title')}")

        markets = event.get("markets", [])
        for m in markets:
            print(f"\n📌 Market: {m.get('question')}")

            up_id = "NOT_FOUND"
            down_id = "NOT_FOUND"

            # STRATEGY A: Check 'clobTokenIds'
            clob_ids = m.get("clobTokenIds", [])
            # handle stringified list
            if isinstance(clob_ids, str):
                try:
                    clob_ids = json.loads(clob_ids)
                except Exception:
                    pass

            if isinstance(clob_ids, list) and len(clob_ids) >= 2:
                print("   (Found via clobTokenIds)")
                up_id = clob_ids[0]   # Index 0 is always YES/UP
                down_id = clob_ids[1] # Index 1 is always NO/DOWN
            else:
                print("   (Fallback to tokens list search)")
                tokens = m.get("tokens", [])
                for t in tokens:
                    outcome = t.get("outcome", "").upper()
                    tid = t.get("token_id")
                    if "UP" in outcome or "YES" in outcome:
                        up_id = tid
                    elif "DOWN" in outcome or "NO" in outcome:
                        down_id = tid

            # Validation: check if book is alive
            print("   (Verifying status with Trading Engine...)")
            is_up_active = check_clob_status(up_id)
            is_down_active = check_clob_status(down_id)
            up_status_label = "✅ ACTIVE" if is_up_active else "❌ DEAD (404)"
            down_status_label = "✅ ACTIVE" if is_down_active else "❌ DEAD (404)"

            print("-" * 60)
            print(f'TOKEN_ID_UP   = "{up_id}" \t# {up_status_label}')
            print(f'TOKEN_ID_DOWN = "{down_id}" \t# {down_status_label}')
            print("-" * 60)

            if not is_up_active:
                print("⚠️ WARNING: These tokens appear expired or invalid. Ensure you have the current window URL.")

    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    fetch_ids_from_url()
