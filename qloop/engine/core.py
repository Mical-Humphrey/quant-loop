from __future__ import annotations

import random
import time
from collections import deque, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, Dict, Iterable, List, Tuple

from qloop.engine.metrics import Metrics
from qloop.feeds.fixtures import load_minute_bars


@dataclass
class EngineConfig:
    seed: int
    duration_s: int
    fixtures: Path
    max_queue: int = 4096  # synthetic queue capacity
    burst_start_s: int = 8
    burst_len_s: int = 4
    burst_multiplier: int = 4  # temporarily multiply event rate


class Engine:
    def __init__(self, cfg: EngineConfig) -> None:
        self.cfg = cfg
        self.metrics = Metrics()
        random.seed(cfg.seed)

        # per-symbol rolling state for a toy mean-reversion
        self.windows: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=10))
        self.sums: Dict[str, float] = defaultdict(float)

        # simple exposure caps (demo)
        self.nav = 1_000_000.0
        self.per_asset_cap = 0.05  # 5% NAV per asset
        self.positions: Dict[str, float] = defaultdict(float)  # notional exposure

    def _update_roll(self, sym: str, px: float) -> float:
        w = self.windows[sym]
        if len(w) == w.maxlen:
            self.sums[sym] -= w[0]
        w.append(px)
        self.sums[sym] += px
        ma = self.sums[sym] / len(w)
        return ma

    def _risk_gate(self, sym: str, notional: float) -> Tuple[bool, str]:
        # Block if per-asset notional exceeds cap
        cap = self.nav * self.per_asset_cap
        if abs(self.positions[sym] + notional) > cap:
            return False, "EXPOSURE_CAP"
        return True, "OK"

    def run(self) -> Metrics:
        # Preload fixtures to a list for deterministic replay
        events = list(load_minute_bars(self.cfg.fixtures))
        start = time.perf_counter_ns()
        end_time = start + self.cfg.duration_s * 1_000_000_000
        idx = 0
        qdepth = 0
        processed = 0
        first_processed_ns: int | None = None
        last_processed_ns: int | None = None
        # idempotency tracking
        seen_order_ids: set[str] = set()

        # expose burst window info to metrics for reporting
        self.metrics.burst_window = {
            "start_s": float(self.cfg.burst_start_s),
            "end_s": float(self.cfg.burst_start_s + self.cfg.burst_len_s),
        }

        # sampling cadence for queue depth (50 ms)
        sample_interval_ns = 50_000_000
        next_sample_ns = start + sample_interval_ns

        while time.perf_counter_ns() < end_time:
            # Synthetic burst window
            multiplier = self.cfg.burst_multiplier if (
                (time.perf_counter_ns() - start) / 1e9 >= self.cfg.burst_start_s
                and (time.perf_counter_ns() - start) / 1e9 < (self.cfg.burst_start_s + self.cfg.burst_len_s)
            ) else 1

            for _ in range(multiplier):
                evt = events[idx % len(events)]
                idx += 1

                # Queue/backpressure simulation
                if qdepth >= self.cfg.max_queue:
                    self.metrics.drop()
                    continue
                qdepth += 1

                t0 = time.perf_counter_ns()
                # Toy strategy: z-score-like signal
                ma = self._update_roll(evt.symbol, evt.close)
                diff = evt.close - ma if len(self.windows[evt.symbol]) >= 5 else 0.0
                signal = -1.0 if diff > 0 else (1.0 if diff < 0 else 0.0)
                notional = 1000.0 * signal  # constant notional per decision

                ok, reason = self._risk_gate(evt.symbol, notional)
                # deterministic order id for idempotency checks
                try:
                    import hashlib

                    oid_src = f"{self.cfg.seed}:{evt.symbol}:{evt.ts}:{int(signal)}"
                    oid = hashlib.sha256(oid_src.encode("utf-8")).hexdigest()[:16]
                except Exception:
                    oid = f"{evt.symbol}:{evt.ts}:{int(signal)}"

                # detect duplicates
                if oid in seen_order_ids:
                    self.metrics.idempotency_violations += 1
                else:
                    seen_order_ids.add(oid)
                if not ok:
                    self.metrics.exposure_block(reason)
                    # record per-symbol exposure block
                    self.metrics.exposure_block(reason, symbol=evt.symbol)
                    # no position change
                else:
                    # update exposure position
                    self.positions[evt.symbol] += notional
                    # count a trade for demo purposes
                    if signal != 0.0:
                        self.metrics.trades_by_sym[evt.symbol] = self.metrics.trades_by_sym.get(evt.symbol, 0) + 1

                t1 = time.perf_counter_ns()
                # pass symbol to get per-symbol timings
                self.metrics.sample(decision_ns=t1 - t0, e2e_ns=(t1 - t0), symbol=evt.symbol)  # ack is same in demo
                processed += 1
                if first_processed_ns is None:
                    first_processed_ns = t1
                last_processed_ns = t1
                qdepth = max(0, qdepth - 1)

                # sample queue depth on interval
                now_ns = time.perf_counter_ns()
                if now_ns >= next_sample_ns:
                    rel_s = (now_ns - start) / 1e9
                    self.metrics.record_queue_depth(rel_s, qdepth)
                    next_sample_ns += sample_interval_ns
        # finalize elapsed (use first/last processed timestamps if available)
        if first_processed_ns and last_processed_ns and last_processed_ns >= first_processed_ns:
            elapsed = (last_processed_ns - first_processed_ns) / 1e9
            self.metrics.set_elapsed(elapsed)

        self.metrics.set_runtime(processed=processed, queue_depth_max=self.cfg.max_queue)
        return self.metrics