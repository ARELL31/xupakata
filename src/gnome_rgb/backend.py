"""Acceso a OpenRGB.

Contrato:
- Los dispositivos se identifican por su dirección SMBus, no por su posición
  en la lista: la posición puede cambiar tras reconectar.
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


class DeviceSummary(TypedDict):
    name: str
    address: str


class DeviceInfo(TypedDict):
    name: str
    address: str
    modes: list[str]
    mode: str
    has_brightness: bool
    brightness: int
    color: tuple[int, int, int] | None


class BackendError(Exception):
    """No se pudo hablar con el servidor OpenRGB."""


def _address(device) -> str:
    """Dirección SMBus del dispositivo (p. ej. 0x70), si la reporta."""
    location = device.metadata.location or ""
    _, _, tail = location.partition("address ")
    return tail.strip()


def _key(device) -> str:
    """Identidad estable del dispositivo.

    SMBus: la dirección. USB sin dirección: el nombre.
    ponytail: dos USB con el mismo nombre no se distinguen; añadir serial
    cuando aparezca hardware así.
    """
    return _address(device) or device.name


class RgbBackend:
    def __init__(self, host: str = HOST, port: int = PORT):
        self._lock = threading.RLock()
        self._host = host
        self._port = port
        self._client = None
        self._connect()

    # --- conexión ---

    def _connect(self) -> None:
        try:
            self._client = OpenRGBClient(
                address=self._host,
                port=self._port,
                name="GNOME RGB",
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
        """Ejecuta fn(client) con acceso exclusivo.

        Si se pierde la conexión se reconecta y reintenta una vez. Es seguro
        porque cada operación se vuelve a resolver por dirección, nunca por
        posición en la lista.
        """
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
            except (IndexError, KeyError, ValueError) as exc:
                raise BackendError(str(exc)) from exc

    @staticmethod
    def _device(client, address: str):
        for device in client.devices:
            if _key(device) == address:
                return device
        raise KeyError(f"no existe el dispositivo {address}")

    # --- API ---

    def devices(self) -> list[DeviceSummary]:
        return self._run(
            lambda client: [
                {"name": device.name, "address": _key(device)}
                for device in client.devices
            ]
        )

    def info(self, address: str) -> DeviceInfo:
        def read(client) -> DeviceInfo:
            device = self._device(client, address)
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
                "address": address,
                "modes": [item.name for item in device.modes],
                "mode": mode.name,
                "has_brightness": top > 0,
                "brightness": brightness,
                "color": color,
            }

        return self._run(read)

    def set_color(self, address: str, red: int, green: int, blue: int) -> None:
        def write(client) -> None:
            device = self._device(client, address)
            if device.modes[device.active_mode].color_mode == utils.ModeColors.NONE:
                # Rainbow, Spectrum Cycle… no aceptan color por LED: no se envía nada.
                device.set_mode("Direct")
            device.set_color(utils.RGBColor(red, green, blue))

        self._run(write)

    def set_mode(self, address: str, name: str) -> None:
        def write(client) -> None:
            device = self._device(client, address)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                device.set_mode(name)
            if caught:
                raise BackendError(f"{device.name} no confirmó el modo {name}")

        self._run(write)

    def set_brightness(self, address: str, percent: int) -> None:
        def write(client) -> None:
            device = self._device(client, address)
            mode = device.modes[device.active_mode]
            if not mode.brightness_max:
                raise BackendError("el modo actual no admite brillo")
            mode.brightness = round(mode.brightness_max * percent / 100)
            device.set_mode(mode)

        self._run(write)


class FakeBackend:
    """Dispositivos simulados, con estado independiente por módulo."""

    def __init__(self):
        self._devices = [
            {"name": "Ventilador (simulado)", "address": "0x2e"},
            {"name": "Teclado (simulado)", "address": "0x30"},
        ]
        self._state = {
            "0x2e": {"mode": "Direct", "brightness": 100, "color": (229, 165, 10)},
            "0x30": {"mode": "Direct", "brightness": 60, "color": (53, 132, 228)},
        }

    def devices(self) -> list[DeviceSummary]:
        return [dict(device) for device in self._devices]

    def info(self, address: str) -> DeviceInfo:
        device = next(d for d in self._devices if d["address"] == address)
        state = self._state[address]
        return {
            "name": device["name"],
            "address": address,
            "modes": ["Direct", "Static", "Rainbow"],
            "mode": state["mode"],
            "has_brightness": True,
            "brightness": state["brightness"],
            "color": state["color"],
        }

    def set_color(self, address: str, red: int, green: int, blue: int) -> None:
        self._state[address]["color"] = (red, green, blue)

    def set_mode(self, address: str, name: str) -> None:
        self._state[address]["mode"] = name

    def set_brightness(self, address: str, percent: int) -> None:
        self._state[address]["brightness"] = percent


def connect(host: str = HOST, port: int = PORT) -> RgbBackend | FakeBackend:
    if os.environ.get("GNOME_RGB_FAKE"):
        return FakeBackend()
    return RgbBackend(host, port)
