from __future__ import annotations

import hashlib
import json
import os
import time
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Optional

import click
import psutil

from qloop.engine.core import Engine, EngineConfig
from qloop.engine.metrics import Metrics
from qloop.report.report import render_report
from qloop.util.hashing import hash_file, hash_code


def _write_metrics(report_dir: Path, metrics: Metrics, seed: int, fixtures: Path) -> Dict:
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = metrics.to_payload()
    payload["seed"] = seed
    payload["fixture_hash"] = hash_file(fixtures) if fixtures.exists() else "n/a"
    payload["code_hash"] = hash_code()
    # determinism key (to be set by baseline check command)
    payload["determinism_ok"] = False

    # embed capped raw decision samples (ms) to improve client-side histogram rendering
    try:
        cap = 2000
        raw = [d / 1e6 for d in metrics.decision_ns]
        if len(raw) > cap:
            # sample down uniformly
            step = max(1, len(raw) // cap)
            raw = raw[::step][:cap]
        payload["_raw_decision_samples"] = raw
    except Exception:
        payload["_raw_decision_samples"] = []

    (report_dir / "metrics.json").write_text(json.dumps(payload, indent=2))
    # simple CSV (metric, value)
    csv_lines = ["metric,value"]
    def flatten(prefix: str, obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                yield from flatten(f"{prefix}.{k}" if prefix else k, v)
        else:
            yield (prefix, obj)

    for k, v in flatten("", payload):
        # sanitize
        csv_lines.append(f"{k},{str(v).replace(',', '')}")
    (report_dir / "metrics.csv").write_text("\n".join(csv_lines))

    # run fingerprint
    fp = f"{seed}:{payload['fixture_hash']}:{payload['code_hash']}"
    (report_dir / "run_fingerprint.txt").write_text(fp + "\n")

    return payload


@click.group(help="QuantLoop: Real-Time Strategy Runner (deterministic demo)")
def cli() -> None:
    pass


@cli.command(help="Run the engine on fixtures for a duration (seconds) and write metrics + HTML report.")
@click.option("--fixtures", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default=Path("fixtures/minute_bars.csv"))
@click.option("--duration", type=int, default=30, show_default=True)
@click.option("--seed", type=int, default=7, show_default=True)
@click.option("--report-dir", type=click.Path(file_okay=False, path_type=Path), default=Path("out"))
@click.option("--open/--no-open", default=True, show_default=True, help="Open report in browser")
def run(fixtures: Path, duration: int, seed: int, report_dir: Path, open: bool) -> None:
    cfg = EngineConfig(seed=seed, duration_s=duration, fixtures=fixtures)
    eng = Engine(cfg)
    metrics = eng.run()

    payload = _write_metrics(report_dir, metrics, seed, fixtures)
    html_path = render_report(payload, report_dir / "report.html")
    click.echo(f"[qloop] report: {html_path}")

    if open:
        webbrowser.open(f"file://{html_path}")


@cli.command(help="Convenience demo: short run with defaults and report.")
@click.option("--report-dir", type=click.Path(file_okay=False, path_type=Path), default=Path("out"))
def demo(report_dir: Path) -> None:
    run.callback(Path("fixtures/minute_bars.csv"), 20, 7, report_dir, True)  # type: ignore


@cli.command(help="Save baseline fingerprint for determinism comparisons.")
@click.option("--report-dir", type=click.Path(file_okay=False, path_type=Path), default=Path("out"))
@click.option("--fixtures", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default=Path("fixtures/minute_bars.csv"))
@click.option("--seed", type=int, default=7)
def baseline_save(report_dir: Path, fixtures: Path, seed: int) -> None:
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    fp = f"{seed}:{hash_file(fixtures)}:{hash_code()}"
    (report_dir / "baseline.txt").write_text(fp + "\n")
    click.echo(f"baseline saved: {fp}")


@cli.command(help="Run engine 3x and compare fingerprints against saved baseline (determinism check).")
@click.option("--report-dir", type=click.Path(file_okay=False, path_type=Path), default=Path("out"))
@click.option("--fixtures", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default=Path("fixtures/minute_bars.csv"))
@click.option("--duration", type=int, default=10)
@click.option("--seed", type=int, default=7)
def baseline_check(report_dir: Path, fixtures: Path, duration: int, seed: int) -> None:
    report_dir = Path(report_dir)
    basef = report_dir / "baseline.txt"
    if not basef.exists():
        click.echo(f"no baseline found at {basef}; create one with 'qloop baseline-save --report-dir {report_dir}'")
        raise SystemExit(2)

    baseline = basef.read_text().strip()
    fprints = []
    ok = True
    # run 3 times
    for i in range(1, 4):
        click.echo(f"run {i}/3")
        cfg = EngineConfig(seed=seed, duration_s=duration, fixtures=fixtures)
        eng = Engine(cfg)
        metrics = eng.run()
        # write artifacts per-run
        run_dir = report_dir / f"run_{i}"
        payload = _write_metrics(run_dir, metrics, seed, fixtures)
        fp = f"{seed}:{payload['fixture_hash']}:{payload['code_hash']}"
        fprints.append(fp)
        if fp != baseline:
            ok = False

    summary = {"baseline": baseline, "fingerprints": fprints, "pass": ok}
    (report_dir / "determinism_result.json").write_text(json.dumps(summary, indent=2))
    click.echo("DETERMINISM PASS" if ok else "DETERMINISM FAIL")
    # write a top-level report for the last run with determinism flag set
    last_run_dir = report_dir / f"run_3"
    payload = json.loads((last_run_dir / "metrics.json").read_text())
    payload["determinism_ok"] = ok
    (last_run_dir / "metrics.json").write_text(json.dumps(payload, indent=2))
    html_path = render_report(payload, last_run_dir / "report.html")
    click.echo(f"report for last run: {html_path}")
    if True:
        webbrowser.open(f"file://{html_path}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()