"""Pruebas de la ventana. Requieren sesión gráfica."""
import os
import threading
import time

import pytest

pytest.importorskip("gi")

if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
    pytest.skip("requiere sesión gráfica", allow_module_level=True)

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib

from xupakata.backend import ConnectionLost
from xupakata.window import Panel, RgbWindow

_counter = iter(range(1000))


def pump(seconds=1.0):
    end = time.time() + seconds
    while time.time() < end:
        while GLib.MainContext.default().iteration(False):
            pass
        time.sleep(0.01)


def wait_for(predicate, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        pump(0.02)
    return predicate()


@pytest.fixture
def window(monkeypatch):
    monkeypatch.setenv("XUPAKATA_FAKE", "1")
    app = Adw.Application(application_id=f"io.test.Xupakata{next(_counter)}")
    app.register(None)
    win = RgbWindow(app)
    assert wait_for(lambda: win.backend is not None, timeout=3.0)
    yield win
    win.shutdown()
    win.destroy()


def select(win, index):
    win.listbox.select_row(win.listbox.get_row_at_index(index))
    assert wait_for(lambda: win._panel in (Panel.READY, Panel.ERROR, Panel.NO_SELECTION))


def test_sin_seleccion_automatica_con_varios(window):
    assert window.device_id is None
    assert window._panel is Panel.NO_SELECTION
    assert window.color_button.get_sensitive() is False


def test_seleccion_actualiza_el_panel(window):
    select(window, 1)

    assert window.device_id == "fake:1"
    assert "Teclado" in window.title.get_text()


def test_ficha_de_memoria_usa_su_ilustracion(window):
    select(window, 2)

    assert "Memoria RAM" in window.subtitle.get_text()
    assert window._illustration_kind == "dram"
    assert window._info_rows["type"].get_subtitle() == "Memoria RAM"


def test_controles_desactivados_mientras_carga(window):
    window.listbox.select_row(window.listbox.get_row_at_index(1))

    assert window._panel is Panel.LOADING
    assert window.color_button.get_sensitive() is False

    assert wait_for(lambda: window._panel is Panel.READY)
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


def test_resultado_obsoleto_no_cambia_estado(window):
    select(window, 1)
    before = (window._panel, window._message, window.device_id)

    window._finish(
        window._generation,
        window.selection_revision - 1,
        window.request_id,
        "fake:0",
        None,
        "aplicado",
        RuntimeError("fallo"),
        None,
    )

    assert (window._panel, window._message, window.device_id) == before


def test_restauracion_ambigua_no_elige(window):
    window._restore = {"vendor": "Demo"}
    window.reload()
    assert wait_for(lambda: window._panel is Panel.NO_SELECTION, timeout=3.0)

    assert window.device_id is None
    assert "varias coincidencias" in window._message


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
    assert wait_for(lambda: window._panel is Panel.READY and not window.color_button.get_sensitive())

    assert window.color_button.get_sensitive() is False


def test_color_abierto_para_otro_dispositivo_se_descarta(window):
    select(window, 0)
    target = (window._generation, window.selection_revision, "fake:0")
    select(window, 1)

    window._apply_color(target, Gdk.RGBA(red=1.0, green=0.0, blue=0.0, alpha=1.0))

    assert "Se descartó el color" in window._message


def test_un_solo_reintento_automatico_por_incidente(window):
    generation = window._generation
    window._load_failed(generation, window.selection_revision, ConnectionLost("caída"))

    assert window._generation == generation + 1
    assert wait_for(lambda: window.backend is not None, timeout=3.0)
    assert window._auto_reconnect_used is False


def test_sin_bucle_de_reconexion(window):
    window._auto_reconnect_used = True
    generation = window._generation

    window._load_failed(generation, window.selection_revision, ConnectionLost("caída"))

    assert window._generation == generation
    assert window._panel is Panel.ERROR
    assert "Reconectar" in window._message


def test_cierre_durante_trabajo_termina(window):
    started = threading.Event()

    def slow():
        started.set()
        time.sleep(0.2)

    window.worker.submit(slow)
    assert started.wait(1)
    worker = window.worker

    window.shutdown()

    assert wait_for(lambda: not worker._thread.is_alive())
    assert window.backend is None


def test_callback_tras_cierre_se_ignora(window):
    generation = window._generation
    revision = window.selection_revision
    window.shutdown()

    window._finish(generation, revision, window.request_id, "fake:0", None, "aplicado", None, None)

    assert window._message != "aplicado"
    assert not window.worker._thread.is_alive()
