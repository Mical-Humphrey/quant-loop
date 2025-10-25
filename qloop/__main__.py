from __future__ import annotations

from pathlib import Path

from qloop.cli import run_engine_once


def main() -> None:
    """Run the default QuantLoop demo with zero configuration."""
    report_dir = Path("out")
    fixtures = Path("fixtures/minute_bars.csv")
    seed = 7
    duration = 20

    payload, html_path = run_engine_once(report_dir, fixtures, duration, seed, open_browser=True)
    fingerprint = f"{seed}:{payload.get('fixture_hash')}:{payload.get('code_hash')}"

    print("[qloop] default demo complete")
    print(f"[qloop] seed={seed} fixture_hash={payload.get('fixture_hash')} code_hash={payload.get('code_hash')}")
    print(f"[qloop] run_fingerprint={fingerprint}")
    print(f"[qloop] report={html_path.resolve()}")
    print("[qloop] tip: run 'qloop demo --baseline' to record a baseline and mark determinism PASS")


if __name__ == "__main__":
    main()
