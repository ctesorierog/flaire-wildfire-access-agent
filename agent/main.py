"""flAIre FINAL · agente para la plataforma del Gipuzkoa AI Hackathon (modo Python).

UN coordinador con 10 herramientas (9 deterministas + ejecutar_codigo de la plantilla).
Opcional (USAR_SUBAGENTE_REVISION = True): comprobar_cifra se sustituye por un sub-agente REVISOR que recomprueba con
comprobar_cifra / calcular_cobertura / consultar_edificios. Sigue habiendo 10 herramientas.
"""
try:
    from instrucciones import COORDINADOR, REVISION
except ImportError:  # paso 1 del despliegue: instrucciones.py todavía no está subido
    COORDINADOR = ("Eres flAIre, asistente de datos para planificar retenes preventivos de bomberos en Tolosaldea. Responde en "
                   "español. Usa ejecutar_codigo para leer con pandas los CSV de 'agentes/flAIr datos FINAL/' (empieza por "
                   "REGLAS_prioridad.md y DICCIONARIO_datos.md con read_text). Cada cifra debe salir de una herramienta. La prioridad "
                   "es de planificación, no probabilidad de incendio; los tiempos son estimaciones, no tiempos de respuesta.")
    REVISION = COORDINADOR
import tools as _tools

# plantilla (pasos 1-2): tools.py solo tiene ejecutar_codigo; versión flAIre: tools.TOOLS
TOOLS = list(getattr(_tools, "TOOLS", None) or [_tools.ejecutar_codigo])

AGENT_NAME = "Agente flAIr FINAL"
STUDIO_MAX_ITERATIONS = 8
STUDIO_MEMORY_ENABLED = True
STUDIO_INTERNET_ENABLED = False
USAR_SUBAGENTE_REVISION = False

STUDIO_CONTEXT_FILES = [
    "agentes/flAIr datos FINAL/edificios_prioridad.csv",
    "agentes/flAIr datos FINAL/tiempos_ligero.csv",
    "agentes/flAIr datos FINAL/tiempos_camion.csv",
    "agentes/flAIr datos FINAL/parques.csv",
    "agentes/flAIr datos FINAL/candidatos.csv",
    "agentes/flAIr datos FINAL/escenarios.csv",
    "agentes/flAIr datos FINAL/municipios.csv",
    "agentes/flAIr datos FINAL/municipios.geojson",
    "agentes/flAIr datos FINAL/meteo_mensual.csv",
    "agentes/flAIr datos FINAL/meteo_anual.csv",
    "agentes/flAIr datos FINAL/meteo_dias_riesgo.csv",
    "agentes/flAIr datos FINAL/meteo_test_zonas.csv",
    "agentes/flAIr datos FINAL/meteo_estaciones.csv",
    "agentes/flAIr datos FINAL/incendios_previos.csv",
    "agentes/flAIr datos FINAL/fuentes.csv",
    "agentes/flAIr datos FINAL/metodologia.csv",
    "agentes/flAIr datos FINAL/cifras_clave_persona1.json",
    "agentes/flAIr datos FINAL/REGLAS_prioridad.md",
    "agentes/flAIr datos FINAL/DICCIONARIO_datos.md",
]


def _buscar(herramientas, nombre):
    for t in herramientas:
        if getattr(t, "name", None) == nombre or getattr(t, "__name__", None) == nombre:
            return t
    return None


def build_agent(model):
    from langchain.agents import create_agent

    herramientas = list(TOOLS)
    comprobar_cifra = _buscar(herramientas, "comprobar_cifra")
    if USAR_SUBAGENTE_REVISION and comprobar_cifra is not None:
        from langchain.tools import tool

        apoyo = [t for t in (comprobar_cifra, _buscar(herramientas, "calcular_cobertura"), _buscar(herramientas, "consultar_edificios")) if t]
        revisor = create_agent(model=model, tools=apoyo,
                               system_prompt=REVISION, name="flaire_revision")

        @tool
        def revisar_propuesta(tarea: str) -> str:
            """Pide al revisor que recompruebe una cifra o propuesta (incluye parámetros: estrategia, k o selección,
            umbral, perfil, pesos y, si existe, la ruta del manifiesto del informe)."""
            res = revisor.invoke({"messages": [{"role": "user", "content": tarea}]})
            ultimo = res["messages"][-1]
            t = getattr(ultimo, "text", None)
            if not isinstance(t, str) and callable(t):
                t = t()
            return t or str(getattr(ultimo, "content", ultimo))

        herramientas = [t for t in herramientas if t is not comprobar_cifra] + [revisar_propuesta]
    assert len(herramientas) <= 10
    return create_agent(model=model, tools=herramientas, system_prompt=COORDINADOR, name="flaire_final")
