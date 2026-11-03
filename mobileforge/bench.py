"""benchmark runner: same cases, same model, same tools, three systems.

  single = one agent with every tool
  multi  = the five-agent workflow, memory off
  full   = the five-agent workflow, verified fix memory on
"""

from __future__ import annotations

import csv
import json
import statistics
import time
from pathlib import Path

from .cases import Case
from .config import RESULTS_DIR
from .memory import FixMemory
from .orchestrator import start_run
from .workspace import Runner, remove_workspace

FIELDS = ["case", "layer", "category", "mode", "trial", "run_id", "status", "reproduced", "verified",
          "hidden_pass", "regression", "attempts", "tool_calls", "input_tokens", "output_tokens", "cost_usd",
          "duration_s", "lines_changed", "memory_hits", "error"]


def row_from_state(case: Case, mode: str, trial: int, s: dict) -> dict:
    u = s.get("usage", {})
    return {"case": case.id, "layer": case.layer, "category": case.category, "mode": mode, "trial": trial,
            "run_id": s.get("run_id"), "status": s.get("status"),
            "reproduced": s.get("repro", {}).get("reproduced", "") if mode != "single" else "",
            "verified": bool(s.get("verified")), "hidden_pass": bool(s.get("hidden_pass")),
            "regression": bool(s.get("regression")), "attempts": s.get("attempt_count", 0),
            "tool_calls": s.get("tool_calls", 0), "input_tokens": u.get("input_tokens", 0),
            "output_tokens": u.get("output_tokens", 0), "cost_usd": s.get("cost_usd", 0),
            "duration_s": s.get("duration_s", 0), "lines_changed": s.get("lines_changed", 0),
            "memory_hits": len(s.get("memory_hits", [])), "error": s.get("error", "")}


def run_benchmark(cases: list[Case], modes: list[str], trials: int, llm, settings, keep: bool = False,
                  log=print, runner: Runner | None = None, start_fn=start_run, cleanup_fn=remove_workspace) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / "runs.csv"
    new = not out.exists()
    with out.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        for trial in range(1, trials + 1):
            # fresh memory per trial so trials stay independent
            mem_path = RESULTS_DIR / "memory" / f"trial-{trial}-{int(time.time())}.db"
            memory = FixMemory(mem_path)
            for mode in modes:
                for case in cases:
                    log(f"\n[{mode} | trial {trial}] {case.id}: {case.title}")
                    try:
                        s = start_fn(case, mode, llm, settings, runner=runner,
                                     memory=memory if mode == "full" else None, log=log)
                    except Exception as e:
                        log(f"  run crashed: {e}")
                        s = {"status": "error", "error": str(e)[:300]}
                    row = row_from_state(case, mode, trial, s)
                    w.writerow(row)
                    f.flush()
                    log(f"  status={row['status']} hidden={'pass' if row['hidden_pass'] else 'fail'} "
                        f"cost=${row['cost_usd']} time={row['duration_s']}s")
                    if not keep and s.get("run_id"):
                        cleanup_fn(s["run_id"])
    summarize()
    return out


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def summarize(path: Path | None = None) -> dict:
    path = path or RESULTS_DIR / "runs.csv"
    if not path.exists():
        raise RuntimeError("no results yet, run `mobileforge bench` first")
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    yes = lambda v: str(v).lower() == "true"
    modes = {}
    for mode in ("single", "multi", "full"):
        rs = [r for r in rows if r["mode"] == mode]
        if not rs:
            continue
        attempted = [r for r in rs if int(r["lines_changed"] or 0) > 0]
        repro_rows = [r for r in rs if r["reproduced"] != ""]
        modes[mode] = {
            "runs": len(rs),
            "cases": len({r["case"] for r in rs}),
            "reproduction_rate": _rate(sum(yes(r["reproduced"]) for r in repro_rows), len(repro_rows)),
            "verified_repair_rate": _rate(sum(yes(r["verified"]) for r in rs), len(rs)),
            "regression_rate": _rate(sum(yes(r["regression"]) for r in attempted), len(attempted)),
            "median_duration_s": round(statistics.median(float(r["duration_s"] or 0) for r in rs), 1),
            "avg_cost_usd": round(statistics.mean(float(r["cost_usd"] or 0) for r in rs), 4),
            "avg_tool_calls": round(statistics.mean(int(r["tool_calls"] or 0) for r in rs), 1),
            "human_intervention_rate": _rate(sum(r["status"] == "needs_info" for r in rs), len(rs)),
            "safe_failure_rate": _rate(sum(r["status"] in ("failed", "rejected_by_review", "needs_info")
                                           and not yes(r["hidden_pass"]) for r in rs), len(rs)),
        }
    comparison = {"modes": modes}
    if "full" in modes and "multi" in modes:
        comparison["memory_benefit_pp"] = round(
            100 * ((modes["full"]["verified_repair_rate"] or 0) - (modes["multi"]["verified_repair_rate"] or 0)), 1)
    if "multi" in modes and "single" in modes:
        comparison["multi_vs_single_pp"] = round(
            100 * ((modes["multi"]["verified_repair_rate"] or 0) - (modes["single"]["verified_repair_rate"] or 0)), 1)

    # per-case matrix: how many trials each mode fixed
    per_case: dict = {}
    for r in rows:
        c = per_case.setdefault(r["case"], {})
        m = c.setdefault(r["mode"], [0, 0])
        m[0] += yes(r["verified"])
        m[1] += 1
    comparison["per_case"] = per_case

    (RESULTS_DIR / "comparison.json").write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    with (RESULTS_DIR / "metrics.csv").open("w", newline="", encoding="utf-8") as f:
        keys = ["mode"] + list(next(iter(modes.values())).keys()) if modes else ["mode"]
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for mode, m in modes.items():
            w.writerow({"mode": mode, **m})
    _write_summary(comparison)
    return comparison


