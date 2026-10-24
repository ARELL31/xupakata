"""Ventana principal: dispositivos, color, modo y brillo.

Solo el hilo del trabajador toca el SDK. Cada tarea captura su generación,
selección y solicitud; los resultados obsoletos se descartan.
"""
import contextlib
from enum import Enum

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .backend import ConnectionLost, DeviceGone, ServerUnavailable, connect
from .i18n import _, plural
from .worker import Worker


class Connection(Enum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    FAILED = "failed"
    RECONNECTING = "reconnecting"


class Panel(Enum):
    EMPTY = "empty"
    NO_SELECTION = "no_selection"
    LOADING = "loading"
    READY = "ready"
    APPLYING = "applying"
    ERROR = "error"


def _subtitle(device) -> str:
    """Bus y dirección: distingue dispositivos del mismo nombre.

    La ubicación completa queda en el tooltip.
    """
    location = device["location"]
    parts = []
    if "i2c-" in location:
        bus = location.split("i2c-", 1)[1].split(")")[0].split(",")[0].strip()
        parts.append(f"i2c-{bus}")
    if "address " in location:
        parts.append(location.rsplit("address ", 1)[-1].strip())
    if parts:
        return " · ".join(parts)
    return location or device["vendor"] or ""


def _matches(device, wanted) -> bool:
    """Solo compara campos no vacíos: un serial ausente no empareja todo."""
    for field in ("name", "vendor", "serial", "location"):
        if wanted.get(field) and wanted[field] != device.get(field):
            return False
    return True


def _label(text: str, widget) -> Gtk.Label:
    label = Gtk.Label(label=text, xalign=0, use_underline=True)
    label.set_mnemonic_widget(widget)
    return label


class RgbWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(
            application=app,
            title="xupakata",
            default_width=900,
            default_height=600,
        )

        self.backend = None
        self.device_id = None
        self._generation = 0
        self.selection_revision = 0
        self.request_id = 0
        self._state = Connection.CONNECTING
        self._panel = Panel.EMPTY
        self._caps = {"color": False, "modes": False, "brightness": False}
        self._loading = False
        self._bright_timer = None
        self._restore = None
        self._closing = False
        self._auto_reconnect_used = False

        self.worker = Worker()

        header = Adw.HeaderBar()
        self.back_button = Gtk.Button(icon_name="go-previous-symbolic")
        self.back_button.set_tooltip_text(_("Volver a dispositivos"))
        self.back_button.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Volver a dispositivos")]
        )
        self.back_button.set_visible(False)
        self.back_button.connect("clicked", lambda *_: self.split.set_show_content(False))
        header.pack_start(self.back_button)

        refresh = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh.set_tooltip_text(_("Reconectar"))
        refresh.update_property([Gtk.AccessibleProperty.LABEL], [_("Reconectar")])
        refresh.connect("clicked", lambda *_: self.reload())
        header.pack_end(refresh)

        menu = Gio.Menu()
        menu.append(_("_Acerca de xupakata"), "app.about")
        menu.append(_("_Salir"), "app.quit")
        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        menu_button.set_tooltip_text(_("Menú principal"))
        menu_button.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Menú principal")]
        )
        header.pack_end(menu_button)

        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.listbox.add_css_class("boxed-list")
        self.listbox.connect("row-selected", self._on_row_selected)
        sidebar = Gtk.ScrolledWindow(
            child=self.listbox, hscrollbar_policy=Gtk.PolicyType.NEVER
        )

        self.title = Gtk.Label(label="", wrap=True)
        self.title.add_css_class("title-4")

        self.spinner = Gtk.Spinner()
        self.status = Gtk.Label(label=_("Conectando con OpenRGB…"), wrap=True)
        status_box = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        status_box.append(self.spinner)
        status_box.append(self.status)

        self._rgba = None
        self._color_dialog = Gtk.ColorDialog(title=_("Color"))

        self.color_button = Gtk.Button()
        self.color_button.set_child(self._build_swatch())
        self.color_button.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Color del dispositivo")]
        )
        self.color_button.connect("clicked", self._on_color_clicked)

        self.mode_dropdown = Gtk.DropDown()
        self.mode_dropdown.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Modo de iluminación")]
        )
        self.mode_dropdown.connect("notify::selected", self._on_mode)

        self.brightness = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL,
            adjustment=Gtk.Adjustment(lower=0, upper=100, step_increment=1),
            width_request=200,
            draw_value=True,
            digits=0,
        )
        self.brightness.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Brillo")]
        )
        self.brightness.connect("value-changed", self._on_brightness)

        self.brightness_label = _label(_("_Brillo"), self.brightness)
        grid = Gtk.Grid(row_spacing=12, column_spacing=12)
        rows = [
            (_label(_("_Color"), self.color_button), self.color_button),
            (_label(_("_Modo"), self.mode_dropdown), self.mode_dropdown),
            (self.brightness_label, self.brightness),
        ]
        for position, (label, widget) in enumerate(rows):
            grid.attach(label, 0, position, 1, 1)
            grid.attach(widget, 1, position, 1, 1)

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
        panel.append(status_box)
        panel.append(grid)

        self.split = Adw.NavigationSplitView()
        self.split.set_sidebar(
            Adw.NavigationPage(title=_("Dispositivos"), child=sidebar)
        )
        self.split.set_content(
            Adw.NavigationPage(title=_("Dispositivo"), child=panel)
        )
        self.split.connect("notify::collapsed", lambda *_: self._render_state())
        self.split.connect("notify::show-content", lambda *_: self._render_state())

        narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 600sp"))
        narrow.add_setter(self.split, "collapsed", True)
        self.add_breakpoint(narrow)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(self.split)
        self.set_content(toolbar)

        self.reload()

    # --- presentación ---

    def _render_state(self):
        """Único lugar que habilita/deshabilita controles según el estado."""
        editable = self._panel is Panel.READY
        self.spinner.set_visible(
            self._state in (Connection.CONNECTING, Connection.RECONNECTING)
        )
        if self.spinner.get_visible():
            self.spinner.start()
        else:
            self.spinner.stop()
        self.listbox.set_sensitive(self._state is Connection.CONNECTED)

        has_color = self._caps.get("color", False)
        self.color_button.set_sensitive(editable and has_color)
        self.mode_dropdown.set_sensitive(editable and self._caps.get("modes", False))
        self.brightness.set_visible(self._caps.get("brightness", False))
        self.brightness_label.set_visible(self._caps.get("brightness", False))
        self.brightness.set_sensitive(editable and self._caps.get("brightness", False))

        self.back_button.set_visible(
            self.split.get_collapsed() and self.split.get_show_content()
        )

    # --- conexión ---

    def reload(self, reconnecting: bool = False, automatic: bool = False):
        if self._closing:
            return
        if automatic:
            if self._auto_reconnect_used:
                self._state = Connection.FAILED
                self._panel = Panel.ERROR
                self.status.set_text(
                    _("OpenRGB sigue sin responder. Usa Reconectar para intentarlo de nuevo.")
                )
                self._render_state()
                return
            self._auto_reconnect_used = True
        else:
            self._auto_reconnect_used = False
        self._generation += 1
        generation = self._generation
        old_backend, self.backend = self.backend, None
        self.device_id = None
        self._caps = {}
        self._panel = Panel.EMPTY
        self._state = Connection.RECONNECTING if reconnecting else Connection.CONNECTING
        self._cancel_brightness()
        self.listbox.remove_all()
        self.status.set_text(
            _("Reconectando con OpenRGB…") if reconnecting else _("Conectando con OpenRGB…")
        )
        self._render_state()

        def job():
            if old_backend is not None:
                with contextlib.suppress(Exception):
                    old_backend.close()
            if generation != self._generation or self._closing:
                return
            backend = None
            try:
                backend = connect()
                devices = backend.devices()
            except Exception as exc:  # noqa: BLE001 — frontera de hilo
                if backend is not None:
                    with contextlib.suppress(Exception):
                        backend.close()
                GLib.idle_add(self._connect_failed, generation, exc)
                return
            if generation != self._generation or self._closing:
                with contextlib.suppress(Exception):
                    backend.close()  # conexión creada para una generación obsoleta
                return
            GLib.idle_add(self._loaded, generation, backend, devices)

        self.worker.submit(job)

    def _connect_failed(self, generation, error):
        if generation != self._generation or self._closing:
            return False
        self._state = Connection.FAILED
        self._panel = Panel.EMPTY
        self._render_state()
        self.status.set_text(_("No se pudo conectar: %(error)s") % {"error": error})
        return False

    def _recover(self, message):
        """Un intento automático por incidente; después, reintento manual."""
        if self._closing:
            return
        if self._auto_reconnect_used:
            self._state = Connection.FAILED
            self._panel = Panel.ERROR
            self.status.set_text(
                _("%(error)s. Usa Reconectar para intentarlo de nuevo.") % {"error": message}
            )
            self._render_state()
            return
        self.reload(reconnecting=True, automatic=True)

    def _loaded(self, generation, backend, devices):
        if generation != self._generation or self._closing:
            with contextlib.suppress(Exception):
                backend.close()
            return False
        self.backend = backend
        self._state = Connection.CONNECTED
        self._auto_reconnect_used = False

        if not devices:
            self._panel = Panel.EMPTY
            self.status.set_text(_("No se encontraron dispositivos OpenRGB"))
            self._render_state()
            return False

        counts = {}
        for device in devices:
            key = (device["name"], device["vendor"], device["serial"], device["location"])
            counts[key] = counts.get(key, 0) + 1

        seen = {}
        for device in devices:
            key = (device["name"], device["vendor"], device["serial"], device["location"])
            title = device["name"]
            if counts[key] > 1:
                seen[key] = seen.get(key, 0) + 1
                title = _("%(name)s · dispositivo %(index)d") % {
                    "name": device["name"],
                    "index": seen[key],
                }
            row = Adw.ActionRow(title=title, subtitle=_subtitle(device))
            row.set_subtitle_lines(1)
            row.set_tooltip_text(device["location"] or device["vendor"])
            row.device = device
            self.listbox.append(row)

        self.status.set_text(
            plural(len(devices), "%(count)d dispositivo", "%(count)d dispositivos")
        )
        self._render_state()
        self._select_best_match()
        return False

    def _select_best_match(self):
        first = self.listbox.get_row_at_index(0)
        if first is None:
            return
        rows = []
        row = first
        while row is not None:
            rows.append(row)
            row = row.get_next_sibling()

        if self._restore is None:
            if len(rows) == 1:
                self.listbox.select_row(rows[0])
            else:
                self._panel = Panel.NO_SELECTION
                self.status.set_text(_("Selecciona un dispositivo"))
                self._render_state()
            return

        matches = [row for row in rows if _matches(row.device, self._restore)]
        if len(matches) == 1:
            self.listbox.select_row(matches[0])
            return

        self.listbox.unselect_all()
        self._panel = Panel.NO_SELECTION
        if matches:
            self.status.set_text(
                _("Selecciona nuevamente el dispositivo: hay varias coincidencias")
            )
        else:
            self.status.set_text(_("El dispositivo anterior ya no está disponible"))
        self._render_state()

    # --- selección ---

    def _on_row_selected(self, _listbox, row):
        self.selection_revision += 1
        revision = self.selection_revision
        self._cancel_brightness()

        if row is None or self.backend is None:
            self.device_id = None
            self._caps = {}
            self._panel = Panel.EMPTY if self.backend is None else Panel.NO_SELECTION
            self.title.set_text("")
            self._render_state()
            return

        self.device_id = row.device["id"]
        self._caps = {}
        self._panel = Panel.LOADING
        self.status.set_text(_("Obteniendo estado…"))
        if self.split.get_collapsed():
            self.split.set_show_content(True)
        self._render_state()
        self._load_info(revision, self.device_id)

    def _load_info(self, revision, ref):
        generation = self._generation
        backend = self.backend

        def job():
            if generation != self._generation or backend is not self.backend:
                return
            try:
                info = backend.info(ref, refresh=True)
            except Exception as exc:  # noqa: BLE001
                GLib.idle_add(self._load_failed, generation, revision, exc)
                return
            GLib.idle_add(self._show_if_current, generation, revision, ref, info)

        self.worker.submit(job)

    def _load_failed(self, generation, revision, error):
        if generation != self._generation or revision != self.selection_revision:
            return False
        if isinstance(error, (ConnectionLost, DeviceGone, ServerUnavailable)):
            self._recover(str(error))
            return False
        self._panel = Panel.ERROR
        self.status.set_text(_("No se pudo leer el dispositivo: %(error)s") % {"error": error})
        self._render_state()
        return False

    def _show_if_current(self, generation, revision, ref, info):
        if generation != self._generation or revision != self.selection_revision:
            return False
        self._show_info(info)
        self._restore = {
            "name": info["name"],
            "vendor": info["vendor"],
            "serial": info["serial"],
            "location": info["location"],
        }
        self._panel = Panel.READY
        self.status.set_text("")
        self._render_state()
        return False

    def _show_info(self, info):
        self._loading = True
        subtitle = _subtitle(info)
        self.title.set_text(f"{info['name']} · {subtitle}" if subtitle else info["name"])

        if info["color"]:
            red, green, blue = info["color"]
            self._rgba = Gdk.RGBA()
            self._rgba.red, self._rgba.green, self._rgba.blue, self._rgba.alpha = (
                red / 255,
                green / 255,
                blue / 255,
                1.0,
            )
            self.swatch.queue_draw()
        else:
            self._rgba = None
            self.swatch.queue_draw()

        self.mode_dropdown.set_model(Gtk.StringList(strings=info["modes"]))
        if info["mode"] in info["modes"]:
            self.mode_dropdown.set_selected(info["modes"].index(info["mode"]))

        self._caps = {
            "color": info["color_supported"],
            "modes": bool(info["modes"]),
            "brightness": info["has_brightness"],
        }
        if not info["color_supported"]:
            tooltip = _("Este modo no admite color manual. Selecciona otro modo para cambiarlo.")
        elif info["color"] is None:
            tooltip = _("OpenRGB no reporta el color actual")
        else:
            tooltip = None
        self.color_button.set_tooltip_text(tooltip)
        self.brightness.set_value(info["brightness"])
        self._loading = False

    # --- aplicar cambios ---

    def _apply(self, ref, fn, message):
        backend = self.backend
        if backend is None or self._closing:
            return
        generation = self._generation
        revision = self.selection_revision
        self.request_id += 1
        request = self.request_id
        self._panel = Panel.APPLYING
        self.status.set_text(_("Enviando cambios…"))
        self._render_state()

        def job():
            if generation != self._generation or backend is not self.backend:
                return
            error = None
            try:
                fn(ref)
            except Exception as exc:  # noqa: BLE001
                error = exc
            info = None
            read_error = None
            try:
                info = backend.info(ref)
            except Exception as exc:  # noqa: BLE001
                read_error = exc
            GLib.idle_add(
                self._finish,
                generation,
                revision,
                request,
                ref,
                info,
                message,
                error,
                read_error,
            )

        self.worker.submit(job)

    def _finish(self, generation, revision, request, ref, info, message, error, read_error):
        if generation != self._generation or self._closing:
            return False
        if revision != self.selection_revision or request != self.request_id:
            # Resultado de otra selección u operación: se descarta por completo.
            return False

        if info is not None:
            self._show_info(info)

        if error is not None:
            self._panel = Panel.ERROR
            self.status.set_text(_("No se pudo aplicar: %(error)s") % {"error": error})
            if isinstance(error, (ConnectionLost, DeviceGone, ServerUnavailable)):
                self._recover(str(error))
                return False
        elif read_error is not None:
            self._panel = Panel.ERROR
            self.status.set_text(
                _("El cambio se envió, pero no se pudo consultar el estado")
            )
            if isinstance(read_error, (ConnectionLost, DeviceGone, ServerUnavailable)):
                self._recover(str(read_error))
                return False
        else:
            self._panel = Panel.READY
            self.status.set_text(message)
        self._render_state()
        return False

    def _build_swatch(self):
        self.swatch = Gtk.DrawingArea()
        self.swatch.set_content_width(36)
        self.swatch.set_content_height(20)
        self.swatch.set_draw_func(self._draw_swatch)
        return self.swatch

    def _draw_swatch(self, _area, cr, width, height):
        if self._rgba is None:
            return
        cr.set_source_rgba(self._rgba.red, self._rgba.green, self._rgba.blue, 1.0)
        cr.rectangle(0, 0, width, height)
        cr.fill()

    def _on_color_clicked(self, _button):
        if self.device_id is None or self._closing:
            return
        target = (self._generation, self.selection_revision, self.device_id)
        initial = self._rgba or Gdk.RGBA(red=1.0, green=1.0, blue=1.0, alpha=1.0)
        self._color_dialog.choose_rgba(
            self, initial, None, self._on_color_chosen, target
        )

    def _on_color_chosen(self, dialog, result, target):
        if self._closing:
            return
        try:
            rgba = dialog.choose_rgba_finish(result)
        except GLib.Error:
            return  # el usuario canceló
        self._apply_color(target, rgba)

    def _apply_color(self, target, rgba):
        if self._closing:
            return
        if target != (self._generation, self.selection_revision, self.device_id):
            self.status.set_text(
                _("Se descartó el color: cambió el dispositivo seleccionado")
            )
            return
        self._rgba = rgba
        self.swatch.queue_draw()
        rgb = tuple(round(value * 255) for value in (rgba.red, rgba.green, rgba.blue))
        ref = self.device_id
        backend = self.backend
        self._apply(
            ref,
            lambda target_ref: backend.set_color(target_ref, *rgb),
            _("OpenRGB reporta el color solicitado"),
        )

    def _on_mode(self, dropdown, _pspec):
        if self._loading or self.device_id is None or self._closing:
            return
        item = dropdown.get_selected_item()
        if item is not None:
            name = item.get_string()
            ref = self.device_id
            backend = self.backend
            self._cancel_brightness()
            self._apply(
                ref,
                lambda target: backend.set_mode(target, name),
                _("OpenRGB reporta el modo solicitado"),
            )

    def _on_brightness(self, scale):
        if self._loading or self.device_id is None or self._closing:
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
                _("OpenRGB reporta el brillo solicitado"),
            )
        return False

    def _cancel_brightness(self):
        if self._bright_timer is not None:
            GLib.source_remove(self._bright_timer)
            self._bright_timer = None

    # --- cierre ---

    def shutdown(self):
        """Cancela pendientes y cierra la conexión desde el trabajador."""
        if self._closing:
            return
        self._closing = True
        self._generation += 1
        self._cancel_brightness()
        self.worker.clear()
        backend, self.backend = self.backend, None
        if backend is not None:
            self.worker.submit(backend.close)
        self.worker.stop()
