import csv
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta # <--- Added timedelta

# --- CONFIGURATION ---
MANAGER_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(MANAGER_DIR)

FETCH_MODULE = "examples.get_autmatic_ids" 
TRADE_MODULE = "examples.engine_improved"
LAST_TRADES_MODULE = "examples.try_get_lasttrades"

LAST_TRADES_ORDER_IDS_RAW = os.getenv("LAST_TRADES_ORDER_IDS", "")
LAST_TRADES_ORDER_IDS = [oid.strip() for oid in LAST_TRADES_ORDER_IDS_RAW.split(",") if oid.strip()]
LAST_TRADES_LIMIT_RAW = os.getenv("LAST_TRADES_LIMIT")
LAST_TRADES_LIMIT = int(LAST_TRADES_LIMIT_RAW) if LAST_TRADES_LIMIT_RAW and LAST_TRADES_LIMIT_RAW.isdigit() else None

TRADE_CSV_PATH = os.getenv("TRADE_CSV_PATH", os.path.join(PROJECT_ROOT, "trade_analytics_temp.csv"))
FINAL_CSV_PATH = os.getenv("TRADE_CSV_FINAL_PATH", os.path.join(PROJECT_ROOT, "trade_analytics_final.csv"))
TICK_COLUMNS = [f"Tick_{i}" for i in range(1, 9)]

# This MUST match the header in engine_improved.py
TEMP_HEADER = [
    "Timestamp",
    "Side",
    "Entry",
    "Spread",
    "Volatility",
    "Velocity",
    "Gear",
    "PredJump",
    "OrderID",
] + TICK_COLUMNS

PYTHON_CMD = sys.executable


def ensure_header_row(path: str, header: list[str]) -> None:
    needs_header = not os.path.exists(path)
    existing_rows: list[list[str]] = []

    if not needs_header:
        try:
            with open(path, newline="") as f:
                reader = csv.reader(f)
                try:
                    first = next(reader)
                except StopIteration:
                    needs_header = True
                else:
                    if first != header:
                        needs_header = True
                        existing_rows = list(reader)
        except Exception:
            needs_header = True

    if needs_header:
        try:
            with open(path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(header)
                if existing_rows:
                    writer.writerows(existing_rows)
        except Exception as e:
            print(f"[Manager] ⚠️ Could not ensure header for {path}: {e}")

def run_id_fetcher():
    print(f"[Manager] 🔄 Fetching new IDs ({datetime.now().strftime('%H:%M:%S')})...")
    try:
        result = subprocess.run(
            [PYTHON_CMD, "-m", FETCH_MODULE],
            check=True, capture_output=True, text=True, cwd=PROJECT_ROOT 
        )
        print("[Manager] ✅ IDs Updated.")
    except subprocess.CalledProcessError as e:
        print(f"[Manager] ❌ ID Fetcher Failed: {e}")
        print(e.stderr)

def start_trader():
    print(f"[Manager] 🚀 Starting HFT Engine ({datetime.now().strftime('%H:%M:%S')})...")
    return subprocess.Popen([PYTHON_CMD, "-m", TRADE_MODULE], cwd=PROJECT_ROOT)

def run_last_trades(order_ids: list[str], limit: int | None = None):
    if not order_ids:
        return [], ""
    cmd = [PYTHON_CMD, "-m", LAST_TRADES_MODULE, "--order-ids", *order_ids]
    if limit:
        cmd += ["--limit", str(limit)]
    print(f"[Manager] 📡 Fetching last trades for {len(order_ids)} order IDs...")
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=PROJECT_ROOT)
        if result.stdout: print(result.stdout, end="")
        if result.stderr: print(result.stderr, end="")
        parsed = parse_helper_output(result.stdout)
        return parsed, result.stdout
    except subprocess.CalledProcessError as e:
        print(f"[Manager] ❌ Last-trades helper failed: {e}")
        print(e.stderr)
        return [], ""

