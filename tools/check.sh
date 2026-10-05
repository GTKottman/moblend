#!/usr/bin/env bash
# Everything CI and reviewers expect, in one command. Run before every commit.
set -euo pipefail
cd "$(dirname "$0")/.."
uvx ruff check --select E,F,W,B,A,C4,SIM,PIE --line-length 120 --target-version py311 .
uvx pylint --disable=all --enable=duplicate-code --min-similarity-lines=5 moblend mcp tests examples | grep -q "10.00/10"
for t in test_api test_ui test_bridge; do
  out=$(blender -b --factory-startup -P "tests/$t.py" 2>&1)
  echo "$out" | grep -q "^RESULT PASS" || { echo "$out" | grep -E "FAIL|Error" | head -20; echo "$t FAILED"; exit 1; }
  echo "$t: PASS"
done
find . -name __pycache__ -prune -exec rm -rf {} +
echo "ALL CHECKS PASSED"
