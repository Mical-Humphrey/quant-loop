from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class Bar:
    ts: str
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float


def load_minute_bars(path: Path) -> Iterable[Bar]:
    with path.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            yield Bar(
                ts=row["ts"],
                symbol=row["symbol"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )