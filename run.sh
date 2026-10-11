#!/usr/bin/env bash
# Runs the diagnosis and compares the output with expected.txt.
set -euo pipefail
cd "$(dirname "$0")"
python3 gen_data.py --check
python3 diagnose.py > /tmp/conversion-drop-actual.txt
if diff -u expected.txt /tmp/conversion-drop-actual.txt; then
  cat /tmp/conversion-drop-actual.txt
  echo
  echo "OK: output matches expected.txt"
else
  echo "FAIL: output differs from expected.txt" >&2
  exit 1
fi
