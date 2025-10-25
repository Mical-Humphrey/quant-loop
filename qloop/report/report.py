from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from jinja2 import Environment, PackageLoader, select_autoescape, FileSystemLoader


def _env(template_dir: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
        enable_async=False,
    )


def render_report(payload: Dict, out_path: Path) -> Path:
    template_dir = Path(__file__).parent
    env = _env(template_dir)
    tpl = env.get_template("template.html")
    html = tpl.render(metrics=payload)
    out_path.write_text(html, encoding="utf-8")
    return out_path