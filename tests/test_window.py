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

from gi.repository import Adw, Gdk, GLib

from gnome_rgb.window import Panel, RgbWindow

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


def test_sin_seleccion_automatica_con_varios(window):
    assert window.device_id is None
    assert window._panel is Panel.NO_SELECTION
    assert window.color_button.get_sensitive() is False


def test_seleccion_actualiza_el_panel(window):
    select(window, 1)

    assert window.device_id == "fake:1"
    assert "Teclado" in window.title.get_text()


def test_controles_desactivados_mientras_carga(window):
    window.listbox.select_row(window.listbox.get_row_at_index(1))

    assert window._panel is Panel.LOADING
    assert window.color_button.get_sensitive() is False

    pump(0.3)
    assert window.color_button.get_sensitive() is True


def test_resultado_de_otra_seleccion_no_toca_el_panel(window):
    select(window, 0)
    revision = window.selection_revision
    stale = window.backend.info("fake:0")
    select(window, 1)

    window._finish(
        window._generation, revision, window.request_id, "fake:0", stale, "", None, None
    )
    pump(0.1)

    assert "Teclado" in window.title.get_text()
    assert window.device_id == "fake:1"


def test_restauracion_ambigua_no_elige(window):
    window._restore = {"vendor": "Demo"}
    window.reload()
    pump(1.0)

    assert window.device_id is None
    assert window._panel is Panel.NO_SELECTION
    assert "varias coincidencias" in window.status.get_text()


def test_cambiar_de_dispositivo_cancela_brillo(window):
    select(window, 0)
    window.brightness.set_value(42)
    pump(0.05)
    assert window._bright_timer is not None

    window.listbox.select_row(window.listbox.get_row_at_index(1))
    assert window._bright_timer is None


def test_color_deshabilitado_en_modo_sin_color(window):
    select(window, 0)
    window.mode_dropdown.set_selected(2)  # Rainbow
    pump(0.5)

    assert window.color_button.get_sensitive() is False


def test_color_abierto_para_otro_dispositivo_se_descarta(window):
    select(window, 0)
    target = (window._generation, window.selection_revision, "fake:0")
    select(window, 1)

    window._apply_color(target, Gdk.RGBA(red=1.0, green=0.0, blue=0.0, alpha=1.0))

    assert "Se descartó el color" in window.status.get_text()


def test_shutdown_detiene_el_trabajador(window):
    worker = window.worker
    window.shutdown()

    assert not worker._thread.is_alive()
    assert window.backend is None
