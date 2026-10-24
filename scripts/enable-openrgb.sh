#!/usr/bin/env bash
# Permisos para OpenRGB: i2c-dev y reglas udev.
# Necesario para controlar RAM y otros dispositivos por SMBus sin sudo.
set -euo pipefail

BIN="${OPENRGB_BIN:-$HOME/.local/opt/openrgb/OpenRGB.AppImage}"
RULES="/etc/udev/rules.d/60-openrgb.rules"

die() { echo "error: $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] && die "ejecútalo sin sudo: el script pide contraseña solo donde hace falta"
[ -x "$BIN" ] || die "no existe $BIN (ejecuta ./scripts/install.sh openrgb)"

echo "==> módulo i2c-dev"
sudo modprobe i2c-dev
echo i2c-dev | sudo tee /etc/modules-load.d/i2c-dev.conf >/dev/null

echo "==> reglas udev"
tmp="$(mktemp)"
"$BIN" --generate-udev-rules "$tmp" >/dev/null
sudo install -m 0644 "$tmp" "$RULES"
rm -f "$tmp"
sudo udevadm control --reload-rules
sudo udevadm trigger

echo "==> buses i2c"
ls /dev/i2c-* 2>/dev/null | tr '\n' ' '; echo

echo "==> dispositivos detectados"
"$BIN" --list-devices

echo
echo "si falta la RAM: añade acpi_enforce_resources=lax a GRUB_CMDLINE_LINUX_DEFAULT,"
echo "ejecuta 'sudo update-grub' y reinicia."
