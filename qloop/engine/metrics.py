from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import psutil


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    k = (len(values) - 1) * pct
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return values[int(k)]
    d0 = values[f] * (c - k)
    d1 = values[c] * (k - f)
    return d0 + d1


@dataclass
class Metrics:
    decision_ns: List[int] = field(default_factory=list)
    e2e_ns: List[int] = field(default_factory=list)
    drops_total: int = 0
    queue_depth_max: int = 0
    exposure_blocks_total: int = 0
    exposure_block_reasons: Dict[str, int] = field(default_factory=dict)
    # per-symbol metrics
    decision_ns_by_sym: Dict[str, List[int]] = field(default_factory=dict)
    e2e_ns_by_sym: Dict[str, List[int]] = field(default_factory=dict)
    processed_by_sym: Dict[str, int] = field(default_factory=dict)
    trades_by_sym: Dict[str, int] = field(default_factory=dict)
    exposure_blocks_by_sym: Dict[str, int] = field(default_factory=dict)
    last_reason_by_sym: Dict[str, str] = field(default_factory=dict)
    processed: int = 0
    cpu_percent: float = 0.0
    rss_mb: float = 0.0
    elapsed_s: float = 0.0
    # queue depth timeseries: list of [t_s, depth]
    queue_depth_series: List[Tuple[float, int]] = field(default_factory=list)
    burst_window: Dict[str, float] = field(default_factory=dict)
    # idempotency violations count
    idempotency_violations: int = 0

    def sample(self, decision_ns: int, e2e_ns: int, symbol: str | None = None) -> None:
        """Record a timing sample. If symbol provided, also record per-symbol."""
        self.decision_ns.append(decision_ns)
        self.e2e_ns.append(e2e_ns)
        if symbol:
            self.decision_ns_by_sym.setdefault(symbol, []).append(decision_ns)
            self.e2e_ns_by_sym.setdefault(symbol, []).append(e2e_ns)
            self.processed_by_sym[symbol] = self.processed_by_sym.get(symbol, 0) + 1

    def drop(self) -> None:
        self.drops_total += 1

    def exposure_block(self, reason: str, symbol: str | None = None) -> None:
        self.exposure_blocks_total += 1
        self.exposure_block_reasons[reason] = self.exposure_block_reasons.get(reason, 0) + 1
        if symbol:
            self.exposure_blocks_by_sym[symbol] = self.exposure_blocks_by_sym.get(symbol, 0) + 1
            self.last_reason_by_sym[symbol] = reason

    def set_runtime(self, processed: int, queue_depth_max: int) -> None:
        self.processed = processed
        self.queue_depth_max = queue_depth_max
        p = psutil.Process()
        with p.oneshot():
            self.cpu_percent = psutil.cpu_percent(interval=None)
            self.rss_mb = p.memory_info().rss / (1024 * 1024)

    def record_queue_depth(self, t_s: float, depth: int, cap: int = 200) -> None:
        self.queue_depth_series.append((t_s, depth))
        if len(self.queue_depth_series) > cap:
            # drop oldest
            self.queue_depth_series.pop(0)

    def set_elapsed(self, elapsed_s: float) -> None:
        self.elapsed_s = elapsed_s

    def to_payload(self) -> Dict:
        dec_sorted = sorted(self.decision_ns)
        e2e_sorted = sorted(self.e2e_ns)
        p50 = _percentile(dec_sorted, 0.50) / 1e6
        p95 = _percentile(dec_sorted, 0.95) / 1e6
        p99 = _percentile(dec_sorted, 0.99) / 1e6
        e2e_p95 = _percentile(e2e_sorted, 0.95) / 1e6

        jitter_ratio = (p99 / p50) if p50 > 0 else 0.0
        duration_s = max(len(self.decision_ns), 1) / max(self.processed, 1)  # placeholder
        # Throughput (events/sec) approximated by processed / elapsed decisions (demo)
        eps = float(self.processed) / max(self.elapsed_s, 1e-9)
        # latency histogram (20 bins up to p99)
        hist = {"bins_ms": [], "counts": []}
        try:
            if dec_sorted:
                upper = _percentile(dec_sorted, 0.99) / 1e6
                upper = max(upper, 1.0)
                bins = 20
                bin_width = upper / bins
                counts = [0] * bins
                for v in dec_sorted:
                    ms = v / 1e6
                    idx = min(bins - 1, int(ms / bin_width))
                    counts[idx] += 1
                edges = [round((i + 1) * bin_width, 3) for i in range(bins)]
                hist = {"bins_ms": edges, "counts": counts}
        except Exception:
            hist = {"bins_ms": [], "counts": []}
        # per-symbol summary
        per_symbol: Dict[str, Dict] = {}
        for sym, lst in self.decision_ns_by_sym.items():
            s_sorted = sorted(lst)
            p95_sym = _percentile(s_sorted, 0.95) / 1e6 if s_sorted else 0.0
            per_symbol[sym] = {
                "processed": self.processed_by_sym.get(sym, 0),
                "latency_p95": p95_sym,
                "trades": self.trades_by_sym.get(sym, 0),
                "exposure_blocks": self.exposure_blocks_by_sym.get(sym, 0),
                "last_reason": self.last_reason_by_sym.get(sym, "-"),
            }

        return {
            "latency": {
                "decision_ms": {"p50": p50, "p95": p95, "p99": p99, "max": (max(dec_sorted) / 1e6) if dec_sorted else 0.0},
                "e2e_ms": {"p95": e2e_p95},
                "jitter_ratio": jitter_ratio,
                "histogram": hist,
            },
            "throughput": {"eps": eps},
            "reliability": {
                "drops": self.drops_total,
                "idempotency_violations": 0,
                "error_rate": 0.0,
                "exposure_blocks": self.exposure_blocks_total,
                "exposure_block_reasons": self.exposure_block_reasons,
            },
            "resources": {
                "cpu_percent": self.cpu_percent,
                "rss_mb": self.rss_mb,
                "queue_depth_max": self.queue_depth_max,
                "queue_depth_series": [[round(t, 3), d] for t, d in self.queue_depth_series],
            },
            "burst_window": self.burst_window or {},
            "processed": self.processed,
            "elapsed_s": self.elapsed_s,
            "per_symbol": per_symbol,
        }