"""Run-wide settings: date window, base volumes and the scale knob."""
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Config:
    """Every generator reads its sizes and dates from one of these."""

    scale: float = 1.0
    seed: int = 20261110
    history_start: pd.Timestamp = pd.Timestamp("2025-01-01")
    history_end: pd.Timestamp = pd.Timestamp("2026-09-30")
    increment_end: pd.Timestamp = pd.Timestamp("2026-10-30")
    clickstream_start: pd.Timestamp = pd.Timestamp("2026-01-01")

    base_customers: int = 60_000
    base_products: int = 5_000
    base_stores: int = 40
    base_suppliers: int = 40
    base_web_orders_per_day: float = 600.0
    base_pos_txns_per_day: float = 600.0
    base_tracked_skus: int = 400

    retailer_name: str = "Larchwood Supply Co."
    employee_domain: str = "larchwood-supply.com"

    def scaled(self, base: float, minimum: int) -> int:
        """Scale a base count, never going below a floor that keeps the model coherent."""
        return max(minimum, int(round(base * self.scale)))

    @property
    def n_customers(self) -> int:
        return self.scaled(self.base_customers, 400)

    @property
    def n_products(self) -> int:
        return self.scaled(self.base_products, 200)

    @property
    def n_stores(self) -> int:
        return self.scaled(self.base_stores, 6)

    @property
    def n_suppliers(self) -> int:
        return self.scaled(self.base_suppliers, 8)

    @property
    def web_orders_per_day(self) -> float:
        return max(4.0, self.base_web_orders_per_day * self.scale)

    @property
    def pos_txns_per_day(self) -> float:
        return max(4.0, self.base_pos_txns_per_day * self.scale)

    @property
    def n_tracked_skus(self) -> int:
        return self.scaled(self.base_tracked_skus, 20)

    @property
    def increment_days(self) -> pd.DatetimeIndex:
        return pd.date_range(self.history_end + pd.Timedelta(days=1), self.increment_end, freq="D")

    def increment_day(self, n: int) -> pd.Timestamp:
        """The n-th increment day, 1-based (day 1 = 2026-10-01)."""
        return self.history_end + pd.Timedelta(days=n)

    def count(self, base: float, minimum: int = 1) -> int:
        """Scale a defect count (how many rows to corrupt)."""
        return self.scaled(base, minimum)
