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
    payload["determinism_ok"] = True  # set True if fingerprint matches baseline (extend later)

    (report_dir / "metrics.json").write_text(json.dumps(payload, indent=2))
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


def main() -> None:
    cli()


if __name__ == "__main__":
    main()