def load_order_ids_from_csv(csv_path: str, max_ids: int | None = None) -> list[str]:
    ensure_header_row(csv_path, TEMP_HEADER)
    order_ids: list[str] = []
    try:
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or "OrderID" not in reader.fieldnames:
                return []
            for row in reader:
                oid = (row.get("OrderID") or "").strip()
                if oid:
                    order_ids.append(oid)
    except Exception as e:
        print(f"[Manager] ⚠️ Could not read {csv_path}: {e}")
        return []

    seen = set()
    deduped: list[str] = []
    for oid in reversed(order_ids):
        if oid in seen: continue
        seen.add(oid)
        deduped.append(oid)
        if max_ids and len(deduped) >= max_ids: break
    return list(reversed(deduped))

def load_csv_rows(csv_path: str):
    ensure_header_row(csv_path, TEMP_HEADER)
    if not os.path.exists(csv_path): return [], []
    try:
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows, reader.fieldnames or []
    except Exception as e:
        print(f"[Manager] ⚠️ Could not read rows from {csv_path}: {e}")
        return [], []

def write_csv_rows(csv_path: str, fieldnames: list[str], rows: list[dict]) -> None:
    if not fieldnames: return
    try:
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    except Exception as e:
        print(f"[Manager] ⚠️ Could not write rows to {csv_path}: {e}")

# --- UPDATED: Parsing logic to handle Time ---
def parse_helper_output(output: str) -> list[dict]:
    trades: list[dict] = []
    for line in output.splitlines():
        if not line.startswith("Order ID:"): continue
        try:
            # Expected format: 
            # Order ID: ... | Price: ... | Size: ... | Time: YYYY-MM-DD HH:MM:SS
            parts = [p.strip() for p in line.split("|")]
            
            oid = parts[0].split("Order ID:")[1].strip()
            price_part = parts[1].split("Price:")[1].strip()
            size_part = parts[2].split("Size:")[1].strip()
            
            # Extract Time
            trade_dt = None
            if len(parts) >= 4 and "Time:" in parts[3]:
                time_str = parts[3].split("Time:")[1].strip()
                if time_str and time_str != "N/A":
                    try:
                        trade_dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        print(f"[Manager] ⚠️ Date parse error: {time_str}")
                        trade_dt = None

            trades.append({
                "order_id": oid, 
                "price": float(price_part), 
                "size": float(size_part),
                "datetime": trade_dt # Store datetime object
            })
        except Exception as e:
            print(f"[Manager] Warning parsing line: {e}")
            continue
    return trades

