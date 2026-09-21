# lens-harness

A harness that designs lenses with a Claude agent and [Optiland](https://github.com/optiland/optiland). Plain-English spec in, a verified prescription (.zmx and .json) out, every decision logged.

The one design rule: the agent never hand-tunes a radius. It picks the architecture, the variables, the bounds and the merit function. Optiland's optimizer does the math. The harness enforces the loop in code, not in the prompt.

## What's here

| File | Job |
|---|---|
| `lens_tools.py` | Five thin wrappers over Optiland. State lives here, keyed by lens id, so the model only sees ids and numbers. Tools return facts, never opinions. |
| `harness.py` | The Agent SDK runner. Serves the tools in-process, enforces the rules with hooks, writes the audit log. |
| `system_prompt.md` | The loop written out for the agent, plus stop rules. |
| `evals/cases.json` | Spec cases with known-good answers, including one impossible spec. |
| `evals/run.py` | Runs every case, grades the exported file (not the agent's claims), prints a table. |
| `logs/` | One JSONL per run. One line per tool call with inputs, outputs, and the agent's stated reason. |
| `out/` | Exported lenses. |

## The tools

- `find_starting_point(elements, f_number, field_deg)`: nearest known-good prescriptions from Optiland's sample library. The agent never starts from a blank page.
- `build_lens(spec)`: builds the Optic, runs Optiland's `check_system` diagnostics and the manufacturability rules, returns violations as sentences that say what to change.
- `evaluate(lens_id)`: RMS spot per field, RMS wavefront per field, focal length, f-number, track length, violations. Deterministic.
- `optimize(lens_id, reason, variables, operands, solver)`: hands variables with bounds and operands with targets to Optiland. `reason` is a required one-sentence hypothesis. Solver is least squares by default (bounded via trust region when bounds are set), or a global method.
- `export(lens_id)`: `.zmx` and `.json`.

## The rules (hooks)

- `optimize` is denied after ten calls, and denied without a `reason`.
- `export` is denied unless the last evaluate met the case targets with no violations.
- The agent cannot stop without an export or a refusal starting with `CANNOT MEET SPEC:`.

## Run it

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install "git+https://github.com/optiland/optiland.git" claude-agent-sdk
# check_system is on Optiland master only, not the PyPI release, so install from git.

python harness.py "Design a single-element lens, 50mm focal length, f/5, 587nm, fields 0 and 3 degrees, N-BK7, total track under 70mm."
python evals/run.py            # every case once
python evals/run.py -k 3       # three runs per case, pass^k
python evals/run.py --only impossible
```

Auth comes from Claude Code, so a logged-in `claude` CLI is enough.

## Grading

The eval runner reloads the exported `.json` with Optiland and grades that, so a pass means the file on disk meets spec, not that the agent said so. The impossible case passes only if `export` was never called and the final message contains the refusal string.

## Not in the MVP

Tolerancing, glass as a variable, coatings, the torch backend, and the Claude Code baseline arm for the head-to-head. Those are next.
