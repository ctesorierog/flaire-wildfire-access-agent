"""flAIre FINAL · consultas deterministas y validadas sobre «agentes/flAIr datos FINAL/» (Tolosaldea).

Pregunta del plan: ¿dónde colocar hasta N retenes preventivos adicionales para las viviendas del borde forestal
de Tolosaldea y en qué días de riesgo activarlos?

Solo usa pandas, numpy y la biblioteca estándar. Cada función pública devuelve un dict con `parametros`,
los resultados, `metodo` y `limites`. Las entradas se validan; un error de entrada lanza `ErrorConsulta`
con un mensaje en español que dice qué valores son válidos. Nada se inventa: las cifras salen de los ficheros.

Reglas que implementa (ver REGLAS_prioridad.md, metodologia.csv):
- Un edificio cuenta una sola vez (mínimo sobre los orígenes activos).
- Los edificios sin ruta se informan aparte y nunca se eliminan ni cuentan como cubiertos.
- Peso ausente = desconocido (se excluye de la suma ponderada y se informa), nunca 0.
- Pesos: 'prioridad' (= peso_optimizador, prioridad sin acceso; POR DEFECTO), 'uniforme', y solo para
  sensibilidad 'meteo' (= peso_meteo_sensibilidad) y 'firescope' (= peso_firescope_sensibilidad).
- Estrategia A: máx. cobertura ponderada (desempate: nº edificios, peor tiempo).
  Estrategia B: mín. sin ruta, después mín. peor tiempo, después máx. ponderada, después nº edificios.
  Desempate final: orden alfabético de la selección.
- La prioridad es de PLANIFICACIÓN (PRIO-v1), no probabilidad de incendio. FireScope e incendios previos son
  solo referencia y nunca se suman a la prioridad.
- El año del plan es una etiqueta: no cambia ningún resultado.
"""
from __future__ import annotations

import json
import math
import unicodedata
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

VERSION = "final-1.0 (datos v0.3.2 + P1-v1 · PRIO-v1)"
EPS = 1e-9
K_MAX_ABS = 6
UMBRAL_DEF = 12.0
PERFILES = ("ligero", "camion")
ESTRATEGIAS = ("A", "B")
PESOS = ("prioridad", "uniforme", "meteo", "firescope")
PESOS_DEF = "prioridad"
CLASES = ("Alta", "Media", "Baja")
CARPETA_DATOS = "flAIr datos FINAL"
MARCADOR = "edificios_prioridad.csv"
_CARPETA_FORZADA = None  # la fija recargar(carpeta); sin variables de entorno (plataforma)

COLUMNA_PESO = {"prioridad": "peso_optimizador", "meteo": "peso_meteo_sensibilidad", "firescope": "peso_firescope_sensibilidad"}

METODO_TIEMPOS = (
    "Tiempo estimado de desplazamiento por carretera (min) desde cada origen a cada edificio: red OSM con velocidades "
    "por clase de vía, Dijkstra hacia el edificio, acceso a la red a 15 km/h en ambos extremos; perfil camión = ligero "
    "x0,9 en autopista/autovía/primaria y x0,8 en el resto. Para un conjunto de orígenes se toma el mínimo por edificio."
)
METODO_COBERTURA = (
    "Edificio dentro del umbral si su mejor tiempo (mínimo entre los 9 parques en base y los retenes elegidos) es <= umbral. "
    "Porcentajes sobre TODOS los edificios del conjunto (los sin ruta cuentan como no cubiertos). Cobertura ponderada = suma "
    "del peso elegido de los edificios dentro / suma total. Alta = edificios de prioridad de planificación Alta (PRIO-v1)."
)
METODO_OPT = (
    "Enumeración exhaustiva de todas las combinaciones de candidatas de tamaño 0..k_max (10 candidatas, k<=6: 848 "
    "combinaciones), calculada en vivo desde tiempos_<perfil>.csv. Estrategia A: máx. cobertura ponderada (desempate nº "
    "edificios, peor tiempo). Estrategia B: mín. edificios sin ruta, mín. peor tiempo, máx. ponderada, nº edificios. "
    "Desempate final: orden alfabético de la selección."
)
AVISO_PRIORIDAD = ("Prioridad de PLANIFICACIÓN (PRIO-v1, decisiones del equipo) para ordenar qué viviendas revisar o proteger "
                   "primero. NO es probabilidad de incendio ni el riesgo real de una casa.")
LIMITES_BASE = [
    "Los tiempos son ESTIMACIONES de desplazamiento con velocidades supuestas (~85 % de tramos sin límite de velocidad en OSM); no son tiempos de respuesta (no incluyen activación, salida ni tráfico).",
    "El umbral de 12 min es un parámetro de demostración, no un estándar oficial.",
    "Las candidatas son lugares de ESTUDIO (OSM): no están autorizadas ni validadas; cada una tiene comprobaciones de campo pendientes.",
    "Los parques de Navarra no están incluidos como orígenes.",
]
LIMITE_PESOS = {
    "prioridad": ("Pesos 'prioridad' = peso_optimizador: prioridad de planificación SIN el componente de acceso (Alta 1,83 · Media 1,22 · "
                  "Baja 0,61; media 1), porque el optimizador ya mide el acceso (así no se cuenta dos veces). " + AVISO_PRIORIDAD),
    "uniforme": "Pesos 'uniforme': cada edificio pesa 1 (cobertura ponderada = nº de edificios).",
    "meteo": ("Pesos 'meteo' (legado jul-ago, solo sensibilidad) = peso_meteo_sensibilidad (regla ADV-v1 de julio-agosto). Las zonas "
              "meteorológicas no se distinguen con 2018-2023 (meteo_test_zonas.csv) y no entran en la prioridad."),
    "firescope": ("Pesos 'firescope' = peso_firescope_sensibilidad (FireScope, INSAIT, media 1): SOLO análisis de sensibilidad. "
                  "Referencia externa experimental, no oficial ni probabilidad calibrada; nunca se suma a la prioridad."),
}
LIMITE_PONDERADA = "Cobertura ponderada no es población protegida; viviendas por edificio vienen de B5M tal cual."
LECTURA_METEO = ("La meteorología dice CUÁNDO, no DÓNDE: las zonas no se distinguen, así que no cambia dónde colocar los retenes; "
                 "sirve para activarlos en días de riesgo (calor seco o viento sur seco) en lugar de fijarlos en julio-agosto.")


class ErrorConsulta(ValueError):
    """Error de entrada con mensaje explicativo en español."""


# ----------------------------------------------------------------------------- utilidades
def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().replace("_", " ").replace("-", " ").replace("/", " ").replace(".", " ")
    return " ".join(s.split())


def _num(x, nd=2):
    if x is None:
        return None
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return x
    if math.isnan(xf) or math.isinf(xf):
        return None
    return round(xf, nd)


def _int(x):
    if x is None:
        return None
    try:
        if isinstance(x, float) and math.isnan(x):
            return None
        return int(float(x))
    except (TypeError, ValueError):
        return None


def _limpio(v):
    """Valor de pandas/numpy -> tipo JSON (NaN -> None)."""
    if v is None:
        return None
    if hasattr(v, "item"):
        try:
            v = v.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def _registros(df, cols=None) -> list:
    if df is None:
        return []
    d = df if cols is None else df[[c for c in cols if c in df.columns]]
    return [{k: _limpio(v) for k, v in r.items()} for r in d.to_dict("records")]


def _entero_rango(x, nombre, lo, hi) -> int:
    try:
        v = int(float(x))
    except (TypeError, ValueError):
        raise ErrorConsulta(f"{nombre} debe ser un entero entre {lo} y {hi} (recibido: {x!r}).")
    if not lo <= v <= hi:
        raise ErrorConsulta(f"{nombre} debe estar entre {lo} y {hi} (recibido: {x}).")
    return v


LIMITE_LISTAS = 50  # máximo de filas por lista en una llamada (coste en tokens)


def _limite(x, nombre="limite", minimo=0) -> int:
    """Entero >= minimo, recortado a LIMITE_LISTAS."""
    return min(_entero_rango(x, nombre, minimo, 10 ** 6), LIMITE_LISTAS)


def _truncada(mostrados, total, archivo):
    if total <= mostrados:
        return None
    return (f"Lista truncada: se muestran {mostrados} de {total} (máximo {LIMITE_LISTAS} por llamada). Para ver más, filtre "
            f"(municipio, prioridad, mes, fechas…) o use ejecutar_codigo con pandas sobre 'agentes/{CARPETA_DATOS}/{archivo}'.")


def _localizar_datos() -> Path:
    here = Path(__file__).resolve().parent
    cwd = Path.cwd()
    cands = []
    if _CARPETA_FORZADA:
        cands.append(Path(_CARPETA_FORZADA))
    cands += [cwd / "agentes" / CARPETA_DATOS,      # plataforma: cwd = raíz del workspace
              here.parent / CARPETA_DATOS,          # carpeta hermana de agentes/agente_flair_final/
              here / CARPETA_DATOS, here / "datos", cwd / "datos", cwd / CARPETA_DATOS]
    for c in cands:
        if (c / MARCADOR).exists():
            return c
    raise FileNotFoundError(f"No se encuentra la carpeta de datos con {MARCADOR} (buscado en: " + ", ".join(str(c) for c in cands) + ")")


