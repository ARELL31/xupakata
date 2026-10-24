"""Ventana principal: dispositivos, color, modo y brillo."""
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk

from .backend import connect


class RgbWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(
            application=app,
            title="GNOME RGB",
            default_width=900,
            default_height=600,
        )

        self.backend = None
        self.device_index = None
        self._loading = False
        self._bright_timer = None

        header = Adw.HeaderBar()
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Reconectar")
        refresh.connect("clicked", lambda *_: self.reload())
        header.pack_start(refresh)

        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-selected", self._on_row_selected)
        sidebar = Gtk.ScrolledWindow(
            child=self.listbox, hscrollbar_policy=Gtk.PolicyType.NEVER
        )

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

        grid = Gtk.Grid(row_spacing=12, column_spacing=12)
        self.brightness_label = Gtk.Label(label="Brillo", xalign=0)
        for row, (label, widget) in enumerate(
            [
                (Gtk.Label(label="Color", xalign=0), self.color_button),
                (Gtk.Label(label="Modo", xalign=0), self.mode_dropdown),
                (self.brightness_label, self.brightness),
            ]
        ):
            grid.attach(label, 0, row, 1, 1)
            grid.attach(widget, 1, row, 1, 1)

        self.controls = [self.color_button, self.mode_dropdown, self.brightness]
        for widget in self.controls:
            widget.set_sensitive(False)

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

    # --- conexión (en hilo aparte: la red no bloquea GTK) ---

    def reload(self):
        self.status.set_text("Conectando…")
        self.listbox.remove_all()
        self.device_index = None
        for widget in self.controls:
            widget.set_sensitive(False)
        threading.Thread(target=self._connect_worker, daemon=True).start()

    def _connect_worker(self):
        try:
            backend = connect()
        except Exception as exc:  # noqa: BLE001 — frontera de hilo: nunca debe morir en silencio
            GLib.idle_add(self._fail, str(exc))
            return
        GLib.idle_add(self._loaded, backend)

    def _loaded(self, backend):
        self.backend = backend
        names = backend.devices()
        if not names:
            self.status.set_text("OpenRGB no reportó dispositivos")
            return False

        for index, name in enumerate(names):
            row = Gtk.ListBoxRow()
            row.index = index
            row.set_child(
                Gtk.Label(
                    label=name,
                    xalign=0,
                    margin_start=12,
                    margin_end=12,
                    margin_top=8,
                    margin_bottom=8,
                )
            )
            self.listbox.append(row)

        self.status.set_text(f"{len(names)} dispositivo" + ("" if len(names) == 1 else "s"))
        self.listbox.select_row(self.listbox.get_row_at_index(0))
        return False

    def _fail(self, message):
        self.status.set_text(message)
        return False

    def _ok(self, info, message):
        self._show_info(info)
        self.status.set_text(message)
        return False

    # --- selección ---

    def _on_row_selected(self, _listbox, row):
        if row is None or self.backend is None:
            return
        self.device_index = row.index
        for widget in self.controls:
            widget.set_sensitive(True)
        self._show_info(self.backend.info(row.index))

    def _show_info(self, info):
        self._loading = True
        modes = Gtk.StringList(strings=info["modes"])
        self.mode_dropdown.set_model(modes)
        if info["mode"] in info["modes"]:
            self.mode_dropdown.set_selected(info["modes"].index(info["mode"]))
        self.mode_dropdown.set_sensitive(True)
        self.brightness_label.set_visible(info["has_brightness"])
        self.brightness.set_visible(info["has_brightness"])
        self.brightness.set_sensitive(info["has_brightness"])
        self.brightness.set_value(info["brightness"])
        self._loading = False

    # --- aplicar cambios ---

    def _run(self, fn, message, *args):
        if self.backend is None or self.device_index is None:
            return
        index = self.device_index

        def worker():
            try:
                fn(index, *args)
                info = self.backend.info(index)
            except Exception as exc:  # noqa: BLE001
                GLib.idle_add(self._fail, f"No se pudo aplicar: {exc}")
            else:
                GLib.idle_add(self._ok, info, message)

        threading.Thread(target=worker, daemon=True).start()

    def _on_color(self, button, _pspec):
        if self._loading or self.backend is None:
            return
        rgba = button.get_rgba()
        rgb = tuple(round(value * 255) for value in (rgba.red, rgba.green, rgba.blue))
        self._run(self.backend.set_color, "Color aplicado", *rgb)

    def _on_mode(self, dropdown, _pspec):
        if self._loading or self.backend is None:
            return
        item = dropdown.get_selected_item()
        if item is not None:
            self._run(self.backend.set_mode, "Modo aplicado", item.get_string())

    def _on_brightness(self, scale):
        if self._loading or self.backend is None:
            return
        if self._bright_timer:
            GLib.source_remove(self._bright_timer)
        value = round(scale.get_value())
        self._bright_timer = GLib.timeout_add(150, self._apply_brightness, value)

    def _apply_brightness(self, value):
        self._bright_timer = None
        self._run(self.backend.set_brightness, "Brillo aplicado", value)
        return False
