"""Side by side: harness vs baseline on the same cases.

python evals/compare.py logs/harness-<stamp> logs/baseline-<stamp>
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path


def load(d: str) -> dict:
    data = json.loads((Path(d) / "results.json").read_text())
    rows = data["rows"] if isinstance(data, dict) else data
    by = {}
    for r in rows:
        by.setdefault(r["case"], []).append(r)
    return by


def summarize(runs: list[dict]) -> dict:
    ok = [r["pass"] for r in runs]
    return {
        "pass": f"{sum(ok)}/{len(ok)}",
        "pass_k": all(ok),
        "sec": round(statistics.median(r["seconds"] for r in runs), 0),
        "usd": round(statistics.median(r["cost_usd"] or 0 for r in runs), 2),
        "opt": round(statistics.median(r["optimize_calls"] or 0 for r in runs), 1),
        "tools": round(statistics.median(r.get("tool_calls") or 0 for r in runs), 1),
    }


def main():
    h, b = load(sys.argv[1]), load(sys.argv[2])
    cases = [c for c in h if c in b]
    print(f"{'case':<14}{'arm':<10}{'pass':>6}{'pass^k':>8}{'med sec':>9}{'med $':>8}{'med opt':>9}{'med tools':>11}")
    tot = {"harness": [], "baseline": []}
    for c in cases:
        for arm, d in (("harness", h), ("baseline", b)):
            s = summarize(d[c])
            tot[arm].extend(d[c])
            print(f"{c:<14}{arm:<10}{s['pass']:>6}{str(s['pass_k']):>8}{s['sec']:>9}{s['usd']:>8}{s['opt']:>9}{s['tools']:>11}")
        print()
    for arm in ("harness", "baseline"):
        runs = tot[arm]
        print(
            f"{arm:<10} passed {sum(r['pass'] for r in runs)}/{len(runs)}   "
            f"total ${round(sum(r['cost_usd'] or 0 for r in runs), 2)}   "
            f"total {round(sum(r['seconds'] for r in runs) / 60, 1)} min   "
            f"pass^k cases {sum(all(r['pass'] for r in h[c] if arm == 'harness') if arm == 'harness' else all(r['pass'] for r in b[c]) for c in cases)}/{len(cases)}"
        )


if __name__ == "__main__":
    main()
