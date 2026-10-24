"""Ventana principal: dispositivos, color, modo y brillo.

Las operaciones de red se ejecutan en un solo hilo auxiliar, en orden. Cada
tarea captura su destino y su época; los resultados obsoletos se descartan y
las órdenes que quedaron pendientes de una conexión anterior no se ejecutan.
"""
import queue
import threading
import traceback

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Gtk

from .backend import ConnectionLost, DeviceGone, connect


def _subtitle(device) -> str:
    """Texto secundario del dispositivo: dirección SMBus si la hay, si no fabricante."""
    location = device["location"]
    if "address " in location:
        return location.rsplit("address ", 1)[-1].strip()
    return device["vendor"] or ""


def _matches(device, wanted) -> bool:
    """Coincidencia para recuperar la selección tras reconectar.

    Solo compara campos no vacíos: un serial ausente no empareja todo.
    """
    for field in ("name", "vendor", "serial", "location"):
        if wanted.get(field) and wanted[field] != device.get(field):
            return False
    return True


class RgbWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(
            application=app,
            title="GNOME RGB",
            default_width=900,
            default_height=600,
        )

        self.backend = None
        self.device_id = None
        self._generation = 0
        self._loading = False
        self._bright_timer = None
        self._restore = None  # metadatos del dispositivo seleccionado

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
        self.device_id = None
        self._cancel_brightness()
        self.listbox.remove_all()
        self._set_controls(False)
        self.status.set_text("Conectando…")

        def job():
            if generation != self._generation:
                return
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
                subtitle=_subtitle(device),
            )
            row.device = device
            self.listbox.append(row)

        self.status.set_text(
            f"{len(devices)} dispositivo" + ("" if len(devices) == 1 else "s")
        )
        self._select_best_match()
        return False

    def _select_best_match(self):
        """Recupera la selección anterior si hay una coincidencia única."""
        first = self.listbox.get_row_at_index(0)
        if first is None:
            return
        rows = []
        row = first
        while row is not None:
            rows.append(row)
            row = row.get_next_sibling()
        if self._restore is not None:
            matches = [row for row in rows if _matches(row.device, self._restore)]
            if len(matches) == 1:
                self.listbox.select_row(matches[0])
                return
        self.listbox.select_row(first)

    def _fail(self, generation, message):
        if generation == self._generation:
            self.status.set_text(message)
        return False

    # --- selección ---

    def _on_row_selected(self, _listbox, row):
        if row is None or self.backend is None:
            return
        self.device_id = row.device["id"]
        self._cancel_brightness()
        self._set_controls(True)
        self.status.set_text("Leyendo dispositivo…")
        self._load_info(self.device_id)

    def _load_info(self, ref):
        generation = self._generation
        backend = self.backend

        def job():
            if generation != self._generation:
                return
            try:
                info = backend.info(ref)
            except Exception as exc:  # noqa: BLE001
                GLib.idle_add(self._load_failed, generation, exc)
                return
            GLib.idle_add(self._show_if_current, generation, ref, info)

        self._jobs.put(job)

    def _load_failed(self, generation, error):
        if generation != self._generation:
            return False
        self.status.set_text(f"No se pudo leer el dispositivo: {error}")
        if isinstance(error, (ConnectionLost, DeviceGone)):
            self.reload()
        return False

    def _show_if_current(self, generation, ref, info):
        if generation == self._generation and ref == self.device_id:
            self._show_info(info)
            self._restore = {
                "name": info["name"],
                "vendor": info["vendor"],
                "serial": info["serial"],
                "location": info["location"],
            }
            self.status.set_text("")
        return False

    def _show_info(self, info):
        self._loading = True
        subtitle = _subtitle(info)
        self.title.set_text(f"{info['name']} · {subtitle}" if subtitle else info["name"])

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
        self.mode_dropdown.set_sensitive(bool(info["modes"]))

        self.color_button.set_sensitive(info["color_supported"])
        self.color_button.set_tooltip_text(
            None
            if info["color_supported"]
            else f"El modo {info['mode'] or 'actual'} no admite color manual"
        )

        self.brightness_label.set_visible(info["has_brightness"])
        self.brightness.set_visible(info["has_brightness"])
        self.brightness.set_sensitive(info["has_brightness"])
        self.brightness.set_value(info["brightness"])
        self._loading = False

    # --- aplicar cambios ---

    def _apply(self, ref, fn, message):
        backend = self.backend
        if backend is None:
            return
        generation = self._generation

        def job():
            if generation != self._generation:
                return  # la orden quedó obsoleta antes de ejecutarse
            error = None
            try:
                fn(ref)
            except Exception as exc:  # noqa: BLE001
                error = exc
            info = self._safe_info(backend, ref)
            GLib.idle_add(self._finish, generation, ref, info, message, error)

        self._jobs.put(job)

    def _safe_info(self, backend, ref):
        try:
            return backend.info(ref)
        except Exception:  # noqa: BLE001 — sin estado, solo se muestra el error
            return None

    def _finish(self, generation, ref, info, message, error):
        if generation != self._generation:
            return False
        if info is not None and ref == self.device_id:
            self._show_info(info)
        if error is not None:
            self.status.set_text(f"No se pudo aplicar: {error}")
            if isinstance(error, (ConnectionLost, DeviceGone)):
                self.reload()
        elif message:
            self.status.set_text(message)
        return False

    def _on_color(self, button, _pspec):
        if self._loading or self.device_id is None:
            return
        rgba = button.get_rgba()
        rgb = tuple(round(value * 255) for value in (rgba.red, rgba.green, rgba.blue))
        ref = self.device_id
        backend = self.backend
        self._apply(
            ref,
            lambda target: backend.set_color(target, *rgb),
            "Color aplicado",
        )

    def _on_mode(self, dropdown, _pspec):
        if self._loading or self.device_id is None:
            return
        item = dropdown.get_selected_item()
        if item is not None:
            name = item.get_string()
            ref = self.device_id
            backend = self.backend
            self._apply(
                ref,
                lambda target: backend.set_mode(target, name),
                "Modo aplicado",
            )

    def _on_brightness(self, scale):
        if self._loading or self.device_id is None:
            return
        ref = self.device_id
        self._cancel_brightness()
        value = round(scale.get_value())
        self._bright_timer = GLib.timeout_add(150, self._apply_brightness, ref, value)

    def _apply_brightness(self, ref, value):
        self._bright_timer = None
        if ref == self.device_id:
            backend = self.backend
            self._apply(
                ref,
                lambda target: backend.set_brightness(target, value),
                "Brillo aplicado",
            )
        return False

    def _cancel_brightness(self):
        if self._bright_timer is not None:
            GLib.source_remove(self._bright_timer)
            self._bright_timer = None
