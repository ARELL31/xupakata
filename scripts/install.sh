#!/usr/bin/env bash
# GNOME RGB — instalación por etapas (Ubuntu 24.04+).
#
# Uso:  ./scripts/install.sh [etapa...]
#
# Etapas:
#   base          compilación y herramientas generales
#   gtk           GTK4, Libadwaita y GNOME Builder
#   openrgb       AppImage de OpenRGB + lanzador del servidor
#   design        Inkscape, portapapeles y uv (para el MCP)
#   design-apps   apps de diseño GNOME desde Flathub (opcional)
#   snap          snapcraft y LXD (solo antes de empaquetar)
#   all           base + gtk + design + openrgb
set -euo pipefail

MIN_UBUNTU="24.04"

die()  { echo "error: $*" >&2; exit 1; }
step() { echo; echo "==> $*"; }
have() { command -v "$1" >/dev/null 2>&1; }

check_ubuntu() {
  # shellcheck disable=SC1091
  . /etc/os-release
  [ "${ID:-}" = "ubuntu" ] || die "se esperaba Ubuntu (encontrado: ${ID:-desconocido})"
  [ "$(printf '%s\n%s\n' "$MIN_UBUNTU" "$VERSION_ID" | sort -V | head -n1)" = "$MIN_UBUNTU" ] \
    || die "se requiere Ubuntu >= $MIN_UBUNTU (tienes $VERSION_ID)"
}

apt_install() {
  sudo apt-get install -y "$@"
}

stage_base() {
  step "Herramientas de desarrollo"
  sudo apt-get update
  apt_install git curl wget build-essential pkg-config \
              python3 python3-dev python3-venv meson ninja-build
  git --version
  python3 --version
  meson --version
}

stage_gtk() {
  step "GTK4 y Libadwaita"
  apt_install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 \
              libadwaita-1-dev libcairo2-dev gobject-introspection gnome-builder
  python3 - <<'PY'
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw  # noqa: F401

print("GTK4: OK")
print("Libadwaita: OK")
PY
}

stage_openrgb() {
  step "OpenRGB"
  local bin="$HOME/.local/opt/openrgb/OpenRGB.AppImage"
  mkdir -p "$(dirname "$bin")" "$HOME/.local/bin"

  if [ ! -x "$bin" ]; then
    local url arch
    case "$(uname -m)" in
      x86_64|x86-64|amd64) arch="x86_64" ;;
      aarch64|arm64)       arch="arm64" ;;
      armv7l|armhf)        arch="armhf" ;;
      *) die "arquitectura no soportada por OpenRGB: $(uname -m)" ;;
    esac
    url=$(curl -fsSL https://api.github.com/repos/CalcProgrammer1/OpenRGB/releases/latest \
      | python3 -c 'import json, sys
arch = sys.argv[1]
d = json.load(sys.stdin)
print(next(a["browser_download_url"] for a in d["assets"]
           if a["name"].endswith(".AppImage") and arch in a["name"]))' "$arch")
    echo "descargando: $url"
    curl -fL --progress-bar -o "$bin" "$url"
    chmod +x "$bin"
  fi

  # Servidor SDK escuchando solo en localhost.
  cat > "$HOME/.local/bin/openrgb-server" <<'SH'
#!/bin/sh
exec "$HOME/.local/opt/openrgb/OpenRGB.AppImage" \
  --server --server-host 127.0.0.1 --server-port 6742 "$@"
SH
  chmod +x "$HOME/.local/bin/openrgb-server"

  echo "servidor:  openrgb-server"
  echo "udev:      https://github.com/CalcProgrammer1/OpenRGB/blob/master/Documentation/UdevRules.md"
}

stage_design() {
  step "Inkscape y uv"
  apt_install inkscape xclip wl-clipboard \
              libcairo2-dev libgirepository-2.0-dev python3-dev pkg-config

  if ! have uv; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  fi
  export PATH="$HOME/.local/bin:$PATH"
  uv --version
  inkscape --version | head -n1
}

stage_design_apps() {
  step "Apps de diseño GNOME (Flathub)"
  if ! have flatpak; then
    apt_install flatpak
  fi
  if ! flatpak remotes --columns=name 2>/dev/null | grep -qx flathub; then
    sudo flatpak remote-add --if-not-exists flathub \
      https://dl.flathub.org/repo/flathub.flatpakrepo
  fi
  flatpak install -y --noninteractive flathub \
    org.gnome.design.AppIconPreview \
    org.gnome.design.SymbolicPreview \
    org.gnome.design.IconLibrary
}

stage_snap() {
  step "Snapcraft y LXD"
  sudo snap install snapcraft --classic
  sudo snap install lxd
  sudo usermod -aG lxd "$USER"
  if ! sudo lxc profile list >/dev/null 2>&1; then
    sudo lxd init --auto
  fi
  snapcraft --version
  echo "cierra sesión y vuelve a entrar para usar LXD sin sudo"
}

usage() {
  sed -n '/^# Uso:/,/^#   all/p' "$0" | sed 's/^# \{0,1\}//'
}

main() {
  [ "$#" -gt 0 ] || { usage; exit 1; }
  check_ubuntu

  for stage in "$@"; do
    case "$stage" in
      base)         stage_base ;;
      gtk)          stage_gtk ;;
      openrgb)      stage_openrgb ;;
      design)       stage_design ;;
      design-apps)  stage_design_apps ;;
      snap)         stage_snap ;;
      all)          stage_base; stage_gtk; stage_design; stage_openrgb ;;
      -h|--help)    usage; exit 0 ;;
      *)            die "etapa desconocida: $stage" ;;
    esac
  done

  echo
  echo "siguiente: ./scripts/bootstrap.sh"
}

main "$@"
