"""Ventana principal: lista de dispositivos y selector de color."""
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
        self.color_button.set_sensitive(False)
        self.color_button.connect("notify::rgba", self._on_color)

        color_row = Gtk.Box(spacing=12)
        color_row.append(Gtk.Label(label="Color"))
        color_row.append(self.color_button)

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
        panel.append(color_row)

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
        self.color_button.set_sensitive(False)
        self.listbox.remove_all()
        self.device_index = None
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

    # --- selección y color ---

    def _on_row_selected(self, _listbox, row):
        if row is None:
            return
        self.device_index = row.index
        self.color_button.set_sensitive(True)

    def _on_color(self, button, _pspec):
        if self.backend is None or self.device_index is None:
            return
        rgba = button.get_rgba()
        rgb = tuple(round(value * 255) for value in (rgba.red, rgba.green, rgba.blue))
        threading.Thread(
            target=self._apply_worker,
            args=(self.device_index, *rgb),
            daemon=True,
        ).start()

    def _apply_worker(self, index, red, green, blue):
        try:
            self.backend.set_color(index, red, green, blue)
        except Exception as exc:  # noqa: BLE001
            GLib.idle_add(self._fail, f"No se pudo aplicar el color: {exc}")
        else:
            GLib.idle_add(self._ok)

    def _ok(self):
        self.status.set_text("Color aplicado")
        return False
