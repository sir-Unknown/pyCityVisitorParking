#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-/tmp/xdg-cache}"
unset VIRTUAL_ENV || true

tool="${1:-}"
if [[ -z "$tool" ]]; then
  echo "Usage: scripts/run-uv-tool.sh <pyright|pytest>" >&2
  exit 2
fi
shift

case "$tool" in
  pyright)
    exec uv run --group typecheck pyright "$@"
    ;;
  pytest)
    export COVERAGE_FILE="${COVERAGE_FILE:-/tmp/pycvp.coverage}"
    exec uv run --group test pytest "$@"
    ;;
  *)
    echo "Unsupported tool: $tool" >&2
    exit 2
    ;;
esac
