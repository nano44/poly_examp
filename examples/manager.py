import subprocess
import time
import sys
import os
from datetime import datetime

# --- CONFIGURATION ---
# Get the absolute directory where manager.py is located (e.g., .../py-clob-client/examples)
MANAGER_DIR = os.path.dirname(os.path.abspath(__file__))
# Get the Project Root (e.g., .../py-clob-client)
PROJECT_ROOT = os.path.dirname(MANAGER_DIR)

# Modules to run (Must match the filename without .py)
FETCH_MODULE = "examples.get_autmatic_ids" 
TRADE_MODULE = "examples.hft_engine"
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

def main():
    print("🤖 Lifecycle Manager Started.")
    print("   -> Logic: Update IDs at :00, :15, :30, :45. Trade from :05 to :00.")
    print(f"   -> Project Root: {PROJECT_ROOT}")
    
    # --- NEW: Run fetcher immediately on startup ---
    run_id_fetcher()
    # -----------------------------------------------
    
    trader_process = None
    current_window_updated = False

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

                time.sleep(1)

    except KeyboardInterrupt:
        print("\n[Manager] Shutting down...")
        if trader_process:
            stop_trader(trader_process)

if __name__ == "__main__":
    main()