import warnings
from types import SimpleNamespace

import pytest
from openrgb import utils

from xupakata import backend


def mode(name, color_mode, brightness_min=0, brightness_max=100, brightness=50):
    return SimpleNamespace(
        name=name,
        color_mode=color_mode,
        brightness_min=brightness_min,
        brightness_max=brightness_max,
        brightness=brightness,
    )


class FakeDevice:
    def __init__(
        self,
        color_mode=utils.ModeColors.PER_LED,
        device_id=0,
        modes=None,
        device_type=utils.DeviceType.DRAM,
    ):
        self.id = device_id
        self.name = "ENE DRAM"
        self.type = device_type
        self.metadata = SimpleNamespace(
            vendor="ENE",
            description="ENE SMBus Device",
            version="v1",
            serial="",
            location="I2C: SMBus PIIX4 adapter port 0 at 0b00 (/dev/i2c-0), address 0x70",
        )
        self.colors = [SimpleNamespace(red=53, green=132, blue=228)]
        if modes is None:
            modes = [
                mode("Direct", utils.ModeColors.PER_LED),
                mode("Rainbow", utils.ModeColors.NONE),
            ]
        self.modes = modes
        self.active_mode = 0 if color_mode == utils.ModeColors.PER_LED else 1
        self.calls = []
        self.updates = 0

    def update(self):
        self.updates += 1

    def set_mode(self, selected):
        self.calls.append(("mode", selected))
        if isinstance(selected, str):
            self.active_mode = next(
                i for i, m in enumerate(self.modes) if m.name == selected
            )

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
    ref = client.devices()[0]["id"]

    client.set_color(ref, 10, 20, 30)

    assert [c[0] for c in device.calls] == ["color"]
    color = device.calls[0][1]
    assert (color.red, color.green, color.blue) == (10, 20, 30)


def test_color_rechazado_si_el_modo_no_lo_admite(monkeypatch):
    device = FakeDevice(utils.ModeColors.NONE)
    client = install(monkeypatch, device)
    ref = client.devices()[0]["id"]

    with pytest.raises(backend.BackendError, match="no admite color"):
        client.set_color(ref, 255, 0, 0)

    assert device.calls == []


def test_info_expone_capacidades(monkeypatch):
    client = install(monkeypatch, FakeDevice())
    ref = client.devices()[0]["id"]

    info = client.info(ref)

    assert info["type"] == "dram"
    assert info["modes"] == ["Direct", "Rainbow"]
    assert info["mode"] == "Direct"
    assert info["color_supported"] is True
    assert info["has_brightness"] is True
    assert info["brightness"] == 50
    assert info["vendor"] == "ENE"
    assert info["color"] == (53, 132, 228)


def test_info_sin_modos_no_falla(monkeypatch):
    client = install(monkeypatch, FakeDevice(modes=[]))
    ref = client.devices()[0]["id"]

    info = client.info(ref)

    assert info["modes"] == []
    assert info["mode"] == ""
    assert info["color_supported"] is False
    assert info["has_brightness"] is False


def test_sin_modos_no_se_puede_cambiar(monkeypatch):
    client = install(monkeypatch, FakeDevice(modes=[]))
    ref = client.devices()[0]["id"]

    with pytest.raises(backend.BackendError, match="no expone modos"):
        client.set_mode(ref, "Direct")


def test_info_refresh_pide_actualizacion(monkeypatch):
    device = FakeDevice()
    client = install(monkeypatch, device)
    ref = client.devices()[0]["id"]

    client.info(ref, refresh=True)
    assert device.updates == 1

    client.info(ref)
    assert device.updates == 1


def test_devices_expone_identidad(monkeypatch):
    client = install(monkeypatch, FakeDevice(device_id=0), FakeDevice(device_id=1))

    devices = client.devices()

    assert [device["id"] for device in devices] == ["1:0", "1:1"]
    assert all(device["name"] == "ENE DRAM" for device in devices)
    assert all(device["type"] == "dram" for device in devices)
    assert all(device["vendor"] == "ENE" for device in devices)


def test_ref_desconocida_no_escribe(monkeypatch):
    client = install(monkeypatch, FakeDevice())
    client.devices()[0]["id"]  # la época actual es 1

    with pytest.raises(backend.DeviceGone):
        client.info("1:7")

    with pytest.raises(backend.DeviceGone):
        client.info("9:0")


def test_set_brightness_escala_al_maximo(monkeypatch):
    device = FakeDevice()
    client = install(monkeypatch, device)
    ref = client.devices()[0]["id"]

    client.set_brightness(ref, 40)

    assert device.modes[0].brightness == 40


def test_brillo_rango_invertido(monkeypatch):
    device = FakeDevice(
        modes=[
            mode("Direct", utils.ModeColors.PER_LED, 200, 0, 50),
            mode("Rainbow", utils.ModeColors.NONE),
        ]
    )
    client = install(monkeypatch, device)
    ref = client.devices()[0]["id"]

    assert client.info(ref)["brightness"] == 25
    client.set_brightness(ref, 40)
    assert device.modes[0].brightness == 80


def test_brillo_constante_no_se_ofrece(monkeypatch):
    device = FakeDevice(
        modes=[mode("Direct", utils.ModeColors.PER_LED, 50, 50, 50)]
    )
    client = install(monkeypatch, device)
    ref = client.devices()[0]["id"]

    assert client.info(ref)["has_brightness"] is False

    with pytest.raises(backend.BackendError, match="no admite brillo"):
        client.set_brightness(ref, 40)


def test_modo_no_confirmado(monkeypatch):
    device = FakeDevice()
    client = install(monkeypatch, device)
    ref = client.devices()[0]["id"]

    def not_confirmed(_mode):
        warnings.warn("no confirmado")

    device.set_mode = not_confirmed

    with pytest.raises(backend.BackendError, match="no confirmó"):
        client.set_mode(ref, "Static")


def test_conexion_perdida_invalida_refs(monkeypatch):
    device = FakeDevice()
    client = install(monkeypatch, device)
    ref = client.devices()[0]["id"]

    def drop(_color):
        raise OSError("caída")

    device.set_color = drop

    with pytest.raises(backend.ConnectionLost):
        client.set_color(ref, 1, 2, 3)
    assert client._client is None

    client.devices()  # reconecta: nueva época
    with pytest.raises(backend.DeviceGone):
        client.set_color(ref, 1, 2, 3)
    assert ("color",) not in [call[0] for call in device.calls]


def test_cierra_la_conexion_al_perderla(monkeypatch):
    device = FakeDevice()
    client = install(monkeypatch, device)
    first = client._client

    def drop(_color):
        raise OSError("caída")

    device.set_color = drop

    with pytest.raises(backend.ConnectionLost):
        client.set_color(client.devices()[0]["id"], 1, 2, 3)

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
    fake.set_color("fake:0", 255, 0, 0)
    fake.set_mode("fake:0", "Rainbow")
    fake.set_brightness("fake:0", 25)

    assert fake.info("fake:0")["color"] == (255, 0, 0)
    assert fake.info("fake:0")["mode"] == "Rainbow"
    assert fake.info("fake:0")["color_supported"] is False
    assert fake.info("fake:0")["brightness"] == 25
    assert fake.info("fake:1")["mode"] == "Direct"
    assert fake.info("fake:1")["color"] != (255, 0, 0)


def test_fake_backend_rechaza_color_en_rainbow():
    fake = backend.FakeBackend()
    fake.set_mode("fake:0", "Rainbow")

    with pytest.raises(backend.BackendError, match="no admite color"):
        fake.set_color("fake:0", 255, 0, 0)
