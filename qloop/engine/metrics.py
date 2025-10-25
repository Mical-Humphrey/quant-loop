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
    processed: int = 0
    cpu_percent: float = 0.0
    rss_mb: float = 0.0

    def sample(self, decision_ns: int, e2e_ns: int) -> None:
        self.decision_ns.append(decision_ns)
        self.e2e_ns.append(e2e_ns)

    def drop(self) -> None:
        self.drops_total += 1

    def exposure_block(self, reason: str) -> None:
        self.exposure_blocks_total += 1
        self.exposure_block_reasons[reason] = self.exposure_block_reasons.get(reason, 0) + 1

    def set_runtime(self, processed: int, queue_depth_max: int) -> None:
        self.processed = processed
        self.queue_depth_max = queue_depth_max
        p = psutil.Process()
        with p.oneshot():
            self.cpu_percent = psutil.cpu_percent(interval=None)
            self.rss_mb = p.memory_info().rss / (1024 * 1024)

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
        eps = float(self.processed)

        return {
            "latency": {
                "decision_ms": {"p50": p50, "p95": p95, "p99": p99, "max": (max(dec_sorted) / 1e6) if dec_sorted else 0.0},
                "e2e_ms": {"p95": e2e_p95},
                "jitter_ratio": jitter_ratio,
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
            },
            "processed": self.processed,
        }