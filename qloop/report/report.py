from __future__ import annotations

import json
from pathlib import Path
from typing import Dict


def _flatten_metrics(payload: Dict) -> Dict[str, str]:
    out: Dict[str, str] = {}

    def walk(prefix: str, obj) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(f"{prefix}.{k}" if prefix else k, v)
        else:
            out[prefix] = str(obj)

    walk("", payload)
    return out


def render_report(payload: Dict, out_path: Path) -> Path:
    """Render a single-file HTML report and write CSV + fingerprint.

    Returns the path to the generated HTML file.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # write metrics.csv (simple key,value rows)
    csv_lines = ["metric,value"]
    flat = _flatten_metrics(payload)
    for k, v in sorted(flat.items()):
        # sanitize commas
        v_safe = v.replace(",", "")
        csv_lines.append(f"{k},{v_safe}")
    (out_path.parent / "metrics.csv").write_text("\n".join(csv_lines), encoding="utf-8")

    # write run_fingerprint.txt
    seed = payload.get("seed", "n/a")
    fh = payload.get("fixture_hash", "n/a")
    ch = payload.get("code_hash", "n/a")
    (out_path.parent / "run_fingerprint.txt").write_text(f"{seed}:{fh}:{ch}\n", encoding="utf-8")

    # Render HTML by embedding the payload JSON and a small JS renderer.
    html = _template().replace("__EMBED_PAYLOAD__", json.dumps(payload))
    out_path.write_text(html, encoding="utf-8")
    return out_path


def _template() -> str:
    # Minimal single-file report: topcards, simple histogram and table
    return (
        """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>QuantLoop Report</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; margin: 20px; color:#111 }
    .cards { display:flex; gap:12px; margin-bottom:18px }
    .card { padding:12px 16px; border-radius:8px; background:#f6f6f8; min-width:160px }
    .grid { display:grid; grid-template-columns: 1fr 1fr; gap:18px }
    canvas { background: #fff; border:1px solid #eee; width:100%; height:200px }
    table { width:100%; border-collapse: collapse }
    th,td { text-align:left; padding:6px; border-bottom:1px solid #eee }
    .muted { color:#666; font-size:0.9em }
  </style>
</head>
<body>
  <h2>QuantLoop Report</h2>
  <div class="cards" id="topcards"></div>
  <div class="grid">
    <div>
      <h3>Latency histogram (ms)</h3>
      <canvas id="hist"></canvas>
      <div class="muted">p50 / p95 / p99 markers shown</div>
    </div>
    <div>
      <h3>Per-symbol summary</h3>
      <div id="symtable"></div>
    </div>
  </div>

  <script>
    const payload = __EMBED_PAYLOAD__;

    function mkCard(title, val, sub) {
      const d = document.createElement('div'); d.className='card';
      d.innerHTML = `<div style="font-size:0.9em;color:#444">${title}</div><div style="font-size:1.2em;font-weight:600">${val}</div>${sub?'<div class="muted">'+sub+'</div>':''}`;
      return d;
    }

    const tc = document.getElementById('topcards');
    tc.appendChild(mkCard('p95 decision latency (ms)', payload.latency.decision_ms.p95));
    tc.appendChild(mkCard('throughput (eps)', payload.throughput.eps));
    tc.appendChild(mkCard('drops', payload.reliability.drops));
    tc.appendChild(mkCard('CPU %', payload.resources.cpu_percent, 'RSS MB: '+payload.resources.rss_mb));
    tc.appendChild(mkCard('Determinism', payload.determinism_ok ? 'PASS' : 'FAIL'));

    // Histogram (very simple)
    const canvas = document.getElementById('hist');
    const ctx = canvas.getContext('2d');
    canvas.width = canvas.clientWidth; canvas.height = canvas.clientHeight;

    // Reconstruct decision samples from flattened payload if available
    const dec = payload._raw_decision_samples || [];
    // If raw not available, synthesize small distribution from p50/p95/p99
    let samples = dec.length ? dec : [payload.latency.decision_ms.p50, payload.latency.decision_ms.p95, payload.latency.decision_ms.p99];
    const maxv = Math.max(...samples, 1);
    const bins = 20; const hist = new Array(bins).fill(0);
    samples.forEach(v=>{ const i = Math.min(bins-1, Math.floor(v/maxv*bins)); hist[i]++ });
    const bw = canvas.width / bins;
    hist.forEach((h,i)=>{ const hh = h / Math.max(...hist) * canvas.height; ctx.fillStyle='#7eaaf3'; ctx.fillRect(i*bw, canvas.height-hh, bw-2, hh) });
    // markers
    const drawMarker = (x, label) => { ctx.fillStyle='red'; ctx.fillRect(x-1,0,2,canvas.height); ctx.fillStyle='red'; ctx.fillText(label,x+4,12) };
    const p50 = payload.latency.decision_ms.p50 || 0; const p95 = payload.latency.decision_ms.p95 || 0; const p99 = payload.latency.decision_ms.p99 || 0;
    [p50,p95,p99].forEach((v,idx)=>{ const x = Math.floor((v/maxv)*canvas.width); drawMarker(x, ['p50','p95','p99'][idx]) });

    // Per-symbol table: try to read from payload.per_symbol else show summary
    const tableDiv = document.getElementById('symtable');
    const tbl = document.createElement('table');
    const header = document.createElement('tr'); header.innerHTML='<th>symbol</th><th>processed</th><th>p95 ms</th><th>trades</th><th>exposure_blocks</th><th>last_reason</th>'; tbl.appendChild(header);
    const syms = payload.per_symbol || {};
    if (Object.keys(syms).length === 0) {
      // fallback: show zeros for known symbols
      ['CRUS','DDOG','QRVO','COP'].forEach(s=>{ const r = document.createElement('tr'); r.innerHTML=`<td>${s}</td><td>${payload.processed||0}</td><td>${payload.latency.decision_ms.p95}</td><td>0</td><td>${payload.reliability.exposure_blocks}</td><td>-</td>`; tbl.appendChild(r) });
    } else {
      Object.entries(syms).forEach(([sym,info])=>{ const r = document.createElement('tr'); r.innerHTML=`<td>${sym}</td><td>${info.processed||0}</td><td>${info.latency_p95||'-'}</td><td>${info.trades||0}</td><td>${info.exposure_blocks||0}</td><td>${info.last_reason||'-'}</td>`; tbl.appendChild(r) });
    }
    tableDiv.appendChild(tbl);
  </script>
</body>
</html>""")