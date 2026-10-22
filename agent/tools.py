"""flAIre FINAL · herramientas del agente (10 como máximo en la plataforma).

Nueve herramientas deterministas envuelven funciones de flaire_data.py o mapas.py, validan la entrada y devuelven
JSON (texto). Los errores de entrada vuelven como {"error": {...}} con los valores válidos, para que el agente
corrija la llamada en lugar de inventar. Parámetros "no indicados": texto vacío ("") o -1 en números.
La décima, ejecutar_codigo, es la herramienta de la plantilla para exploración libre con los datos.

Despliegue por pasos: ETAPA decide qué herramientas se activan (3 = consultar_prioridad; 4 = + calcular_cobertura y
comprobar_cifra; 5 = + optimizar_despliegue, comparar_selecciones y consultar_edificios; 6 = + perfil_meteorologico y
consultar_contexto; 7 = + generar_informe, que necesita mapas.py). Versión final: ETAPA = 7.
"""
from __future__ import annotations

import json

from studio import artifacts, tool

import flaire_data as fd

ETAPA = 7  # despliegue por pasos (ver arriba); 7 = las 10 herramientas


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str, separators=(",", ":"))


def _llamar(fn, *a, **kw) -> str:
    try:
        return _json(fn(*a, **kw))
    except fd.ErrorConsulta as e:
        return _json({"error": {"codigo": "PARAMETRO_INVALIDO", "mensaje": str(e)}})
    except FileNotFoundError as e:
        return _json({"error": {"codigo": "DATOS_NO_ENCONTRADOS", "mensaje": str(e)}})
    except Exception as e:  # noqa: BLE001
        return _json({"error": {"codigo": "ERROR_INTERNO", "mensaje": f"{type(e).__name__}: {e}"}})


def _opt(s):
    """'' -> None (parámetro no indicado)."""
    return None if s is None or (isinstance(s, str) and s.strip() == "") else s


def _optk(k):
    return None if k is None or (isinstance(k, (int, float)) and k < 0) else int(k)


def _optf(x):
    return None if x is None or (isinstance(x, (int, float)) and x < 0) else x


@tool
def consultar_contexto(apartado: str = "resumen", anio_plan: int = 2027) -> str:
    """Marco del análisis. Llamar SOLO en el primer turno o ante preguntas de alcance, fuentes, método o límites.

    Args:
        apartado: 'resumen' (pregunta del plan, ámbito, prioridad por clase, parques, candidatas, «cuándo» meteorológico,
            parámetros por defecto), 'fuentes' (fuentes.csv con licencia y responsable), 'metodologia' (metodologia.csv),
            'limitaciones' (límites con recuentos en vivo), 'diccionario' (columnas de los datos), 'referencias'
            (FireScope e incendios previos, solo referencia) o 'reglas' (reglas de la prioridad).
        anio_plan: año del plan (solo etiqueta: NO cambia ningún resultado).
    """
    a = fd._norm(apartado or "resumen")
    rutas = {"fuente": fd.fuentes, "metodo": fd.metodologia, "limit": fd.limitaciones, "diccion": fd.diccionario,
             "refer": fd.referencias, "regla": fd.reglas_prioridad}
    for pref, fn in rutas.items():
        if a.startswith(pref):
            return _llamar(fn)
    if a != "resumen":
        return _json({"error": {"codigo": "PARAMETRO_INVALIDO", "mensaje": "apartado debe ser 'resumen', 'fuentes', 'metodologia', "
                                "'limitaciones', 'diccionario', 'referencias' o 'reglas'."}})
    return _llamar(fd.contexto, anio_plan)


