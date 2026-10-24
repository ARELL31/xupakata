from types import SimpleNamespace

import pytest
from openrgb import utils

from gnome_rgb import backend


class FakeDevice:
    def __init__(self, color_mode=utils.ModeColors.PER_LED):
        self.name = "ENE DRAM"
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


class FakeClient:
    def __init__(self, devices):
        self.devices = devices


def install(monkeypatch, *devices):
    monkeypatch.setattr(backend, "OpenRGBClient", lambda **_kw: FakeClient(list(devices)))
    return backend.RgbBackend()


def test_set_color_traduce_rgb(monkeypatch):
    device = FakeDevice()
    client = install(monkeypatch, device)

    client.set_color(0, 10, 20, 30)

    assert [c[0] for c in device.calls] == ["color"]
    color = device.calls[0][1]
    assert (color.red, color.green, color.blue) == (10, 20, 30)


def test_cambia_a_direct_si_el_modo_no_admite_color(monkeypatch):
    device = FakeDevice(utils.ModeColors.NONE)
    client = install(monkeypatch, device)

    client.set_color(0, 255, 0, 0)

    assert device.calls[0] == ("mode", "Direct")
    assert device.calls[1][0] == "color"


def test_info_expone_modos_y_brillo(monkeypatch):
    client = install(monkeypatch, FakeDevice())

    info = client.info(0)

    assert info["modes"] == ["Direct", "Rainbow"]
    assert info["mode"] == "Direct"
    assert info["has_brightness"] is True
    assert info["brightness"] == 50


def test_set_brightness_escala_al_maximo(monkeypatch):
    device = FakeDevice()
    client = install(monkeypatch, device)

    client.set_brightness(0, 40)

    assert device.modes[0].brightness == 40


def test_brightness_falla_si_el_modo_no_lo_admite(monkeypatch):
    device = FakeDevice()
    device.modes[0].brightness_max = 0
    client = install(monkeypatch, device)

    with pytest.raises(backend.BackendError):
        client.set_brightness(0, 40)


def test_error_si_no_hay_servidor(monkeypatch):
    def refuse(**_kw):
        raise ConnectionRefusedError

    monkeypatch.setattr(backend, "OpenRGBClient", refuse)

    with pytest.raises(backend.BackendError):
        backend.RgbBackend()


def test_fake_backend_para_desarrollo():
    fake = backend.FakeBackend()
    fake.set_color(1, 255, 0, 0)
    fake.set_brightness(0, 30)
    fake.set_mode(0, "Rainbow")

    assert fake.colors[1] == (255, 0, 0)
    assert fake.info(0)["brightness"] == 30
    assert fake.info(0)["mode"] == "Rainbow"
    assert len(fake.devices()) == 2
