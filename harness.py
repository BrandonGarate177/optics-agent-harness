"""The harness. Everything around the model that isn't the model.

Tools: five thin wrappers over Optiland (lens_tools.py), served in-process.
Hooks: PreToolUse caps optimize at MAX_OPTIMIZE and gates export on a passing
evaluate; Stop refuses to end without an export or a refusal. The tool wrapper
writes one JSONL line per call, errors included.

Run one spec:   python harness.py "50mm f/5 singlet, 587nm, 0 and 3 deg, N-BK7"
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
    query,
    tool,
)

import lens_tools as lt

ROOT = Path(__file__).parent
import os
MAX_OPTIMIZE = int(os.environ.get("LENS_MAX_OPTIMIZE", "10"))
HARNESS_VERSION = "2.0"
REFUSAL = "CANNOT MEET SPEC"
SYSTEM_PROMPT = (ROOT / "system_prompt.md").read_text()


class Run:
    """Per-run state the hooks read and write. One instance per query."""

    def __init__(self, run_id: str, log_dir: Path):
        self.run_id = run_id
        self.optimize_calls = 0
        self.last_eval_ok: bool | None = None
        self.exported = False
        self.refused = False
        self.final_text = ""
        self.tool_calls: list[dict] = []
        self.cost_usd: float | None = None
        self.turns: int | None = None
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = log_dir / f"{run_id}.jsonl"

    def log(self, event: dict):
        event["t"] = round(time.time(), 3)
        event["run_id"] = self.run_id
        with self.log_path.open("a") as f:
            f.write(json.dumps(event, default=str) + "\n")


def _ok(payload: Any) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload, default=str)}]}


def _err(msg: str) -> dict:
    return {"content": [{"type": "text", "text": msg}], "is_error": True}


def make_server(run: Run, targets: dict | None):
    """Build the five tools bound to this run. Every call is logged here, errors included."""

    def _call(short: str, fn, args: dict) -> dict:
        try:
            payload = fn(args)
            err = None
        except KeyError as e:
            payload, err = None, f"{short} failed, missing key {e}. Check the argument shape in the tool description."
        except Exception as e:  # noqa: BLE001
            payload, err = None, f"{short} failed: {e.__class__.__name__}: {e}"
        if payload is not None:
            if short == "optimize" and "iteration" in payload:
                run.optimize_calls += 1
                run.last_eval_ok = _meets(payload["after"], targets)
            elif short == "evaluate":
                run.last_eval_ok = _meets(payload, targets)
            elif short == "export" and "zmx" in payload:
                run.exported = True
        entry = {
            "event": "tool",
            "tool": short,
            "input": args,
            "output": payload if payload is not None else err,
            "error": err is not None,
            "optimize_calls": run.optimize_calls,
            "last_eval_ok": run.last_eval_ok,
        }
        run.tool_calls.append(entry)
        run.log(entry)
        return _ok(payload) if payload is not None else _err(err)

    @tool(
        "find_starting_point",
        "Find the closest known-good lens prescriptions from Optiland's sample library. "
        "Call this first. Returns up to three candidates with a full spec you can pass to build_lens.",
        {"elements": int, "f_number": float, "field_deg": float},
    )
    async def find_starting_point(args):
        return await asyncio.to_thread(
            _call, "find_starting_point",
            lambda a: lt.find_starting_point(int(a["elements"]), float(a["f_number"]), float(a["field_deg"])), args
        )

    @tool(
        "build_lens",
        "Build a lens from a prescription and check it. Returns lens_id, system findings from Optiland's "
        "check_system, effective focal length, and manufacturability violations written as what to change. "
        "spec = {surfaces:[{radius,thickness,material,is_stop}], epd, fields_deg:[..], wavelengths_um:[..]}. "
        "Surface 0 is the object (thickness null = infinity). Last surface is the image. radius null = flat. "
        "material null = air. Set is_stop on exactly one surface.",
        {"type": "object", "properties": {"spec": {"type": "object"}}, "required": ["spec"]},
    )
    async def build_lens(args):
        return await asyncio.to_thread(_call, "build_lens", lambda a: lt.build_lens(a["spec"]), args)

    @tool(
        "evaluate",
        "Grade a lens. Deterministic. Returns efl_mm, f_number, rms_spot_um_per_field, "
        "rms_wavefront_waves_per_field, total_track_mm and manufacturability_violations. "
        "Call after every build_lens and after every optimize.",
        {"lens_id": str},
    )
    async def evaluate(args):
        return await asyncio.to_thread(_call, "evaluate", lambda a: lt.evaluate(a["lens_id"]), args)

    @tool(
        "optimize",
        "Hand the lens to Optiland's optimizer. You choose what varies and what the targets are, Optiland does the math. "
        "reason: one sentence hypothesis, required. "
        "variables: [{type:'radius'|'thickness'|'conic', surface:int, min:float, max:float}]. "
        "operands: [{type:'f2'|'rms_spot_size'|'total_track'|'edge_thickness', target?:float, weight?:float, "
        "min?:float, max?:float, field_y?:float (0..1 normalized, for rms_spot_size), surface?:int (for edge_thickness)}]. "
        "solver: least_squares (default), differential_evolution, basin_hopping. "
        "Returns before and after metrics plus the new prescription.",
        {
            "type": "object",
            "properties": {
                "lens_id": {"type": "string"},
                "reason": {"type": "string"},
                "variables": {"type": "array", "items": {"type": "object"}},
                "operands": {"type": "array", "items": {"type": "object"}},
                "solver": {"type": "string", "enum": list(lt.SOLVERS)},
            },
            "required": ["lens_id", "reason", "variables", "operands"],
        },
    )
    async def optimize(args):
        lens_id = args.get("lens_id", "")
        snap = None
        try:
            snap = await asyncio.to_thread(lt.snapshot, lens_id)
        except Exception:  # noqa: BLE001
            pass
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    _call, "optimize",
                    lambda a: lt.optimize(
                        a["lens_id"], variables=a["variables"], operands=a["operands"],
                        solver=a.get("solver", "least_squares"),
                    ),
                    args,
                ),
                timeout=lt.OPTIMIZE_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            # The worker thread keeps running, so roll the lens back to the snapshot.
            # The orphaned thread mutates the discarded object, not the live one.
            if snap is not None:
                try:
                    await asyncio.to_thread(lt.restore, lens_id, snap)
                except Exception:  # noqa: BLE001
                    pass
            msg = (
                f"optimize exceeded {lt.OPTIMIZE_TIMEOUT_S}s and was stopped. The lens is unchanged. "
                f"Reduce the variable count, tighten the bounds, or use least_squares."
            )
            run.log({"event": "tool", "tool": "optimize", "input": args, "output": msg,
                     "error": True, "timeout": True, "optimize_calls": run.optimize_calls,
                     "last_eval_ok": run.last_eval_ok})
            return _err(msg)

    @tool(
        "export",
        "Write the lens as .zmx and .json. Only allowed once evaluate shows the targets are met with no "
        "manufacturability violations. Returns file paths and the final prescription.",
        {"lens_id": str},
    )
    async def export(args):
        return await asyncio.to_thread(
            _call, "export", lambda a: lt.export(a["lens_id"], out_dir=str(ROOT / "out" / run.run_id)), args
        )

    return create_sdk_mcp_server(name="lens", version="0.1.0", tools=[find_starting_point, build_lens, evaluate, optimize, export])


def make_hooks(run: Run, targets: dict | None):
    def deny(reason: str, tool: str = "", tool_input: dict | None = None) -> dict:
        run.log({"event": "hook_deny", "tool": tool, "input": tool_input or {}, "reason": reason})
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }

    async def pre_tool(input_data, tool_use_id, context):
        name = input_data.get("tool_name", "")
        short = name.split("__")[-1]
        tin = input_data.get("tool_input") or {}
        if short == "optimize":
            if run.optimize_calls >= MAX_OPTIMIZE:
                return deny(
                    f"Iteration budget spent ({MAX_OPTIMIZE} optimize calls). Either export the best lens you have "
                    f"if it meets spec, or write a refusal starting with '{REFUSAL}:'.",
                    short, tin,
                )
            if not tin.get("reason"):
                return deny("optimize needs a one-sentence reason (your hypothesis) before it runs.", short, tin)
        if short == "export":
            if run.last_eval_ok is False:
                return deny(
                    "The last evaluate did not meet the targets or had manufacturability violations. "
                    "Fix the lens or write a refusal. Export is only for a passing lens.",
                    short, tin,
                )
            if run.last_eval_ok is None:
                return deny("Call evaluate before export.", short, tin)
        return {}

    async def stop(input_data, tool_use_id, context):
        if run.exported or run.refused:
            return {}
        if input_data.get("stop_hook_active"):
            return {}
        reason = f"You have not exported a lens or written a refusal starting with '{REFUSAL}:'. Do one of the two."
        run.log({"event": "hook_block_stop", "reason": reason})
        return {"decision": "block", "reason": reason}

    return {
        "PreToolUse": [HookMatcher(matcher="^mcp__lens__", hooks=[pre_tool])],
        "Stop": [HookMatcher(hooks=[stop])],
    }


def _meets(m: dict, targets: dict | None) -> bool:
    """Deterministic pass/fail against the case targets. Grader v2."""
    if m.get("manufacturability_violations"):
        return False
    if not targets:
        return True
    efl = m.get("efl_mm")
    if "efl_mm" in targets and isinstance(efl, (int, float)):
        tol = targets.get("efl_tol_pct", 1) / 100 * targets["efl_mm"]
        if abs(efl - targets["efl_mm"]) > tol:
            return False
    spots = m.get("rms_spot_um_per_field") or []
    if "max_spot_um" in targets and spots and max(spots) > targets["max_spot_um"]:
        return False
    if "max_track_mm" in targets and m.get("total_track_mm", 0) > targets["max_track_mm"]:
        return False
    # v2 gates
    if "max_wavefront_waves" in targets:
        wfe = m.get("rms_wavefront_waves_per_field") or []
        nums = [v for v in wfe if isinstance(v, (int, float))]
        if not nums or max(nums) > targets["max_wavefront_waves"]:
            return False
    if "max_chromatic_shift_mm" in targets:
        c = m.get("chromatic_focal_shift_mm")
        if not isinstance(c, (int, float)) or c > targets["max_chromatic_shift_mm"]:
            return False
    if "min_bfd_mm" in targets:
        b = m.get("back_focal_distance_mm")
        if not isinstance(b, (int, float)) or b < targets["min_bfd_mm"]:
            return False
    return True


async def run_spec(
    prompt: str,
    run_id: str,
    targets: dict | None = None,
    log_dir: Path | None = None,
    model: str | None = None,
    arm: str = "harness",
    verbose: bool = True,
) -> Run:
    """arm='harness': our system prompt, only the lens tools, hooks on.
    arm='baseline': Claude Code's own system prompt and built-in tools, same lens tools, no hooks."""
    # No global state reset: lens ids are uuids, so concurrent runs coexist safely.
    run = Run(run_id, log_dir or ROOT / "logs")
    server = make_server(run, targets)
    if arm == "harness":
        options = ClaudeAgentOptions(
            system_prompt=SYSTEM_PROMPT,
            mcp_servers={"lens": server},
            allowed_tools=["mcp__lens__*"],
            tools=[],
            hooks=make_hooks(run, targets),
            max_turns=60,
            permission_mode="bypassPermissions",
            cwd=str(ROOT),
            **({"model": model} if model else {}),
        )
    else:
        scratch = ROOT / "out" / "baseline-scratch" / run_id
        scratch.mkdir(parents=True, exist_ok=True)
        prompt = prompt + BASELINE_SUFFIX
        options = ClaudeAgentOptions(
            system_prompt={"type": "preset", "preset": "claude_code"},
            tools={"type": "preset", "preset": "claude_code"},
            mcp_servers={"lens": server},
            allowed_tools=["mcp__lens__*"],
            max_turns=60,
            permission_mode="bypassPermissions",
            cwd=str(scratch),
            **({"model": model} if model else {}),
        )
    run.log({"event": "start", "arm": arm, "harness_version": HARNESS_VERSION, "grader_version": lt.VERSION, "prompt": prompt, "targets": targets})
    async for msg in query(prompt=prompt, options=options):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, ToolUseBlock):
                    if verbose:
                        print(f"  [tool] {block.name.split('__')[-1]} {json.dumps(block.input, default=str)[:160]}")
                elif isinstance(block, TextBlock) and block.text.strip():
                    run.final_text = block.text
                    if REFUSAL in block.text:
                        run.refused = True
                    if verbose:
                        print(f"  [agent] {block.text.strip()[:300]}")
        elif isinstance(msg, ResultMessage):
            run.cost_usd, run.turns = msg.total_cost_usd, msg.num_turns
            run.log({"event": "result", "subtype": msg.subtype, "turns": msg.num_turns, "cost_usd": msg.total_cost_usd})
            if msg.result:
                run.final_text = msg.result
                if REFUSAL in msg.result:
                    run.refused = True
    run.log({"event": "end", "exported": run.exported, "refused": run.refused, "optimize_calls": run.optimize_calls})
    return run


if __name__ == "__main__":
    spec = " ".join(sys.argv[1:]) or "Design a single-element lens, 50mm focal length, f/5, 587nm, fields 0 and 3 degrees, N-BK7, total track under 70mm."
    r = asyncio.run(run_spec(spec, run_id=f"cli-{int(time.time())}"))
    print("\nexported:", r.exported, "refused:", r.refused, "optimize calls:", r.optimize_calls)
    print("log:", r.log_path)