# --- NEW: Calculation Logic ---
def calculate_time_till_strike(trade_dt: datetime) -> str:
    """
    Calculates seconds remaining until the next 15-minute strike 
    (:00, :15, :30, :45).
    """
    if not trade_dt:
        return "N/A"
    
    # Logic: Round minutes down to nearest 15, then add 15 minutes
    base = trade_dt.replace(second=0, microsecond=0)
    minute = base.minute
    
    floored_minute = (minute // 15) * 15
    current_window_start = base.replace(minute=floored_minute)
    next_strike = current_window_start + timedelta(minutes=15)
    
    # Calculate Difference
    diff = next_strike - trade_dt
    seconds_left = int(diff.total_seconds())
    
    # Handle rare clock skew edge cases
    return str(max(0, seconds_left))

def enrich_helper_trades_with_csv(helper_trades: list[dict], csv_rows: list[dict]):
    remaining = list(csv_rows)
    enriched: list[dict] = []
    for ht in helper_trades:
        oid = ht.get("order_id")
        if not oid: continue
        match_index = next((i for i, r in enumerate(remaining) if (r.get("OrderID") or "").strip() == oid), None)
        if match_index is None: continue
        row = remaining.pop(match_index)
        
        # --- APPLY CALCULATION ---
        time_till_strike = calculate_time_till_strike(ht.get("datetime"))
        
        # Merge API Data + CSV Data
        combined = {
            "order_id": oid,
            "price": ht.get("price"), # Actual Filled Price
            "size": ht.get("size"),   # Actual Filled Size
            "timestamp": row.get("Timestamp"),
            "side": row.get("Side"),
            "entry": row.get("Entry"),       
            "spread": row.get("Spread"),
            "velocity": row.get("Velocity"),
            "volatility": row.get("Volatility"),
            "gear": row.get("Gear"),             
            "pred_jump": row.get("PredJump"),
            "time_till_strike": time_till_strike # <--- Added Field
        }
        for key, val in row.items():
            if key.startswith("Tick_"):
                combined[key] = val
        enriched.append(combined)
    return enriched, remaining

def append_final_rows(rows: list[dict], path: str = FINAL_CSV_PATH) -> None:
    """Append enriched rows to the final CSV."""
    if not rows: return

    # --- UPDATED HEADER ---
    fieldnames = [
        "Timestamp",
        "Side",
        "Thought entry price",
        "Actual entry price",
        "Spread",
        "Volatility",
        "Velocity",
        "Gear",
        "PredJump",
        "Time till strike", # <--- New Header Column
        "OrderID",
        "Size",
    ] + TICK_COLUMNS
    ensure_header_row(path, fieldnames)

    def _map_row(r: dict) -> dict:
        mapped = {
            "Timestamp": r.get("timestamp"),
            "Side": r.get("side"),
            "Thought entry price": r.get("entry"),
            "Actual entry price": r.get("price"),
            "Spread": r.get("spread"),
            "Volatility": r.get("volatility"),
            "Velocity": r.get("velocity"),
            "Gear": r.get("gear"),
            "PredJump": r.get("pred_jump"),
            "Time till strike": r.get("time_till_strike"), # <--- Map the value
            "OrderID": r.get("order_id"),
            "Size": r.get("size"),
        }
        for tick in TICK_COLUMNS:
            mapped[tick] = r.get(tick)
        return mapped

    try:
        with open(path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writerows(_map_row(r) for r in rows)
    except Exception as e:
        print(f"[Manager] ⚠️ Could not append to {path}: {e}")

def stop_trader(process):
    if process:
        print(f"[Manager] 🛑 Stopping HFT Engine...")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            print("[Manager] ⚠️ Force killing engine...")
            process.kill()
        print("[Manager] 💤 Engine Stopped.")

def collect_order_ids() -> list[str]:
    ids_from_csv = load_order_ids_from_csv(TRADE_CSV_PATH)
    if ids_from_csv: return ids_from_csv
    return LAST_TRADES_ORDER_IDS

def main():
    print("🤖 Lifecycle Manager Started.")
    print("   -> Logic: Update IDs at :00, :15, :30, :45. Trade from :05 to :00.")
    print(f"   -> Project Root: {PROJECT_ROOT}")
    
    run_id_fetcher()
    startup_order_ids = collect_order_ids()
    if startup_order_ids:
        run_last_trades(startup_order_ids, LAST_TRADES_LIMIT)
    
    trader_process = None
    current_window_updated = False
    last_trades_poll_ts = 0.0

    try:
        while True:
            now = datetime.now()
            seconds_past_quarter = (now.minute % 15) * 60 + now.second
            
            if 0 <= seconds_past_quarter < 5:
                if trader_process is not None:
                    stop_trader(trader_process)
                    trader_process = None
                if not current_window_updated:
                    run_id_fetcher()
                    current_window_updated = True
                time.sleep(0.5)
            else:
                if current_window_updated: current_window_updated = False
                if trader_process is None:
                    print(f"[Manager] ⏱️ 5-second delay complete. Launching trader.")
                    trader_process = start_trader()
                if trader_process.poll() is not None:
                    print("[Manager] ⚠️ Trader crashed! Restarting...")
                    trader_process = start_trader()

                now_ts = time.time()
                if now_ts - last_trades_poll_ts >= 60:
                    poll_order_ids = collect_order_ids()
                    if poll_order_ids:
                        helper_trades, _ = run_last_trades(poll_order_ids, LAST_TRADES_LIMIT)
                        if helper_trades:
                            csv_rows, fieldnames = load_csv_rows(TRADE_CSV_PATH)
                            enriched, remaining = enrich_helper_trades_with_csv(helper_trades, csv_rows)
                            if enriched:
                                print(f"[Manager] 📄 Enriched {len(enriched)} trades with CSV data.")
                                append_final_rows(enriched, FINAL_CSV_PATH)
                            if fieldnames:
                                write_csv_rows(TRADE_CSV_PATH, fieldnames, remaining)
                    last_trades_poll_ts = now_ts
                time.sleep(1)
    except KeyboardInterrupt:
        print("\n[Manager] Shutting down...")
        if trader_process: stop_trader(trader_process)

if __name__ == "__main__":
    main()