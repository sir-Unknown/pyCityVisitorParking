#!/bin/bash
set -e

REPO_DIR="$(git rev-parse --show-toplevel)"
VENV_DIR="$REPO_DIR/.venv"

echo "🐍 Installing Python $(cat "$REPO_DIR/.python-version")..."
uv python install "$(cat "$REPO_DIR/.python-version")"
uv venv "$VENV_DIR" --python "$(cat "$REPO_DIR/.python-version")"

source "$VENV_DIR/bin/activate"

echo "📦 Installing package (editable) + dev extras..."
uv pip install -e '.[dev]'

# ── Activate venv in shell profiles ──────────────────────────────
for profile in ~/.bashrc ~/.zshrc; do
  if [ -f "$profile" ] && ! grep -q "$VENV_DIR/bin/activate" "$profile"; then
    echo "source $VENV_DIR/bin/activate" >> "$profile"
  fi
done

echo "🪝 Installing pre-commit hooks..."
cd "$REPO_DIR"
pre-commit install

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Setup complete!"
echo "Venv: $VENV_DIR"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
