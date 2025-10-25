# QuantLoop: Real‑Time Strategy Runner

A self-contained, deterministic demo of a real‑time quant trading loop with a laptop‑friendly benchmark and HTML report. Includes fixtures for CRUS, DDOG, QRVO, and COP.

Why this is interview‑ready
- Offline, seeded, reproducible
- Tail latency (p95/p99), throughput, jitter, drops, queue depth, error rate
- Safety gates: idempotency violations (expected 0), exposure caps with reasons
- Determinism badge (seed + fixture hash + code hash)

Quickstart
```bash
# Zero-config: run the default demo and open the report
python -m qloop

# Create a venv and install
python -m venv .venv && source .venv/bin/activate
pip install -U pip
pip install -e .

# Run the demo (generates an HTML report and opens it)
qloop demo --report-dir out

Determinism / baseline (fixing a FAIL)
- The report shows a determinism badge calculated from the tuple: seed + fixture_hash + code_hash.
- If the badge reads FAIL it's because no baseline is present or the saved baseline differs from the current run.
- To set the baseline to the current code+fixtures+seed run (so future runs compare against it):
  - qloop baseline-save --report-dir out
- To run a 3-run determinism check against the saved baseline (will write determinism_result.json):
  - qloop baseline-check --report-dir out --duration 10
- Shortcut: the demo command's --baseline flag saves a baseline then runs a quick 3-run check:
  - qloop demo --report-dir out --baseline
    - opens only the final updated report; determinism PASS/FAIL is written back to `out/report.html`
    - add `--no-open` to skip launching a browser when running headless

# Or run the engine only, 30s, fixed seed
qloop run --fixtures fixtures/minute_bars.csv --duration 30 --seed 7 --report-dir out
```

What to show in 20–30 seconds
- Terminal: call out the seed, fixture hash, code hash printed at start.
- Browser: the HTML report opens automatically with:
  - Topline: p95 decision latency, throughput, drops, CPU%, memory, determinism PASS
  - Latency histogram with p50/p95/p99 markers
  - Queue depth timeline (includes a short synthetic burst)
  - Per-symbol table (CRUS/DDOG/QRVO/COP) with last‑trade “reason”

  What these metrics mean
  -----------------------
  - p50/p95/p99 decision latency: how long the strategy took to make decisions (lower is better).
  - e2e p95: end-to-end latency from event ingestion to acknowledgement.
  - throughput (eps): events processed per run (higher indicates more work done).
  - jitter_ratio: p99/p50, shows tail dispersion.
  - drops: events dropped due to queue/backpressure.
  - exposure_blocks: safety gate activations that prevented positions from exceeding caps.
  - idempotency_violations: repeated side-effects (expected 0 in demo).
  - CPU% / RSS: process resource usage snapshot at the end of the run.


Measured metrics
- Performance: decision_latency_ms p50/p95/p99/max, e2e_latency_ms p95, throughput (eps), jitter_ratio
- Reliability/safety: drop_rate, idempotency_violations, error_rate, exposure_blocks (count + reason)
- Resources: CPU%, RSS, queue_depth_max, backpressure_activations
- Determinism: seed, fixture_hash, code_hash; baseline drift=0

License: MIT