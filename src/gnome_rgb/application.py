"""Punto de entrada de la aplicación."""
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio

from .window import RgbWindow


class RgbApplication(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="io.github.gnome_rgb.GnomeRgb",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )

    def do_activate(self):
        window = self.props.active_window or RgbWindow(self)
        window.present()


def main(argv=None):
    return RgbApplication().run(argv)
