#!/usr/bin/env bash
# GNOME RGB — estructura del proyecto, entorno virtual y primer commit.
# Uso:  ./scripts/bootstrap.sh   (desde cualquier directorio)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

die()  { echo "error: $*" >&2; exit 1; }
step() { echo; echo "==> $*"; }

mkdir -p src/gnome_rgb/{backend,models,widgets,services} \
         data/icons/{scalable,symbolic} \
         data/illustrations/{keyboards,fans,controllers} \
         data/ui tests docs snap

step "Archivos base"
cat > .gitignore <<'EOF'
.venv/
__pycache__/
.pytest_cache/
.ruff_cache/
*.pyc
build/
dist/
*.snap
EOF

cat > pyproject.toml <<'EOF'
[project]
name = "gnome-rgb"
version = "0.1.0"
description = "Control de iluminación RGB para GNOME"
requires-python = ">=3.12"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.pytest.ini_options]
testpaths = ["tests"]
EOF

touch src/gnome_rgb/__init__.py tests/.gitkeep

cat > opencode.json <<'EOF'
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "inkscape": {
      "type": "local",
      "command": ["uvx", "inkscape_mcp"],
      "enabled": true,
      "timeout": 120000
    }
  },
  "instructions": ["docs/gnome-icon-guidelines.md"]
}
EOF

step "Entorno virtual"
if ! command -v uv >/dev/null 2>&1 && [ -x "$HOME/.local/bin/uv" ]; then
  export PATH="$HOME/.local/bin:$PATH"
fi
command -v uv >/dev/null 2>&1 || die "falta uv (ejecuta ./scripts/install.sh design)"

if [ ! -d .venv ]; then
  uv venv --python /usr/bin/python3 --system-site-packages .venv
fi
uv pip install --python .venv/bin/python openrgb-python pytest ruff

step "Git"
[ -d .git ] || git init -q
if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
  git add .
  if [ -n "$(git config user.email || true)" ]; then
    git commit -qm "Estructura inicial del proyecto"
  else
    echo "git sin user.email: configura tu identidad y luego:"
    echo "  git commit -m 'Estructura inicial del proyecto'"
  fi
fi

echo
echo "listo: $ROOT"
echo "  source .venv/bin/activate && python demo.py"
