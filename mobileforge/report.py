"""html run reports. one page per run with the timeline, evidence, diff and cost."""

from __future__ import annotations

import html
import json
from pathlib import Path

from .context import read_trace

CSS = """
:root{--bg:#0b0f14;--card:#121821;--line:#223041;--text:#e6edf3;--muted:#8b98a8;--good:#3fb950;--bad:#f85149;
--warn:#d29922;--accent:#58a6ff;font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif}
body{background:var(--bg);color:var(--text);margin:0;padding:28px;max-width:1100px;margin:auto}
a{color:var(--accent)} h1{margin:0 0 4px;font-size:24px} h2{font-size:16px;margin:0 0 10px}
.muted{color:var(--muted)} .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin:14px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
.stat b{display:block;font-size:24px} .pill{display:inline-block;padding:2px 10px;border-radius:99px;font-size:13px;font-weight:600}
.ok{background:#12361e;color:var(--good)} .no{background:#3d1214;color:var(--bad)} .mid{background:#3a2c0b;color:var(--warn)}
pre{background:#0d1117;border:1px solid var(--line);border-radius:8px;padding:12px;overflow:auto;font-size:12.5px;max-height:420px}
.add{color:var(--good)} .del{color:var(--bad)} table{width:100%;border-collapse:collapse;font-size:14px}
td,th{border-bottom:1px solid var(--line);padding:8px;text-align:left;vertical-align:top}
.step{border-left:2px solid var(--line);padding:6px 0 6px 14px;margin-left:6px}
.step.tool{color:var(--muted);font-size:13px} .step.node{border-color:var(--accent);font-weight:600}
"""

STATUS_PILL = {"awaiting_approval": "ok", "approved": "ok", "running": "mid", "needs_info": "mid",
               "failed": "no", "rejected_by_review": "no", "error": "no"}


def esc(x) -> str:
    return html.escape(str(x))


def pill(text: str, kind: str | None = None) -> str:
    return f'<span class="pill {kind or STATUS_PILL.get(text, "mid")}">{esc(text)}</span>'


def diff_html(diff: str) -> str:
    out = []
    for line in diff.splitlines():
        cls = "add" if line.startswith("+") and not line.startswith("+++") else \
              "del" if line.startswith("-") and not line.startswith("---") else ""
        out.append(f'<span class="{cls}">{esc(line)}</span>')
    return "<pre>" + "\n".join(out) + "</pre>" if out else '<p class="muted">no changes</p>'


def page(title: str, body: str, refresh: bool = False) -> str:
    meta = '<meta http-equiv="refresh" content="3">' if refresh else ""
    return (f'<!doctype html><html><head><meta charset="utf-8">{meta}<title>{esc(title)}</title>'
            f'<style>{CSS}</style></head><body>{body}</body></html>')


