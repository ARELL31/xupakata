import warnings
from types import SimpleNamespace

import pytest
from openrgb import utils

from gnome_rgb import backend


class FakeDevice:
    def __init__(self, color_mode=utils.ModeColors.PER_LED):
        self.name = "ENE DRAM"
        self.metadata = SimpleNamespace(
            location="I2C: SMBus PIIX4 adapter port 0 at 0b00 (/dev/i2c-0), address 0x70"
        )
        self.colors = [SimpleNamespace(red=53, green=132, blue=228)]
        self.modes = [
            SimpleNamespace(
                name="Direct",
                color_mode=utils.ModeColors.PER_LED,
                brightness_max=100,
                brightness=50,
            ),
            SimpleNamespace(
                name="Rainbow",
                color_mode=utils.ModeColors.NONE,
                brightness_max=100,
                brightness=50,
            ),
        ]
        self.active_mode = 0 if color_mode == utils.ModeColors.PER_LED else 1
        self.calls = []

    def set_mode(self, mode):
        self.calls.append(("mode", mode))
        if isinstance(mode, str):
            self.active_mode = next(i for i, m in enumerate(self.modes) if m.name == mode)

    def set_color(self, color):
        self.calls.append(("color", color))


class FakeComms:
    def __init__(self):
        self.closed = False

    def stop_connection(self):
        self.closed = True


class FakeClient:
    def __init__(self, devices):
        self.devices = devices
        self.comms = FakeComms()


def install(monkeypatch, *devices):
    monkeypatch.setattr(backend, "OpenRGBClient", lambda **_kw: FakeClient(list(devices)))
    return backend.RgbBackend()


def test_set_color_traduce_rgb(monkeypatch):
    device = FakeDevice()
    client = install(monkeypatch, device)

    client.set_color("0x70", 10, 20, 30)

    assert [c[0] for c in device.calls] == ["color"]
    color = device.calls[0][1]
    assert (color.red, color.green, color.blue) == (10, 20, 30)


def test_cambia_a_direct_si_el_modo_no_admite_color(monkeypatch):
    device = FakeDevice(utils.ModeColors.NONE)
    client = install(monkeypatch, device)

    client.set_color("0x70", 255, 0, 0)

    assert device.calls[0] == ("mode", "Direct")
    assert device.calls[1][0] == "color"


def test_info_expone_modos_y_brillo(monkeypatch):
    client = install(monkeypatch, FakeDevice())

    info = client.info("0x70")

    assert info["modes"] == ["Direct", "Rainbow"]
    assert info["mode"] == "Direct"
    assert info["has_brightness"] is True
    assert info["brightness"] == 50
    assert info["address"] == "0x70"
    assert info["color"] == (53, 132, 228)


def test_devices_expone_direccion(monkeypatch):
    client = install(monkeypatch, FakeDevice(), FakeDevice())

    assert client.devices() == [
        {"name": "ENE DRAM", "address": "0x70"},
        {"name": "ENE DRAM", "address": "0x70"},
    ]


def test_dispositivo_inexistente(monkeypatch):
    client = install(monkeypatch, FakeDevice())

    with pytest.raises(backend.BackendError, match="no existe"):
        client.info("0x99")


def test_set_brightness_escala_al_maximo(monkeypatch):
    device = FakeDevice()
    client = install(monkeypatch, device)

    client.set_brightness("0x70", 40)

    assert device.modes[0].brightness == 40


def test_brightness_falla_si_el_modo_no_lo_admite(monkeypatch):
    device = FakeDevice()
    device.modes[0].brightness_max = 0
    client = install(monkeypatch, device)

    with pytest.raises(backend.BackendError):
        client.set_brightness("0x70", 40)


def test_modo_no_confirmado(monkeypatch):
    device = FakeDevice()
    client = install(monkeypatch, device)

    def not_confirmed(_mode):
        warnings.warn("no confirmado")

    device.set_mode = not_confirmed

    with pytest.raises(backend.BackendError, match="no confirmó"):
        client.set_mode("0x70", "Static")


def test_reintenta_una_vez_tras_caida(monkeypatch):
    device = FakeDevice()
    client = install(monkeypatch, device)
    original = device.set_color
    attempts = []

    def flaky(color):
        attempts.append(color)
        if len(attempts) == 1:
            raise OSError("caída")
        original(color)

    device.set_color = flaky

    client.set_color("0x70", 1, 2, 3)

    assert len(attempts) == 2
    assert device.calls[-1][0] == "color"


def test_cierra_la_conexion_al_perderla(monkeypatch):
    device = FakeDevice()
    client = install(monkeypatch, device)
    first = client._client

    def always_fails(_color):
        raise OSError("caída")

    device.set_color = always_fails

    with pytest.raises(backend.BackendError):
        client.set_color("0x70", 1, 2, 3)

    assert first.comms.closed is True
    assert client._client is None


def test_error_si_no_hay_servidor(monkeypatch):
    def refuse(**_kw):
        raise ConnectionRefusedError

    monkeypatch.setattr(backend, "OpenRGBClient", refuse)

    with pytest.raises(backend.BackendError):
        backend.RgbBackend()


def test_fake_backend_estado_independiente():
    fake = backend.FakeBackend()
    fake.set_color("0x2e", 255, 0, 0)
    fake.set_mode("0x2e", "Rainbow")
    fake.set_brightness("0x2e", 25)

    assert fake.info("0x2e")["color"] == (255, 0, 0)
    assert fake.info("0x2e")["mode"] == "Rainbow"
    assert fake.info("0x2e")["brightness"] == 25
    assert fake.info("0x30")["mode"] == "Direct"
    assert fake.info("0x30")["color"] != (255, 0, 0)
