import math
import time

# Simplified constants for the offline test
TARGET_STRIKE = 90000.0  # pretend open
MAX_SIZE = 10.0
MIN_SIZE = 1.0
SIZE_SIGMA = 50.0
VELOCITY_THRESHOLD = 25.0


def calculate_size(price: float) -> float:
    dist = abs(price - TARGET_STRIKE)
    size = MAX_SIZE * math.exp(-(dist**2) / (2 * SIZE_SIGMA**2))
    return max(MIN_SIZE, size)


class MockState:
    def __init__(self):
        self.prices = []  # (timestamp, price) tuples

    def update(self, price: float, timestamp: float) -> None:
        self.prices.append((timestamp, price))

    def get_velocity(self, window_s: float = 1.0) -> float:
        if len(self.prices) < 2:
            return 0.0
        now = self.prices[-1][0]
        oldest_t, oldest_p = self.prices[0]
        for t, p in reversed(self.prices):
            if now - t <= window_s:
                oldest_t, oldest_p = t, p
            else:
                break
        newest_t, newest_p = self.prices[-1]
        dt = newest_t - oldest_t
        if dt <= 0:
            return 0.0
        return (newest_p - oldest_p) / dt


def run_tests():
    print("🧪 STARTING ENGINE DIAGNOSTICS...\n")

    # TEST 1: SIZING LOGIC
    print("🔹 TEST 1: Dynamic Sizing Check")
    scenarios = [
        (90000.0, "At The Money (Perfect)"),
        (90050.0, "Edge of Zone ($50 away)"),
        (90100.0, "Far Away ($100 away)"),
        (95000.0, "Moon ($5000 away)"),
    ]

    for price, desc in scenarios:
        size = calculate_size(price)
        print(f"   Price: ${price:,.0f} ({desc}) -> Size: {size:.2f}")

    # TEST 2: VELOCITY TRIGGER
    print("\n🔹 TEST 2: Velocity Trigger Check")
    state = MockState()
    start_time = 1000.0

    print("   [T+0s] Price $90,000 (Flat)")
    state.update(90000.0, start_time)

    print("   [T+2s] Price $90,010 (Slow Drift)")
    state.update(90010.0, start_time + 2.0)
    vel = state.get_velocity()
    print(f"      Velocity: {vel:.2f}/s (Trigger? {'✅ YES' if vel > VELOCITY_THRESHOLD else '❌ NO'})")

    print("   [T+2.5s] Price $90,050 (MOON!)")
    state.update(90050.0, start_time + 2.5)
    vel = state.get_velocity()
    print(f"      Velocity: {vel:.2f}/s (Trigger? {'✅ YES' if vel > VELOCITY_THRESHOLD else '❌ NO'})")


if __name__ == "__main__":
    run_tests()
