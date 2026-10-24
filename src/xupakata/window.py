"""Ventana principal: dispositivos, color, modo y brillo.

Solo el hilo del trabajador toca el SDK. Cada tarea captura su generación,
selección y solicitud; los resultados obsoletos se descartan.
"""
import contextlib
import os
from enum import Enum
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .backend import ConnectionLost, DeviceGone, ServerUnavailable, connect
from .i18n import _, plural
from .worker import Worker

DEVICE_ICONS = {
    "cooler": "xupakata-cooler-symbolic",
    "dram": "xupakata-dram-symbolic",
    "keyboard": "xupakata-keyboard-symbolic",
    "keypad": "xupakata-keyboard-symbolic",
    "ledstrip": "xupakata-ledstrip-symbolic",
    "light": "xupakata-ledstrip-symbolic",
    "mouse": "xupakata-mouse-symbolic",
}

DEVICE_NAMES = {
    "accessory": _("Accesorio"),
    "case": _("Caja"),
    "cooler": _("Refrigeración"),
    "dram": _("Memoria RAM"),
    "gamepad": _("Mando"),
    "gpu": _("Tarjeta gráfica"),
    "headset": _("Auriculares"),
    "headset_stand": _("Soporte de auriculares"),
    "keyboard": _("Teclado"),
    "keypad": _("Teclado numérico"),
    "ledstrip": _("Tira LED"),
    "light": _("Iluminación"),
    "microphone": _("Micrófono"),
    "motherboard": _("Placa base"),
    "mouse": _("Ratón"),
    "mousemat": _("Alfombrilla"),
    "speaker": _("Altavoz"),
    "storage": _("Almacenamiento"),
    "virtual": _("Virtual"),
}


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

    La ubicación completa queda en la ficha y en el tooltip.
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


def _resource(*parts: str) -> str:
    """Ruta de un recurso instalado, o la del árbol de trabajo en desarrollo."""
    root = os.environ.get("SNAP")
    if root:
        return os.path.join(root, "usr", "share", "xupakata", *parts)
    return str(Path(__file__).resolve().parents[2] / "data" / Path(*parts))


def _illustration(kind: str) -> str:
    name = "dram" if kind == "dram" else "generic"
    return _resource("illustrations", "hardware", f"{name}.svg")


def _device_icon(kind: str) -> str:
    return DEVICE_ICONS.get(kind, "xupakata-generic-symbolic")


def _device_name(kind: str) -> str:
    return DEVICE_NAMES.get(kind, _("Dispositivo RGB"))


def _hex(color) -> str:
    return "#{:02X}{:02X}{:02X}".format(*color)


class RgbWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(
            application=app,
            title="xupakata",
            default_width=900,
            default_height=620,
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
        self._message = ""
        self._rgba = None
        self._illustration_kind = None

        self.worker = Worker()
        self._add_icon_paths()
        self._install_css()

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
        menu_button.update_property([Gtk.AccessibleProperty.LABEL], [_("Menú principal")])
        header.pack_end(menu_button)

        self._build_sidebar()
        self._build_content()

        self.toast_overlay = Adw.ToastOverlay(child=self.stack)

        self.split = Adw.NavigationSplitView()
        self.split.set_sidebar(Adw.NavigationPage(title=_("Dispositivos"), child=self.sidebar))
        self.split.set_content(Adw.NavigationPage(title=_("Dispositivo"), child=self.toast_overlay))
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

    # --- construcción ---

    def _add_icon_paths(self):
        display = Gdk.Display.get_default()
        if display is None:
            return
        theme = Gtk.IconTheme.get_for_display(display)
        root = os.environ.get("SNAP")
        if root:
            theme.add_search_path(os.path.join(root, "usr", "share", "icons"))
        else:
            candidate = Path(__file__).resolve().parents[2] / "data" / "icons"
            if candidate.is_dir():
                theme.add_search_path(str(candidate))

    def _install_css(self):
        display = Gdk.Display.get_default()
        if display is None or getattr(RgbWindow, "_css_ready", False):
            return
        provider = Gtk.CssProvider()
        provider.load_from_data(
            b"""
            .device-list,
            .device-list > row {
              background-color: transparent;
            }
            .sidebar-pane {
              background-color: @window_bg_color;
            }
            .device-list > row {
              border-radius: 9px;
              margin: 2px 0;
            }
            .device-list > row:hover,
            .device-list > row:selected:hover {
              background-color: rgba(120, 120, 120, 0.16);
            }
            .device-list > row:selected {
              background-color: transparent;
              color: inherit;
            }
            """
        )
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        RgbWindow._css_ready = True

    def _build_sidebar(self):
        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.listbox.add_css_class("device-list")
        self.listbox.connect("row-selected", self._on_row_selected)

        self.device_count = Gtk.Label(label="", xalign=0)
        self.device_count.add_css_class("dim-label")
        self.device_count.set_margin_start(12)
        self.device_count.set_margin_end(12)
        self.device_count.set_margin_top(12)

        scroller = Gtk.ScrolledWindow(
            child=self.listbox, hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True
        )
        scroller.set_margin_start(12)
        scroller.set_margin_end(12)
        scroller.set_margin_top(6)
        scroller.set_margin_bottom(12)

        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.sidebar.append(self.device_count)
        self.sidebar.append(scroller)
        self.sidebar.set_size_request(280, -1)

    def _build_content(self):
        self.status_page = Adw.StatusPage(title="", description="")
        self.status_spinner = Gtk.Spinner(halign=Gtk.Align.CENTER)
        self.status_reconnect = Gtk.Button(label=_("Reconectar"), halign=Gtk.Align.CENTER)
        self.status_reconnect.add_css_class("suggested-action")
        self.status_reconnect.connect("clicked", lambda *_: self.reload())

        self.picture = Gtk.Picture()
        self.picture.set_size_request(132, 132)
        self.picture.set_can_shrink(True)
        self.picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.picture.set_halign(Gtk.Align.CENTER)

        self.title = Gtk.Label(label="", wrap=True, justify=Gtk.Justification.CENTER)
        self.title.add_css_class("title-1")
        self.title.set_xalign(0.5)

        self.busy_spinner = Gtk.Spinner(visible=False)
        title_box = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        title_box.append(self.title)
        title_box.append(self.busy_spinner)

        self.subtitle = Gtk.Label(label="", wrap=True, justify=Gtk.Justification.CENTER)
        self.subtitle.add_css_class("dim-label")
        self.subtitle.set_xalign(0.5)

        self.banner = Adw.Banner(title="")
        self.banner.set_revealed(False)

        self._color_dialog = Gtk.ColorDialog(title=_("Color"))
        self.group = Adw.PreferencesGroup(title=_("Iluminación"))

        self.mode_row = Adw.ComboRow(title=_("Modo"))
        self.mode_row.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Modo de iluminación")]
        )
        self.mode_row.connect("notify::selected", self._on_mode)
        self.mode_dropdown = self.mode_row

        self.color_row = Adw.ActionRow(title=_("Color"))
        self.color_row.set_activatable(True)
        self.color_button = Gtk.DrawingArea()
        self.color_button.set_content_width(38)
        self.color_button.set_content_height(24)
        self.color_button.set_draw_func(self._draw_swatch)
        self.color_button.set_valign(Gtk.Align.CENTER)
        self.color_row.add_suffix(self.color_button)
        self.color_row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        self.color_row.connect("activated", self._on_color_clicked)
        self.swatch = self.color_button

        self.brightness = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL,
            adjustment=Gtk.Adjustment(lower=0, upper=100, step_increment=1),
            width_request=170,
            draw_value=True,
            digits=0,
            valign=Gtk.Align.CENTER,
        )
        self.brightness.update_property([Gtk.AccessibleProperty.LABEL], [_("Brillo")])
        self.brightness.connect("value-changed", self._on_brightness)
        self.brightness_row = Adw.ActionRow(title=_("Brillo"))
        self.brightness_row.add_suffix(self.brightness)
        self.brightness_row.set_activatable_widget(self.brightness)

        self.group.add(self.mode_row)
        self.group.add(self.color_row)
        self.group.add(self.brightness_row)

        self.info_expander = Adw.ExpanderRow(title=_("Información del dispositivo"))
        self._info_rows = {}
        for key, label in (
            ("type", _("Tipo")),
            ("vendor", _("Fabricante")),
            ("name", _("Nombre reportado")),
            ("serial", _("Número de serie")),
            ("location", _("Ubicación")),
        ):
            row = Adw.ActionRow(title=label)
            row.set_subtitle_selectable(True)
            self.info_expander.add_row(row)
            self._info_rows[key] = row

        device_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=18,
            margin_bottom=24,
            margin_start=12,
            margin_end=12,
        )
        device_box.append(self.picture)
        device_box.append(title_box)
        device_box.append(self.subtitle)
        device_box.append(self.banner)
        device_box.append(self.group)
        device_box.append(self.info_expander)

        clamp = Adw.Clamp(maximum_size=520, tightening_threshold=420)
        clamp.set_child(device_box)
        scroller = Gtk.ScrolledWindow(
            child=clamp, hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True
        )

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.add_named(self.status_page, "status")
        self.stack.add_named(scroller, "device")

    def _draw_swatch(self, _area, cr, width, height):
        radius = 5
        cr.new_sub_path()
        cr.arc(width - radius, radius, radius, -1.5708, 0)
        cr.arc(width - radius, height - radius, radius, 0, 1.5708)
        cr.arc(radius, height - radius, radius, 1.5708, 3.1416)
        cr.arc(radius, radius, radius, 3.1416, 4.7124)
        cr.close_path()
        if self._rgba is None:
            cr.set_source_rgba(0.5, 0.5, 0.5, 0.18)
        else:
            cr.set_source_rgba(self._rgba.red, self._rgba.green, self._rgba.blue, 1.0)
        cr.fill_preserve()
        cr.set_source_rgba(0, 0, 0, 0.18)
        cr.set_line_width(1)
        cr.stroke()

    # --- presentación ---

    def _render_state(self):
        """Único lugar que habilita/deshabilita controles según el estado."""
        connected = self._state is Connection.CONNECTED
        editable = self._panel is Panel.READY
        busy = self._panel in (Panel.LOADING, Panel.APPLYING)
        self.listbox.set_sensitive(connected)

        has_color = self._caps.get("color", False)
        self.color_button.set_sensitive(editable and has_color)
        self.color_row.set_sensitive(editable and has_color)
        self.mode_row.set_sensitive(editable and bool(self._caps.get("modes")))

        has_brightness = self._caps.get("brightness", False)
        self.brightness_row.set_visible(has_brightness)
        self.brightness.set_sensitive(editable and has_brightness)

        self.back_button.set_visible(self.split.get_collapsed() and self.split.get_show_content())
        self.busy_spinner.set_visible(busy and self.device_id is not None)
        if busy:
            self.busy_spinner.start()
        else:
            self.busy_spinner.stop()

        self.banner.set_title(self._message)
        self.banner.set_revealed(self._panel is Panel.ERROR and bool(self._message))

        if self._state in (Connection.CONNECTING, Connection.RECONNECTING):
            self._show_status(
                _("Conectando con OpenRGB…"),
                _("Buscando el servidor local en 127.0.0.1:6742."),
                spinner=True,
            )
        elif self._state is Connection.FAILED:
            self._show_status(
                _("No se pudo conectar con OpenRGB"),
                self._message or _("Comprueba que el servidor OpenRGB esté iniciado."),
                icon="network-offline-symbolic",
                action=True,
            )
        elif self._panel is Panel.EMPTY:
            self._show_status(
                _("No hay dispositivos"),
                _("OpenRGB no detectó dispositivos. Revisa sus permisos y vuelve a intentarlo."),
                icon="view-list-symbolic",
                action=True,
            )
        elif self.device_id is None:
            self._show_status(
                _("Selecciona un dispositivo"),
                self._message or _("Elige un dispositivo para controlar su iluminación."),
                icon="go-next-symbolic",
            )
        elif self._panel is Panel.ERROR and not self._caps:
            self._show_status(
                _("No se pudo leer el dispositivo"),
                self._message,
                icon="dialog-warning-symbolic",
                action=True,
            )
        else:
            self.stack.set_visible_child_name("device")

    def _show_status(self, title, description, *, icon="", spinner=False, action=False):
        self.status_page.set_title(title)
        self.status_page.set_description(description or "")
        self.status_page.set_icon_name(icon or None)
        if spinner:
            self.status_spinner.start()
            self.status_page.set_child(self.status_spinner)
        else:
            self.status_spinner.stop()
            self.status_page.set_child(self.status_reconnect if action else None)
        self.stack.set_visible_child_name("status")

    def _toast(self, message):
        toast = Adw.Toast(title=message)
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)

    # --- conexión ---

    def reload(self, reconnecting: bool = False, automatic: bool = False):
        if self._closing:
            return
        if automatic:
            if self._auto_reconnect_used:
                self._state = Connection.FAILED
                self._panel = Panel.ERROR
                self._message = _(
                    "OpenRGB sigue sin responder. Usa Reconectar para intentarlo de nuevo."
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
        self._message = ""
        self._state = Connection.RECONNECTING if reconnecting else Connection.CONNECTING
        self._cancel_brightness()
        self.listbox.remove_all()
        self.device_count.set_text("")
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
        self._message = _("No se pudo conectar: %(error)s") % {"error": error}
        self._render_state()
        return False

    def _recover(self, message):
        """Un intento automático por incidente; después, reintento manual."""
        if self._closing:
            return
        if self._auto_reconnect_used:
            self._state = Connection.FAILED
            self._panel = Panel.ERROR
            self._message = _("%(error)s. Usa Reconectar para intentarlo de nuevo.") % {
                "error": message
            }
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
            icon = Gtk.Image.new_from_icon_name(_device_icon(device.get("type", "")))
            icon.set_pixel_size(24)
            row.add_prefix(icon)
            check = Gtk.Image.new_from_icon_name("object-select-symbolic")
            check.set_visible(False)
            check.add_css_class("dim-label")
            row.add_suffix(check)
            row.check = check
            row.device = device
            self.listbox.append(row)

        self.device_count.set_text(
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
                self._message = ""
                self._render_state()
            return

        matches = [row for row in rows if _matches(row.device, self._restore)]
        if len(matches) == 1:
            self.listbox.select_row(matches[0])
            return

        self.listbox.unselect_all()
        self._panel = Panel.NO_SELECTION
        if matches:
            self._message = _(
                "Hay varias coincidencias. Selecciona nuevamente el dispositivo."
            )
        else:
            self._message = _("El dispositivo anterior ya no está disponible.")
        self._render_state()

    # --- selección ---

    def _update_selection_marks(self):
        row = self.listbox.get_row_at_index(0)
        while row is not None:
            mark = getattr(row, "check", None)
            if mark is not None:
                mark.set_visible(row.is_selected())
            row = row.get_next_sibling()

    def _on_row_selected(self, _listbox, row):
        self.selection_revision += 1
        revision = self.selection_revision
        self._cancel_brightness()
        self._message = ""
        self._update_selection_marks()

        if row is None or self.backend is None:
            self.device_id = None
            self._caps = {}
            self._panel = Panel.EMPTY if self.backend is None else Panel.NO_SELECTION
            self.title.set_text("")
            self.subtitle.set_text("")
            self._render_state()
            return

        self.device_id = row.device["id"]
        self._caps = {}
        self._panel = Panel.LOADING
        self.title.set_text(row.get_title())
        self.subtitle.set_text(_subtitle(row.device))
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
        self._message = _("No se pudo leer el dispositivo: %(error)s") % {"error": error}
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
        self._message = ""
        self._render_state()
        return False

    def _show_info(self, info):
        self._loading = True
        kind = info.get("type", "")
        subtitle = _subtitle(info)
        self.title.set_text(info["name"])
        self.subtitle.set_text(
            f"{_device_name(kind)} · {subtitle}" if subtitle else _device_name(kind)
        )

        if kind != self._illustration_kind:
            path = _illustration(kind)
            if not os.path.exists(path):
                path = _illustration("generic")
            self.picture.set_filename(path)
            self._illustration_kind = kind

        if info["color"]:
            red, green, blue = info["color"]
            self._rgba = Gdk.RGBA()
            self._rgba.red, self._rgba.green, self._rgba.blue, self._rgba.alpha = (
                red / 255,
                green / 255,
                blue / 255,
                1.0,
            )
        else:
            self._rgba = None
        self.swatch.queue_draw()

        self.mode_row.set_model(Gtk.StringList(strings=info["modes"]))
        if info["mode"] in info["modes"]:
            self.mode_row.set_selected(info["modes"].index(info["mode"]))

        self._caps = {
            "color": info["color_supported"],
            "modes": bool(info["modes"]),
            "brightness": info["has_brightness"],
        }

        if not info["color_supported"]:
            self.color_row.set_subtitle(_("Controlado por el modo actual"))
            tooltip = _("Este modo no admite color manual. Selecciona otro modo para cambiarlo.")
        elif info["color"] is None:
            self.color_row.set_subtitle(_("No disponible"))
            tooltip = _("OpenRGB no reporta el color actual")
        else:
            self.color_row.set_subtitle(_hex(info["color"]))
            tooltip = _("Elegir color")
        self.color_row.set_tooltip_text(tooltip)

        self._info_rows["type"].set_subtitle(_device_name(kind))
        for key in ("vendor", "name", "serial", "location"):
            self._info_rows[key].set_subtitle(info[key] or "—")
        self.info_expander.set_subtitle(subtitle)

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
            self._message = _("No se pudo aplicar: %(error)s") % {"error": error}
            if isinstance(error, (ConnectionLost, DeviceGone, ServerUnavailable)):
                self._recover(str(error))
                return False
        elif read_error is not None:
            self._panel = Panel.ERROR
            self._message = _("El cambio se envió, pero no se pudo consultar el estado")
            if isinstance(read_error, (ConnectionLost, DeviceGone, ServerUnavailable)):
                self._recover(str(read_error))
                return False
        else:
            self._panel = Panel.READY
            self._message = ""
            self._toast(message)
        self._render_state()
        return False

    def _on_color_clicked(self, _button):
        if self.device_id is None or self._closing:
            return
        target = (self._generation, self.selection_revision, self.device_id)
        initial = self._rgba or Gdk.RGBA(red=1.0, green=1.0, blue=1.0, alpha=1.0)
        self._color_dialog.choose_rgba(self, initial, None, self._on_color_chosen, target)

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
            self._message = _("Se descartó el color: cambió el dispositivo seleccionado")
            self._render_state()
            return
        self._rgba = rgba
        self.swatch.queue_draw()
        rgb = tuple(round(value * 255) for value in (rgba.red, rgba.green, rgba.blue))
        self.color_row.set_subtitle(_hex(rgb))
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
