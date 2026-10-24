"""Punto de entrada de la aplicación."""
import contextlib
import importlib.metadata

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, Gtk

from .i18n import _
from .window import RgbWindow

APPLICATION_ID = "io.github.ARELL31.Xupakata"
PROJECT_URL = "https://github.com/ARELL31/xupakata"


def version() -> str:
    try:
        return importlib.metadata.version("xupakata")
    except importlib.metadata.PackageNotFoundError:
        return "0.1.0"


class XupakataApplication(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id=APPLICATION_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self._window = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        self._add_action("quit", self._on_quit, ["<Control>q"])
        self._add_action("refresh", self._on_refresh, ["<Control>r"])
        self._add_action("about", self._on_about, [])

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

    def _on_about(self, *_args):
        about = Adw.AboutDialog(
            application_name="xupakata",
            application_icon=APPLICATION_ID,
            developer_name="ARELL31",
            version=version(),
            comments=_(
                "Controla la iluminación RGB de tus dispositivos a través de OpenRGB."
            ),
            license_type=Gtk.License.GPL_3_0,
            website=PROJECT_URL,
            issue_url=f"{PROJECT_URL}/issues",
            developers=["ARELL31"],
            copyright="© 2026 ARELL31",
        )
        about.present(self._window)

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
    return XupakataApplication().run(argv)
