#!/usr/bin/env bash
# GNOME RGB — entorno virtual y dependencias del proyecto.
# Uso:  ./scripts/bootstrap.sh   (desde cualquier directorio)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

die()  { echo "error: $*" >&2; exit 1; }
step() { echo; echo "==> $*"; }

[ "$(id -u)" -eq 0 ] && die "no ejecutes este script con sudo: las dependencias de Python deben quedar en tu usuario"

mkdir -p src/gnome_rgb/{models,widgets,services} \
         data/icons/{scalable,symbolic} \
         data/illustrations/{keyboards,fans,controllers} \
         data/ui tests docs snap

step "Entorno virtual"
if ! command -v uv >/dev/null 2>&1 && [ -x "$HOME/.local/bin/uv" ]; then
  export PATH="$HOME/.local/bin:$PATH"
fi
command -v uv >/dev/null 2>&1 || die "falta uv (ejecuta ./scripts/install.sh design)"

if [ ! -d .venv ]; then
  uv venv --python /usr/bin/python3 --system-site-packages .venv
fi
uv pip install -e . pytest ruff

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
echo "  source .venv/bin/activate && python -m gnome_rgb"
