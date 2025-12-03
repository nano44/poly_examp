# This module acts as a singleton store for live market data.
# It is updated by the Websocket listener and read by the Trading Engine.

# --- LIVE PRICES (UP) ---
UP_askprice = 0.0
UP_bidprice = 0.0
spread_up = 0.0

# --- LIVE PRICES (DOWN) ---
DOWN_askprice = 0.0
DOWN_bidprice = 0.0
spread_down = 0.0

# --- HELPERS ---
def update_spreads():
    """Recalculates the spreads based on current Bid/Ask prices for each side."""
    global spread_up, spread_down, UP_askprice, UP_bidprice, DOWN_askprice, DOWN_bidprice
    
    # Update UP Spread
    if UP_askprice > 0 and UP_bidprice > 0:
        spread_up = abs(UP_askprice - UP_bidprice)
        spread_up = float(f"{spread_up:.3f}")
    else:
        spread_up = 0.0

    # Update DOWN Spread
    if DOWN_askprice > 0 and DOWN_bidprice > 0:
        spread_down = abs(DOWN_askprice - DOWN_bidprice)
        spread_down = float(f"{spread_down:.3f}")
    else:
        spread_down = 0.0