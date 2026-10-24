import pytest

from gnome_rgb import backend


class FakeDevice:
    def __init__(self):
        self.colors = []

    def set_color(self, color):
        self.colors.append(color)


class FakeClient:
    def __init__(self, devices):
        self.devices = devices


def test_set_color_traduce_rgb(monkeypatch):
    device = FakeDevice()
    monkeypatch.setattr(backend, "OpenRGBClient", lambda **_kw: FakeClient([device]))

    client = backend.RgbBackend()
    client.set_color(0, 10, 20, 30)

    color = device.colors[0]
    assert (color.red, color.green, color.blue) == (10, 20, 30)


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
