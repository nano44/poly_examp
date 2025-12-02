import argparse
import math
from typing import Optional


def calculate_transmission_coefficient(
    spot_price: float,
    strike_price: float,
    time_to_expiry_sec: float,
    annual_volatility: float,
) -> float:
    """
    Calculates the "Gear Ratio": how much the contract should move per $1 spot move.
    """
    if time_to_expiry_sec < 1:
        return 0.0

    t_years = time_to_expiry_sec / 31_536_000  # seconds per year
    std_dev_move = spot_price * annual_volatility * math.sqrt(t_years)
    if std_dev_move == 0:
        return 0.0

    z_score = (spot_price - strike_price) / std_dev_move
    pdf_height = math.exp(-0.5 * z_score**2) / math.sqrt(2 * math.pi)
    return pdf_height / std_dev_move


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Compute transmission coefficient (gear ratio).")
    parser.add_argument("--spot", type=float, required=True, help="Current spot price")
    parser.add_argument("--strike", type=float, required=True, help="Strike price")
    parser.add_argument("--expiry-sec", type=float, required=True, help="Seconds to expiry")
    parser.add_argument("--vol", type=float, required=True, help="Annualized volatility (e.g., 0.8 for 80%)")
    args = parser.parse_args()

    result = calculate_transmission_coefficient(
        spot_price=args.spot,
        strike_price=args.strike,
        time_to_expiry_sec=args.expiry_sec,
        annual_volatility=args.vol,
    )
    print(f"Transmission Coefficient: {result:.6f}")


if __name__ == "__main__":
    _cli()
