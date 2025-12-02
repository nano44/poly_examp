import csv
import os
import subprocess
import sys
import time
from datetime import datetime

# --- CONFIGURATION ---
# Get the absolute directory where manager.py is located (e.g., .../py-clob-client/examples)
MANAGER_DIR = os.path.dirname(os.path.abspath(__file__))
# Get the Project Root (e.g., .../py-clob-client)
PROJECT_ROOT = os.path.dirname(MANAGER_DIR)

# Modules to run (Must match the filename without .py)
FETCH_MODULE = "examples.get_autmatic_ids" 
TRADE_MODULE = "examples.hft_engine_v2"
LAST_TRADES_MODULE = "examples.try_get_lasttrades"

# Optional: set LAST_TRADES_ORDER_IDS as comma-separated list to trigger last-trades fetch on startup.
LAST_TRADES_ORDER_IDS_RAW = os.getenv("LAST_TRADES_ORDER_IDS", "")
LAST_TRADES_ORDER_IDS = [oid.strip() for oid in LAST_TRADES_ORDER_IDS_RAW.split(",") if oid.strip()]
LAST_TRADES_LIMIT_RAW = os.getenv("LAST_TRADES_LIMIT")
LAST_TRADES_LIMIT = int(LAST_TRADES_LIMIT_RAW) if LAST_TRADES_LIMIT_RAW and LAST_TRADES_LIMIT_RAW.isdigit() else None
# CSV that hft_engine_v2 writes executed trades to; only OrderID is read.
TRADE_CSV_PATH = os.getenv("TRADE_CSV_PATH", os.path.join(PROJECT_ROOT, "trade_analytics_temp.csv"))
PYTHON_CMD = sys.executable

def run_id_fetcher():
    """Runs the ID fetcher as a module."""
    print(f"[Manager] 🔄 Fetching new IDs ({datetime.now().strftime('%H:%M:%S')})...")
    try:
        # Run with -m from the Project Root
        result = subprocess.run(
            [PYTHON_CMD, "-m", FETCH_MODULE],
            check=True,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT 
        )
        print("[Manager] ✅ IDs Updated.")
    except subprocess.CalledProcessError as e:
        print(f"[Manager] ❌ ID Fetcher Failed: {e}")
        print(e.stderr)

def start_trader():
    """Starts the trading bot as a module."""
    print(f"[Manager] 🚀 Starting HFT Engine ({datetime.now().strftime('%H:%M:%S')})...")
    # Run with -m from the Project Root
    return subprocess.Popen(
        [PYTHON_CMD, "-m", TRADE_MODULE],
        cwd=PROJECT_ROOT
    )

def run_last_trades(order_ids: list[str], limit: int | None = None) -> None:
    """Runs the last-trades helper if order IDs are provided."""
    if not order_ids:
        return

    cmd = [PYTHON_CMD, "-m", LAST_TRADES_MODULE, "--order-ids", *order_ids]
    if limit:
        cmd += ["--limit", str(limit)]

    print(f"[Manager] 📡 Fetching last trades for {len(order_ids)} order IDs...")
    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="")
    except subprocess.CalledProcessError as e:
        print(f"[Manager] ❌ Last-trades helper failed: {e}")
        print(e.stderr)


def load_order_ids_from_csv(csv_path: str, max_ids: int | None = None) -> list[str]:
    """
    Read OrderID values from the trade CSV.
    Returns most-recent unique order ids (preserves order).
    """
    if not os.path.exists(csv_path):
        return []

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

    # Deduplicate while keeping most recent entries
    seen = set()
    deduped: list[str] = []
    for oid in reversed(order_ids):
        if oid in seen:
            continue
        seen.add(oid)
        deduped.append(oid)
        if max_ids and len(deduped) >= max_ids:
            break

    return list(reversed(deduped))

def stop_trader(process):
    """Gracefully stops the trading bot."""
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
    """Prefer order ids from the trade CSV; fall back to env list."""
    ids_from_csv = load_order_ids_from_csv(TRADE_CSV_PATH)
    if ids_from_csv:
        return ids_from_csv
    return LAST_TRADES_ORDER_IDS

def main():
    print("🤖 Lifecycle Manager Started.")
    print("   -> Logic: Update IDs at :00, :15, :30, :45. Trade from :05 to :00.")
    print(f"   -> Project Root: {PROJECT_ROOT}")
    
    # --- NEW: Run fetcher immediately on startup ---
    run_id_fetcher()
    # -----------------------------------------------

    # Optionally fetch recent trades for provided order IDs (CSV if present)
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
            
            # --- PHASE 1: MAINTENANCE (0s to 5s) ---
            if 0 <= seconds_past_quarter < 5:
                if trader_process is not None:
                    stop_trader(trader_process)
                    trader_process = None
                
                if not current_window_updated:
                    run_id_fetcher()
                    current_window_updated = True
                
                time.sleep(0.5)

            # --- PHASE 2: TRADING (5s to 900s) ---
            else:
                if current_window_updated:
                    current_window_updated = False

                if trader_process is None:
                    print(f"[Manager] ⏱️ 5-second delay complete. Launching trader.")
                    trader_process = start_trader()
                
                if trader_process.poll() is not None:
                    print("[Manager] ⚠️ Trader crashed! Restarting...")
                    trader_process = start_trader()

                # Periodically fetch last trades while running
                now_ts = time.time()
                if now_ts - last_trades_poll_ts >= 60:
                    poll_order_ids = collect_order_ids()
                    if poll_order_ids:
                        run_last_trades(poll_order_ids, LAST_TRADES_LIMIT)
                    last_trades_poll_ts = now_ts

                time.sleep(1)

    except KeyboardInterrupt:
        print("\n[Manager] Shutting down...")
        if trader_process:
            stop_trader(trader_process)

if __name__ == "__main__":
    main()