@tool
def consultar_prioridad(apartado: str = "resumen", clase: str = "", municipio: str = "", building_id: str = "", limite: int = 20) -> str:
    """Prioridad de PLANIFICACIÓN de las viviendas del borde forestal (PRIO-v1: distancia a vegetación + tipo de vegetación +
    acceso actual; Alta >= 6 puntos). NO es probabilidad de incendio. Usar para «¿cuántas Alta hay?», «¿dónde están?»,
    «¿por qué esta casa es Alta?», «¿cómo se puntúa?».

    Args:
        apartado: 'resumen' (recuentos por clase con viviendas, Alta sin ruta, top municipios, Alta dentro de 12 min con k=0 y
            con la mejor k=3), 'municipios' (tabla por municipio), 'lista' (viviendas de una clase/municipio con su motivo),
            'edificio' (ficha de puntos de un edificio), 'reglas' (reglas y decisiones del equipo) o 'referencias'
            (FireScope e incendios previos: solo referencia, nunca suman).
        clase: 'Alta', 'Media' o 'Baja' (para 'lista'; vacío = todas).
        municipio: municipio de Tolosaldea (filtra 'municipios' y 'lista'). Acentos y mayúsculas no importan.
        building_id: id INSPIRE (ES.GFA.BU.<n>) o solo el número (para 'edificio').
        limite: máximo de filas en 'lista' (1-50; más se recorta y se avisa).
    """
    return _llamar(fd.prioridad, apartado, _opt(clase), _opt(municipio), _opt(building_id), limite)


@tool
def perfil_meteorologico(zona: str = "", municipio: str = "", mes: int = -1, anio: int = -1, tipo: str = "",
                         fecha_desde: str = "", fecha_hasta: str = "", top_dias: int = 10) -> str:
    """Meteorología de TODO el año (2018-2023): días de riesgo = calor seco o viento sur seco, por mes y zona (media ≈ 26 al
    año; feb-abr y sep-oct concentran la mayoría, jul-ago poco), por año, prueba de si las zonas se distinguen (no), el
    episodio de validación Bera–Aiako Harria (19-21 feb 2021) y la lista de días de riesgo filtrable. Dice CUÁNDO activar
    los retenes, no DÓNDE colocarlos.

    Args:
        zona: estación (C026 Berastegi, C029 Zizurkil, C058 Bidania; C043 Ordizia = control) o su nombre; vacío = las 3 zonas.
        municipio: municipio de Tolosaldea (se usa su zona asignada).
        mes: 1-12 para filtrar la lista de días (-1 = todos).
        anio: 2018-2023 para filtrar la lista de días (-1 = todos).
        tipo: 'calor' o 'viento' para filtrar la lista (vacío = ambos).
        fecha_desde: AAAA-MM-DD (opcional).
        fecha_hasta: AAAA-MM-DD (opcional).
        top_dias: cuántos días de riesgo listar, del más reciente al más antiguo (0-50; más se recorta y se avisa).
    """
    return _llamar(fd.perfil_meteo, _opt(zona), _opt(municipio), _optk(mes), _optk(anio), _opt(tipo), _opt(fecha_desde),
                   _opt(fecha_hasta), top_dias)


@tool
def calcular_cobertura(seleccion: str = "", umbral: float = 12, perfil: str = "ligero", pesos: str = "prioridad",
                       municipio: str = "", k: int = -1, estrategia: str = "A") -> str:
    """Calcula EN VIVO la cobertura de los 9 parques en base más los retenes indicados: edificios dentro del umbral, %,
    edificios de prioridad Alta dentro (de 243) y Alta sin ruta, cobertura ponderada, peor tiempo y p95, sin ruta, mejora
    frente a k=0, desglose por municipio y qué origen llega antes.

    Args:
        seleccion: candidatas separadas por ';' (p. ej. 'CAND-01;CAND-02'); vacío = solo parques (k=0).
        umbral: minutos (1-60); 12 por defecto (demostración, no oficial).
        perfil: 'ligero' o 'camion'.
        pesos: 'prioridad' (por defecto: prioridad de planificación sin acceso), 'uniforme', 'meteo' (legado jul-ago, solo
            sensibilidad) o 'firescope' (solo sensibilidad).
        municipio: si se indica, devuelve solo la fila de ese municipio.
        k: si seleccion está vacía y k>=0, usa la mejor combinación de `estrategia` con k retenes.
        estrategia: 'A' o 'B' (solo se usa con k).
    """
    sel, kk = _opt(seleccion), _optk(k)
    if sel is None and kk is None:
        sel = ""
    return _llamar(fd.cobertura, sel, umbral, perfil, pesos, _opt(municipio), kk, estrategia)