def _pct(v) -> str:
    return "-" if v is None else f"{v * 100:.0f}%"


def _write_summary(c: dict) -> None:
    modes = c["modes"]
    head = "| metric | " + " | ".join(modes) + " |\n|---|" + "---|" * len(modes) + "\n"
    lines = []
    for key, label, fmt in [("verified_repair_rate", "verified repair rate", _pct),
                            ("reproduction_rate", "reproduction rate", _pct),
                            ("regression_rate", "regression rate", _pct),
                            ("safe_failure_rate", "failed safely (no bad patch shipped)", _pct),
                            ("median_duration_s", "median time per issue (s)", str),
                            ("avg_cost_usd", "avg cost per issue (usd)", lambda v: f"${v:.3f}"),
                            ("avg_tool_calls", "avg tool calls", str),
                            ("human_intervention_rate", "needed more info", _pct),
                            ("runs", "runs", str)]:
        lines.append(f"| {label} | " + " | ".join(fmt(m[key]) for m in modes.values()) + " |")
    md = "# Benchmark results\n\n" + head + "\n".join(lines) + "\n"
    if "memory_benefit_pp" in c:
        md += f"\nmemory benefit (full minus multi): {c['memory_benefit_pp']:+.1f} percentage points\n"
    if "multi_vs_single_pp" in c:
        md += f"multi-agent vs single agent: {c['multi_vs_single_pp']:+.1f} percentage points\n"
    md += "\n## Per case (verified fixes / trials)\n\n| case | " + " | ".join(modes) + " |\n|---|" + "---|" * len(modes) + "\n"
    for case, by_mode in sorted(c["per_case"].items()):
        md += f"| {case} | " + " | ".join(f"{by_mode.get(m, [0, 0])[0]}/{by_mode.get(m, [0, 0])[1]}" for m in modes) + " |\n"
    (RESULTS_DIR / "summary.md").write_text(md, encoding="utf-8")

    cells = "".join(f"<th>{m}</th>" for m in modes)
    body = "".join(
        f"<tr><td>{label}</td>" + "".join(f"<td>{fmt(m[key])}</td>" for m in modes.values()) + "</tr>"
        for key, label, fmt in [("verified_repair_rate", "verified repair rate", _pct),
                                ("regression_rate", "regression rate", _pct),
                                ("median_duration_s", "median seconds", str),
                                ("avg_cost_usd", "avg cost", lambda v: f"${v:.3f}"),
                                ("avg_tool_calls", "avg tool calls", str)])
    (RESULTS_DIR / "summary.html").write_text(
        f'<div class="card"><h2>Benchmark</h2><table><tr><th></th>{cells}</tr>{body}</table>'
        f'<p class="muted">full table in results/summary.md</p></div>', encoding="utf-8")
