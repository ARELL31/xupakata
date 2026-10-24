"""Acceso a OpenRGB.

Contrato:
- Cada conexión tiene una época. Los identificadores de dispositivo (ref)
  solo son válidos dentro de su época: tras reconectar hay que volver a
  enumerar. Una ref vieja nunca escribe en otro dispositivo.
- Una sola operación a la vez: el cliente SDK no es seguro entre hilos.
"""
from __future__ import annotations

import contextlib
import os
import threading
import warnings
from typing import TypedDict

from openrgb import OpenRGBClient, utils

HOST = "127.0.0.1"
PORT = 6742


class BackendError(Exception):
    """La operación fue rechazada por OpenRGB o por el dispositivo."""


class ConnectionLost(BackendError):
    """Se perdió la conexión con el servidor; hay que volver a enumerar."""


class DeviceGone(BackendError):
    """La referencia al dispositivo ya no es válida (reconexión o desconexión)."""


class DeviceSummary(TypedDict):
    id: str
    name: str
    vendor: str
    serial: str
    location: str


class DeviceInfo(TypedDict):
    id: str
    name: str
    vendor: str
    serial: str
    location: str
    modes: list[str]
    mode: str
    color_supported: bool
    has_brightness: bool
    brightness: int
    color: tuple[int, int, int] | None


def _meta(device, field: str) -> str:
    metadata = device.metadata
    value = getattr(metadata, field, None) if metadata else None
    return value or ""


def _ref(epoch: int, device) -> str:
    return f"{epoch}:{device.id}"


def _split(ref: str) -> tuple[int, int]:
    epoch, _, device_id = ref.partition(":")
    return int(epoch), int(device_id)


def _brightness_range(mode):
    """(lo, hi) del rango de brillo del modo, o None si no es utilizable.

    Cubre rangos ausentes, constantes e invertidos.
    """
    bottom, top = mode.brightness_min, mode.brightness_max
    if bottom is None or top is None or bottom == top:
        return None
    return min(bottom, top), max(bottom, top)


def _brightness_percent(mode) -> tuple[int, bool]:
    rng = _brightness_range(mode)
    if rng is None:
        return 0, False
    lo, hi = rng
    current = mode.brightness
    if current is None:
        return 0, True
    return round((current - lo) * 100 / (hi - lo)), True


class RgbBackend:
    def __init__(self, host: str = HOST, port: int = PORT):
        self._lock = threading.RLock()
        self._host = host
        self._port = port
        self._client = None
        self._epoch = 0
        self._connect()

    # --- conexión ---

    def _connect(self) -> None:
        try:
            client = OpenRGBClient(
                address=self._host,
                port=self._port,
                name="GNOME RGB",
            )
        except OSError as exc:
            raise BackendError(
                f"servidor OpenRGB no disponible en {self._host}:{self._port}"
            ) from exc
        self._client = client
        self._epoch += 1

    def close(self) -> None:
        with self._lock:
            self._close()

    def _close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            with contextlib.suppress(Exception):
                client.comms.stop_connection()

    def _run(self, fn):
        """Ejecuta fn(client) con acceso exclusivo.

        Una caída invalida la época: no se reintenta a ciegas porque las refs
        anteriores podrían corresponder a otro dispositivo.
        """
        with self._lock:
            if self._client is None:
                self._connect()
            try:
                return fn(self._client)
            except OSError as exc:  # incluye OpenRGBDisconnected y timeouts
                self._close()
                raise ConnectionLost(f"se perdió la conexión con OpenRGB: {exc}") from exc
            except (IndexError, ValueError) as exc:
                raise BackendError(str(exc)) from exc

    def _device(self, client, ref: str):
        epoch, device_id = _split(ref)
        if epoch != self._epoch:
            raise DeviceGone("el dispositivo ya no está disponible: el servidor se reconectó")
        for device in client.devices:
            if device.id == device_id:
                return device
        raise DeviceGone("el dispositivo se desconectó")

    # --- API ---

    def devices(self) -> list[DeviceSummary]:
        return self._run(
            lambda client: [
                {
                    "id": _ref(self._epoch, device),
                    "name": device.name,
                    "vendor": _meta(device, "vendor"),
                    "serial": _meta(device, "serial"),
                    "location": _meta(device, "location"),
                }
                for device in client.devices
            ]
        )

    def info(self, ref: str) -> DeviceInfo:
        def read(client) -> DeviceInfo:
            device = self._device(client, ref)
            mode = (
                device.modes[device.active_mode]
                if device.modes and device.active_mode < len(device.modes)
                else None
            )
            color = None
            if device.colors:
                first = device.colors[0]
                color = (first.red, first.green, first.blue)
            brightness, supported = _brightness_percent(mode) if mode else (0, False)
            return {
                "id": ref,
                "name": device.name,
                "vendor": _meta(device, "vendor"),
                "serial": _meta(device, "serial"),
                "location": _meta(device, "location"),
                "modes": [item.name for item in device.modes],
                "mode": mode.name if mode else "",
                "color_supported": bool(mode and mode.color_mode != utils.ModeColors.NONE),
                "has_brightness": supported,
                "brightness": brightness,
                "color": color,
            }

        return self._run(read)

    def set_color(self, ref: str, red: int, green: int, blue: int) -> None:
        def write(client) -> None:
            device = self._device(client, ref)
            mode = (
                device.modes[device.active_mode]
                if device.modes and device.active_mode < len(device.modes)
                else None
            )
            if mode is None or mode.color_mode == utils.ModeColors.NONE:
                current = mode.name if mode else "desconocido"
                raise BackendError(
                    f"{device.name} en modo {current} no admite color manual; "
                    "elige un modo compatible"
                )
            device.set_color(utils.RGBColor(red, green, blue))

        self._run(write)

    def set_mode(self, ref: str, name: str) -> None:
        def write(client) -> None:
            device = self._device(client, ref)
            if not device.modes:
                raise BackendError(f"{device.name} no expone modos")
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                device.set_mode(name)
            if caught:
                raise BackendError(f"{device.name} no confirmó el modo {name}")

        self._run(write)

    def set_brightness(self, ref: str, percent: int) -> None:
        def write(client) -> None:
            device = self._device(client, ref)
            mode = (
                device.modes[device.active_mode]
                if device.modes and device.active_mode < len(device.modes)
                else None
            )
            rng = _brightness_range(mode) if mode else None
            if rng is None:
                raise BackendError("el modo actual no admite brillo")
            lo, hi = rng
            mode.brightness = lo + round(percent * (hi - lo) / 100)
            device.set_mode(mode)

        self._run(write)


