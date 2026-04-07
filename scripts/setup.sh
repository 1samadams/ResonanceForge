#!/usr/bin/env bash
# ResonanceForge - macOS/Linux bootstrap
# Creates a .venv and installs the project with GUI extras.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$HERE/.venv"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found; install Python 3.10+" >&2
  exit 1
fi

if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install --upgrade pip wheel setuptools
pip install -e "$HERE[gui,test]"

echo
echo "Setup complete. Activate with:  source $VENV/bin/activate"
echo "Run GUI:  resonanceforge-gui"
echo "Run CLI:  resonanceforge <input> <output>"
echo "Tests:    pytest -q"
