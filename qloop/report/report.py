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
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; margin: 12px; color:#111 }
    .cards { display:flex; gap:10px; margin-bottom:12px; flex-wrap:wrap }
    .card { padding:10px 12px; border-radius:8px; background:#f6f6f8; min-width:120px; flex:1 1 140px }
    .grid { display:grid; grid-template-columns: 1fr 1fr; gap:12px }
    canvas { background: #fff; border:1px solid #eee; width:100% }
    canvas#hist { height:180px }
    canvas#qdepth { height:80px }
    table { width:100%; border-collapse: collapse; font-size:0.95rem }
    th,td { text-align:left; padding:6px; border-bottom:1px solid #eee }
    .muted { color:#666; font-size:0.85em }
    /* compact sparklines */
    canvas.spark { width:120px; height:24px }

    @media (max-width: 900px) {
      .grid { grid-template-columns: 1fr }
      canvas#hist { height:140px }
      canvas#qdepth { height:60px }
      .card { min-width:100px; padding:8px }
      th,td { font-size:0.82rem; padding:4px }
      body { margin:10px }
    }
  </style>
</head>
<body>
  <h2>QuantLoop Report</h2>
  <div class="cards" id="topcards"></div>
  <div class="grid">
    <div>
      <h3>Latency histogram (ms)</h3>
      <canvas id="hist"></canvas>
      <h4 style="margin-top:8px">Queue depth timeline</h4>
      <canvas id="qdepth" style="height:80px"></canvas>
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
  tc.appendChild(mkCard('p99/p50 (jitter ratio)', payload.latency.jitter_ratio));
  tc.appendChild(mkCard('drops', payload.reliability.drops));
  tc.appendChild(mkCard('exposure_blocks', payload.reliability.exposure_blocks));
  tc.appendChild(mkCard('idempotency_violations', payload.reliability.idempotency_violations || 0));
  tc.appendChild(mkCard('CPU %', payload.resources.cpu_percent, 'RSS MB: '+payload.resources.rss_mb));
  tc.appendChild(mkCard('Determinism', payload.determinism_ok ? 'PASS' : 'FAIL'));

    // Responsive drawing helpers
    function drawHistogram() {
      const canvas = document.getElementById('hist');
      const ctx = canvas.getContext('2d');
      canvas.width = canvas.clientWidth; canvas.height = canvas.clientHeight;
      ctx.clearRect(0,0,canvas.width,canvas.height);
      const histData = payload.latency.histogram || {bins_ms: [], counts: []};
      if (histData && histData.bins_ms && histData.counts && histData.counts.length > 0) {
        const counts = histData.counts;
        const maxCount = Math.max(...counts, 1);
        const bw = canvas.width / counts.length;
        counts.forEach((c, i) => {
          const hh = (c / maxCount) * canvas.height;
          ctx.fillStyle = '#7eaaf3';
          ctx.fillRect(i * bw, canvas.height - hh, Math.max(2, bw - 3), hh);
        });
      } else {
        const dec = payload._raw_decision_samples || [];
        let samples = dec.length ? dec : [payload.latency.decision_ms.p50, payload.latency.decision_ms.p95, payload.latency.decision_ms.p99];
        const maxv = Math.max(...samples, 1);
        const bins = 20; const hist = new Array(bins).fill(0);
        samples.forEach(v=>{ const i = Math.min(bins-1, Math.floor(v/maxv*bins)); hist[i]++ });
        const bw = canvas.width / bins;
        const m = Math.max(...hist,1);
        hist.forEach((h,i)=>{ const hh = (h / m) * canvas.height; ctx.fillStyle='#7eaaf3'; ctx.fillRect(i*bw, canvas.height-hh, Math.max(2, bw-3), hh) });
      }
      // markers
      const p50 = payload.latency.decision_ms.p50 || 0; const p95 = payload.latency.decision_ms.p95 || 0; const p99 = payload.latency.decision_ms.p99 || 0;
      const maxx = (histData && histData.bins_ms && histData.bins_ms.length) ? histData.bins_ms[histData.bins_ms.length-1] : Math.max(p99,1);
      const drawMarker = (v, label) => { const x = Math.floor((v/maxx)*canvas.width); ctx.fillStyle='red'; ctx.fillRect(x-1,0,2,canvas.height); ctx.fillStyle='red'; ctx.fillText(label,x+4,12); };
      [p50,p95,p99].forEach((v,idx)=>{ drawMarker(v, ['p50','p95','p99'][idx]) });
    }

    function drawQDepth() {
      const qcanvas = document.getElementById('qdepth');
      const qctx = qcanvas.getContext('2d');
      qcanvas.width = qcanvas.clientWidth; qcanvas.height = qcanvas.clientHeight;
      qctx.clearRect(0,0,qcanvas.width,qcanvas.height);
      const qseries = (payload.resources && payload.resources.queue_depth_series) ? payload.resources.queue_depth_series : [];
      if (qseries.length > 0) {
        const times = qseries.map(p=>p[0]);
        const depths = qseries.map(p=>p[1]);
        const tmin = Math.min(...times);
        const tmax = Math.max(...times);
        const dmax = Math.max(...depths, 1);
        if (payload.burst_window && payload.burst_window.start_s !== undefined) {
          const bw0 = payload.burst_window.start_s;
          const bw1 = payload.burst_window.end_s;
          const x0 = ((bw0 - tmin) / Math.max(1e-6, (tmax - tmin))) * qcanvas.width;
          const x1 = ((bw1 - tmin) / Math.max(1e-6, (tmax - tmin))) * qcanvas.width;
          qctx.fillStyle = 'rgba(250,200,200,0.25)';
          qctx.fillRect(x0, 0, Math.max(1, x1 - x0), qcanvas.height);
        }
        qctx.beginPath(); qctx.strokeStyle = '#7eaaf3'; qctx.lineWidth = 2;
        qseries.forEach((p, i) => {
          const x = ((p[0] - tmin) / Math.max(1e-6, (tmax - tmin))) * qcanvas.width;
          const y = qcanvas.height - (p[1] / dmax) * qcanvas.height;
          if (i === 0) qctx.moveTo(x, y); else qctx.lineTo(x, y);
        });
        qctx.stroke();
      } else {
        qctx.fillStyle = '#f6f6f8'; qctx.fillRect(0,0,qcanvas.width,qcanvas.height);
        qctx.fillStyle='#666'; qctx.fillText('no queue data',10,14);
      }
    }

    // Per-symbol table: try to read from payload.per_symbol else show summary
  const tableDiv = document.getElementById('symtable');
  const tbl = document.createElement('table');
  const header = document.createElement('tr');
  header.innerHTML='<th>symbol</th><th>spark</th><th>processed</th><th>p95 ms</th><th>trades</th><th>exposure_blocks</th><th>last_reason</th>';
  tbl.appendChild(header);
    const syms = payload.per_symbol || {};
    if (Object.keys(syms).length === 0) {
      // fallback: show zeros for known symbols
      ['CRUS','DDOG','QRVO','COP'].forEach(s=>{ const id = 'spark-'+s.replace(/[^a-zA-Z0-9]/g,'_'); const r = document.createElement('tr'); r.innerHTML=`<td>${s}</td><td><canvas id="${id}" style="width:120px;height:24px"></canvas></td><td>${payload.processed||0}</td><td>${payload.latency.decision_ms.p95}</td><td>0</td><td>${payload.reliability.exposure_blocks}</td><td>-</td>`; tbl.appendChild(r) });
    } else {
      Object.entries(syms).forEach(([sym,info])=>{ const id = 'spark-'+sym.replace(/[^a-zA-Z0-9]/g,'_'); const r = document.createElement('tr'); r.innerHTML=`<td>${sym}</td><td><canvas id="${id}" style="width:120px;height:24px"></canvas></td><td>${info.processed||0}</td><td>${info.latency_p95||'-'}</td><td>${info.trades||0}</td><td>${info.exposure_blocks||0}</td><td>${info.last_reason||'-'}</td>`; tbl.appendChild(r) });
    }
    tableDiv.appendChild(tbl);

  // draw per-symbol sparklines if samples provided
    try {
      Object.keys(syms).forEach(sym=>{
        const info = syms[sym] || {};
        const samples = info.samples_ms || [];
        const cid = 'spark-'+sym.replace(/[^a-zA-Z0-9]/g,'_');
        const c = document.getElementById(cid);
        if (!c) return;
        const w = Math.max(80, c.clientWidth | 0);
        const h = 24;
        c.width = w; c.height = h;
        const ctx = c.getContext('2d');
        ctx.clearRect(0,0,w,h);
        if (!samples || samples.length === 0) {
          ctx.fillStyle = '#999'; ctx.fillText('-', 4, 14); return;
        }
        const maxv = Math.max(...samples, 1e-6);
        ctx.beginPath(); ctx.strokeStyle = '#6aa3d9'; ctx.lineWidth = 1.5;
        samples.forEach((v,i)=>{
          const x = (i/(samples.length-1 || 1)) * (w-4) + 2;
          const y = h - ((v / maxv) * (h-6)) - 2;
          if (i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
        });
        ctx.stroke();
        // draw p95 marker if available
        const p95 = info.latency_p95 || payload.latency.decision_ms.p95;
        if (p95) {
          const mx = Math.min(1, p95 / maxv);
          const px = Math.floor(mx * (w-4)) + 2;
          ctx.fillStyle = 'rgba(255,80,80,0.9)'; ctx.fillRect(px-1,2,2,h-4);
        }
      });
    } catch (e) {
      // non-fatal for rendering
      console.warn('sparkline draw failed', e);
    }

    // initial draw and redraw on resize (debounced)
    function redrawAll() { try { drawHistogram(); drawQDepth();
      // redraw sparklines by re-running same block
      try { Object.keys(syms).forEach(sym=>{ const id = 'spark-'+sym.replace(/[^a-zA-Z0-9]/g,'_'); const c = document.getElementById(id); if (!c) return; const samples = (syms[sym]||{}).samples_ms||[]; const w = Math.max(80, c.clientWidth|0); const h=24; c.width=w; c.height=h; const ctx = c.getContext('2d'); ctx.clearRect(0,0,w,h); if (!samples||samples.length===0){ctx.fillStyle='#999';ctx.fillText('-',4,14);return;} const maxv=Math.max(...samples,1e-6); ctx.beginPath(); ctx.strokeStyle='#6aa3d9'; ctx.lineWidth=1.5; samples.forEach((v,i)=>{ const x=(i/(samples.length-1||1))*(w-4)+2; const y=h-((v/maxv)*(h-6))-2; if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y); }); ctx.stroke(); const p95=(syms[sym]||{}).latency_p95||payload.latency.decision_ms.p95; if(p95){ const mx=Math.min(1,p95/maxv); const px=Math.floor(mx*(w-4))+2; ctx.fillStyle='rgba(255,80,80,0.9)'; ctx.fillRect(px-1,2,2,h-4);} }); } catch(e){console.warn('sparks redraw failed',e);} } catch(e){console.warn('redrawAll',e);} }

    redrawAll();
    let resizeTimer = null;
    window.addEventListener('resize', ()=>{ if (resizeTimer) clearTimeout(resizeTimer); resizeTimer = setTimeout(redrawAll, 120); });
  </script>
</body>
</html>""")