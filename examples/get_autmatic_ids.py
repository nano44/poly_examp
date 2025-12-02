import requests
import time
import json
from pathlib import Path

def save_current_market_data(data):
    """
    Overwrites active_ids.json with the latest market data.
    We use 'w' mode to ensure the file always contains only the current active market.
    """
    # Go up two levels: examples/script.py -> examples -> root/
    file_path = Path(__file__).resolve().parent.parent / "active_ids.json"
    
    try:
        with open(file_path, "w") as f:
            json.dump(data, f, indent=4)
        print(f"   -> ✅ Saved successfully to: {file_path}")
    except Exception as e:
        print(f"   -> ❌ Error writing file: {e}")

def get_and_save_btc_15m_ids():
    # --- 1. Calculate Time & Slug ---
    now_ts = int(time.time())
    # Round down to nearest 15 mins (900s)
    start_ts = (now_ts // 900) * 900
    slug = f"btc-updown-15m-{start_ts}"
    
    print(f"1. Processing Slug: {slug}")

    # --- 2. Fetch from Gamma (Event Details) ---
    gamma_url = "https://gamma-api.polymarket.com/events"
    
    try:
        resp = requests.get(gamma_url, params={"slug": slug})
        resp.raise_for_status() # Check for network errors
        events = resp.json()
    except Exception as e:
        print(f"   -> Network error fetching Gamma: {e}")
        return

    if not events:
        print("   -> ⚠️ Event not found in Gamma (Market likely doesn't exist yet).")
        return

    # --- 3. Fetch from CLOB (Token IDs) ---
    market_obj = events[0]['markets'][0]
    condition_id = market_obj['conditionId']
    question_title = market_obj['question']
    
    print(f"   -> Market Found: {question_title}")
    
    clob_url = f"https://clob.polymarket.com/markets/{condition_id}"
    try:
        clob_data = requests.get(clob_url).json()
        tokens = clob_data.get('tokens', [])
    except Exception as e:
        print(f"   -> Error fetching CLOB: {e}")
        return

    # --- 4. Smart Matching (Up/Down) ---
    # Looks for "Yes" or "Up" for the UP token
    up_token = next((t for t in tokens if t['outcome'] in ["Yes", "Up"]), None)
    # Looks for "No" or "Down" for the DOWN token
    down_token = next((t for t in tokens if t['outcome'] in ["No", "Down"]), None)

    if up_token and down_token:
        # Generate timestamp in milliseconds for the TID url parameter
        tid_ms = int(time.time() * 1000)
        
        # Construct the final clean data object
        final_data = {
            "UP": up_token['token_id'],
            "DOWN": down_token['token_id'],
            "market": question_title,
            "updated_at": time.time(),
            "source_url": f"https://polymarket.com/event/{slug}?tid={tid_ms}"
        }
        
        # Print preview to console
        print(f"   -> UP ID:   {final_data['UP'][:15]}...")
        print(f"   -> DOWN ID: {final_data['DOWN'][:15]}...")
        
        # Save to file
        save_current_market_data(final_data)
        
    else:
        print("   -> ❌ Error: Could not identify Up/Down tokens in CLOB response.")

if __name__ == "__main__":
    get_and_save_btc_15m_ids()