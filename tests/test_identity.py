"""La identidad pública debe coincidir en todos los artefactos."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_ID = "io.github.ARELL31.Xupakata"


def test_aplicacion_usa_el_id_publico():
    source = (ROOT / "src/xupakata/application.py").read_text()
    assert f'APPLICATION_ID = "{APP_ID}"' in source


def test_lanzador_coincide_con_el_id():
    desktop = (ROOT / f"data/{APP_ID}.desktop").read_text()
    assert f"Icon={APP_ID}" in desktop
    assert "Name=xupakata" in desktop
    assert "Exec=xupakata" in desktop
    assert "Terminal=false" in desktop


def test_metadatos_declaran_el_lanzador_y_la_licencia():
    metainfo = (ROOT / f"data/{APP_ID}.metainfo.xml").read_text()
    assert f"<id>{APP_ID}</id>" in metainfo
    assert f'<launchable type="desktop-id">{APP_ID}.desktop</launchable>' in metainfo
    assert "<project_license>GPL-3.0-or-later</project_license>" in metainfo


def test_iconos_existen_para_el_id():
    icons = ROOT / "data/icons/hicolor"
    assert (icons / f"scalable/apps/{APP_ID}.svg").is_file()
    assert (icons / f"symbolic/apps/{APP_ID}-symbolic.svg").is_file()
    assert (ROOT / "snap/gui/icon.png").is_file()


def test_snap_usa_el_mismo_id_y_nombre():
    snap = (ROOT / "snap/snapcraft.yaml").read_text()
    assert snap.startswith("name: xupakata\n")
    assert f"desktop: usr/share/applications/{APP_ID}.desktop" in snap
    assert f"common-id: {APP_ID}.desktop" in snap
    assert f"name: {APP_ID}" in snap
    assert "license: GPL-3.0-or-later" in snap
    assert "confinement: strict" in snap


def test_el_paquete_python_se_llama_xupakata():
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert 'name = "xupakata"' in pyproject
    assert 'xupakata = "xupakata.application:main"' in pyproject
    assert 'license = "GPL-3.0-or-later"' in pyproject


def test_la_version_coincide_en_los_artefactos():
    import tomllib

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    version = pyproject["project"]["version"]
    metainfo = (ROOT / f"data/{APP_ID}.metainfo.xml").read_text()

    assert f'version: "{version}"' in (ROOT / "snap/snapcraft.yaml").read_text()
    assert f'<release version="{version}"' in metainfo
