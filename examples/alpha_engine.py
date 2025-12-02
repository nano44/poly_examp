# alpha_engine.py
import math

class AlphaEngine:
    def __init__(self, strike_price: float, max_size: float = 1.5, min_size: float = 1.0, sigma: float = 50.0):
        self.strike_price = strike_price
        
        # Sizing Configuration
        self.max_size = max_size
        self.min_size = min_size
        self.sigma = sigma
        
        # Internal State for Velocity
        self.last_price = None
        self.last_ts = None

    def calculate_size(self, current_price: float) -> float:
        """
        Calculates bet size using Gaussian decay based on distance from Strike.
        """
        if self.strike_price is None: 
            return self.min_size
            
        dist = abs(current_price - self.strike_price)
        # Gaussian formula: Max * e^(-(x^2) / (2*sigma^2))
        raw_size = self.max_size * math.exp(-(dist**2) / (2 * self.sigma**2))
        return max(self.min_size, raw_size)

    def get_signal_strength(self, price: float, ts: float) -> float:
        """
        Calculates a 'Score' for the current tick.
        Score = Velocity ($/sec) * Context Multiplier
        """
        # 1. Initialize on first tick
        if self.last_price is None:
            self.last_price = price
            self.last_ts = ts
            return 0.0

        # 2. Time Delta (Prevent division by zero)
        dt = ts - self.last_ts
        if dt < 0.001: 
            return 0.0

        # 3. Calculate Raw Velocity ($ moved per second)
        delta_p = price - self.last_price
        velocity = delta_p / dt

        # 4. Context Multiplier (The "Strike Cross" Boost)
        # If we cross the strike, we boost the signal strength by 2x
        multiplier = 1.0
        crossed_up = (self.last_price < self.strike_price) and (price >= self.strike_price)
        crossed_down = (self.last_price > self.strike_price) and (price <= self.strike_price)
        
        if crossed_up or crossed_down:
            multiplier = 2.0

        # 5. Update State
        self.last_price = price
        self.last_ts = ts

        # 6. Return Weighted Score
        return velocity * multiplier