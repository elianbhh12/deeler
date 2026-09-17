from datetime import datetime, timedelta

from python_pipeline import limpieza


def _crear_descarga(config_mod, tabla, ambiente, fecha_str, con_archivo=True):
    carpeta = config_mod.DESCARGAS_DIR / tabla / ambiente / fecha_str
    carpeta.mkdir(parents=True, exist_ok=True)
    if con_archivo:
        (carpeta / "item1.json").write_text("{}", encoding="utf-8")
    return carpeta


def test_medir_descargas_cuenta_carpetas_y_tamano(tmp_path, monkeypatch):
    monkeypatch.setattr(limpieza.config, "DESCARGAS_DIR", tmp_path / "descargas")
    _crear_descarga(limpieza.config, "config-control", "qa", "2026-09-01")
    _crear_descarga(limpieza.config, "text-analyzer", "qa", "2026-09-02")

    resumen = limpieza.medir_descargas()

    assert resumen.carpetas_de_fecha == 2
    assert resumen.bytes_totales > 0


def test_medir_descargas_sin_carpeta_no_revienta(tmp_path, monkeypatch):
    monkeypatch.setattr(limpieza.config, "DESCARGAS_DIR", tmp_path / "no_existe")
    resumen = limpieza.medir_descargas()
    assert resumen.carpetas_de_fecha == 0
    assert resumen.bytes_totales == 0


def test_limpiar_descargas_viejas_borra_solo_las_antiguas(tmp_path, monkeypatch):
    monkeypatch.setattr(limpieza.config, "DESCARGAS_DIR", tmp_path / "descargas")
    monkeypatch.setattr(limpieza.config, "DATE_FORMAT", "%Y-%m-%d")

    hoy = datetime.now()
    fecha_vieja = (hoy - timedelta(days=40)).strftime("%Y-%m-%d")
    fecha_reciente = (hoy - timedelta(days=2)).strftime("%Y-%m-%d")

    vieja = _crear_descarga(limpieza.config, "config-control", "qa", fecha_vieja)
    reciente = _crear_descarga(limpieza.config, "config-control", "qa", fecha_reciente)

    resultado = limpieza.limpiar_descargas_viejas(dias_retener=30)

    assert str(vieja) in resultado["borradas"]
    assert not vieja.exists()
    assert reciente.exists()
    assert resultado["conservadas"] == 1
    assert resultado["bytes_liberados"] > 0


def test_limpiar_descargas_viejas_dry_run_no_borra_nada(tmp_path, monkeypatch):
    monkeypatch.setattr(limpieza.config, "DESCARGAS_DIR", tmp_path / "descargas")

    fecha_vieja = (datetime.now() - timedelta(days=100)).strftime("%Y-%m-%d")
    vieja = _crear_descarga(limpieza.config, "config-control", "qa", fecha_vieja)

    resultado = limpieza.limpiar_descargas_viejas(dias_retener=30, dry_run=True)

    assert str(vieja) in resultado["borradas"]
    assert vieja.exists(), "dry_run no debe borrar nada de verdad"


def test_limpiar_descargas_viejas_no_toca_carpetas_con_nombre_no_fecha(tmp_path, monkeypatch):
    """Nombre de carpeta que no es una fecha reconocible (formato legacy, o
    algo puesto a mano) -- no se toca, mejor conservador que borrar algo
    que no se entiende."""
    monkeypatch.setattr(limpieza.config, "DESCARGAS_DIR", tmp_path / "descargas")
    rara = _crear_descarga(limpieza.config, "config-control", "qa", "carpeta_rara")

    resultado = limpieza.limpiar_descargas_viejas(dias_retener=30)

    assert str(rara) not in resultado["borradas"]
    assert rara.exists()
    assert resultado["conservadas"] == 1
