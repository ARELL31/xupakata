"""Punto de entrada de la aplicación."""
import contextlib

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
        self._window = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        self._add_action("quit", self._on_quit, ["<Control>q"])
        self._add_action("refresh", self._on_refresh, ["<Control>r"])

    def _add_action(self, name, callback, accels):
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        self.set_accels_for_action(f"app.{name}", accels)

    def _on_quit(self, *_args):
        self.quit()

    def _on_refresh(self, *_args):
        if self._window is not None:
            self._window.reload()

    def do_activate(self):
        if self._window is None:
            self._window = RgbWindow(self)
        self._window.present()

    def do_shutdown(self):
        if self._window is not None:
            with contextlib.suppress(Exception):
                self._window.shutdown()
        Adw.Application.do_shutdown(self)


def main(argv=None):
    return RgbApplication().run(argv)
