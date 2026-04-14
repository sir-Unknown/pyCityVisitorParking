#!/bin/bash
set -e

REPO_DIR="$(git rev-parse --show-toplevel)"
VENV_DIR="$REPO_DIR/.venv"

echo "📦 Installing package (editable) + dev extras..."
cd "$REPO_DIR"
uv sync --group dev

# ── Activate venv in shell profiles ──────────────────────────────
for profile in ~/.bashrc ~/.zshrc; do
  if [ -f "$profile" ] && ! grep -q "$VENV_DIR/bin/activate" "$profile"; then
    echo "source $VENV_DIR/bin/activate" >> "$profile"
  fi
done

echo "🪝 Installing pre-commit hooks..."
uv run pre-commit install

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Setup complete!"
echo "Venv: $VENV_DIR"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
