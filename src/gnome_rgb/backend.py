"""Cliente mínimo sobre openrgb-python."""
from __future__ import annotations

import os

from openrgb import OpenRGBClient, utils

HOST = "127.0.0.1"
PORT = 6742


class BackendError(Exception):
    """No se pudo hablar con el servidor OpenRGB."""


class RgbBackend:
    def __init__(self, host: str = HOST, port: int = PORT):
        try:
            self._client = OpenRGBClient(address=host, port=port, name="GNOME RGB")
        except OSError as exc:
            raise BackendError(f"servidor OpenRGB no disponible en {host}:{port}") from exc

    def devices(self) -> list[str]:
        return [device.name for device in self._client.devices]

    def set_color(self, index: int, red: int, green: int, blue: int) -> None:
        try:
            device = self._client.devices[index]
            if device.modes[device.active_mode].color_mode == utils.ModeColors.NONE:
                # Rainbow, Spectrum Cycle… no aceptan color por LED: no se envía nada.
                device.set_mode("Direct")
            device.set_color(utils.RGBColor(red, green, blue))
        except (OSError, IndexError, ValueError) as exc:
            raise BackendError(str(exc)) from exc


class FakeBackend:
    """Dispositivos simulados para trabajar sin hardware."""

    def __init__(self):
        self.colors: dict[int, tuple[int, int, int]] = {}

    def devices(self) -> list[str]:
        return ["Ventilador (simulado)", "Teclado (simulado)"]

    def set_color(self, index: int, red: int, green: int, blue: int) -> None:
        self.colors[index] = (red, green, blue)


def connect(host: str = HOST, port: int = PORT) -> RgbBackend | FakeBackend:
    if os.environ.get("GNOME_RGB_FAKE"):
        return FakeBackend()
    return RgbBackend(host, port)
