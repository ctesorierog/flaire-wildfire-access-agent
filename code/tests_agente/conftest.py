"""Configuración de pruebas locales. Datos: FLAIRE_TEST_DATOS > agent/datos (si existe escenarios.csv) > sintético."""
import os
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
AGENT = TESTS.parent
sys.path.insert(0, str(TESTS))   # studio falso
sys.path.insert(1, str(AGENT))


def _carpeta_datos(tmp_root: Path) -> Path:
    if os.environ.get("FLAIRE_TEST_DATOS"):
        return Path(os.environ["FLAIRE_TEST_DATOS"])
    if (AGENT / "datos" / "escenarios.csv").exists():
        return AGENT / "datos"
    import sintetico
    return sintetico.construir(tmp_root / "datos_sinteticos")


@pytest.fixture(scope="session", autouse=True)
def datos_flaire(tmp_path_factory):
    root = tmp_path_factory.mktemp("flaire")
    carpeta = _carpeta_datos(root)
    import flaire_data as fd
    import mapas
    fd.recargar(str(carpeta))
    mapas.CARPETA_RESULTADOS = str(root / "resultados")
    print(f"\n[flaire tests] datos = {carpeta}")
    return carpeta
