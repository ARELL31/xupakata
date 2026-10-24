"""Prueba mínima: ventana GTK4 + Libadwaita sin conexión a OpenRGB."""
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402


class RGBApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id="com.example.RGBDemo")

    def do_activate(self):
        window = Adw.ApplicationWindow(application=self)
        window.set_title("GNOME RGB")
        window.set_default_size(900, 600)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())

        page = Adw.StatusPage(
            title="GNOME RGB",
            description="Control de iluminación RGB para GNOME",
            icon_name="preferences-color-symbolic",
        )
        toolbar.set_content(page)

        window.set_content(toolbar)
        window.present()


app = RGBApplication()
app.run(None)