_MODES = [
    {"name": "Direct", "color": True},
    {"name": "Static", "color": True},
    {"name": "Rainbow", "color": False},
]


class FakeBackend:
    """Dispositivos simulados, con estado independiente por módulo."""

    def __init__(self):
        self._devices = [
            {
                "id": "fake:0",
                "name": "Ventilador (simulado)",
                "vendor": "Demo",
                "serial": "SIM-0001",
                "location": "USB demo, address 0x2e",
            },
            {
                "id": "fake:1",
                "name": "Teclado (simulado)",
                "vendor": "Demo",
                "serial": "SIM-0002",
                "location": "USB demo, address 0x30",
            },
        ]
        self._state = {
            device["id"]: {
                "mode": "Direct",
                "brightness": 100,
                "color": (229, 165, 10),
            }
            for device in self._devices
        }

    def close(self) -> None:
        pass

    def devices(self) -> list[DeviceSummary]:
        return [dict(device) for device in self._devices]

    def info(self, ref: str) -> DeviceInfo:
        device = next(d for d in self._devices if d["id"] == ref)
        state = self._state[ref]
        current = next(m for m in _MODES if m["name"] == state["mode"])
        return {
            "id": ref,
            "name": device["name"],
            "vendor": device["vendor"],
            "serial": device["serial"],
            "location": device["location"],
            "modes": [m["name"] for m in _MODES],
            "mode": state["mode"],
            "color_supported": current["color"],
            "has_brightness": True,
            "brightness": state["brightness"],
            "color": state["color"],
        }

    def set_color(self, ref: str, red: int, green: int, blue: int) -> None:
        current = next(m for m in _MODES if m["name"] == self._state[ref]["mode"])
        if not current["color"]:
            raise BackendError(
                f"el modo {current['name']} no admite color manual; elige un modo compatible"
            )
        self._state[ref]["color"] = (red, green, blue)

    def set_mode(self, ref: str, name: str) -> None:
        self._state[ref]["mode"] = name

    def set_brightness(self, ref: str, percent: int) -> None:
        self._state[ref]["brightness"] = percent


def connect(host: str = HOST, port: int = PORT) -> RgbBackend | FakeBackend:
    if os.environ.get("GNOME_RGB_FAKE"):
        return FakeBackend()
    return RgbBackend(host, port)
