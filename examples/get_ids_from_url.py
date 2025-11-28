import json
import requests
import time

# ==========================================
# 1. PASTE YOUR NEW URL HERE (EVERY 15 MIN)
# ==========================================
TARGET_URL = "https://polymarket.com/event/btc-updown-15m-1764323100?tid=1764323111632"
OUTPUT_FILE = "active_ids.json"


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


def save_ids(up_id, down_id, market_question):
    """Saves the valid IDs to a JSON file for the bot to read."""
    data = {
        "UP": up_id,
        "DOWN": down_id,
        "market": market_question,
        "updated_at": time.time(),
        "source_url": TARGET_URL,
    }
    with open(OUTPUT_FILE, "w") as f:
        json.dump(data, f, indent=4)
    print(f"\n💾 SUCCESS: Saved to {OUTPUT_FILE}")
    print(f"   UP ID:   {up_id}")
    print(f"   DOWN ID: {down_id}")


def fetch_and_save_ids():
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
        markets = event.get("markets", [])
        print(f"📊 Found {len(markets)} market(s). Scanning for active pairs...")

        found_valid_pair = False

        for m in markets:
            market_question = m.get("question")
            print(f"\n📌 Checking: {market_question}")

            # Get Token IDs
            clob_ids = m.get("clobTokenIds", [])
            if isinstance(clob_ids, str):
                try:
                    clob_ids = json.loads(clob_ids)
                except Exception:
                    pass

            tokens_meta = m.get("tokens", [])
            if not clob_ids and tokens_meta:
                clob_ids = [t.get("token_id") or t.get("id") for t in tokens_meta]

            if len(clob_ids) < 2:
                print("   ❌ Not enough tokens.")
                continue

            # Identify UP vs DOWN (prefer labels; fallback to list order)
            up_id = None
            down_id = None

            for idx, token_id in enumerate(clob_ids):
                if not token_id:
                    continue

                outcome = ""
                if idx < len(tokens_meta):
                    meta = tokens_meta[idx] or {}
                    outcome = (
                        meta.get("outcome")
                        or meta.get("ticker")
                        or meta.get("label")
                        or ""
                    ).upper()

                if outcome in ["UP", "YES"]:
                    up_id = token_id
                elif outcome in ["DOWN", "NO"]:
                    down_id = token_id

            if len(clob_ids) >= 2:
                up_id = up_id or clob_ids[0]
                down_id = down_id or clob_ids[1]

            # Validate and Save
            if up_id and down_id:
                up_active = check_clob_status(up_id)
                down_active = check_clob_status(down_id)
                if up_active and down_active:
                    print("   ✅ IDs are ACTIVE on CLOB.")
                    save_ids(up_id, down_id, market_question)
                    found_valid_pair = True
                    return
                print(
                    "   ⚠️ IDs found, but CLOB returned 404 (Expired/Inactive). "
                    f"UP active? {up_active} | DOWN active? {down_active}"
                )
            else:
                print("   ❌ Could not identify UP/DOWN pair.")

        if not found_valid_pair:
            print("\n❌ Failed: No active UP/DOWN token pair found in this event.")

    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    fetch_and_save_ids()
