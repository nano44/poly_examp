import json
import sys

import requests


def fetch_markets():
    url = "https://gamma-api.polymarket.com/markets"
    params = {
        "active": "true",
        "closed": "false",
        "limit": 100,
        "tag_id": 1,  # crypto tag to narrow search
    }
    resp = requests.get(url, params=params, timeout=5)
    resp.raise_for_status()
    return resp.json()


def main():
    try:
        data = fetch_markets()
    except Exception as e:
        print(f"Error fetching markets: {e}")
        sys.exit(1)

    markets = data if isinstance(data, list) else data.get("markets", [])

    for m in markets:
        question = m.get("question", "")
        if "bitcoin up or down" not in question.lower():
            continue
        tokens = m.get("tokens", [])
        if len(tokens) < 2:
            continue
        # Determine which token is up/down based on outcome label
        up_id = down_id = None
        for t in tokens:
            outcome = t.get("outcome", "").lower()
            tid = t.get("token_id") or t.get("id")
            if not tid:
                continue
            if "up" in outcome or "yes" in outcome:
                up_id = tid
            elif "down" in outcome or "no" in outcome:
                down_id = tid

        # Fallback to positional assumption if labels not found
        if not up_id and len(tokens) >= 1:
            up_id = tokens[0].get("token_id") or tokens[0].get("id")
        if not down_id and len(tokens) >= 2:
            down_id = tokens[1].get("token_id") or tokens[1].get("id")

        print(question)
        print(f'TOKEN_ID_UP = "{up_id}"')
        print(f'TOKEN_ID_DOWN = "{down_id}"')
        return

    print("No active 'Bitcoin Up or Down' market found.")


if __name__ == "__main__":
    main()