def write_run_report(run_dir: Path, state: dict) -> Path:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    trace = read_trace(run_dir)
    case = state.get("case", {})
    checks = state.get("test_results", {})
    ok_checks = sum(1 for v in checks.values() if isinstance(v, dict) and v.get("ok"))
    all_checks = sum(1 for v in checks.values() if isinstance(v, dict))
    diff = (run_dir / "fix.patch").read_text(encoding="utf-8") if (run_dir / "fix.patch").exists() else ""

    stats = [("checks passed", f"{ok_checks}/{all_checks}"), ("lines changed", state.get("lines_changed", "-")),
             ("patch attempts", state.get("attempt_count", 0)), ("tool calls", state.get("tool_calls", 0)),
             ("cost", f"${state.get('cost_usd', 0):.3f}"), ("time", f"{state.get('duration_s', '-')}s")]
    if "hidden_pass" in state:
        stats.insert(0, ("hidden tests", "pass" if state["hidden_pass"] else "fail"))

    steps = []
    for e in trace:
        if e["kind"] == "node":
            steps.append(f'<div class="step node">{esc(e["node"])}</div>')
        elif e["kind"] == "tool":
            flag = " (error)" if e.get("error") else ""
            steps.append(f'<div class="step tool">{esc(e["agent"])} called <b>{esc(e["tool"])}</b>{flag} '
                         f'{esc(json.dumps(e.get("input"))[:160])}</div>')
        elif e["kind"] == "submit":
            steps.append(f'<div class="step">{esc(e["agent"])} submitted<pre>{esc(json.dumps(e["output"], indent=2)[:2500])}</pre></div>')
        elif e["kind"] == "verify":
            steps.append(f'<div class="step">verification: {esc(json.dumps(e["checks"]))}</div>')
        elif e["kind"] == "error":
            steps.append(f'<div class="step">{pill("error")} {esc(e["error"])}</div>')

    check_rows = "".join(
        f"<tr><td>{esc(k)}</td><td>{pill('pass', 'ok') if v.get('ok') else pill('fail', 'no')}</td>"
        f"<td><details><summary>output</summary><pre>{esc(v.get('output', ''))}</pre></details></td></tr>"
        for k, v in checks.items() if isinstance(v, dict))

    repro = state.get("repro", {})
    def shot_src(p: str) -> str:
        try:
            return Path(p).resolve().relative_to(run_dir.resolve()).as_posix()
        except ValueError:
            return Path(p).as_uri()
    shots = "".join(f'<img src="{esc(shot_src(p))}" style="max-width:220px;margin:4px;border-radius:8px">'
                    for p in repro.get("screenshots", []))
    review = state.get("review")

    body = f"""
<p class="muted"><a href="/">all runs</a></p>
<h1>{esc(case.get('id'))} {pill(state.get('status', 'running'))}</h1>
<p class="muted">{esc(case.get('title', ''))} &middot; layer {esc(case.get('layer'))} &middot; mode {esc(state.get('mode'))} &middot; model {esc(state.get('model'))}</p>
<div class="card"><h2>Bug report</h2><p>{esc(case.get('bug_report', ''))}</p></div>
<div class="grid">{''.join(f'<div class="stat"><span class="muted">{esc(k)}</span><b>{esc(v)}</b></div>' for k, v in stats)}</div>
<div class="card"><h2>Reproduction</h2>{pill('reproduced', 'ok') if repro.get('reproduced') else pill('not reproduced', 'mid') if repro else ''}
<pre>{esc(repro.get('failing_output') or repro.get('evidence') or '')}</pre>{shots}</div>
<div class="card"><h2>Root cause</h2><p>{esc(state.get('root_cause') or '-')}</p></div>
<div class="card"><h2>Patch</h2>{diff_html(diff)}</div>
<div class="card"><h2>Verification</h2><table>{check_rows or '<tr><td class="muted">not run yet</td></tr>'}</table></div>
{f'<div class="card"><h2>Review</h2><pre>{esc(json.dumps(review, indent=2))}</pre></div>' if review else ''}
<div class="card"><h2>Timeline</h2>{''.join(steps)}</div>
<div class="card"><h2>Tokens by agent</h2><pre>{esc(json.dumps(state.get('usage', {}).get('by_agent', {}), indent=2))}</pre></div>
"""
    path = run_dir / "report.html"
    path.write_text(page(f"MobileForge {case.get('id')}", body, refresh=state.get("next") != "done"), encoding="utf-8")
    (run_dir / "state.json").write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    return path


def index_page(runs: list[dict], summary_html: str = "") -> str:
    rows = "".join(
        f"<tr><td><a href='/runs/{esc(r['run_id'])}/report.html'>{esc(r['run_id'])}</a></td>"
        f"<td>{esc(r.get('mode'))}</td><td>{pill(r.get('status', 'running'))}</td>"
        f"<td>{'pass' if r.get('hidden_pass') else ('fail' if 'hidden_pass' in r else '-')}</td>"
        f"<td>{esc(r.get('attempt_count', 0))}</td><td>${r.get('cost_usd', 0):.3f}</td>"
        f"<td>{esc(r.get('duration_s', '-'))}</td></tr>" for r in runs)
    body = f"""<h1>MobileForge</h1><p class="muted">autonomous multi-agent bug repair for Fineprint</p>
{summary_html}
<div class="card"><h2>Runs</h2><table><tr><th>run</th><th>mode</th><th>status</th><th>hidden tests</th>
<th>attempts</th><th>cost</th><th>seconds</th></tr>{rows or '<tr><td class="muted">no runs yet</td></tr>'}</table></div>"""
    return page("MobileForge", body, refresh=any(r.get("next") != "done" for r in runs))
