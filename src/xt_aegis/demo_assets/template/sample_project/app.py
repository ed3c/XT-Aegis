"""Small legacy module used by the deterministic refactor demo."""


def calculate_tax(amount: float) -> float:
    if amount < 0:
        raise ValueError("Amount cannot be negative")
    return round(amount * 0.05, 2)
