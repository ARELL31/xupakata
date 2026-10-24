"""Ventana principal: dispositivos, color, modo y brillo.

Las operaciones de red se ejecutan en un solo hilo auxiliar, en orden, y sus
resultados se aplican a la interfaz solo si siguen correspondiendo al
dispositivo seleccionado.
"""
import queue
import threading
import traceback

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Gtk

from .backend import connect


def _subtitle(address: str) -> str:
    return f"SMBus {address}" if address.startswith("0x") else ""


class RgbWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(
            application=app,
            title="GNOME RGB",
            default_width=900,
            default_height=600,
        )

        self.backend = None
        self.device_address = None
        self._generation = 0
        self._loading = False
        self._bright_timer = None

        self._jobs = queue.Queue()
        threading.Thread(target=self._work_loop, daemon=True).start()

        header = Adw.HeaderBar()
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Reconectar")
        refresh.connect("clicked", lambda *_: self.reload())
        header.pack_start(refresh)

        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.listbox.add_css_class("boxed-list")
        self.listbox.connect("row-selected", self._on_row_selected)
        sidebar = Gtk.ScrolledWindow(
            child=self.listbox, hscrollbar_policy=Gtk.PolicyType.NEVER
        )

        self.title = Gtk.Label(label="", wrap=True)
        self.title.add_css_class("title-4")
        self.status = Gtk.Label(label="Conectando…", wrap=True)

        self.color_button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(title="Color"))
        self.color_button.connect("notify::rgba", self._on_color)

        self.mode_dropdown = Gtk.DropDown()
        self.mode_dropdown.connect("notify::selected", self._on_mode)

        self.brightness = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL,
            adjustment=Gtk.Adjustment(lower=0, upper=100, step_increment=1),
            width_request=200,
            draw_value=True,
            digits=0,
        )
        self.brightness.connect("value-changed", self._on_brightness)

        self.brightness_label = Gtk.Label(label="Brillo", xalign=0)
        grid = Gtk.Grid(row_spacing=12, column_spacing=12)
        rows = [
            (Gtk.Label(label="Color", xalign=0), self.color_button),
            (Gtk.Label(label="Modo", xalign=0), self.mode_dropdown),
            (self.brightness_label, self.brightness),
        ]
        for position, (label, widget) in enumerate(rows):
            grid.attach(label, 0, position, 1, 1)
            grid.attach(widget, 1, position, 1, 1)

        self.controls = [self.color_button, self.mode_dropdown, self.brightness]
        self._set_controls(False)

        panel = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=18,
            margin_top=24,
            margin_bottom=24,
            margin_start=24,
            margin_end=24,
            valign=Gtk.Align.CENTER,
            halign=Gtk.Align.CENTER,
        )
        panel.append(self.title)
        panel.append(self.status)
        panel.append(grid)

        split = Adw.NavigationSplitView()
        split.set_sidebar(Adw.NavigationPage(title="Dispositivos", child=sidebar))
        split.set_content(Adw.NavigationPage(title="Dispositivo", child=panel))

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(split)
        self.set_content(toolbar)

        self.reload()

    # --- hilo de trabajo ---

    def _work_loop(self):
        while True:
            job = self._jobs.get()
            try:
                job()
            except Exception:  # noqa: BLE001 — el hilo no debe morir en silencio
                traceback.print_exc()

    def _set_controls(self, enabled: bool) -> None:
        for widget in self.controls:
            widget.set_sensitive(enabled)

    # --- conexión ---

    def reload(self):
        self._generation += 1
        generation = self._generation
        self.device_address = None
        self._cancel_brightness()
        self.listbox.remove_all()
        self._set_controls(False)
        self.status.set_text("Conectando…")

        def job():
            try:
                backend = connect()
                devices = backend.devices()
            except Exception as exc:  # noqa: BLE001 — frontera de hilo
                GLib.idle_add(self._fail, generation, str(exc))
                return
            GLib.idle_add(self._loaded, generation, backend, devices)

        self._jobs.put(job)

    def _loaded(self, generation, backend, devices):
        if generation != self._generation:
            return False
        self.backend = backend

        if not devices:
            self.status.set_text("OpenRGB no reportó dispositivos")
            return False

        for device in devices:
            row = Adw.ActionRow(
                title=device["name"],
                subtitle=_subtitle(device["address"]),
            )
            row.address = device["address"]
            self.listbox.append(row)

        self.status.set_text(
            f"{len(devices)} dispositivo" + ("" if len(devices) == 1 else "s")
        )
        self.listbox.select_row(self.listbox.get_row_at_index(0))
        return False

    def _fail(self, generation, message):
        if generation == self._generation:
            self.status.set_text(message)
        return False

    # --- selección ---

    def _on_row_selected(self, _listbox, row):
        if row is None or self.backend is None:
            return
        self.device_address = row.address
        self._cancel_brightness()
        self._set_controls(True)
        self.status.set_text("Leyendo dispositivo…")
        self._load_info(row.address)

    def _load_info(self, address):
        generation = self._generation

        def job():
            try:
                info = self.backend.info(address)
            except Exception as exc:  # noqa: BLE001
                GLib.idle_add(self._fail, generation, f"No se pudo leer el dispositivo: {exc}")
                return
            GLib.idle_add(self._show_if_current, generation, address, info)

        self._jobs.put(job)

    def _show_if_current(self, generation, address, info):
        if generation == self._generation and address == self.device_address:
            self._show_info(info)
            self.status.set_text("")
        return False

    def _show_info(self, info):
        self._loading = True
        self.title.set_text(
            f"{info['name']} · {info['address']}" if _subtitle(info["address"]) else info["name"]
        )
        if info["color"]:
            red, green, blue = info["color"]
            rgba = Gdk.RGBA()
            rgba.red, rgba.green, rgba.blue, rgba.alpha = (
                red / 255,
                green / 255,
                blue / 255,
                1.0,
            )
            self.color_button.set_rgba(rgba)
        self.mode_dropdown.set_model(Gtk.StringList(strings=info["modes"]))
        if info["mode"] in info["modes"]:
            self.mode_dropdown.set_selected(info["modes"].index(info["mode"]))
        self.mode_dropdown.set_sensitive(True)
        self.brightness_label.set_visible(info["has_brightness"])
        self.brightness.set_visible(info["has_brightness"])
        self.brightness.set_sensitive(info["has_brightness"])
        self.brightness.set_value(info["brightness"])
        self._loading = False

    # --- aplicar cambios ---

    def _apply(self, address, fn, message):
        if self.backend is None:
            return
        generation = self._generation

        def job():
            result = message
            try:
                fn(address)
            except Exception as exc:  # noqa: BLE001
                result = f"No se pudo aplicar: {exc}"
            info = self._safe_info(address)
            GLib.idle_add(self._finish, generation, address, info, result)

        self._jobs.put(job)

    def _safe_info(self, address):
        try:
            return self.backend.info(address)
        except Exception:  # noqa: BLE001 — sin estado, solo se muestra el error
            return None

    def _finish(self, generation, address, info, message):
        if generation != self._generation:
            return False
        if info is not None and address == self.device_address:
            self._show_info(info)
        if message:
            self.status.set_text(f"{message} · {address}" if address else message)
        return False

    def _on_color(self, button, _pspec):
        if self._loading or self.device_address is None:
            return
        rgba = button.get_rgba()
        rgb = tuple(round(value * 255) for value in (rgba.red, rgba.green, rgba.blue))
        address = self.device_address
        self._apply(
            address,
            lambda target: self.backend.set_color(target, *rgb),
            "Color aplicado",
        )

    def _on_mode(self, dropdown, _pspec):
        if self._loading or self.device_address is None:
            return
        item = dropdown.get_selected_item()
        if item is not None:
            name = item.get_string()
            address = self.device_address
            self._apply(
                address,
                lambda target: self.backend.set_mode(target, name),
                "Modo aplicado",
            )

    def _on_brightness(self, scale):
        if self._loading or self.device_address is None:
            return
        address = self.device_address
        self._cancel_brightness()
        value = round(scale.get_value())
        self._bright_timer = GLib.timeout_add(150, self._apply_brightness, address, value)

    def _apply_brightness(self, address, value):
        self._bright_timer = None
        if address == self.device_address:
            self._apply(
                address,
                lambda target: self.backend.set_brightness(target, value),
                "Brillo aplicado",
            )
        return False

    def _cancel_brightness(self):
        if self._bright_timer is not None:
            GLib.source_remove(self._bright_timer)
            self._bright_timer = None