@tool
def optimizar_despliegue(k_max: int = 6, estrategia: str = "A", umbral: float = 12, perfil: str = "ligero",
                         pesos: str = "prioridad", objetivo_pct: float = -1, metrica: str = "edificios") -> str:
    """Mejor combinación de retenes adicionales para cada k = 0..k_max por enumeración exhaustiva EN VIVO (10 candidatas,
    hasta 848 combinaciones). Por k: selección, edificios dentro, %, Alta dentro, cobertura ponderada, peor tiempo, sin
    ruta, mejora frente a k=0 y k-1, si reutiliza los sitios de k-1, empates y siguientes mejores. Con objetivo_pct
    devuelve además el MENOR k para el que ALGUNA combinación alcanza el objetivo en la métrica elegida (busca en las 848
    combinaciones la que maximiza esa métrica, sin depender de la estrategia) y el máximo alcanzable; es un mínimo dentro
    del modelo, no una dotación operativa.

    Args:
        k_max: máximo de retenes adicionales (0-6). Con objetivo_pct se usa siempre 6.
        estrategia: 'A' = máxima cobertura ponderada; 'B' = mejorar el peor acceso (menos sin ruta, después menor peor tiempo).
        umbral: minutos (1-60), 12 por defecto (demostración).
        perfil: 'ligero' o 'camion'.
        pesos: 'prioridad' (por defecto), 'uniforme', 'meteo' (legado jul-ago, solo sensibilidad) o 'firescope' (sensibilidad).
        objetivo_pct: objetivo en % (0-100), p. ej. 95; -1 = no calcular mínimo.
        metrica: para el mínimo: 'edificios' (% dentro), 'ponderada' (% ponderada) o 'alta' (% de Alta dentro).
    """
    return _llamar(fd.optimizar, k_max, estrategia, umbral, perfil, pesos, _optf(objetivo_pct), metrica)


@tool
def comparar_selecciones(seleccion_a: str = "", seleccion_b: str = "", k: int = 3, umbral: float = 12,
                         perfil: str = "ligero", pesos: str = "prioridad", estrategia_a: str = "A", estrategia_b: str = "B") -> str:
    """Compara dos despliegues: métricas lado a lado (incluidas las Alta dentro), sitios que solo están en uno (con municipio
    y cuántos edificios y Alta atienden primero), edificios dentro solo con A o solo con B por municipio, peor edificio de
    cada uno y hechos para explicar la diferencia. Sin selecciones y con k>=0 compara la mejor de estrategia_a con la mejor
    de estrategia_b. Para «¿qué cambia con 15 min / camión / otros pesos?» pase las selecciones de cada caso.

    Args:
        seleccion_a: candidatas separadas por ';' (vacío junto con seleccion_b vacío = usar k).
        seleccion_b: candidatas separadas por ';'.
        k: número de retenes para comparar estrategias (por defecto 3; se ignora si se dan selecciones).
        umbral: minutos (1-60).
        perfil: 'ligero' o 'camion'.
        pesos: 'prioridad' (por defecto), 'uniforme', 'meteo' (legado jul-ago) o 'firescope'.
        estrategia_a: estrategia del primer despliegue cuando se usa k.
        estrategia_b: estrategia del segundo despliegue cuando se usa k.
    """
    sa, sb = _opt(seleccion_a), _opt(seleccion_b)
    if (sa is None) != (sb is None):
        sa, sb = sa or "", sb or ""
    return _llamar(fd.comparar, sa, sb, umbral, perfil, pesos, _optk(k), estrategia_a, estrategia_b)


