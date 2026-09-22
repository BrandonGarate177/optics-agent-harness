"""Read the Claude Code transcripts for a run directory and report what really happened.

The harness's own JSONL records only its seven lens tools. Everything else an arm
does, shell commands, file reads, its own scripts, is invisible there. That is how
the v2 control arm read evals/cases.json in four runs without anyone noticing.

    python evals/audit.py logs/free-20260922-120000

Exit code 1 if any run touched the answer key.
"""

from __future__ import annotations

import glob
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# Anything here tells an arm what it is being graded on, or what the experiment is.
ANSWER_KEY = ("cases.json", "evals/", "harness.py", "lens_tools.py", "system_prompt.md", "git log", "git show")


def transcript_dir(cwd: str) -> Path:
    """Claude Code slugs the working directory to name its project folder."""
    return Path.home() / ".claude" / "projects" / cwd.replace("/", "-").replace("_", "-").replace(".", "-")


def audit_run(jsonl: Path, repo: Path | None = None) -> dict:
    """repo: the checkout the run came from. Defaults to this file's repo, which is
    wrong when auditing logs produced by a different worktree."""
    repo = repo or REPO
    events = [json.loads(l) for l in jsonl.open()]
    start = next((e for e in events if e.get("event") == "start"), {})
    cwd = start.get("cwd")
    out = {"run": jsonl.stem, "arm": start.get("arm", "?"), "cwd": cwd,
           "tools": Counter(), "touched": [], "transcript": None, "audited": False}
    if not cwd:
        # Runs from before cwd logging. Reconstruct the slug from the old convention.
        arm = start.get("arm", "baseline")
        for candidate in (
            repo / "out" / f"{arm}-scratch" / jsonl.stem,
            repo / "out" / "baseline-scratch" / jsonl.stem,
            repo / "out" / "free-scratch" / jsonl.stem,
            Path(tempfile.gettempdir()) / "lens-free" / jsonl.stem,
            repo,
        ):
            if glob.glob(str(transcript_dir(str(candidate)) / "*.jsonl")):
                cwd = str(candidate)
                break
        else:
            out["transcript"] = "UNAUDITABLE: no cwd recorded and no transcript found"
            return out
    d = transcript_dir(cwd)
    files = sorted(glob.glob(str(d / "*.jsonl")), key=os.path.getmtime, reverse=True)
    if not files:
        out["transcript"] = f"UNAUDITABLE: no transcript at {d.name}"
        return out
    out["transcript"] = os.path.basename(files[0])
    out["audited"] = True
    for line in open(files[0]):
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = e.get("message") or {}
        if msg.get("role") != "assistant":
            continue
        for block in msg.get("content") or []:
            if not (isinstance(block, dict) and block.get("type") == "tool_use"):
                continue
            out["tools"][block["name"]] += 1
            blob = json.dumps(block.get("input", {}))
            for marker in ANSWER_KEY:
                if marker in blob:
                    out["touched"].append(f"{block['name']}: {marker}")
    out["touched"] = sorted(set(out["touched"]))
    return out


def main(log_dir: str) -> int:
    # The repo the runs came from, inferred from the log directory itself.
    repo = Path(log_dir).resolve().parent.parent
    rows = [audit_run(Path(f), repo) for f in sorted(glob.glob(f"{log_dir}/*.jsonl"))]
    dirty = [r for r in rows if r["touched"]]
    blind = [r for r in rows if not r["audited"]]
    print(f"{'run':<20}{'arm':<10}{'own tools':>10}{'other tools':>13}   flagged")
    for r in rows:
        own = sum(v for k, v in r["tools"].items() if k.startswith("mcp__lens"))
        other = sum(v for k, v in r["tools"].items() if not k.startswith("mcp__lens"))
        flag = ", ".join(r["touched"])[:60] or ("-" if r["tools"] else r["transcript"])
        print(f"{r['run']:<20}{r['arm']:<10}{own:>10}{other:>13}   {flag}")
    other_mix = Counter()
    for r in rows:
        for k, v in r["tools"].items():
            if not k.startswith("mcp__lens"):
                other_mix[k] += v
    if other_mix:
        print(f"\nnon-lens tools used: {dict(other_mix.most_common())}")
    if blind:
        print(f"\nUNAUDITABLE: {len(blind)} of {len(rows)} runs have no readable transcript. "
              f"Not clean, unknown. {', '.join(r['run'] for r in blind[:6])}")
    if dirty:
        print(f"CONTAMINATED: {len(dirty)} of {len(rows)} runs reached the answer key or the repo.")
    if dirty or blind:
        return 1
    print(f"\nclean: {len(rows)} runs audited, none touched the answer key.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
