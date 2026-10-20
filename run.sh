#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export PYTHONUTF8=1

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
else
  echo "[ERROR] Python 3을 찾을 수 없습니다. Ubuntu에 python3를 설치해 주세요." >&2
  exit 1
fi

exec "$PYTHON_BIN" -u "$SCRIPT_DIR/app.py"