@tool
def consultar_edificios(building_id: str = "", modo: str = "fuera", seleccion: str = "", k: int = -1, estrategia: str = "A",
                        umbral: float = 12, perfil: str = "ligero", pesos: str = "prioridad", municipio: str = "",
                        prioridad: str = "", limite: int = 15) -> str:
    """Edificios concretos. Tres usos:
    1) building_id: ficha trazable de UN edificio (prioridad y motivo, viviendas, vegetación, tiempos desde cada parque y
       candidata, mejor origen antes y después de la selección).
    2) modo='fuera' (por defecto): edificios que siguen FUERA del umbral con la selección (ordenados por tiempo, con la
       candidata no usada más rápida) y los sin ruta, por municipio; filtrable por prioridad (p. ej. 'Alta').
    3) modo='ganados' con k>=1: qué aporta el k-ésimo retén (edificios y Alta que entran con la mejor de k frente a la
       mejor de k-1, perdidos si no están anidadas, los que siguen fuera).

    Args:
        building_id: id INSPIRE (ES.GFA.BU.<n>) o solo el número; vacío = modo lista.
        modo: 'fuera' o 'ganados'.
        seleccion: candidatas separadas por ';' (modo fuera / ficha); vacío y k=-1 = solo parques.
        k: modo fuera/ficha: usa la mejor combinación de `estrategia` con k retenes; modo ganados: el k-ésimo retén (1-6).
        estrategia: 'A' o 'B'.
        umbral: minutos (1-60).
        perfil: 'ligero' o 'camion'.
        pesos: 'prioridad' (por defecto), 'uniforme', 'meteo' (legado jul-ago) o 'firescope' (para elegir la mejor combinación con k).
        municipio: filtrar a un municipio.
        prioridad: 'Alta', 'Media' o 'Baja' para filtrar (vacío = todas).
        limite: máximo de edificios por lista (0-50; más se recorta y se avisa).
    """
    sel, kk = _opt(seleccion), _optk(k)
    if _opt(building_id):
        return _llamar(fd.edificio, building_id, sel, umbral, perfil, kk, estrategia, pesos)
    m = fd._norm(modo or "fuera")
    if m.startswith("gan"):
        if kk is None:
            return _json({"error": {"codigo": "PARAMETRO_INVALIDO", "mensaje": "modo='ganados' necesita k entre 1 y 6 (el k-ésimo retén)."}})
        return _llamar(fd.edificios_ganados, kk, estrategia, umbral, perfil, pesos, _opt(municipio), limite, _opt(prioridad))
    if not m.startswith("fuera"):
        return _json({"error": {"codigo": "PARAMETRO_INVALIDO", "mensaje": "modo debe ser 'fuera' o 'ganados' (o indique building_id)."}})
    return _llamar(fd.fuera_umbral, sel, umbral, perfil, _opt(municipio), limite, kk, estrategia, pesos, _opt(prioridad))


@tool
def generar_informe(seleccion: str = "", k: int = 3, estrategia: str = "A", umbral: float = 12, perfil: str = "ligero",
                    pesos: str = "prioridad", anio_plan: int = 2027):
    """Genera el informe HTML «Plan preventivo flAIre · Tolosaldea <año>»: dos mapas sincronizados (solo parques vs parques +
    retenes) con las viviendas coloreadas por prioridad (Alta/Media/Baja) y halo si quedan fuera o sin ruta, gráficos de
    beneficio por retén (Alta dentro y % de edificios, A y B), tabla de indicadores, «cuándo activar» (días de riesgo por
    mes), retenes con comprobaciones pendientes, fuentes y límites; más un manifiesto JSON con todas las cifras. Adjunta el HTML.

    Args:
        seleccion: candidatas separadas por ';'; vacío = la mejor de `estrategia` con k retenes.
        k: número de retenes (0-6) cuando no se da selección.
        estrategia: 'A' o 'B'.
        umbral: minutos (1-60).
        perfil: 'ligero' o 'camion'.
        pesos: 'prioridad' (por defecto), 'uniforme', 'meteo' (legado jul-ago) o 'firescope'.
        anio_plan: año que aparece en el título (no cambia cifras).
    """
    try:
        import mapas  # import diferido: mapas.py solo hace falta desde el paso 7
        r = mapas.informe_html(_opt(seleccion), _optk(k), estrategia, umbral, perfil, pesos, anio_plan)
    except fd.ErrorConsulta as e:
        return _json({"error": {"codigo": "PARAMETRO_INVALIDO", "mensaje": str(e)}})
    except Exception as e:  # noqa: BLE001
        return _json({"error": {"codigo": "ERROR_INTERNO", "mensaje": f"{type(e).__name__}: {e}"}})
    msg = _json({k2: r[k2] for k2 in ("parametros", "html", "manifiesto", "bytes", "cifras_principales", "limites")})
    return artifacts(r["html"], message=msg)


