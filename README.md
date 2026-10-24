# xupakata

Control de iluminación RGB para GNOME. xupakata significa «arcoíris».

La aplicación usa [OpenRGB](https://openrgb.org/) como servidor local y no
incluye controladores de hardware propios. Cambia color, modo y brillo según
las capacidades que OpenRGB reporte para cada dispositivo.

## Requisitos

- GNOME con GTK 4 y Libadwaita.
- OpenRGB instalado en el equipo, con permisos para acceder a los dispositivos.
- Servidor SDK de OpenRGB escuchando en `127.0.0.1:6742`:

```bash
openrgb-server
# o directamente:
OpenRGB --server --server-host 127.0.0.1 --server-port 6742
```

Los permisos de hardware (reglas udev o módulo `i2c-dev`) se configuran en
OpenRGB, no en xupakata. Sin ellos el servidor no puede detectar los
dispositivos.

## Uso

1. Inicia el servidor de OpenRGB.
2. Abre xupakata.
3. Selecciona un dispositivo.
4. Ajusta color, modo o brillo. Los controles no compatibles aparecen
   desactivados con una explicación.

Si el servidor se detiene, xupakata intenta reconectarse una vez. Después
muestra el error y deja el reintento manual en **Reconectar** (`Ctrl+R`).

## Desarrollo

```bash
./scripts/install.sh base gtk openrgb
./scripts/bootstrap.sh
.venv/bin/python -m xupakata
```

Para probar sin hardware:

```bash
XUPAKATA_FAKE=1 .venv/bin/python -m xupakata
```

Pruebas y estilo:

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests
```

## Snap

La receta está en `snap/snapcraft.yaml`. El Snap solo contiene la aplicación:
OpenRGB sigue siendo un requisito externo. Para construir:

```bash
./scripts/install.sh snap
snapcraft pack
sudo snap install --dangerous xupakata_0.1.0_amd64.snap
```

## Alcance

xupakata depende de lo que OpenRGB exponga para cada dispositivo. Se ha
probado con módulos ENE de memoria RAM; otros dispositivos pueden mostrar
menos controles o requerir ajustes en OpenRGB.

## Licencia

GPL-3.0-or-later. Consulta [LICENSE](LICENSE).
