"""Cliente mínimo sobre openrgb-python."""
from __future__ import annotations

import contextlib
import os
import threading

from openrgb import OpenRGBClient, utils

HOST = "127.0.0.1"
PORT = 6742


class BackendError(Exception):
    """No se pudo hablar con el servidor OpenRGB."""


def _address(device) -> str:
    """Dirección SMBus del dispositivo (p. ej. 0x70), si la reporta."""
    location = device.metadata.location or ""
    _, _, tail = location.partition("address ")
    return tail.strip()


class RgbBackend:
    def __init__(self, host: str = HOST, port: int = PORT):
        self._lock = threading.RLock()
        self._host = host
        self._port = port
        self._client = None
        self._connect()

    def _connect(self) -> None:
        try:
            self._client = OpenRGBClient(
                address=self._host, port=self._port, name="GNOME RGB"
            )
        except OSError as exc:
            raise BackendError(
                f"servidor OpenRGB no disponible en {self._host}:{self._port}"
            ) from exc

    def _close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            with contextlib.suppress(Exception):
                client.comms.stop_connection()

    def _run(self, fn, retry: bool = True):
        """Serializa el acceso: un cliente SDK no admite hilos en paralelo."""
        with self._lock:
            if self._client is None:
                self._connect()
            try:
                return fn(self._client)
            except OSError as exc:  # incluye OpenRGBDisconnected y timeouts
                self._close()
                if retry:
                    return self._run(fn, retry=False)
                raise BackendError(f"se perdió la conexión con OpenRGB: {exc}") from exc
            except (IndexError, ValueError) as exc:
                raise BackendError(str(exc)) from exc

    def devices(self) -> list[dict]:
        return self._run(
            lambda client: [
                {"name": device.name, "address": _address(device)}
                for device in client.devices
            ]
        )

    def info(self, index: int) -> dict:
        def read(client):
            device = client.devices[index]
            mode = device.modes[device.active_mode]
            top = mode.brightness_max or 0
            brightness = 0
            if top and mode.brightness is not None:
                brightness = round(mode.brightness * 100 / top)
            color = None
            if device.colors:
                first = device.colors[0]
                color = (first.red, first.green, first.blue)
            return {
                "name": device.name,
                "address": _address(device),
                "modes": [item.name for item in device.modes],
                "mode": mode.name,
                "has_brightness": top > 0,
                "brightness": brightness,
                "color": color,
            }

        return self._run(read)

    def set_color(self, index: int, red: int, green: int, blue: int) -> None:
        def write(client):
            device = client.devices[index]
            if device.modes[device.active_mode].color_mode == utils.ModeColors.NONE:
                # Rainbow, Spectrum Cycle… no aceptan color por LED: no se envía nada.
                device.set_mode("Direct")
            device.set_color(utils.RGBColor(red, green, blue))

        self._run(write)

    def set_mode(self, index: int, name: str) -> None:
        self._run(lambda client: client.devices[index].set_mode(name))

    def set_brightness(self, index: int, percent: int) -> None:
        def write(client):
            device = client.devices[index]
            mode = device.modes[device.active_mode]
            if not mode.brightness_max:
                raise BackendError("el modo actual no admite brillo")
            mode.brightness = round(mode.brightness_max * percent / 100)
            device.set_mode(mode)

        self._run(write)


class FakeBackend:
    """Dispositivos simulados para trabajar sin hardware."""

    def __init__(self):
        self.colors: dict[int, tuple[int, int, int]] = {}
        self.modes = ["Direct", "Static", "Rainbow"]
        self.mode = "Direct"
        self.brightness = 100

    def devices(self) -> list[dict]:
        return [
            {"name": "Ventilador (simulado)", "address": "0x2e"},
            {"name": "Teclado (simulado)", "address": "0x30"},
        ]

    def info(self, index: int) -> dict:
        return {
            "name": self.devices()[index]["name"],
            "address": self.devices()[index]["address"],
            "modes": self.modes,
            "mode": self.mode,
            "has_brightness": True,
            "brightness": self.brightness,
            "color": self.colors.get(index, (229, 165, 10)),
        }

    def set_color(self, index: int, red: int, green: int, blue: int) -> None:
        self.colors[index] = (red, green, blue)

    def set_mode(self, index: int, name: str) -> None:
        self.mode = name

    def set_brightness(self, index: int, percent: int) -> None:
        self.brightness = percent


def connect(host: str = HOST, port: int = PORT) -> RgbBackend | FakeBackend:
    if os.environ.get("GNOME_RGB_FAKE"):
        return FakeBackend()
    return RgbBackend(host, port)