@tool
def comprobar_cifra(estrategia: str = "A", k: int = 3, umbral: float = 12, perfil: str = "ligero", pesos: str = "prioridad",
                    seleccion: str = "", manifiesto: str = "") -> str:
    """Revisión: recalcula por un camino de código independiente (lectura fresca de los CSV, pandas groupby-min) la cobertura
    de k=0 y de la selección (edificios, %, ponderada, peor tiempo, sin ruta, Alta dentro) y la compara con el motor, con
    escenarios.csv (si tiene esos parámetros; no tiene pesos 'prioridad'), con las cifras citables del equipo (49 / 177 Alta)
    y, si se indica, con el manifiesto de un informe. Usar antes de dar por buena una cifra decisiva o un informe.

    Args:
        estrategia: 'A' o 'B' (para resolver la mejor selección con k).
        k: número de retenes (0-6) si no se da selección; -1 = no indicado (3).
        umbral: minutos (1-60).
        perfil: 'ligero' o 'camion'.
        pesos: 'prioridad' (por defecto), 'uniforme', 'meteo' (legado jul-ago) o 'firescope'.
        seleccion: candidatas separadas por ';' (opcional; si se da, manda sobre k).
        manifiesto: ruta del manifiesto (o del HTML) devuelta por generar_informe (opcional).
    """
    kk = _optk(k)
    return _llamar(fd.comprobar, estrategia, 3 if kk is None else kk, umbral, perfil, pesos,
                   _opt(seleccion), _opt(manifiesto))


@tool
def ejecutar_codigo(code: str):
    """Exploración libre SOLO si ninguna otra herramienta responde (cifras de las herramientas = referencia).
    Ejecuta Python (≤ 6.000 caracteres; sin open/eval/while/class) con pandas, numpy, math, statistics, json, datetime y
    html. Use print() para devolver resultados. Datos en 'agentes/flAIr datos FINAL/' (p. ej.
    pd.read_csv('agentes/flAIr datos FINAL/edificios_prioridad.csv'); unir con tiempos_ligero.csv por building_id).
    Ayudas: read_text(ruta, offset) para leer md/csv/json (30.000 caracteres) y save_html(nombre, contenido) para adjuntar
    un HTML. Vacío = desconocido (nunca 0). Prioridad = de planificación, no probabilidad de incendio.

    Args:
        code: programa Python completo que imprime el resultado.
    """
    try:
        from ejecucion import execute_program
        output, generated = execute_program(code)
    except Exception as e:  # noqa: BLE001
        return f"ERROR DE EJECUCIÓN: {type(e).__name__}: {e}"
    if generated:
        return artifacts(*[g["path"] for g in generated], message=output)
    return output


# (paso en que se activa, herramienta) en el orden en que las ve el modelo
_POR_ETAPA = [(6, consultar_contexto), (3, consultar_prioridad), (6, perfil_meteorologico), (4, calcular_cobertura),
              (5, optimizar_despliegue), (5, comparar_selecciones), (5, consultar_edificios), (7, generar_informe),
              (4, comprobar_cifra), (1, ejecutar_codigo)]
TOOLS = [t for e, t in _POR_ETAPA if e <= ETAPA]
assert len(TOOLS) <= 10
