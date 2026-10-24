from types import SimpleNamespace

import pytest
from openrgb import utils

from gnome_rgb import backend


class FakeDevice:
    def __init__(self, color_mode=utils.ModeColors.PER_LED):
        self.modes = [
            SimpleNamespace(name="Direct", color_mode=utils.ModeColors.PER_LED),
            SimpleNamespace(name="Rainbow", color_mode=utils.ModeColors.NONE),
        ]
        self.active_mode = 0 if color_mode == utils.ModeColors.PER_LED else 1
        self.calls = []

    def set_mode(self, name):
        self.calls.append(("mode", name))

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


def test_error_si_no_hay_servidor(monkeypatch):
    def refuse(**_kw):
        raise ConnectionRefusedError

    monkeypatch.setattr(backend, "OpenRGBClient", refuse)

    with pytest.raises(backend.BackendError):
        backend.RgbBackend()


def test_fake_backend_para_desarrollo():
    fake = backend.FakeBackend()
    fake.set_color(1, 255, 0, 0)
    assert fake.colors[1] == (255, 0, 0)
    assert len(fake.devices()) == 2