class _Datos:
    """Carga única de los CSV (caché de módulo)."""

    def __init__(self, carpeta: Path):
        self.carpeta = carpeta
        rd = lambda f, **kw: pd.read_csv(carpeta / f, **kw)
        opt = lambda f, **kw: rd(f, **kw) if (carpeta / f).exists() else None
        e = rd(MARCADOR, dtype={"building_id": str, "muni_ine": str, "zona_meteo": str, "sin_ruta": str, "prioridad": str,
                                "prioridad_sin_acceso": str, "motivo_prioridad": str, "fs_clase": str})
        if e.building_id.duplicated().any():
            raise ValueError(f"{MARCADOR} tiene building_id duplicados: cada edificio debe contar una vez")
        self.edif = e.sort_values("building_id").reset_index(drop=True)
        e = self.edif
        self.ids = e.building_id.to_numpy()
        self.n = len(e)
        self.parques = rd("parques.csv", dtype={"origen_id": str})
        self.cands = rd("candidatos.csv", dtype={"origen_id": str, "osm_id": str}).sort_values("origen_id").reset_index(drop=True)
        self.munis = rd("municipios.csv", dtype={"muni_ine": str, "zona_meteo": str})
        self.esc = opt("escenarios.csv", dtype={"seleccion": str, "estrategia": str, "perfil": str, "pesos": str})
        if self.esc is not None:
            self.esc["seleccion"] = self.esc["seleccion"].fillna("")
        self.m_est = opt("meteo_estaciones.csv", dtype={"codigo": str})
        self.m_mensual = opt("meteo_mensual.csv", dtype={"codigo": str})
        self.m_anual = opt("meteo_anual.csv", dtype={"codigo": str, "anio_completo": str})
        self.m_dias = opt("meteo_dias_riesgo.csv", dtype={"codigo": str, "fecha": str, "tipo": str})
        self.m_test = opt("meteo_test_zonas.csv", dtype={"distinguible": str})
        self.incendios = opt("incendios_previos.csv")
        self.fuentes = opt("fuentes.csv", dtype=str)
        self.metodologia = opt("metodologia.csv", dtype=str)
        self.cifras = None
        if (carpeta / "cifras_clave_persona1.json").exists():
            try:
                self.cifras = json.loads((carpeta / "cifras_clave_persona1.json").read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                self.cifras = None
        self.textos = {}
        for f in ("REGLAS_prioridad.md", "DICCIONARIO_datos.md"):
            if (carpeta / f).exists():
                self.textos[f] = (carpeta / f).read_text(encoding="utf-8")
        self.parques_base = self.parques[self.parques.en_base.astype(int) == 1].origen_id.tolist()
        self.cand_ids = self.cands.origen_id.tolist()
        self.tiempos = {}
        for p in PERFILES:
            t = rd(f"tiempos_{p}.csv", dtype={"building_id": str}).set_index("building_id")
            if t.index.duplicated().any():
                raise ValueError(f"tiempos_{p}.csv tiene building_id duplicados")
            missing = [o for o in self.parques_base + self.cand_ids if o not in t.columns]
            if missing:
                raise ValueError(f"tiempos_{p}.csv no tiene columnas para {missing}")
            t = t.reindex(self.ids)
            T = t[self.parques_base + self.cand_ids].to_numpy(dtype=float)
            T[~np.isfinite(T)] = np.nan
            if (T[~np.isnan(T)] < 0).any():
                raise ValueError(f"tiempos negativos en tiempos_{p}.csv")
            self.tiempos[p] = T  # (n, 9+10)
        self.n_parq = len(self.parques_base)
        self.peso = {"uniforme": np.ones(self.n)}
        for w, col in COLUMNA_PESO.items():
            self.peso[w] = pd.to_numeric(e[col], errors="coerce").to_numpy(float) if col in e.columns else np.full(self.n, np.nan)
        self.clase = e["prioridad"].fillna("").astype(str).str.strip().to_numpy() if "prioridad" in e.columns else np.full(self.n, "", dtype=object)
        self.alta = self.clase == "Alta"
        self.sin_ruta = e["sin_ruta"].fillna("").map(_norm).isin(["si", "yes", "1", "true"]).to_numpy() if "sin_ruta" in e.columns \
            else np.zeros(self.n, bool)
        self.viv = pd.to_numeric(e.get("viviendas"), errors="coerce").to_numpy(float)
        if self.m_est is not None and "usada_en_zonas" in self.m_est.columns:
            self.zonas = sorted(self.m_est[pd.to_numeric(self.m_est.usada_en_zonas, errors="coerce") == 1].codigo.tolist())
        else:
            self.zonas = sorted(set(e.zona_meteo.dropna().astype(str)))
        self.muni_nombres = sorted(self.munis.municipio.dropna().unique().tolist())
        self.edif_muni = e.municipio.to_numpy()

    def base(self, perfil):
        T = self.tiempos[perfil][:, : self.n_parq]
        filled = np.where(np.isnan(T), np.inf, T)
        arg = np.argmin(filled, axis=1)
        best = filled[np.arange(self.n), arg]
        return best, arg  # inf = sin ruta

    def cand_t(self, perfil):
        T = self.tiempos[perfil][:, self.n_parq:]
        return np.where(np.isnan(T), np.inf, T).T  # (10, n)


_DATOS = None


def datos() -> _Datos:
    global _DATOS
    if _DATOS is None:
        _DATOS = _Datos(_localizar_datos())
    return _DATOS


def recargar(carpeta: str | None = None) -> None:
    """Vuelve a leer los datos (tests o tras actualizar la carpeta de datos)."""
    global _DATOS, _CARPETA_FORZADA
    if carpeta:
        _CARPETA_FORZADA = str(carpeta)
    _DATOS = None
    _optimizar_cache.cache_clear()
    _matriz.cache_clear()


_COMPROB = {"heavy_vehicle_space": "espacio y maniobra para vehículo pesado", "ownership_permit": "titularidad y permiso de uso",
            "truck_access": "acceso de camión (anchura, pendiente, gálibo, firme)", "water": "agua cercana (hidrante/depósito)",
            "traffic_restrictions": "restricciones de tráfico/ocupación", "ortho_location": "ubicación exacta en ortofoto"}


def traducir_comprobaciones(s) -> str:
    if s is None or (isinstance(s, float) and math.isnan(s)):
        return ""
    sep = ";" if ";" in str(s) else ","
    partes = [x.strip() for x in str(s).split(sep) if x.strip()]
    return "; ".join(_COMPROB.get(x, x) for x in partes)


# ----------------------------------------------------------------------------- validación
def v_umbral(umbral) -> float:
    try:
        u = float(umbral)
    except (TypeError, ValueError):
        raise ErrorConsulta(f"umbral debe ser un número de minutos entre 1 y 60 (recibido: {umbral!r}).")
    if math.isnan(u) or not (1 <= u <= 60):
        raise ErrorConsulta(f"umbral debe estar entre 1 y 60 minutos (recibido: {umbral}). Por defecto 12 (demostración, no oficial).")
    return u


def v_perfil(perfil) -> str:
    p = _norm(perfil or "ligero")
    alias = {"ligero": "ligero", "light": "ligero", "vehiculo ligero": "ligero", "coche": "ligero",
             "camion": "camion", "truck": "camion", "pesado": "camion", "autobomba": "camion"}
    if p not in alias:
        raise ErrorConsulta(f"perfil debe ser 'ligero' o 'camion' (recibido: {perfil!r}).")
    return alias[p]


def v_estrategia(e) -> str:
    s = str(e or "A").strip().upper()
    if s not in ESTRATEGIAS:
        raise ErrorConsulta(f"estrategia debe ser 'A' (máx. cobertura ponderada) o 'B' (mejorar el peor acceso) (recibido: {e!r}).")
    return s


def v_pesos(p) -> str:
    s = _norm(p or PESOS_DEF)
    alias = {"prioridad": "prioridad", "prioridad sin acceso": "prioridad", "peso optimizador": "prioridad", "optimizador": "prioridad",
             "planificacion": "prioridad", "prio": "prioridad", "defecto": "prioridad",
             "uniforme": "uniforme", "uniformes": "uniforme", "ninguno": "uniforme", "sin pesos": "uniforme", "none": "uniforme",
             "meteo": "meteo", "meteo sensibilidad": "meteo", "historico": "meteo", "historicos": "meteo",
             "firescope": "firescope", "fire scope": "firescope", "insait": "firescope", "firescope sensibilidad": "firescope"}
    if s not in alias:
        raise ErrorConsulta(f"pesos debe ser 'prioridad' (por defecto: prioridad de planificación sin acceso), 'uniforme' (todos 1), "
                            f"'meteo' (legado jul-ago, solo sensibilidad) o 'firescope' (solo sensibilidad) (recibido: {p!r}).")
    w = alias[s]
    if w != "uniforme" and np.isnan(datos().peso[w]).all():
        raise ErrorConsulta(f"Los pesos '{w}' no están disponibles en estos datos (falta {COLUMNA_PESO[w]} en {MARCADOR}).")
    return w


def v_clase(c, permitir_vacio=True):
    if c is None or str(c).strip() == "":
        if permitir_vacio:
            return None
        raise ErrorConsulta("Indique la clase de prioridad: 'Alta', 'Media' o 'Baja'.")
    s = _norm(c)
    for k in CLASES:
        if s == _norm(k) or s == _norm(k)[:1]:
            return k
    raise ErrorConsulta(f"Clase de prioridad desconocida: {c!r}. Válidas: Alta, Media, Baja.")


def v_k(k, nombre="k", minimo=0) -> int:
    D = datos()
    try:
        kf = float(k)
        ki = int(kf)
    except (TypeError, ValueError):
        raise ErrorConsulta(f"{nombre} debe ser un entero (recibido: {k!r}).")
    if kf != ki:
        raise ErrorConsulta(f"{nombre} debe ser un entero (recibido: {k}).")
    kmax = min(K_MAX_ABS, len(D.cand_ids))
    if not (minimo <= ki <= kmax):
        raise ErrorConsulta(
            f"{nombre}={ki} fuera de rango: debe estar entre {minimo} y {kmax} (máximo {K_MAX_ABS} retenes adicionales y "
            f"nunca más que las {len(D.cand_ids)} candidatas válidas).")
    return ki


def etiqueta_candidata(nombre, municipio) -> str:
    """'nombre (municipio)' sin repetir el municipio si el nombre ya lo incluye."""
    n, m = str(nombre), str(municipio)
    return n if _norm(m) and _norm(m) in _norm(n) else f"{n} ({m})"


def v_candidata(c) -> str:
    D = datos()
    s = str(c).strip().upper().replace(" ", "").replace("_", "-")
    digits = "".join(ch for ch in s if ch.isdigit())
    if s.startswith("CAND") or s.isdigit():
        if digits:
            cid = f"CAND-{int(digits):02d}"
            if cid in D.cand_ids:
                return cid
    lista = "; ".join(f"{r.origen_id} {etiqueta_candidata(r.nombre, r.municipio)}" for r in D.cands.itertuples())
    raise ErrorConsulta(f"Candidata desconocida: {c!r}. Válidas: {lista}.")


def v_seleccion(sel) -> list:
    """Lista de candidatas (vacía = solo parques, k=0). Acepta lista o texto separado por ; , | o espacios."""
    if sel is None:
        return []
    if isinstance(sel, str):
        s = sel.strip()
        if _norm(s) in ("", "ninguna", "ninguno", "k0", "k 0", "solo parques", "sin retenes", "parques", "0"):
            return []
        for sep in [";", "|", ","]:
            s = s.replace(sep, " ")
        items = s.split()
    else:
        items = list(sel)
    out = []
    for it in items:
        cid = v_candidata(it)
        if cid not in out:
            out.append(cid)
    if len(out) > min(K_MAX_ABS, len(datos().cand_ids)):
        raise ErrorConsulta(f"Como máximo {K_MAX_ABS} retenes adicionales (recibidas {len(out)} candidatas).")
    return sorted(out)


_ALIAS_MUNI = {"amasa villabona": "Villabona", "villabona amasa": "Villabona", "amasa": "Villabona",
               "bidania": "Bidania-Goiatz", "goiatz": "Bidania-Goiatz", "bidania goiatz": "Bidania-Goiatz",
               "abalcisqueta": "Abaltzisketa", "albistur": "Albiztur", "alquiza": "Alkiza", "alzo": "Altzo",
               "amezqueta": "Amezketa", "belaunza": "Belauntza", "berastegui": "Berastegi", "cizurquil": "Zizurkil",
               "elduayen": "Elduain", "icazteguieta": "Ikaztegieta", "lizarza": "Lizartza", "oreja": "Orexa"}


def v_municipio(m) -> str:
    D = datos()
    if m is None or str(m).strip() == "":
        raise ErrorConsulta("Falta el municipio.")
    nm = _norm(m)
    by = {_norm(x): x for x in D.muni_nombres}
    if nm in by:
        return by[nm]
    if nm in _ALIAS_MUNI and _ALIAS_MUNI[nm] in D.muni_nombres:
        return _ALIAS_MUNI[nm]
    hits = [x for k, x in by.items() if nm and (k.startswith(nm) or nm in k.split())]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise ErrorConsulta(f"Municipio ambiguo: {m!r} coincide con {hits}. Indique uno.")
    raise ErrorConsulta(f"Municipio desconocido: {m!r}. Válidos (28 de Tolosaldea): {', '.join(D.muni_nombres)}.")


def v_edificio(b) -> str:
    D = datos()
    s = str(b).strip()
    if s.isdigit():
        s = f"ES.GFA.BU.{s}"
    idx = {x.upper(): x for x in D.ids}
    if s.upper() in idx:
        return idx[s.upper()]
    raise ErrorConsulta(f"Edificio {b!r} no está en el conjunto de análisis ({D.n} edificios residenciales a <=100 m de "
                        "vegetación). Los id tienen la forma ES.GFA.BU.<número> (INSPIRE B5M).")


# ----------------------------------------------------------------------------- núcleo de cálculo
def _evaluar(seleccion: list, umbral: float, perfil: str, pesos: str) -> dict:
    """Evalúa una selección concreta (parques en base + candidatas)."""
    D = datos()
    base, arg = D.base(perfil)
    best = base.copy()
    origen = np.array(D.parques_base, dtype=object)[arg]
    C = D.cand_t(perfil)
    for cid in seleccion:
        j = D.cand_ids.index(cid)
        better = C[j] < best
        best = np.where(better, C[j], best)
        origen = np.where(better, cid, origen)
    routable = np.isfinite(best)
    origen = np.where(routable, origen, None)
    cubierto = routable & (best <= umbral + EPS)
    w = D.peso[pesos]
    known = ~np.isnan(w)
    wt = float(w[known].sum())
    wc = float(w[known & cubierto].sum())
    n = D.n
    worst = float(best[routable].max()) if routable.any() else None
    p95 = float(np.percentile(best[routable], 95)) if routable.any() else None
    j_worst = int(np.argmax(np.where(routable, best, -np.inf))) if routable.any() else None
    return dict(best=best, origen=origen, cubierto=cubierto, routable=routable,
                n=n, n_cubiertos=int(cubierto.sum()), pct=100.0 * cubierto.sum() / n if n else 0.0,
                n_sin_ruta=int((~routable).sum()), peor=worst, p95=p95, j_peor=j_worst,
                pond=wc, pond_total=wt, pct_pond=100.0 * wc / wt if wt > 0 else None, n_peso_faltante=int((~known).sum()))


def _alta(ev: dict) -> dict:
    """Recuentos de prioridad Alta (y por clase) para una evaluación."""
    D = datos()
    a = D.alta
    n_a = int(a.sum())
    dentro = int((ev["cubierto"] & a).sum())
    return {"alta_total": n_a, "alta_dentro": dentro, "pct_alta_dentro": _num(100.0 * dentro / n_a) if n_a else None,
            "alta_sin_ruta": int((~ev["routable"] & a).sum()), "alta_fuera_con_ruta": int((ev["routable"] & ~ev["cubierto"] & a).sum()),
            "dentro_por_prioridad": {c: int((ev["cubierto"] & (D.clase == c)).sum()) for c in CLASES},
            "viviendas_dentro": _int(np.nansum(np.where(ev["cubierto"], D.viv, 0.0)))}


def _metricas(ev: dict) -> dict:
    D = datos()
    j = ev["j_peor"]
    out = {
        "edificios_total": ev["n"],
        "edificios_dentro": ev["n_cubiertos"],
        "pct_dentro": _num(ev["pct"]),
        "cobertura_ponderada": _num(ev["pond"], 3),
        "cobertura_ponderada_total": _num(ev["pond_total"], 3),
        "pct_ponderada": _num(ev["pct_pond"]),
        "peor_tiempo_min": _num(ev["peor"]),
        "p95_tiempo_min": _num(ev.get("p95")),
        "peor_edificio": None if j is None else {"building_id": D.ids[j], "municipio": D.edif_muni[j], "origen": ev["origen"][j],
                                                 "prioridad": D.clase[j]},
        "sin_ruta": ev["n_sin_ruta"],
        "peso_faltante": ev["n_peso_faltante"],
    }
    out.update(_alta(ev))
    return out


def _combinaciones(seq, k):
    """Equivalente a itertools.combinations (orden lexicográfico), sin importar itertools."""
    seq = list(seq)
    n = len(seq)
    if k > n:
        return []
    if k == 0:
        return [()]
    idx = list(range(k))
    out = [tuple(seq[i] for i in idx)]
    for _ in range(10 ** 7):
        i = k - 1
        for _j in range(k):
            if idx[i] != i + n - k:
                break
            i -= 1
        else:
            return out
        if i < 0:
            return out
        idx[i] += 1
        for j in range(i + 1, k):
            idx[j] = idx[j - 1] + 1
        out.append(tuple(seq[i2] for i2 in idx))
    return out


def _memo(fn):
    """Caché de módulo (sustituye a functools.lru_cache)."""
    cache = {}

    def envoltura(*a):
        if a not in cache:
            if len(cache) > 64:
                cache.clear()
            cache[a] = fn(*a)
        return cache[a]
    envoltura.cache_clear = cache.clear
    return envoltura


def _combos(k_max: int):
    cands = sorted(datos().cand_ids)
    out = []
    for k in range(k_max + 1):
        out += _combinaciones(cands, k)
    return out


@_memo
def _matriz(k_max: int, umbral: float, perfil: str, pesos: str):
    """Agregados por combinación (0..k_max candidatas): edificios dentro, Alta dentro, sin ruta, peor tiempo, ponderada."""
    D = datos()
    combos = _combos(k_max)
    cands = sorted(D.cand_ids)
    M = np.zeros((len(combos), len(cands)), dtype=bool)
    for i, c in enumerate(combos):
        for cid in c:
            M[i, cands.index(cid)] = True
    base, _ = D.base(perfil)
    C = D.cand_t(perfil)
    best = np.broadcast_to(base, (len(combos), D.n)).copy()
    for j, cid in enumerate(cands):
        jj = D.cand_ids.index(cid)
        rows = M[:, j]
        if rows.any():
            best[rows] = np.minimum(best[rows], C[jj][None, :])
    routable = np.isfinite(best)
    cub = routable & (best <= umbral + EPS)
    n_cov = cub.sum(axis=1)
    n_unr = (~routable).sum(axis=1)
    n_alta = cub[:, D.alta].sum(axis=1)
    worst = np.where(routable, best, -np.inf).max(axis=1)
    worst = np.where(np.isfinite(worst), worst, np.inf)
    w = D.peso[pesos]
    known = ~np.isnan(w)
    wk = np.where(known, w, 0.0)
    uniq = np.unique(wk[known])
    if len(uniq) <= 64:
        # suma por valor distinto de peso: misma cuenta -> mismo resultado bit a bit (empates exactos)
        counts = np.stack([(cub & (known & (wk == u))[None, :]).sum(axis=1) for u in uniq], axis=1).astype(float)
        wc = np.zeros(len(combos))
        for i_u, u in enumerate(uniq):
            wc = wc + counts[:, i_u] * u
    else:
        wc = cub.astype(float) @ wk
    wt = float(wk.sum())
    ks = M.sum(axis=1)
    return dict(combos=combos, ks=ks, n_cov=n_cov, n_unr=n_unr, n_alta=n_alta, worst=worst, wc=wc, wt=wt)


@_memo
def _optimizar_cache(k_max: int, estrategia: str, umbral: float, perfil: str, pesos: str):
    X = _matriz(k_max, umbral, perfil, pesos)
    combos, ks, n_cov, n_unr, n_alta, worst, wc, wt = (X[c] for c in ("combos", "ks", "n_cov", "n_unr", "n_alta", "worst", "wc", "wt"))
    pos = np.arange(len(combos))  # orden lexicográfico = orden alfabético de la selección
    wc_r = np.round(wc, 9)
    worst_r = np.round(worst, 9)
    per_k = []
    for k in range(k_max + 1):
        idx = np.where(ks == k)[0]
        if estrategia == "A":
            keys = (pos[idx], worst_r[idx], -n_cov[idx], -wc_r[idx])
        else:
            keys = (pos[idx], -n_cov[idx], -wc_r[idx], worst_r[idx], n_unr[idx])
        order = idx[np.lexsort(keys)]
        top = order[0]
        if estrategia == "A":
            same = (wc_r[order] == wc_r[top]) & (n_cov[order] == n_cov[top]) & (worst_r[order] == worst_r[top])
        else:
            same = (n_unr[order] == n_unr[top]) & (worst_r[order] == worst_r[top]) & (wc_r[order] == wc_r[top]) & (n_cov[order] == n_cov[top])
        tied = order[same]
        per_k.append(dict(k=k, idx=int(top), seleccion=list(combos[top]), n_cub=int(n_cov[top]), n_unr=int(n_unr[top]),
                          n_alta=int(n_alta[top]), peor=float(worst[top]) if np.isfinite(worst[top]) else None, pond=float(wc[top]),
                          empates=int(len(tied)), empatadas=[list(combos[t]) for t in tied[:6]],
                          rank2=[dict(seleccion=list(combos[t]), edificios_dentro=int(n_cov[t]), alta_dentro=int(n_alta[t]),
                                      pct_ponderada=_num(100 * wc[t] / wt if wt else None),
                                      peor_tiempo_min=_num(worst[t]), sin_ruta=int(n_unr[t])) for t in order[1:4]]))
    return dict(per_k=per_k, wt=wt, n_combos=len(combos))


def greedy_cobertura(cubierto_base: np.ndarray, cubre: np.ndarray, k: int) -> list:
    """Greedy maximal coverage, for pools too big to enumerate (PLAN.md item 9).

    cubierto_base: (n,) bool, homes already within the threshold from the parks.
    cubre: (m, n) bool, homes each site reaches within the threshold.
    Up to k times, adds the site that reaches the most homes not yet covered (ties: lowest index); stops early when no
    site adds anything. Returns [(site index, homes gained)] in order of choice.
    """
    cubierto = np.asarray(cubierto_base, dtype=bool).copy()
    cubre = np.asarray(cubre, dtype=bool)
    pasos = []
    for _ in range(k):
        gains = (cubre & ~cubierto).sum(axis=1)
        j = int(np.argmax(gains)) if len(gains) else 0
        if not len(gains) or gains[j] == 0:
            break
        pasos.append((j, int(gains[j])))
        cubierto |= cubre[j]
    return pasos


def _clave(m, estrategia):
    if estrategia == "A":
        return (-round(m["pond"], 9), -m["n_cub"], round(m["peor"] if m["peor"] is not None else math.inf, 9))
    return (m["n_unr"], round(m["peor"] if m["peor"] is not None else math.inf, 9), -round(m["pond"], 9), -m["n_cub"])


def _escenario_guardado(estrategia, k, umbral, perfil, pesos):
    D = datos()
    if D.esc is None:
        return None
    e = D.esc
    r = e[(e.estrategia.str.upper() == estrategia) & (e.k.astype(int) == k) & (np.isclose(e.umbral_min.astype(float), umbral))
          & (e.perfil == perfil) & (e.pesos == pesos)]
    if r.empty:
        return None
    return r.iloc[0].to_dict()


def _nota_escenarios(estrategia, umbral, perfil, pesos):
    """Texto si no hay escenario guardado para estos parámetros (p. ej. pesos 'prioridad')."""
    if _escenario_guardado(estrategia, 0, umbral, perfil, pesos) is not None:
        return None
    return (f"escenarios.csv no tiene la combinación ({estrategia}, {umbral:g} min, {perfil}, pesos '{pesos}'): la cifra calculada EN VIVO "
            "es la referencia; para recomprobarla use comprobar_cifra (recálculo independiente).")


def _resolver_seleccion(seleccion, k, estrategia, umbral, perfil, pesos):
    """seleccion explícita, o la mejor de `estrategia` con `k` retenes."""
    if seleccion is not None and not (isinstance(seleccion, str) and seleccion.strip() == "" and k is not None):
        return v_seleccion(seleccion), "explicita"
    if k is None:
        return [], "k0"
    kk = v_k(k)
    res = _optimizar_cache(kk, estrategia, umbral, perfil, pesos)
    return list(res["per_k"][kk]["seleccion"]), f"mejor_{estrategia}_k{kk}"


def _limites_pesos(w):
    return [LIMITE_PESOS[w]]


# ----------------------------------------------------------------------------- meteorología (todo el año)
def _meteo_resumen() -> dict:
    """Media de las zonas del modelo por mes, total anual y reparto por ventanas."""
    D = datos()
    if D.m_mensual is None:
        return {}
    m = D.m_mensual[D.m_mensual.codigo.isin(D.zonas)]
    g = m.groupby("mes")[["media_dias_riesgo_por_mes", "media_calor_seco_por_mes", "media_viento_sur_por_mes"]].mean().sort_index()
    r = g.media_dias_riesgo_por_mes
    tot = float(r.sum())
    rep = lambda meses: _num(100.0 * float(r[r.index.isin(meses)].sum()) / tot, 0) if tot else None
    meses = [{"mes": int(i), "dias_riesgo": _num(x.media_dias_riesgo_por_mes, 1), "calor_seco": _num(x.media_calor_seco_por_mes, 1),
              "viento_sur": _num(x.media_viento_sur_por_mes, 1)} for i, x in g.iterrows()]
    out = {"zonas": list(D.zonas),
           "por_mes_media_zonas": meses,
           "dias_riesgo_por_anio": _num(sum(x["dias_riesgo"] for x in meses), 1),
           "dias_riesgo_por_anio_sin_redondeo": _num(tot, 1),
           "reparto_pct": {"feb-abr": rep([2, 3, 4]), "jul-ago": rep([7, 8]), "sep-oct": rep([9, 10])},
           "meses_pico": [x["mes"] for x in sorted(meses, key=lambda x: -(x["dias_riesgo"] or 0))[:2]],
           "zonas_distinguibles": None}
    if D.m_test is not None and len(D.m_test):
        out["zonas_distinguibles"] = bool(D.m_test.distinguible.fillna("").map(_norm).isin(["si", "yes"]).any())
    out["nota_total"] = ("Total anual = suma de las medias mensuales redondeadas a 1 decimal (cifra citada en REGLAS_prioridad.md); "
                         "sin redondeo, dias_riesgo_por_anio_sin_redondeo.")
    return out


def _zona_desde_texto(z) -> str:
    D = datos()
    if D.m_est is None:
        raise ErrorConsulta("No hay meteo_estaciones.csv en los datos.")
    validas = sorted(set(D.m_mensual.codigo)) if D.m_mensual is not None else list(D.zonas)
    s = str(z).strip().upper()
    if s in validas:
        return s
    if s.startswith("Z-") and s[2:] in validas:
        return s[2:]
    nm = _norm(z)
    hit = D.m_est[D.m_est.codigo.isin(validas) & (D.m_est.nombre.map(_norm) == nm)]
    if len(hit) == 1:
        return hit.codigo.iloc[0]
    nombres = [f"{r.codigo} {r.nombre}" + ("" if r.codigo in D.zonas else " (control)") for r in D.m_est[D.m_est.codigo.isin(validas)].itertuples()]
    raise ErrorConsulta(f"Zona meteorológica desconocida: {z!r}. Válidas: {', '.join(nombres)}.")


def _fecha(s, nombre):
    if s is None or str(s).strip() == "":
        return None
    try:
        return datetime.strptime(str(s).strip()[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise ErrorConsulta(f"{nombre} debe tener formato AAAA-MM-DD (recibido: {s!r}).")


def perfil_meteo(zona=None, municipio=None, mes=None, anio=None, tipo=None, fecha_desde=None, fecha_hasta=None, top_dias=10) -> dict:
    """Meteorología de TODO el año: días de riesgo (calor seco o viento sur seco) por mes y zona, por año, prueba de
    zonas, episodio de validación (Bera–Aiako Harria, feb. 2021) y lista filtrable de días de riesgo."""
    D = datos()
    if D.m_mensual is None or D.m_dias is None:
        raise ErrorConsulta("Faltan meteo_mensual.csv o meteo_dias_riesgo.csv en los datos.")
    top = _limite(top_dias, "top_dias")
    mes_v = None if mes is None else _entero_rango(mes, "mes", 1, 12)
    anio_v = None if anio is None else _entero_rango(anio, "anio", 2018, 2023)
    fd_, fh_ = _fecha(fecha_desde, "fecha_desde"), _fecha(fecha_hasta, "fecha_hasta")
    tipo_v = None
    if tipo:
        t = _norm(tipo)
        if t.startswith("calor"):
            tipo_v = "calor"
        elif t.startswith("viento") or t == "sur":
            tipo_v = "viento"
        else:
            raise ErrorConsulta("tipo debe ser 'calor' (calor seco) o 'viento' (viento sur seco); vacío = ambos.")
    muni = None
    if municipio:
        muni = v_municipio(municipio)
        zs = D.munis[D.munis.municipio == muni].zona_meteo.dropna().astype(str).tolist()
        codigos = zs
        if zona and _zona_desde_texto(zona) not in zs:
            raise ErrorConsulta(f"{muni} está asignado a la zona {zs}, no a {zona}.")
    elif zona:
        codigos = [_zona_desde_texto(zona)]
    else:
        codigos = list(D.zonas)
    est = D.m_est.set_index("codigo") if D.m_est is not None else None
    zonas = []
    for c in codigos:
        z = {"codigo": c, "nombre": None if est is None or c not in est.index else str(est.loc[c, "nombre"]),
             "zona_del_modelo": c in D.zonas,
             "municipios_asignados": sorted(D.munis[D.munis.zona_meteo == c].municipio.tolist())}
        if D.m_anual is not None:
            a = D.m_anual[D.m_anual.codigo == c].sort_values("anio")
            comp = a[a.anio_completo.fillna("").map(_norm).isin(["si", "yes"])]
            z["dias_riesgo_por_anio_media_anios_completos"] = _num(comp.dias_riesgo_por_anio.mean(), 1)
            z["sd_interanual"] = _num(comp.dias_riesgo_por_anio.std(), 1)
            z["anios_completos"] = comp.anio.astype(int).tolist()
            if zona or municipio:
                z["por_anio"] = [{"anio": int(x.anio), "dias_validos": _int(x.dias_validos), "dias_riesgo": _int(x.dias_riesgo),
                                  "calor_seco": _int(x.dias_calor_seco), "viento_sur": _int(x.dias_viento_sur),
                                  "completo": str(x.anio_completo), "dias_riesgo_por_anio": _num(x.dias_riesgo_por_anio, 1)} for x in a.itertuples()]
        mm = D.m_mensual[D.m_mensual.codigo == c].sort_values("mes")
        if zona or municipio:
            z["por_mes"] = [{"mes": int(x.mes), "dias_riesgo_media": _num(x.media_dias_riesgo_por_mes, 2),
                             "calor_seco_media": _num(x.media_calor_seco_por_mes, 2), "viento_sur_media": _num(x.media_viento_sur_por_mes, 2),
                             "dias_riesgo_total": _int(x.dias_riesgo), "dias_validos": _int(x.dias_validos)} for x in mm.itertuples()]
        z["dias_riesgo_por_anio_suma_medias_mensuales"] = _num(mm.media_dias_riesgo_por_mes.sum(), 1)
        zonas.append(z)
    # días de riesgo filtrados
    dd = D.m_dias[D.m_dias.codigo.isin(codigos)].copy()
    fechas = pd.to_datetime(dd.fecha, errors="coerce")
    mask = np.ones(len(dd), bool)
    if mes_v:
        mask &= (fechas.dt.month == mes_v).to_numpy()
    if anio_v:
        mask &= (fechas.dt.year == anio_v).to_numpy()
    if fd_:
        mask &= (dd.fecha.astype(str) >= fd_).to_numpy()
    if fh_:
        mask &= (dd.fecha.astype(str) <= fh_).to_numpy()
    if tipo_v == "calor":
        mask &= dd.tipo.fillna("").str.contains("calor").to_numpy()
    elif tipo_v == "viento":
        mask &= dd.tipo.fillna("").str.contains("viento").to_numpy()
    sel = dd[mask].sort_values(["fecha", "codigo"], ascending=[False, True])
    lista = [{"fecha": str(x.fecha), "zona": f"{x.codigo} {x.zona}", "tipo": str(x.tipo), "tmax_c": _num(x.tmax_c, 1),
              "hr_min_pct": _num(x.hr_min_pct, 0), "registros_viento_sur_seco_10min": _int(x.registros_viento_sur_seco_10min),
              "racha_max_sur_ms": _num(x.racha_max_sur_ms, 1), "lluvia_dia_mm": _num(x.lluvia_dia_mm, 1)} for x in sel.head(top).itertuples()]
    # episodio de validación: Bera–Aiako Harria 19-21/02/2021 (todas las estaciones, incluida la de control)
    ep = D.m_dias[(D.m_dias.fecha.astype(str) >= "2021-02-19") & (D.m_dias.fecha.astype(str) <= "2021-02-21")]
    episodio = {"nombre": "Incendio de Bera–Aiako Harria (19–21 de febrero de 2021)",
                "dias_marcados_por_estacion": {f"{c} {g.zona.iloc[0]}": sorted(g.fecha.astype(str).tolist()) for c, g in ep.groupby("codigo")},
                "tipos": sorted(set(ep.tipo.astype(str))),
                "detectado": bool(len(ep) > 0)}
    test = _registros(D.m_test)
    out = {"parametros": {"zona": codigos if (zona or municipio) else "todas las zonas del modelo", "municipio": muni, "mes": mes_v,
                          "anio": anio_v, "tipo": tipo_v, "fecha_desde": fd_, "fecha_hasta": fh_, "top_dias": top},
           "resumen_anual": _meteo_resumen(),
           "zonas": zonas,
           "test_zonas": test,
           "zonas_distinguibles": None,
           "dias_riesgo_encontrados": int(mask.sum()),
           "dias_riesgo": lista,
           "lista_truncada": _truncada(len(lista), int(mask.sum()), "meteo_dias_riesgo.csv"),
           "episodio_validacion": episodio,
           "lectura": LECTURA_METEO,
           "metodo": ("Dos reglas exploratorias (no FWI, no índice oficial): calor seco CS-v1 = ADV-v1 (Tmax >= 25 °C, HRmin <= 40 % y "
                      "sin lluvia >= 1 mm en los 3 días previos) y viento sur seco VS-v1 (>= 18 registros de 10 min con viento del sector "
                      "S 135-225° >= 3 m/s y HR <= 50 %, sin lluvia en los 3 días previos). Día de riesgo = cumple alguna. Medias por mes "
                      "sobre 2018-2023 (días válidos). Prueba de zonas: bootstrap por bloques mensuales y permutación (meteo_test_zonas.csv)."),
           "limites": ["Solo 3 estaciones meteorológicas para 28 municipios, todas de valle; C043 Ordizia es control (fuera de Tolosaldea).",
                       "Reglas con umbrales redondos (decisión del equipo), no calibradas con registros de incendios; no es probabilidad de incendio.",
                       "Días UTC; huecos: C026 Berastegi sin datos de jun. 2021 a jun. 2022 (años incompletos marcados en por_anio).",
                       "Los días de riesgo dicen CUÁNDO activar retenes; no cambian DÓNDE colocarlos (zonas no distinguibles)."]}
    out["zonas_distinguibles"] = out["resumen_anual"].get("zonas_distinguibles")
    return out


# ----------------------------------------------------------------------------- prioridad
def _tabla_municipios(municipio=None) -> list:
    D = datos()
    m = D.munis.copy()
    if municipio:
        m = m[m.municipio == municipio]
    m["pct_alta"] = (100 * pd.to_numeric(m.alta, errors="coerce") / pd.to_numeric(m.edificios_analisis, errors="coerce")).round(1)
    m = m.sort_values(["alta", "municipio"], ascending=[False, True])
    cols = ["municipio", "edificios_analisis", "viviendas_analisis", "alta", "media", "baja", "pct_alta", "viviendas_alta", "sin_ruta",
            "t_base_mediana_min", "t_base_max_min", "fs_mediana", "ha_incendios_previos_2018_2026_aprox", "zona_meteo"]
    return _registros(m, cols)


def _fila_prioridad(i) -> dict:
    D = datos()
    r = D.edif.iloc[i]
    g = lambda c: _limpio(r[c]) if c in D.edif.columns else None
    return {"building_id": D.ids[i], "municipio": D.edif_muni[i], "viviendas": _int(g("viviendas")), "prioridad": g("prioridad"),
            "puntos_total": _int(g("puntos_total")), "motivo_prioridad": g("motivo_prioridad"),
            "t_base_ligero_min": _num(g("t_base_ligero_min")), "sin_ruta": bool(D.sin_ruta[i])}


def referencias() -> dict:
    """FireScope e incendios previos: SOLO referencia (nunca suman a la prioridad)."""
    D = datos()
    e = D.edif
    fs = e.fs_clase.fillna("desconocido").value_counts() if "fs_clase" in e.columns else pd.Series(dtype=int)
    fs_pct = {str(k): _num(100.0 * v / D.n, 1) for k, v in fs.items()}
    cruce = {}
    if "fs_clase" in e.columns:
        ct = pd.crosstab(e.prioridad, e.fs_clase)
        cruce = {str(c): {str(k): int(v) for k, v in ct.loc[c].items()} for c in ct.index}
    out = {"firescope": {"fuente": "FireScope (INSAIT, CVPR 2026, CC BY 4.0) · puntuación 0-100 = ráster/2,55",
                         "leyenda": "< 25 Seguro · 25-50 Bajo · 50-75 Moderado · >= 75 Alto",
                         "clases_conjunto": {str(k): int(v) for k, v in fs.items()}, "clases_pct": fs_pct,
                         "mediana_puntuacion": _num(pd.to_numeric(e.get("fs_puntuacion_0_100"), errors="coerce").median(), 1),
                         "cruce_prioridad_x_firescope": cruce,
                         "lectura": ("Coincide en la tendencia (más alto en el sureste, en el Aralar), pero es demasiado suave para decidir "
                                     "vivienda a vivienda. Solo referencia: no suma puntos a la prioridad.")}}
    inc = D.incendios
    if inc is not None and len(inc):
        ha = inc.groupby("zona").superficie_ha_aprox.sum().round(1)
        tol = inc[inc.zona == "Tolosaldea"]
        be = inc[(inc.muni_alta_mas_cercana == "Berastegi") & (inc.anio >= 2021) & (inc.dist_vivienda_alta_aprox_m <= 1700)]
        out["incendios_previos"] = {
            "fuente": "Capa «Previous Wildfires» de FireScope 2018-2026 (aproximada; fuente original no documentada)",
            "trozos_poligono": int(len(inc)), "ha_por_zona": {str(k): float(v) for k, v in ha.items()},
            "dentro_de_tolosaldea": [{"anio": int(x.anio), "municipio": x.municipio_tolosaldea, "ha_aprox": _num(x.superficie_ha_aprox, 1)}
                                     for x in tol.itertuples()],
            "cerca_de_alta_berastegi_2021_2026": {"n": int(len(be)), "dist_min_m": _num(be.dist_vivienda_alta_aprox_m.min(), 0),
                                                  "dist_max_m": _num(be.dist_vivienda_alta_aprox_m.max(), 0),
                                                  "anios": sorted(set(be.anio.astype(int).tolist())), "zona": sorted(set(be.zona.astype(str)))},
            "lectura": ("Dentro de Tolosaldea solo hay un incendio cartografiado (Amezketa 2019, ~39 ha); casi todo lo quemado está en "
                        "Navarra. Hay incendios de 2021-2026 a 0,45-1,6 km de viviendas Alta de Berastegi. Solo referencia.")}
    out.update({"parametros": {}, "aviso": "Referencias externas: NUNCA se suman a la prioridad ni al optimizador.",
                "metodo": "Lectura directa de edificios_prioridad.csv (fs_*) e incendios_previos.csv.",
                "limites": ["FireScope es un modelo de IA de terceros (experimental), no un dato oficial ni una probabilidad calibrada.",
                            "Polígonos de incendios aproximados; distancias aproximadas."]})
    return out


def reglas_prioridad() -> dict:
    D = datos()
    txt = D.textos.get("REGLAS_prioridad.md", "")
    secciones = {}
    actual = None
    for linea in txt.splitlines():
        if linea.startswith("## "):
            actual = linea[3:].strip()
            secciones[actual] = []
        elif actual:
            secciones[actual].append(linea)
    sec = {k: "\n".join(v).strip() for k, v in secciones.items()}
    met = []
    if D.metodologia is not None:
        met = _registros(D.metodologia[D.metodologia.clave.isin(["prioridad", "peso_optimizador", "distancia_vegetacion_m",
                                                                  "vegetacion_proximidad_clases", "conjunto_analisis"])])
    return {"parametros": {}, "aviso": AVISO_PRIORIDAD, "reglas": sec, "metodologia": met,
            "decisiones_del_equipo": ["umbral de 100 m a la vegetación", "bandas de distancia", "niveles de vegetación",
                                      "cortes de las clases (Alta >= 6, Media 4-5, Baja <= 3)", "umbrales meteorológicos"],
            "metodo": "Texto de REGLAS_prioridad.md y filas de metodologia.csv.", "limites": [AVISO_PRIORIDAD]}


def prioridad(apartado="resumen", clase=None, municipio=None, building_id=None, limite=20) -> dict:
    """Prioridad de planificación (PRIO-v1): resumen por clase, por municipio, lista de viviendas, ficha, reglas, referencias."""
    D = datos()
    a = _norm(apartado or "resumen")
    lim = _limite(limite, "limite", 1)
    cl = v_clase(clase)
    mu = v_municipio(municipio) if municipio else None
    e = D.edif
    base = {"parametros": {"apartado": a, "clase": cl, "municipio": mu, "limite": lim}, "aviso": AVISO_PRIORIDAD}
    if a.startswith("regla"):
        return reglas_prioridad()
    if a.startswith("refer") or a.startswith("firescope") or a.startswith("incend"):
        return referencias()
    if a.startswith("edificio") or a.startswith("ficha") or (building_id and str(building_id).strip()):
        if not building_id:
            raise ErrorConsulta("Indique building_id (ES.GFA.BU.<n> o solo el número) para la ficha de un edificio.")
        bid = v_edificio(building_id)
        i = int(np.where(D.ids == bid)[0][0])
        r = e.iloc[i]
        cols = ["municipio", "viviendas", "uso_original", "dist_veg_m", "banda_distancia", "vegetacion_cercana", "tipo_veg_nivel",
                "t_base_ligero_min", "parque_base_ligero", "t_segundo_parque_ligero_min", "banda_acceso", "sin_ruta", "zona_meteo",
                "puntos_distancia", "puntos_vegetacion", "puntos_acceso", "puntos_meteo", "puntos_total", "prioridad", "peso_prioridad",
                "prioridad_sin_acceso", "peso_optimizador", "motivo_prioridad"]
        ref = ["fs_puntuacion_0_100", "fs_clase", "dist_incendio_previo_aprox_m", "anio_incendio_previo_cercano"]
        base["parametros"]["building_id"] = bid
        base.update({"edificio": {c: _limpio(r[c]) for c in cols if c in e.columns},
                     "referencias_no_suman": {c: _limpio(r[c]) for c in ref if c in e.columns},
                     "nota": "Para tiempos desde cada parque/candidata y cobertura con retenes use consultar_edificios(building_id=...).",
                     "metodo": "Fila de edificios_prioridad.csv (puntos según REGLAS_prioridad.md).",
                     "limites": [AVISO_PRIORIDAD, "El tipo de vegetación no es un modelo de combustible.",
                                 "FireScope e incendio previo: solo referencia."]})
        return base
    if a.startswith("munic"):
        base.update({"municipios": _tabla_municipios(mu),
                     "metodo": "municipios.csv (recuentos por municipio del conjunto de análisis); pct_alta = alta / edificios_analisis.",
                     "limites": [AVISO_PRIORIDAD]})
        return base
    if a.startswith("lista") or a.startswith("top") or a.startswith("vivienda"):
        mask = np.ones(D.n, bool)
        if cl:
            mask &= D.clase == cl
        if mu:
            mask &= D.edif_muni == mu
        idx = np.where(mask)[0]
        pts = pd.to_numeric(e.puntos_total, errors="coerce").to_numpy(float)
        tb = pd.to_numeric(e.t_base_ligero_min, errors="coerce").to_numpy(float)
        tb = np.where(np.isnan(tb), np.inf, tb)
        orden = idx[np.lexsort((D.ids[idx], -tb[idx], -pts[idx]))]
        base.update({"n_encontrados": int(len(idx)), "viviendas_encontradas": _int(np.nansum(D.viv[idx])),
                     "sin_ruta_encontrados": int(D.sin_ruta[idx].sum()),
                     "lista": [_fila_prioridad(i) for i in orden[:lim]],
                     "lista_truncada": _truncada(min(lim, len(orden)), len(orden), MARCADOR),
                     "orden": "puntos_total descendente, después tiempo actual desde el parque más cercano descendente (sin ruta primero)",
                     "metodo": "Filtro de edificios_prioridad.csv por clase y municipio.",
                     "limites": [AVISO_PRIORIDAD, "Viviendas según B5M; uso desconocido en muchos edificios (252 caseríos fuera del conjunto)."]})
        return base
    if a != "resumen":
        raise ErrorConsulta("apartado debe ser 'resumen', 'municipios', 'lista', 'edificio', 'reglas' o 'referencias'.")
    por_clase = {}
    for c in CLASES:
        m = D.clase == c
        por_clase[c] = {"edificios": int(m.sum()), "viviendas": _int(np.nansum(D.viv[m])), "pct_edificios": _num(100.0 * m.sum() / D.n, 1),
                        "sin_ruta": int((m & D.sin_ruta).sum())}
    psa = e.prioridad_sin_acceso.value_counts().to_dict() if "prioridad_sin_acceso" in e.columns else {}
    tm = _tabla_municipios()
    ev0 = _evaluar([], UMBRAL_DEF, "ligero", PESOS_DEF)
    opt3 = _optimizar_cache(3, "A", UMBRAL_DEF, "ligero", PESOS_DEF)["per_k"][3]
    base.update({
        "edificios_analisis": D.n, "viviendas_analisis": _int(np.nansum(D.viv)),
        "por_clase": por_clase,
        "prioridad_sin_acceso_para_optimizador": {str(k): int(v) for k, v in psa.items()},
        "alta_por_municipio_top5": [{"municipio": r["municipio"], "alta": r["alta"], "pct_alta": r["pct_alta"]} for r in tm[:5]],
        "bandas_acceso": {str(k): int(v) for k, v in e.banda_acceso.value_counts().items()} if "banda_acceso" in e.columns else {},
        "puntos_total": {str(int(k)): int(v) for k, v in pd.to_numeric(e.puntos_total, errors="coerce").value_counts().sort_index().items()},
        "alta_y_cobertura_12min_ligero": {"k0_alta_dentro": int((ev0["cubierto"] & D.alta).sum()),
                                          "mejor_A_k3_seleccion": opt3["seleccion"], "mejor_A_k3_alta_dentro": opt3["n_alta"],
                                          "alta_sin_ruta": int((D.alta & D.sin_ruta).sum()),
                                          "nota": "Calculado en vivo (pesos 'prioridad'). Las Alta sin ruta no mejoran con ningún retén: necesitan otra medida (acceso, autoprotección)."},
        "componentes": "distancia a vegetación (1-3) + tipo de vegetación (0-2) + acceso actual (0-3) + meteorología (0 para todos) → Alta >= 6 · Media 4-5 · Baja <= 3",
        "metodo": "Recuentos en vivo desde edificios_prioridad.csv; reglas en REGLAS_prioridad.md.",
        "limites": [AVISO_PRIORIDAD, "252 edificios con nombre de caserío y uso desconocido a <= 100 m quedan fuera; si fueran viviendas, 70 serían Alta.",
                    "Tiempos estimados (componente de acceso); el tipo de vegetación no es un modelo de combustible."]})
    return base


# ----------------------------------------------------------------------------- contexto
def contexto(anio_plan: int = 2027) -> dict:
    """Marco de cualquier respuesta: pregunta, ámbito, prioridad, orígenes, parámetros y 'cuándo' (meteo)."""
    D = datos()
    try:
        anio = int(anio_plan)
    except (TypeError, ValueError):
        raise ErrorConsulta(f"anio_plan debe ser un año (recibido {anio_plan!r}).")
    if not (2024 <= anio <= 2040):
        raise ErrorConsulta("anio_plan debe estar entre 2024 y 2040 (es solo una etiqueta del plan).")
    pq = D.parques[D.parques.en_base.astype(int) == 1]
    mr = _meteo_resumen()
    out = {
        "parametros": {"anio_plan": anio},
        "pregunta": (f"Plan {anio}: ¿dónde colocar hasta N retenes preventivos adicionales para las viviendas del borde forestal de "
                     "Tolosaldea y en qué días de riesgo activarlos?"),
        "titulo_plan": f"Plan preventivo flAIre · Tolosaldea {anio}",
        "efecto_anio_plan": f"Solo etiqueta: cambiar {anio} por otro año no cambia ninguna cifra.",
        "ambito": {"zona": "Tolosaldea (28 municipios)", "n_municipios": int(D.munis.municipio.nunique()), "edificios_analisis": D.n,
                   "viviendas_analisis": _int(np.nansum(D.viv)), "edificios_sin_ruta": int(D.sin_ruta.sum()),
                   "regla": "edificio residencial (B5M) a <= 100 m de bosque o matorral (Mapa Forestal del País Vasco 2024)"},
        "prioridad": {"Alta": int(D.alta.sum()), "Media": int((D.clase == "Media").sum()), "Baja": int((D.clase == "Baja").sum()),
                      "alta_sin_ruta": int((D.alta & D.sin_ruta).sum()), "aviso": AVISO_PRIORIDAD},
        "donde": {"parques_en_base": [f"{r.origen_id} ({r.municipio})" for r in pq.itertuples()],
                  "candidatas": [f"{r.origen_id} {etiqueta_candidata(r.nombre, r.municipio)}" for r in D.cands.itertuples()],
                  "nota": "Candidatas = lugares de ESTUDIO, no autorizados."},
        "cuando": {"dias_riesgo_por_anio": mr.get("dias_riesgo_por_anio"), "reparto_pct": mr.get("reparto_pct"),
                   "zonas_distinguibles": mr.get("zonas_distinguibles"), "lectura": LECTURA_METEO},
        "parametros_defecto": {"umbral_min": UMBRAL_DEF, "perfil": "ligero", "pesos": PESOS_DEF, "estrategia": "A",
                               "k_max": min(K_MAX_ABS, len(D.cand_ids)),
                               "umbrales_en_escenarios_csv": sorted(D.esc.umbral_min.astype(float).unique().tolist()) if D.esc is not None else []},
        "version_datos": VERSION,
        "otros_apartados": "fuentes · metodologia · limitaciones · diccionario · referencias · reglas",
        "metodo": METODO_COBERTURA,
        "limites": LIMITES_BASE + [LIMITE_PESOS[PESOS_DEF]],
    }
    return out


def fuentes() -> dict:
    """Registro de fuentes (fuentes.csv, con responsable)."""
    D = datos()
    cols = ["source_id", "conjunto", "organismo", "url", "licencia", "fecha_descarga", "edicion_periodo", "estado", "responsable"]
    rows = _registros(D.fuentes.fillna(""), cols) if D.fuentes is not None else []
    por_resp = {}
    for r in rows:
        por_resp[r.get("responsable") or "—"] = por_resp.get(r.get("responsable") or "—", 0) + 1
    return {"parametros": {}, "fuentes": rows, "n_fuentes": len(rows), "por_responsable": por_resp,
            "metodo": "Lectura directa de fuentes.csv.", "limites": ["Licencias según cada fuente (columna licencia)."]}


def metodologia(clave=None) -> dict:
    D = datos()
    if D.metodologia is None:
        raise ErrorConsulta("No hay metodologia.csv en los datos.")
    m = D.metodologia
    if clave:
        nm = _norm(clave)
        m = m[m.clave.map(_norm).str.contains(nm, regex=False) | m.valor.fillna("").map(_norm).str.contains(nm, regex=False)]
        if m.empty:
            raise ErrorConsulta(f"Ninguna clave de metodologia.csv coincide con {clave!r}. Claves: {', '.join(D.metodologia.clave)}.")
    return {"parametros": {"clave": clave}, "metodologia": _registros(m), "n": int(len(m)),
            "metodo": "Lectura directa de metodologia.csv (clave / valor / explicación).", "limites": []}


def diccionario() -> dict:
    D = datos()
    return {"parametros": {}, "diccionario": D.textos.get("DICCIONARIO_datos.md", "(no disponible)"),
            "carpeta_datos": f"agentes/{CARPETA_DATOS}/", "metodo": "Texto de DICCIONARIO_datos.md.",
            "limites": ["Vacío = desconocido (nunca 0)."]}


def limitaciones() -> dict:
    """Límites honestos con recuentos en vivo desde los datos."""
    D = datos()
    ncomp = 0
    if "comprobaciones_pendientes" in D.cands.columns:
        ncomp = int(D.cands.comprobaciones_pendientes.fillna("").map(lambda s: 1 if str(s).strip() else 0).sum())
    mr = _meteo_resumen()
    lim = [
        {"id": "L1", "texto": "Tiempos = estimaciones de desplazamiento con velocidades supuestas (≈85 % de tramos sin maxspeed en OSM), sin tráfico, giros ni tiempo de salida. No son tiempos de respuesta."},
        {"id": "L2", "texto": "Edificios sin ruta (a > 150 m de la red viaria) se informan y cuentan como no cubiertos; nunca se eliminan. Ningún retén los mejora.",
         "n": int(D.sin_ruta.sum()), "alta": int((D.alta & D.sin_ruta).sum())},
        {"id": "L3", "texto": "La prioridad es de PLANIFICACIÓN (PRIO-v1), no probabilidad de incendio ni riesgo real. Umbral de 100 m, bandas, niveles de vegetación y cortes de clase son decisiones del equipo."},
        {"id": "L4", "texto": "Meteorología: dos reglas exploratorias (calor seco, viento sur seco), no FWI; 3 estaciones de valle; las zonas no se distinguen, así que la meteo dice cuándo, no dónde.",
         "zonas_distinguibles": mr.get("zonas_distinguibles"), "dias_riesgo_por_anio": mr.get("dias_riesgo_por_anio")},
        {"id": "L5", "texto": "Cobertura ponderada ≠ población protegida; viviendas según B5M.", "viviendas_nulas": int(np.isnan(D.viv).sum())},
        {"id": "L6", "texto": "Candidatas = lugares de estudio desde OSM: no autorizadas; comprobaciones de campo pendientes (espacio, titularidad, acceso de camión, agua, tráfico, ortofoto).",
         "candidatas_con_comprobaciones": ncomp, "candidatas": len(D.cand_ids)},
        {"id": "L7", "texto": "Parques: posición oficial B5M no verificada en ortofoto. Parques de Navarra no incluidos como orígenes.", "parques_en_base": len(D.parques_base)},
        {"id": "L8", "texto": "12 min es un umbral de demostración, no un estándar oficial."},
        {"id": "L9", "texto": "Uso B5M desconocido en muchos edificios: 252 caseríos con uso desconocido a ≤100 m quedan fuera (70 serían Alta)."},
        {"id": "L10", "texto": "El tipo de vegetación no es un modelo de combustible."},
        {"id": "L11", "texto": "El mínimo de retenes del modelo no es una dotación operativa (personal, vehículos, turnos): eso no está en los datos."},
        {"id": "L12", "texto": "FireScope e incendios previos son solo referencia (no suman a la prioridad); pesos 'meteo' y 'firescope' solo para sensibilidad."},
        {"id": "L13", "texto": "escenarios.csv no incluye la ponderación 'prioridad': esas cifras se calculan en vivo y se recomprueban con comprobar_cifra."},
        {"id": "L14", "texto": "Fuera de ámbito: municipios y parques de Navarra; la red sí incluye carreteras navarras."},
    ]
    return {"parametros": {}, "limitaciones": lim, "metodo": "Recuentos calculados en vivo desde los datos.", "limites": []}


# ----------------------------------------------------------------------------- cobertura y optimizador
def _por_municipio(ev: dict) -> list:
    D = datos()
    df = pd.DataFrame({"municipio": D.edif_muni, "cub": ev["cubierto"], "ruta": ev["routable"], "alta": D.alta,
                       "alta_cub": ev["cubierto"] & D.alta, "t": np.where(ev["routable"], ev["best"], np.nan)})
    df["sinr"] = ~df.ruta
    g = df.groupby("municipio").agg(n=("cub", "size"), dentro=("cub", "sum"), sin_ruta=("sinr", "sum"), alta=("alta", "sum"),
                                    alta_dentro=("alta_cub", "sum"), peor=("t", "max"), mediana=("t", "median")).reset_index()
    g["pct_dentro"] = (100 * g.dentro / g.n).round(1)
    g = g.sort_values(["pct_dentro", "municipio"])
    return [{"municipio": r.municipio, "edificios": int(r.n), "dentro": int(r.dentro), "pct_dentro": float(r.pct_dentro),
             "alta": int(r.alta), "alta_dentro": int(r.alta_dentro), "sin_ruta": int(r.sin_ruta), "peor_min": _num(r.peor),
             "mediana_min": _num(r.mediana)} for r in g.itertuples()]


def cobertura(seleccion=None, umbral=UMBRAL_DEF, perfil="ligero", pesos=PESOS_DEF, municipio=None, k=None, estrategia="A") -> dict:
    """Cobertura en vivo de los 9 parques + las candidatas de `seleccion` (vacío = k=0).
    Si no se da selección y sí `k`, usa la mejor combinación de `estrategia` para ese k."""
    u, p, w, e = v_umbral(umbral), v_perfil(perfil), v_pesos(pesos), v_estrategia(estrategia)
    sel, origen_sel = _resolver_seleccion(seleccion, k, e, u, p, w)
    D = datos()
    ev = _evaluar(sel, u, p, w)
    ev0 = _evaluar([], u, p, w)
    a0, a1 = _alta(ev0), _alta(ev)
    out = {"parametros": {"seleccion": sel, "origen_seleccion": origen_sel, "umbral_min": u, "perfil": p, "pesos": w,
                          "parques_en_base": D.parques_base},
           "resultado": _metricas(ev),
           "mejora_vs_k0": {"edificios": ev["n_cubiertos"] - ev0["n_cubiertos"], "alta": a1["alta_dentro"] - a0["alta_dentro"],
                            "alta_k0": a0["alta_dentro"], "puntos_pct": _num(ev["pct"] - ev0["pct"]),
                            "puntos_pct_ponderada": _num((ev["pct_pond"] or 0) - (ev0["pct_pond"] or 0)),
                            "peor_tiempo_k0": _num(ev0["peor"])},
           "sin_ruta": {"n": ev["n_sin_ruta"], "alta": a1["alta_sin_ruta"],
                        "nota": "Edificios a > 150 m de la red viaria; se informan, no se eliminan; ningún retén los arregla."}}
    orig = pd.Series([o for o in ev["origen"] if o is not None]).value_counts()
    out["edificios_por_origen_mas_rapido"] = {str(kk): int(v) for kk, v in orig.items()}
    pm = _por_municipio(ev)
    if municipio:
        mu = v_municipio(municipio)
        out["parametros"]["municipio"] = mu
        out["municipio"] = [r for r in pm if r["municipio"] == mu]
    else:
        out["por_municipio"] = pm
    chk = []
    for est in ESTRATEGIAS:
        g = _escenario_guardado(est, len(sel), u, p, w)
        if g is not None and str(g["seleccion"]) == ";".join(sel):
            chk.append({"escenario": f"{est}-k{len(sel)}-{u:g}min-{p}-{w}",
                        "guardado_edificios": _int(g["edificios_cubiertos"]), "calculado_edificios": ev["n_cubiertos"],
                        "guardado_peor": _num(g["peor_tiempo"]), "calculado_peor": _num(ev["peor"]),
                        "coincide": _int(g["edificios_cubiertos"]) == ev["n_cubiertos"] and abs(float(g["peor_tiempo"]) - (ev["peor"] or 0)) < 0.011})
    out["comprobacion_escenarios_csv"] = chk
    nota = _nota_escenarios(e, u, p, w)
    if nota:
        out["nota_escenarios"] = nota
    out["metodo"] = METODO_TIEMPOS + " " + METODO_COBERTURA
    out["limites"] = LIMITES_BASE + [LIMITE_PONDERADA] + _limites_pesos(w)
    return out


def _minimo(objetivo_pct, metrica, umbral, perfil, pesos):
    """Menor k (0..6) tal que ALGUNA combinación de k candidatas alcanza objetivo_pct en la métrica elegida.
    Para cada k busca en todas las combinaciones (848 en total) la que maximiza esa métrica
    (desempate: ponderada, edificios, menor peor tiempo, orden alfabético)."""
    try:
        obj = float(objetivo_pct)
    except (TypeError, ValueError):
        raise ErrorConsulta(f"objetivo_pct debe ser un porcentaje entre 0 y 100 (recibido {objetivo_pct!r}).")
    if math.isnan(obj) or not (0 < obj <= 100):
        raise ErrorConsulta(f"objetivo_pct debe estar entre 0 y 100 (recibido {objetivo_pct}).")
    met = _norm(metrica or "edificios")
    alias = {"edificios": "edificios", "pct dentro": "edificios", "ponderada": "ponderada", "cobertura ponderada": "ponderada",
             "pct ponderada": "ponderada", "alta": "alta", "prioridad alta": "alta", "viviendas alta": "alta", "pct alta": "alta"}
    if met not in alias:
        raise ErrorConsulta("metrica debe ser 'edificios' (% de edificios dentro), 'ponderada' (% de cobertura ponderada) o 'alta' (% de edificios Alta dentro).")
    met = alias[met]
    D = datos()
    kmax = min(K_MAX_ABS, len(D.cand_ids))
    X = _matriz(kmax, umbral, perfil, pesos)
    n_alta = int(D.alta.sum())
    if met == "edificios":
        val = 100.0 * X["n_cov"] / D.n
    elif met == "alta":
        val = 100.0 * X["n_alta"] / n_alta if n_alta else np.zeros(len(X["combos"]))
    else:
        val = 100.0 * X["wc"] / X["wt"] if X["wt"] else np.zeros(len(X["combos"]))
    pos = np.arange(len(X["combos"]))
    curva = []
    for k in range(kmax + 1):
        idx = np.where(X["ks"] == k)[0]
        orden = idx[np.lexsort((pos[idx], np.round(X["worst"][idx], 9), -X["n_cov"][idx], -np.round(X["wc"][idx], 9), -np.round(val[idx], 9)))]
        t = orden[0]
        n_max = int(np.sum(np.round(val[idx], 9) == np.round(val[t], 9)))
        curva.append({"k": k, "seleccion": list(X["combos"][t]), "valor_pct": _num(val[t]), "edificios_dentro": int(X["n_cov"][t]),
                      "alta_dentro": int(X["n_alta"][t]), "pct_ponderada": _num(100 * X["wc"][t] / X["wt"] if X["wt"] else None),
                      "combinaciones_con_ese_maximo": n_max})
    alc = next((c for c in curva if c["valor_pct"] is not None and c["valor_pct"] + 1e-9 >= obj), None)
    mejor = max(curva, key=lambda c: (c["valor_pct"] or 0, -c["k"]))
    out = {"objetivo_pct": obj, "metrica": met, "alcanzado": alc is not None, "k_minimo": None if alc is None else alc["k"],
           "seleccion": None if alc is None else alc["seleccion"], "valor_pct": None if alc is None else alc["valor_pct"],
           "maximo_alcanzable_pct": mejor["valor_pct"], "seleccion_maximo": mejor["seleccion"],
           "curva_mejor_por_k": curva,
           "metodo": (f"Para cada k = 0..{kmax} se evalúan TODAS las combinaciones de k candidatas ({len(X['combos'])} en total) y se toma la "
                      f"que maximiza la métrica '{met}' (desempate: ponderada, edificios, peor tiempo, orden alfabético). Es independiente de "
                      "la estrategia A/B: la selección puede diferir de la de por_k."),
           "aviso": ("Mínimo DENTRO DEL MODELO (tiempos estimados, umbral de demostración, 10 candidatas de estudio, k<=6). No es una "
                     "dotación operativa: no dice cuántos bomberos, vehículos o turnos hacen falta.")}
    if alc is None:
        out["nota"] = (f"Con hasta {kmax} retenes ninguna combinación llega al {obj:g} % ({met}): máximo {mejor['valor_pct']} % con "
                       f"{';'.join(mejor['seleccion']) or 'solo parques'}. Los sin ruta nunca cuentan como dentro.")
    return out


def optimizar(k_max=6, estrategia="A", umbral=UMBRAL_DEF, perfil="ligero", pesos=PESOS_DEF, objetivo_pct=None, metrica="edificios") -> dict:
    """Mejor combinación de candidatas para cada k = 0..k_max (enumeración exhaustiva en vivo). Con objetivo_pct,
    añade el menor k que lo alcanza buscando en TODAS las combinaciones la que maximiza la métrica elegida."""
    e, u, p, w = v_estrategia(estrategia), v_umbral(umbral), v_perfil(perfil), v_pesos(pesos)
    kk = v_k(k_max, "k_max")
    if objetivo_pct is not None:
        kk = min(K_MAX_ABS, len(datos().cand_ids))
    t0 = datetime.now()
    res = _optimizar_cache(kk, e, u, p, w)
    dt = (datetime.now() - t0).total_seconds()
    D = datos()
    n = D.n
    n_alta = int(D.alta.sum())
    wt = res["wt"]
    pk = res["per_k"]
    cm = D.cands.set_index("origen_id")
    filas = []
    monot = True
    for i, m in enumerate(pk):
        f = {"k": m["k"], "seleccion": m["seleccion"],
             "municipios_seleccion": [cm.municipio.get(c) for c in m["seleccion"]],
             "edificios_dentro": m["n_cub"], "pct_dentro": _num(100 * m["n_cub"] / n),
             "alta_dentro": m["n_alta"], "pct_alta_dentro": _num(100 * m["n_alta"] / n_alta) if n_alta else None,
             "cobertura_ponderada": _num(m["pond"], 3), "pct_ponderada": _num(100 * m["pond"] / wt if wt else None),
             "peor_tiempo_min": _num(m["peor"]), "p95_tiempo_min": _num(_evaluar(m["seleccion"], u, p, w)["p95"]), "sin_ruta": m["n_unr"],
             "mejora_vs_k0_edificios": m["n_cub"] - pk[0]["n_cub"], "mejora_vs_k0_alta": m["n_alta"] - pk[0]["n_alta"],
             "mejora_vs_k_anterior_edificios": None if i == 0 else m["n_cub"] - pk[i - 1]["n_cub"],
             "reutiliza_k_anterior": None if i == 0 else set(pk[i - 1]["seleccion"]) <= set(m["seleccion"]),
             "empates": m["empates"]}
        if m["empates"] > 1:
            f["combinaciones_empatadas"] = m["empatadas"]
        f["siguientes_mejores"] = m["rank2"]
        if i > 0 and _clave(m, e) > _clave(pk[i - 1], e):
            monot = False
        g = _escenario_guardado(e, m["k"], u, p, w)
        if g is not None:
            f["coincide_escenarios_csv"] = (str(g["seleccion"]) == ";".join(m["seleccion"]) and _int(g["edificios_cubiertos"]) == m["n_cub"])
        filas.append(f)
    out = {"parametros": {"k_max": kk, "estrategia": e, "umbral_min": u, "perfil": p, "pesos": w},
           "objetivo": ("A: máxima cobertura ponderada (pesos 'prioridad' = más peso a Alta y Media, sin contar el acceso dos veces)" if e == "A" else
                        "B: primero menos edificios sin ruta, después menor peor tiempo, después cobertura ponderada"),
           "combinaciones_evaluadas": res["n_combos"], "segundos": round(dt, 3),
           "alta_total": n_alta,
           "por_k": filas,
           "objetivo_monotono": monot,
           "edificios_monotono": all(filas[i]["edificios_dentro"] >= filas[i - 1]["edificios_dentro"] for i in range(1, len(filas))),
           "sin_ruta": {"n": pk[0]["n_unr"], "alta": int((D.alta & D.sin_ruta).sum()),
                        "nota": "constante en todos los k: ningún retén arregla un edificio sin enganche a la red"},
           "nota_anidamiento": "La mejor combinación de k no tiene por qué contener la de k-1 (ver reutiliza_k_anterior).",
           "metodo": METODO_OPT, "limites": LIMITES_BASE + _limites_pesos(w)}
    nota = _nota_escenarios(e, u, p, w)
    if nota:
        out["nota_escenarios"] = nota
    if objetivo_pct is not None:
        out["minimo"] = _minimo(objetivo_pct, metrica, u, p, w)
    return out


def minimo_k(objetivo_pct, estrategia="A", metrica="edificios", umbral=UMBRAL_DEF, perfil="ligero", pesos=PESOS_DEF) -> dict:
    """Menor k que alcanza objetivo_pct en la métrica elegida (todas las combinaciones; la estrategia no influye)."""
    v_estrategia(estrategia)
    return _minimo(objetivo_pct, metrica, v_umbral(umbral), v_perfil(perfil), v_pesos(pesos))


def comparar(seleccion_a=None, seleccion_b=None, umbral=UMBRAL_DEF, perfil="ligero", pesos=PESOS_DEF, k=None,
             estrategia_a="A", estrategia_b="B") -> dict:
    """Compara dos selecciones (o, sin selecciones y con k, la mejor de estrategia_a frente a la de estrategia_b)."""
    u, p, w = v_umbral(umbral), v_perfil(perfil), v_pesos(pesos)
    ea, eb = v_estrategia(estrategia_a), v_estrategia(estrategia_b)
    if seleccion_a is None and seleccion_b is None:
        if k is None:
            raise ErrorConsulta("Indique seleccion_a y seleccion_b, o k para comparar la mejor de cada estrategia.")
        kk = v_k(k)
        sa = _optimizar_cache(kk, ea, u, p, w)["per_k"][kk]["seleccion"]
        sb = _optimizar_cache(kk, eb, u, p, w)["per_k"][kk]["seleccion"]
        etiqueta = (f"mejor {ea} k={kk}", f"mejor {eb} k={kk}")
    else:
        sa, sb = v_seleccion(seleccion_a), v_seleccion(seleccion_b)
        etiqueta = ("A", "B")
    D = datos()
    a, b = _evaluar(list(sa), u, p, w), _evaluar(list(sb), u, p, w)
    solo_a = a["cubierto"] & ~b["cubierto"]
    solo_b = b["cubierto"] & ~a["cubierto"]
    dfm = pd.DataFrame({"municipio": D.edif_muni, "solo_a": solo_a, "solo_b": solo_b})
    gm = dfm.groupby("municipio")[["solo_a", "solo_b"]].sum()
    gm = gm[(gm.solo_a > 0) | (gm.solo_b > 0)].sort_values(["solo_a", "solo_b"], ascending=False)
    cm = D.cands.set_index("origen_id")

    def sitios(sel, ev):
        return [{"id": c, "nombre": cm.nombre.get(c), "municipio": cm.municipio.get(c),
                 "edificios_servidos_primero": int((ev["origen"] == c).sum()),
                 "edificios_dentro_por_este": int(((ev["origen"] == c) & ev["cubierto"]).sum()),
                 "alta_dentro_por_este": int(((ev["origen"] == c) & ev["cubierto"] & D.alta).sum())} for c in sel]

    def peor(ev):
        j = ev["j_peor"]
        return None if j is None else {"building_id": D.ids[j], "municipio": D.edif_muni[j], "min": _num(ev["peor"]), "origen": ev["origen"][j]}

    ma, mb = _metricas(a), _metricas(b)
    out = {"parametros": {"seleccion_a": list(sa), "seleccion_b": list(sb), "etiquetas": etiqueta, "umbral_min": u, "perfil": p, "pesos": w},
           "metricas_a": ma, "metricas_b": mb,
           "sitios_solo_en_a": sitios([c for c in sa if c not in sb], a), "sitios_solo_en_b": sitios([c for c in sb if c not in sa], b),
           "sitios_comunes": [c for c in sa if c in sb],
           "edificios_dentro_solo_con_a": int(solo_a.sum()), "edificios_dentro_solo_con_b": int(solo_b.sum()),
           "alta_dentro_solo_con_a": int((solo_a & D.alta).sum()), "alta_dentro_solo_con_b": int((solo_b & D.alta).sum()),
           "por_municipio": [{"municipio": m, "solo_a": int(r.solo_a), "solo_b": int(r.solo_b)} for m, r in gm.iterrows()],
           "peor_edificio_a": peor(a), "peor_edificio_b": peor(b),
           "hechos_para_explicar": [
               "A maximiza la cobertura ponderada dentro del umbral (pesos 'prioridad': las Alta pesan 3 veces una Baja): elige sitios cerca de muchos edificios justo por encima del umbral.",
               "B no mira primero cuántos edificios entran: minimiza los sin ruta (constante) y después el PEOR tiempo; por eso gasta retenes en los edificios más alejados aunque sean pocos.",
               f"Peor tiempo: {etiqueta[0]} {_num(a['peor'])} min vs {etiqueta[1]} {_num(b['peor'])} min; edificios dentro: {a['n_cubiertos']} vs {b['n_cubiertos']}; Alta dentro: {ma['alta_dentro']} vs {mb['alta_dentro']}."],
           "sin_ruta": {"a": a["n_sin_ruta"], "b": b["n_sin_ruta"]},
           "metodo": METODO_COBERTURA, "limites": LIMITES_BASE + _limites_pesos(w)}
    return out


def edificio(building_id, seleccion=None, umbral=UMBRAL_DEF, perfil="ligero", k=None, estrategia="A", pesos=PESOS_DEF) -> dict:
    """Ficha trazable de un edificio: prioridad, tiempos desde cada origen, antes (solo parques) y después (con la selección)."""
    bid = v_edificio(building_id)
    u, p, e, w = v_umbral(umbral), v_perfil(perfil), v_estrategia(estrategia), v_pesos(pesos)
    sel, origen_sel = _resolver_seleccion(seleccion, k, e, u, p, w)
    D = datos()
    j = int(np.where(D.ids == bid)[0][0])
    r = D.edif.iloc[j]
    T = D.tiempos[p][j]
    origenes = D.parques_base + D.cand_ids
    tiempos = sorted([{"origen": o, "tipo": "parque" if i < D.n_parq else "candidata", "min": _num(T[i]),
                       "activo": (i < D.n_parq) or (o in sel)} for i, o in enumerate(origenes)],
                     key=lambda x: (x["min"] is None, x["min"] if x["min"] is not None else 0))
    ev0, ev = _evaluar([], u, p, w), _evaluar(sel, u, p, w)
    ficha = {k2: _limpio(v) for k2, v in r.to_dict().items()}
    refs = {c: ficha.pop(c) for c in ("fs_puntuacion_0_100", "fs_clase", "dist_incendio_previo_aprox_m", "anio_incendio_previo_cercano",
                                      "peso_meteo_sensibilidad", "peso_firescope_sensibilidad") if c in ficha}
    out = {"parametros": {"building_id": bid, "seleccion": sel, "origen_seleccion": origen_sel, "umbral_min": u, "perfil": p},
           "edificio": ficha,
           "referencias_no_suman": refs,
           "tiempos_por_origen": tiempos,
           "antes_k0": {"mejor_origen": ev0["origen"][j], "min": _num(ev0["best"][j]), "dentro_umbral": bool(ev0["cubierto"][j])},
           "despues": {"mejor_origen": ev["origen"][j], "min": _num(ev["best"][j]), "dentro_umbral": bool(ev["cubierto"][j])},
           "sin_ruta": not bool(ev0["routable"][j]),
           "aviso": AVISO_PRIORIDAD,
           "metodo": METODO_TIEMPOS, "limites": LIMITES_BASE}
    return out


def edificios_ganados(k, estrategia="A", umbral=UMBRAL_DEF, perfil="ligero", pesos=PESOS_DEF, municipio=None, limite=20, clase=None) -> dict:
    """Qué edificios entran en el umbral con el k-ésimo retén (mejor k frente a mejor k-1), cuáles se pierden si las
    combinaciones no están anidadas y cuáles siguen fuera, por municipio."""
    kk = v_k(k, "k", minimo=1)
    e, u, p, w = v_estrategia(estrategia), v_umbral(umbral), v_perfil(perfil), v_pesos(pesos)
    lim = _limite(limite)
    cl = v_clase(clase)
    res = _optimizar_cache(kk, e, u, p, w)
    s0, s1 = res["per_k"][kk - 1]["seleccion"], res["per_k"][kk]["seleccion"]
    a, b = _evaluar(list(s0), u, p, w), _evaluar(list(s1), u, p, w)
    D = datos()
    gan = b["cubierto"] & ~a["cubierto"]
    per = a["cubierto"] & ~b["cubierto"]
    fuera = b["routable"] & ~b["cubierto"]
    sinr = ~b["routable"]
    mask = np.ones(D.n, bool)
    mu = None
    if municipio:
        mu = v_municipio(municipio)
        mask &= D.edif_muni == mu
    if cl:
        mask &= D.clase == cl
    df = pd.DataFrame({"municipio": D.edif_muni, "gan": gan, "per": per, "fuera": fuera, "sinr": sinr, "gan_alta": gan & D.alta})[mask]
    g = df.groupby("municipio")[["gan", "gan_alta", "per", "fuera", "sinr"]].sum()
    g = g[(g.sum(axis=1)) > 0].sort_values(["gan", "fuera"], ascending=False)
    w_arr = D.peso[w]

    def muestra(m, orden_por):
        idx = np.where(m & mask)[0]
        if not len(idx):
            return []
        idx = idx[np.argsort(-orden_por[idx], kind="stable")][:lim]
        return [{"building_id": D.ids[i], "municipio": D.edif_muni[i], "prioridad": D.clase[i], "antes_min": _num(a["best"][i]),
                 "despues_min": _num(b["best"][i]), "origen_despues": b["origen"][i]} for i in idx]

    anadida = [c for c in s1 if c not in s0]
    quitada = [c for c in s0 if c not in s1]
    out = {"parametros": {"modo": "ganados", "k": kk, "estrategia": e, "umbral_min": u, "perfil": p, "pesos": w, "municipio": mu,
                          "prioridad": cl, "limite": lim},
           "seleccion_k_anterior": list(s0), "seleccion_k": list(s1),
           "anidada": set(s0) <= set(s1), "candidatas_anadidas": anadida, "candidatas_quitadas": quitada,
           "n_ganados": int((gan & mask).sum()), "n_ganados_alta": int((gan & mask & D.alta).sum()), "n_perdidos": int((per & mask).sum()),
           "n_siguen_fuera_con_ruta": int((fuera & mask).sum()), "n_sin_ruta": int((sinr & mask).sum()),
           "ganados_ponderado": _num(float(np.nansum(np.where(gan & mask, w_arr, 0.0))), 3),
           "por_municipio": [{"municipio": m, "ganados": int(r.gan), "ganados_alta": int(r.gan_alta), "perdidos": int(r.per),
                              "siguen_fuera": int(r.fuera), "sin_ruta": int(r.sinr)} for m, r in g.iterrows()],
           "muestra_ganados": muestra(gan, np.where(np.isfinite(a["best"]) & np.isfinite(b["best"]),
                                                    np.nan_to_num(a["best"], posinf=0) - np.nan_to_num(b["best"], posinf=0), 0)),
           "muestra_siguen_fuera": muestra(fuera, np.where(np.isfinite(b["best"]), b["best"], 0)),
           "muestras_truncadas": _truncada(lim, max(int((gan & mask).sum()), int((fuera & mask).sum())), f"tiempos_{p}.csv"),
           "metodo": "Diferencia entre la cobertura de la mejor combinación con k retenes y la mejor con k-1 (mismos parámetros). " + METODO_COBERTURA,
           "limites": LIMITES_BASE}
    if not out["anidada"]:
        out["nota"] = f"La mejor combinación con {kk} no contiene la de {kk - 1}: cambia {quitada} por {anadida}; por eso puede haber edificios perdidos."
    return out


def fuera_umbral(seleccion=None, umbral=UMBRAL_DEF, perfil="ligero", municipio=None, limite=30, k=None, estrategia="A",
                 pesos=PESOS_DEF, clase=None) -> dict:
    """Edificios que siguen por encima del umbral con la selección dada (y los sin ruta, aparte), filtrables por prioridad."""
    u, p, e, w = v_umbral(umbral), v_perfil(perfil), v_estrategia(estrategia), v_pesos(pesos)
    sel, origen_sel = _resolver_seleccion(seleccion, k, e, u, p, w)
    lim = _limite(limite)
    cl = v_clase(clase)
    D = datos()
    ev = _evaluar(sel, u, p, w)
    mask = np.ones(D.n, bool)
    mu = None
    if municipio:
        mu = v_municipio(municipio)
        mask &= D.edif_muni == mu
    if cl:
        mask &= D.clase == cl
    fuera = ev["routable"] & ~ev["cubierto"] & mask
    sinr = ~ev["routable"] & mask
    C = D.cand_t(p)
    libres = [c for c in D.cand_ids if c not in sel]
    idx = np.where(fuera)[0]
    idx = idx[np.argsort(-ev["best"][idx], kind="stable")]
    motivo = D.edif.motivo_prioridad.to_numpy() if "motivo_prioridad" in D.edif.columns else np.full(D.n, None)
    lista = []
    for i in idx[:lim]:
        mejor_libre, tmin = None, None
        for c in libres:
            t = C[D.cand_ids.index(c)][i]
            if np.isfinite(t) and (tmin is None or t < tmin):
                mejor_libre, tmin = c, float(t)
        lista.append({"building_id": D.ids[i], "municipio": D.edif_muni[i], "prioridad": D.clase[i], "min": _num(ev["best"][i]),
                      "exceso_min": _num(ev["best"][i] - u), "origen": ev["origen"][i],
                      "candidata_no_usada_mas_rapida": mejor_libre, "min_desde_esa_candidata": _num(tmin)})
    dfm = pd.DataFrame({"municipio": D.edif_muni, "fuera": fuera, "sinr": sinr, "fuera_alta": fuera & D.alta, "sinr_alta": sinr & D.alta})
    g = dfm.groupby("municipio")[["fuera", "fuera_alta", "sinr", "sinr_alta"]].sum()
    g = g[(g.fuera > 0) | (g.sinr > 0)].sort_values("fuera", ascending=False)
    out = {"parametros": {"modo": "fuera", "seleccion": sel, "origen_seleccion": origen_sel, "umbral_min": u, "perfil": p, "municipio": mu,
                          "prioridad": cl, "limite": lim},
           "n_fuera_con_ruta": int(fuera.sum()), "n_fuera_alta": int((fuera & D.alta).sum()),
           "n_sin_ruta": int(sinr.sum()), "n_sin_ruta_alta": int((sinr & D.alta).sum()),
           "por_municipio": [{"municipio": m, "fuera_con_ruta": int(r.fuera), "fuera_alta": int(r.fuera_alta), "sin_ruta": int(r.sinr),
                              "sin_ruta_alta": int(r.sinr_alta)} for m, r in g.iterrows()],
           "edificios_fuera": lista,
           "lista_truncada": _truncada(len(lista), int(fuera.sum()), f"tiempos_{p}.csv + " + MARCADOR),
           "sin_ruta": [{"building_id": D.ids[i], "municipio": D.edif_muni[i], "prioridad": D.clase[i], "motivo_prioridad": _limpio(motivo[i])}
                        for i in np.where(sinr)[0][:lim]],
           "sin_ruta_truncada": _truncada(min(lim, int(sinr.sum())), int(sinr.sum()), MARCADOR),
           "nota_sin_ruta": "Sin ruta por carretera (pistas forestales): ningún retén los mejora; necesitan otra medida (acceso, autoprotección).",
           "metodo": METODO_COBERTURA, "limites": LIMITES_BASE}
    return out


def comprobar(estrategia="A", k=3, umbral=UMBRAL_DEF, perfil="ligero", pesos=PESOS_DEF, seleccion=None, manifiesto=None) -> dict:
    """Comprobación independiente de una cifra decisiva: relee tiempos_<perfil>.csv y edificios_prioridad.csv desde disco y
    recalcula con otro camino de código (pandas, formato largo, groupby-min) la cobertura de k=0 y de la selección; la compara
    con el motor, con escenarios.csv (si hay), con cifras_clave_persona1.json (si aplica) y con el manifiesto de un informe."""
    e, u, p, w = v_estrategia(estrategia), v_umbral(umbral), v_perfil(perfil), v_pesos(pesos)
    if seleccion is not None and not (isinstance(seleccion, str) and seleccion.strip() == ""):
        sel, origen_sel = v_seleccion(seleccion), "explicita"
    else:
        kk = v_k(k)
        sel, origen_sel = list(_optimizar_cache(kk, e, u, p, w)["per_k"][kk]["seleccion"]), f"mejor_{e}_k{kk}"
    D = datos()
    raw = pd.read_csv(D.carpeta / f"tiempos_{p}.csv", dtype={"building_id": str})
    ed = pd.read_csv(D.carpeta / MARCADOR, dtype={"building_id": str, "prioridad": str})
    largo = raw.melt(id_vars="building_id", var_name="origen", value_name="min").dropna(subset=["min"])

    def recalcula(activos):
        m = largo[largo.origen.isin(activos)].groupby("building_id")["min"].min().reindex(ed.building_id)
        dentro = (m <= u + EPS).to_numpy()
        wv = pd.Series(1.0, index=ed.index) if w == "uniforme" else pd.to_numeric(ed[COLUMNA_PESO[w]], errors="coerce")
        known = wv.notna().to_numpy()
        es_alta = (ed.prioridad.astype(str) == "Alta").to_numpy()
        return {"edificios_total": int(len(ed)), "edificios_dentro": int(dentro.sum()), "sin_ruta": int(m.isna().sum()),
                "peor_tiempo_min": _num(m.max()), "pct_dentro": _num(100 * dentro.sum() / len(ed)),
                "pct_ponderada": _num(100 * wv[known & dentro].sum() / wv[known].sum()),
                "alta_dentro": int((dentro & es_alta).sum())}

    r0, r1 = recalcula(D.parques_base), recalcula(D.parques_base + sel)
    v0, v1 = _metricas(_evaluar([], u, p, w)), _metricas(_evaluar(sel, u, p, w))
    campos = ("edificios_dentro", "sin_ruta", "peor_tiempo_min", "pct_dentro", "pct_ponderada", "alta_dentro")
    comps = []
    for nombre, a, b in (("k0: recalculo vs motor", r0, v0), ("seleccion: recalculo vs motor", r1, v1)):
        for c in campos:
            ok = a[c] == b[c] or (a[c] is not None and b[c] is not None and abs(a[c] - b[c]) <= 0.011)
            comps.append({"comparacion": nombre, "campo": c, "recalculado": a[c], "motor": b[c], "coincide": bool(ok)})
    g0, g1 = _escenario_guardado(e, 0, u, p, w), _escenario_guardado(e, len(sel), u, p, w)
    for nombre, g, r in (("k0: escenarios.csv", g0, r0), ("seleccion: escenarios.csv", g1, r1)):
        if g is None:
            continue
        if nombre.startswith("seleccion") and str(g["seleccion"]) != ";".join(sel):
            comps.append({"comparacion": nombre, "campo": "seleccion", "recalculado": ";".join(sel), "motor": str(g["seleccion"]),
                          "coincide": False, "nota": "la selección comprobada no es la óptima guardada para ese k"})
            continue
        for c, cg in (("edificios_dentro", "edificios_cubiertos"), ("sin_ruta", "sin_ruta"), ("peor_tiempo_min", "peor_tiempo")):
            gv = _num(g[cg])
            comps.append({"comparacion": nombre, "campo": c, "recalculado": r[c], "guardado": gv,
                          "coincide": bool(gv is not None and r[c] is not None and abs(gv - r[c]) <= 0.011)})
    # cifras citables del equipo (Persona 1): Alta dentro de 12 min en vehículo ligero
    if D.cifras and p == "ligero" and abs(u - 12) < 1e-9:
        if "alta_dentro_12min_k0" in D.cifras:
            comps.append({"comparacion": "k0: cifras_clave_persona1.json", "campo": "alta_dentro", "recalculado": r0["alta_dentro"],
                          "guardado": D.cifras["alta_dentro_12min_k0"], "coincide": r0["alta_dentro"] == D.cifras["alta_dentro_12min_k0"]})
        if sel == ["CAND-01", "CAND-02", "CAND-03"] and "alta_dentro_12min_k3_CAND01_02_03" in D.cifras:
            comps.append({"comparacion": "seleccion: cifras_clave_persona1.json", "campo": "alta_dentro", "recalculado": r1["alta_dentro"],
                          "guardado": D.cifras["alta_dentro_12min_k3_CAND01_02_03"],
                          "coincide": r1["alta_dentro"] == D.cifras["alta_dentro_12min_k3_CAND01_02_03"]})
    if manifiesto:
        mp = Path(str(manifiesto))
        if not mp.is_absolute() and not mp.exists():
            mp = Path.cwd() / mp
        if mp.suffix == ".html":
            mp = mp.with_suffix(".manifest.json")
        if not mp.exists():
            raise ErrorConsulta(f"No encuentro el manifiesto {manifiesto!r}.")
        man = json.loads(mp.read_text(encoding="utf-8"))
        ps = man.get("parametros", {})
        if ps.get("seleccion") != sel or float(ps.get("umbral_min", -1)) != u or ps.get("perfil") != p or ps.get("pesos") != w:
            raise ErrorConsulta(f"El manifiesto corresponde a otros parámetros: {ps}. Llame a comprobar con esos parámetros.")
        for nombre, mm, r in (("manifiesto k0", man["cifras"]["k0"], r0), ("manifiesto propuesta", man["cifras"]["propuesta"], r1)):
            for c in campos:
                ok = mm.get(c) == r[c] or (mm.get(c) is not None and r[c] is not None and abs(mm[c] - r[c]) <= 0.011)
                comps.append({"comparacion": nombre, "campo": c, "recalculado": r[c], "informe": mm.get(c), "coincide": bool(ok)})
    ev0, ev1 = _evaluar([], u, p, w), _evaluar(sel, u, p, w)
    mej = np.where(np.isfinite(ev0["best"]) & np.isfinite(ev1["best"]), np.nan_to_num(ev0["best"], posinf=0) - np.nan_to_num(ev1["best"], posinf=0), -1)
    mej = np.where(D.alta, mej + 1000, mej) if (mej[D.alta] > 0).any() else mej  # preferir un edificio Alta como ejemplo
    j = int(np.argmax(mej))
    fila = raw.set_index("building_id").loc[D.ids[j]]
    ejemplo = {"building_id": D.ids[j], "municipio": D.edif_muni[j], "prioridad": D.clase[j],
               "tiempos_parques": {o: _num(fila[o]) for o in D.parques_base},
               "tiempos_retenes_seleccion": {o: _num(fila[o]) for o in sel},
               "minimo_k0": _num(ev0["best"][j]), "minimo_con_seleccion": _num(ev1["best"][j]),
               "como_comprobar": f"Abrir tiempos_{p}.csv, buscar la fila {D.ids[j]} y tomar el mínimo de las columnas de parques (k0) y de parques + {', '.join(sel) or '—'}."}
    todo_ok = all(c["coincide"] for c in comps if "nota" not in c)
    out = {"parametros": {"estrategia": e, "seleccion": sel, "origen_seleccion": origen_sel, "umbral_min": u, "perfil": p, "pesos": w,
                          "manifiesto": str(manifiesto) if manifiesto else None},
           "todo_coincide": bool(todo_ok), "comparaciones": comps, "edificio_ejemplo": ejemplo,
           "pendiente_supervision_humana": [
               "Validar en campo las candidatas propuestas (" + "; ".join(_COMPROB.values()) + ").",
               "Confirmar con el servicio de bomberos si el umbral de demostración y el perfil de vehículo son adecuados.",
               "Comprobar en ortofoto la posición de los parques (punto de dirección B5M).",
               "Las cifras son estimaciones del modelo; la decisión operativa (dotación, turnos, días de activación) es humana."],
           "metodo": "Recalculo independiente: lectura fresca de CSV, formato largo y groupby-min (pandas), distinto del motor vectorizado (numpy).",
           "limites": LIMITES_BASE}
    nota = _nota_escenarios(e, u, p, w)
    if nota:
        out["nota_escenarios"] = nota
    return out
