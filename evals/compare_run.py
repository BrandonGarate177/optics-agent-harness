"""Side by side for one run id, harness against baseline.

python evals/compare_run.py singlet_50-1
"""

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def summarize(path: str) -> dict | None:
    if not Path(path).exists():
        return None
    ev = [json.loads(l) for l in open(path)]
    if not any(e["event"] == "end" for e in ev):
        return {"unfinished": True}
    tools = [e for e in ev if e["event"] == "tool"]
    den = [e for e in ev if e["event"].startswith("hook_")]
    res = [e for e in ev if e["event"] == "result"]
    end = [e for e in ev if e["event"] == "end"][0]
    last, presc = None, None
    for e in tools:
        o = e["output"]
        if isinstance(o, dict):
            if e["tool"] == "evaluate":
                last = o
            if e["tool"] == "optimize" and "after" in o:
                last, presc = o["after"], o.get("prescription")
            if e["tool"] == "export":
                presc = o.get("prescription")
    return {
        "secs": round(ev[-1]["t"] - ev[0]["t"]),
        "tools": len(tools),
        "den": len(den),
        "cost": round(res[0]["cost_usd"], 2) if res and res[0].get("cost_usd") else None,
        "opt": end["optimize_calls"],
        "exported": end["exported"],
        "refused": end["refused"],
        "m": last or {},
        "presc": [
            (r["radius"], r["thickness"], r["material"])
            for r in (presc or [])
            if r["material"] not in ("IdealMaterial", None)
        ],
    }


def main(run_id: str):
    h = sorted(glob.glob(str(ROOT / "logs" / "harness-20260922-*")))[-1]
    b = sorted(glob.glob(str(ROOT / "logs" / "baseline-20260922-*")))[-1]
    case = run_id.rsplit("-", 1)[0]
    targets = {c["id"]: c["expect"] for c in json.load(open(ROOT / "evals" / "cases.json"))}[case]
    hh, bb = summarize(f"{h}/{run_id}.jsonl"), summarize(f"{b}/{run_id}.jsonl")
    for name, v in (("harness", hh), ("baseline", bb)):
        if v is None:
            print(f"{run_id}: {name} has not started this run"), sys.exit(0)
        if v.get("unfinished"):
            print(f"{run_id}: {name} still running"), sys.exit(0)

    def row(label, fn):
        print(f"{label:<28}{str(fn(hh)):<24}{str(fn(bb))}")

    print(f"\n{run_id:<28}{'HARNESS':<24}BASELINE")
    row("wall clock", lambda v: f"{v['secs']}s")
    row("tool calls", lambda v: v["tools"])
    row("optimize calls", lambda v: v["opt"])
    row("hook denials", lambda v: v["den"])
    row("cost (API equiv)", lambda v: f"${v['cost']}")
    row("outcome", lambda v: "exported" if v["exported"] else ("refused" if v["refused"] else "neither"))
    labels = [
        ("efl mm", "efl_mm", f"target {targets.get('efl_mm', '-')}"),
        ("f-number", "f_number", ""),
        ("spot um", "rms_spot_um_per_field", f"limit {targets.get('max_spot_um', '-')}"),
        ("wavefront waves", "rms_wavefront_waves_per_field", f"limit {targets.get('max_wavefront_waves', '-')}"),
        ("chromatic shift mm", "chromatic_focal_shift_mm", f"limit {targets.get('max_chromatic_shift_mm', '-')}"),
        ("magnification", "magnification", f"target {targets.get('magnification', '-')}"),
        ("back focus mm", "back_focal_distance_mm", f"min {targets.get('min_bfd_mm', '-')}"),
        ("track mm", "total_track_mm", f"max {targets.get('max_track_mm', '-')}"),
        ("violations", "manufacturability_violations", ""),
    ]
    for label, key, note in labels:
        if hh["m"].get(key) is None and bb["m"].get(key) is None:
            continue
        row(f"{label} ({note})" if note else label, lambda v, k=key: v["m"].get(k))
    print(f"\nharness prescription:  {hh['presc']}")
    print(f"baseline prescription: {bb['presc']}")


if __name__ == "__main__":
    main(sys.argv[1])
