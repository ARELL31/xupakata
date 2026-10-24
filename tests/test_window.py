"""Pruebas de la ventana. Requieren sesión gráfica (DISPLAY)."""
import os
import time

import pytest

pytest.importorskip("gi")

if not os.environ.get("DISPLAY"):
    pytest.skip("requiere sesión gráfica", allow_module_level=True)

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib

from gnome_rgb.window import RgbWindow

_counter = iter(range(1000))


def pump(seconds=1.0):
    end = time.time() + seconds
    while time.time() < end:
        while GLib.MainContext.default().iteration(False):
            pass
        time.sleep(0.01)


@pytest.fixture
def window(monkeypatch):
    monkeypatch.setenv("GNOME_RGB_FAKE", "1")
    app = Adw.Application(application_id=f"io.test.GnomeRgb{next(_counter)}")
    app.register(None)
    win = RgbWindow(app)
    deadline = time.time() + 3
    while win.backend is None and time.time() < deadline:
        pump(0.05)
    assert win.backend is not None
    return win


def select(win, index):
    win.listbox.select_row(win.listbox.get_row_at_index(index))
    pump(0.3)


def test_seleccion_actualiza_el_panel(window):
    select(window, 1)

    assert window.device_address == "0x30"
    assert "0x30" in window.title.get_text()


def test_resultado_antiguo_no_cambia_el_panel(window):
    select(window, 1)
    stale = window.backend.info("0x2e")

    window._finish(window._generation - 1, "0x2e", stale, "")
    pump(0.1)
    assert "0x30" in window.title.get_text()

    window._finish(window._generation, "0x2e", stale, "")
    pump(0.1)
    assert "0x30" in window.title.get_text()


def test_cambiar_de_dispositivo_cancela_brillo(window):
    select(window, 0)
    window.brightness.set_value(42)
    pump(0.05)
    assert window._bright_timer is not None

    window.listbox.select_row(window.listbox.get_row_at_index(1))
    assert window._bright_timer is None
