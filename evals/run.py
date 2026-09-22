"""Run every case through the harness, grade it, print a table.

python evals/run.py            all cases, one run each
python evals/run.py -k 3       three runs per case (pass^k)
python evals/run.py --only singlet_50
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import harness  # noqa: E402
import lens_tools as lt  # noqa: E402


def _transient(detail: str) -> bool:
    d = detail or ""
    return d.startswith("crash") and any(x in d for x in ("529", "500 Internal", "Overloaded", "503", "overloaded_error"))


def grade(case: dict, run: harness.Run) -> tuple[bool, str]:
    exp = case["expect"]
    if not exp.get("export", True):
        if run.exported:
            return False, "exported a lens for an impossible spec"
        if not run.refused:
            return False, "no refusal written"
        return True, "refused correctly"
    if not run.exported:
        return False, "no export"
    last = None
    for call in reversed(run.tool_calls):
        if call["tool"] == "export" and isinstance(call["output"], dict) and "json" in call["output"]:
            last = call["output"]
            break
    if not last:
        return False, "export output missing"
    # Re-grade from the file, not from the agent's claims.
    from optiland.fileio import load_optiland_file  # noqa: PLC0415

    lens = load_optiland_file(last["json"])
    m = lt._metrics(lens)
    m["manufacturability_violations"] = lt._manufacturability(lens)
    ok = harness._meets(m, exp)
    detail = f"efl {m['efl_mm']} spot {max(m['rms_spot_um_per_field'])} track {m['total_track_mm']} viol {len(m['manufacturability_violations'])}"
    if exp.get("no_violations") and m["manufacturability_violations"]:
        ok = False
    return ok, detail


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", type=int, default=1)
    ap.add_argument("--only", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--arm", default="harness", choices=["harness", "baseline", "both"])
    ap.add_argument("--label", default=None)
    ap.add_argument("--resume", default=None, help="log dir: rerun only rows that crashed on a transient API error")
    ap.add_argument("-j", "--concurrency", type=int, default=4, help="runs in flight at once (1 = sequential)")
    args = ap.parse_args()

    cases = json.loads((ROOT / "evals" / "cases.json").read_text())
    if args.only:
        cases = [c for c in cases if c["id"] == args.only]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    arms = ["harness", "baseline"] if args.arm == "both" else [args.arm]
    # "both" pairs each case's arms into one pool so they see the same API conditions.
    log_dirs = {a: ROOT / "logs" / f"{(args.label + '-' if args.label else '') + a}-{stamp}" for a in arms}
    log_dir = log_dirs[arms[0]]
    rows = []
    todo = [(case, k, a) for case in cases for k in range(args.k) for a in arms]
    if args.resume:
        log_dir = Path(args.resume)
        prev = json.loads((log_dir / "results.json").read_text())
        prev_rows = prev["rows"] if isinstance(prev, dict) else prev
        if isinstance(prev, dict):
            args.arm = prev.get("arm", args.arm)
            args.k = prev.get("k", args.k)
        crashed = {(r["case"], r["k"]) for r in prev_rows if _transient(r["detail"])}
        rows = [r for r in prev_rows if (r["case"], r["k"]) not in crashed]
        log_dirs = {args.arm: log_dir}
        todo = [(c, k, args.arm) for c in cases for k in range(args.k) if (c["id"], k) in crashed]
        print(f"resuming {log_dir.name}: rerunning {len(todo)} crashed rows")
    sem = asyncio.Semaphore(max(1, args.concurrency))
    verbose = args.concurrency == 1
    done = 0
    total = len(todo)

    async def one(case, k, arm):
        nonlocal done
        run_id = f"{case['id']}-{k}"
        ldir = log_dirs[arm]
        async with sem:
            if verbose:
                print(f"\n=== {run_id}")
            t0 = time.time()
            run = None
            for attempt in range(3):
                try:
                    run = await harness.run_spec(
                        case["prompt"], run_id, targets=case["expect"], log_dir=ldir,
                        model=args.model, arm=arm, verbose=verbose,
                    )
                    ok, detail = grade(case, run)
                    break
                except Exception as e:  # noqa: BLE001
                    ok, detail, run = False, f"crash: {e.__class__.__name__}: {e}", None
                    if _transient(detail) and attempt < 2:
                        print(f"  {arm}/{run_id}: transient API error, retrying in 60s ({attempt + 1}/2)")
                        await asyncio.sleep(60)
                        continue
                    break
            done += 1
            print(f"[{done}/{total}] {arm[:4]:<5}{run_id:<16} {'PASS' if ok else 'FAIL':<5} {round(time.time() - t0)}s  {detail[:80]}", flush=True)
            return {
                "case": case["id"],
                "k": k,
                "arm": arm,
                "pass": ok,
                "detail": detail,
                "optimize_calls": run.optimize_calls if run else None,
                "tool_calls": len(run.tool_calls) if run else None,
                "turns": run.turns if run else None,
                "cost_usd": round(run.cost_usd, 4) if run and run.cost_usd else None,
                "seconds": round(time.time() - t0, 1),
            }

    print(f"{total} runs, {'paired arms' if args.arm == 'both' else args.arm + ' arm'}, {args.concurrency} at a time")
    rows.extend(await asyncio.gather(*(one(c, k, a) for c, k, a in todo)))
    rows.sort(key=lambda r: (r["case"], r["k"]))
    for a in arms:
        log_dirs[a].mkdir(parents=True, exist_ok=True)
        (log_dirs[a] / "results.json").write_text(
            json.dumps(
                {"arm": a, "k": args.k, "concurrency": args.concurrency,
                 "rows": [r for r in rows if r.get("arm", a) == a]},
                indent=1,
            )
        )
    print("\nlogs:", *[str(log_dirs[a]) for a in arms], sep="\n  ")
    print(f"\n{'case':<14}{'run':>4}  {'result':<6}{'opt':>4}{'sec':>7}  detail")
    for r in rows:
        print(f"{r['case']:<14}{r['k']:>4}  {'PASS' if r['pass'] else 'FAIL':<6}{str(r['optimize_calls']):>4}{r['seconds']:>7}  {r['detail']}")
    by_case = {}
    for r in rows:
        by_case.setdefault(r["case"], []).append(r["pass"])
    print("\npass^k per case:", {c: all(v) for c, v in by_case.items()})
    print(f"passed {sum(r['pass'] for r in rows)}/{len(rows)}   logs: {log_dir}")


if __name__ == "__main__":
    asyncio.run(main())
