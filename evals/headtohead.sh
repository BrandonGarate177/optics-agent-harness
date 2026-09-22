#!/bin/zsh
# Both arms, same cases, same concurrency, back to back. Logs land in logs/<arm>-<stamp>.
cd "$(dirname "$0")/.."
K=${1:-3}
J=${2:-4}
.venv/bin/python -u -W ignore evals/run.py --arm harness  -k $K -j $J 2>&1 | grep -v Deprecation
.venv/bin/python -u -W ignore evals/run.py --arm baseline -k $K -j $J 2>&1 | grep -v Deprecation
H=$(ls -td logs/harness-* | head -1); B=$(ls -td logs/baseline-* | head -1)
echo; echo "=== COMPARE $H $B"
.venv/bin/python evals/compare.py "$H" "$B"
