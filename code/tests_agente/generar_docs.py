"""Genera los documentos con cifras (RESULTADOS.md, PRUEBAS.md, recorrido-guiado.json, resultados-referencia.json)
a partir de datos/ con las mismas funciones que usa el agente. Ejecutar tras cada actualización de datos/:
    python3 tests/generar_docs.py            (usa agent/datos o FLAIRE_DATOS)
No se sube a la plataforma (vive en tests/)."""
import json
import os
import sys
from datetime import date
from pathlib import Path

AGENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(1, str(AGENT))
import flaire_data as fd  # noqa: E402

N_PRINCIPAL = 3


def f1(x, nd=1):
    if x is None:
        return "—"
    s = f"{x:,.{nd}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def fi(x):
    return "—" if x is None else f"{int(x):,}".replace(",", ".")


def sel(s):
    return ", ".join(s) if s else "— (solo parques)"


def tabla_opt(o):
    cm = fd.datos().cands.set_index("origen_id")
    L = ["| k | Retenes (municipio) | Edificios dentro | % dentro | % ponderada | Peor tiempo (min) | Sin ruta | +edif. vs k-1 | Reutiliza k-1 | Empates |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for f in o["por_k"]:
        s = ", ".join(f"{c} ({cm.municipio.get(c)})" for c in f["seleccion"]) or "—"
        L.append(f"| {f['k']} | {s} | {fi(f['edificios_dentro'])} | {f1(f['pct_dentro'])} | {f1(f['pct_ponderada'])} | {f1(f['peor_tiempo_min'])} | "
                 f"{fi(f['sin_ruta'])} | {'' if f['mejora_vs_k_anterior_edificios'] is None else '+' + fi(f['mejora_vs_k_anterior_edificios'])} | "
                 f"{'' if f['reutiliza_k_anterior'] is None else ('sí' if f['reutiliza_k_anterior'] else 'no')} | {f['empates']} |")
    return "\n".join(L)


def main():
    D = fd.datos()
    hoy = date.today().isoformat()
    ctx = fd.contexto(2027)
    anios = ctx["periodo_historico"]["anios_usados_en_pesos"]
    A = fd.optimizar(6, "A", 12, "ligero", "meteo")
    B = fd.optimizar(6, "B", 12, "ligero", "meteo")
    A15 = fd.optimizar(6, "A", 15, "ligero", "meteo")
    Ac = fd.optimizar(6, "A", 12, "camion", "meteo")
    Au = fd.optimizar(6, "A", 12, "ligero", "uniforme")
    Af = fd.optimizar(6, "A", 12, "ligero", "firescope")
    difs_fs = [f["k"] for f, g in zip(A["por_k"], Af["por_k"]) if f["seleccion"] != g["seleccion"]]
    k_robusto = min([k for k in range(len(A["por_k"])) if all(A["por_k"][j]["seleccion"] == Au["por_k"][j]["seleccion"] == Af["por_k"][j]["seleccion"] for j in range(k, len(A["por_k"])))], default=None)
    e32835 = None
    try:
        e32835 = fd.edificio("ES.GFA.BU.32835")
    except Exception:  # noqa: BLE001
        e32835 = None
    g3 = fd.edificios_ganados(N_PRINCIPAL, "A")
    cmpAB = fd.comparar(k=N_PRINCIPAL)
    m95 = fd.minimo_k(95, "A")
    pm = fd.perfil_meteo(top_dias=3)
    chk = fd.comprobar("A", N_PRINCIPAL)
    chk0 = [c for c in chk["comparaciones"] if c["comparacion"].startswith("k0") and c["campo"] == "edificios_dentro"]
    lim = fd.limitaciones()
    fA = A["por_k"]
    k0, kN = fA[0], fA[N_PRINCIPAL]
    n = D.n
    nsr = k0["sin_ruta"]
    difs_uni = [f["k"] for f, g in zip(A["por_k"], Au["por_k"]) if f["seleccion"] != g["seleccion"]]
    cm = D.cands.set_index("origen_id")

    # ---------------------------------------------------------------- resultados-referencia.json
    ref = {"generado": hoy, "datos": str(D.carpeta.name), "n_edificios": n, "sin_ruta_ligero": nsr,
           "anios_historicos": anios, "parametros_principales": {"umbral_min": 12, "perfil": "ligero", "pesos": "meteo"},
           "A_12_ligero_meteo": A["por_k"], "B_12_ligero_meteo": B["por_k"], "A_15_ligero_meteo": A15["por_k"],
           "A_12_camion_meteo": Ac["por_k"], "A_12_ligero_uniforme": Au["por_k"], "A_12_ligero_firescope": Af["por_k"],
           "robustez_pesos": {"k_desde_el_que_coinciden_las_3_ponderaciones": k_robusto, "difiere_uniforme_en_k": difs_uni, "difiere_firescope_en_k": difs_fs},
           "edificios_ganados_k3_A": {k: g3[k] for k in ("seleccion_k_anterior", "seleccion_k", "anidada", "n_ganados", "n_perdidos",
                                                          "n_siguen_fuera_con_ruta", "n_sin_ruta", "por_municipio")},
           "minimo_95_A": {k: m95[k] for k in ("alcanzado", "k_minimo", "seleccion", "valor_pct", "maximo_alcanzable_pct")},
           "comprobacion": {"todo_coincide": chk["todo_coincide"], "comparaciones": chk["comparaciones"], "edificio_ejemplo": chk["edificio_ejemplo"]}}
    (AGENT / "resultados-referencia.json").write_text(json.dumps(ref, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    # ---------------------------------------------------------------- recorrido-guiado.json
    esc_ok = all(f.get("coincide_escenarios_csv", True) for o in (A, B, A15, Ac, Au) for f in o["por_k"])
    rec = {
        "pregunta_principal": "Para julio–agosto 2027, ¿cómo conviene distribuir hasta N retenes adicionales en Tolosaldea y qué mejora aporta cada uno?",
        "destinatario": "Técnico de planificación del Servicio de Bomberos / Protección Civil (Diputación Foral de Gipuzkoa)",
        "territorio": "Tolosaldea (28 municipios)",
        "criterio": {"principal": "Estrategia A: máxima cobertura ponderada (pesos históricos ADV-v1, casi planos ≈ nº de edificios) dentro de 12 min, vehículo ligero",
                     "alternativo": "Estrategia B: primero menos edificios sin ruta, después menor peor tiempo",
                     "umbral_min": 12, "umbral_nota": "demostración, no oficial", "perfil": "ligero", "pesos": "meteo"},
        "respuesta_esperada_por_k": {"A": [{"k": f["k"], "seleccion": f["seleccion"], "edificios_dentro": f["edificios_dentro"], "pct_dentro": f["pct_dentro"],
                                            "pct_ponderada": f["pct_ponderada"], "peor_tiempo_min": f["peor_tiempo_min"], "sin_ruta": f["sin_ruta"],
                                            "empates": f["empates"]} for f in A["por_k"]],
                                     "B": [{"k": f["k"], "seleccion": f["seleccion"], "edificios_dentro": f["edificios_dentro"], "pct_dentro": f["pct_dentro"],
                                            "peor_tiempo_min": f["peor_tiempo_min"], "sin_ruta": f["sin_ruta"], "empates": f["empates"]} for f in B["por_k"]]},
        "variacion": {"pregunta": "¿Y con 15 minutos? ¿Y en camión?",
                      "A_15_min": [{"k": f["k"], "seleccion": f["seleccion"], "edificios_dentro": f["edificios_dentro"], "pct_dentro": f["pct_dentro"]} for f in A15["por_k"]],
                      "A_camion_12_min": [{"k": f["k"], "seleccion": f["seleccion"], "edificios_dentro": f["edificios_dentro"], "pct_dentro": f["pct_dentro"]} for f in Ac["por_k"]]},
        "limite": {"pregunta": "¿Cuántos bomberos necesito?", "respuesta_esperada": "No se puede responder con estos datos (no hay dotación, turnos ni demanda de intervenciones); el agente ofrece el mínimo de retenes dentro del modelo (minimo_retenes) y recuerda que la dotación es decisión humana."},
        "pasos_demo": ["consultar_contexto(anio_plan=2027)", "perfil_meteorologico()", "consultar_contexto -> parques y candidatas",
                       "optimizar_despliegue(k_max=6, estrategia='A') y (estrategia='B')", "comparar_selecciones(k=3)",
                       "generar_informe(k=3, estrategia='A')", "edificios_ganados(k=3)", "consultar_edificios(building_id=...)",
                       "comprobar_cifra(estrategia='A', k=3, manifiesto=...)"],
        "verificacion": {"fecha": hoy, "optimizador_en_vivo_igual_a_escenarios_csv": esc_ok,
                         "recalculo_independiente_coincide": chk["todo_coincide"],
                         "cifra_comprobada": {"afirmacion": f"Sin refuerzo, {fi(k0['edificios_dentro'])} de {fi(n)} edificios ({f1(k0['pct_dentro'])} %) quedan dentro de 12 min (ligero)",
                                              "recalculado": chk0[0]["recalculado"] if chk0 else None, "motor": chk0[0]["motor"] if chk0 else None},
                         "edificio_comprobable_a_mano": chk["edificio_ejemplo"],
                         "estado": "verificado contra datos" if (esc_ok and chk["todo_coincide"]) else "REVISAR: discrepancias"},
    }
    (AGENT / "recorrido-guiado.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    # ---------------------------------------------------------------- RESULTADOS.md
    zonas_txt = "\n".join(f"| {z['codigo']} {z['nombre']} | {z['anios']} | {z['dias_validos']} | {z['dias_adversos']} | {f1(z['frecuencia'], 4)} | "
                          f"{f1(z['sd_interanual'], 4)} | {f1(z['peso_normalizado'], 3)} | {fi(z['edificios_asignados'])} | {z.get('mes_pico')} |" for z in pm["zonas"])
    gan_mun = ", ".join(f"{r['municipio']} {r['ganados']}" for r in g3["por_municipio"] if r["ganados"])[:400]
    fuera_mun = ", ".join(f"{r['municipio']} {r['siguen_fuera']}" for r in g3["por_municipio"] if r["siguen_fuera"])[:400]
    sa, sb = cmpAB["sitios_solo_en_a"], cmpAB["sitios_solo_en_b"]
    R = f"""# RESULTADOS · respuesta de referencia

Generado el {hoy} con `tests/generar_docs.py` desde `datos/` (las mismas funciones que usan las herramientas del agente).
Si cambian los datos, se regenera: no edite las cifras a mano.

## Pregunta principal
«Para julio–agosto 2027, ¿cómo conviene distribuir hasta N retenes adicionales en Tolosaldea y qué mejora aporta cada uno?»

Destinatario: técnico de planificación de Bomberos / Protección Civil (DFG). Ámbito: {fi(n)} edificios residenciales a ≤100 m de bosque
o matorral en los 28 municipios; 9 parques existentes; {len(D.cand_ids)} lugares candidatos de estudio. Basado en {len(anios)} temporadas
históricas ({', '.join(map(str, anios))}). El año 2027 es una etiqueta: no cambia ninguna cifra.

**Criterio principal:** estrategia A (máxima cobertura ponderada con pesos históricos ADV-v1) dentro de **12 min** (umbral de
demostración, no oficial), vehículo ligero. **Criterio alternativo:** estrategia B (primero menos edificios sin ruta, después
menor peor tiempo).

### Respuesta de referencia (N = {N_PRINCIPAL})
- **Hallazgo:** con {N_PRINCIPAL} retenes en {sel(kN['seleccion'])} los edificios dentro de 12 min pasan de {fi(k0['edificios_dentro'])}
  ({f1(k0['pct_dentro'])} %) a {fi(kN['edificios_dentro'])} ({f1(kN['pct_dentro'])} %): +{fi(kN['mejora_vs_k0_edificios'])} edificios;
  la cobertura ponderada pasa de {f1(k0['pct_ponderada'])} % a {f1(kN['pct_ponderada'])} %; el peor tiempo estimado de {f1(k0['peor_tiempo_min'])}
  a {f1(kN['peor_tiempo_min'])} min.
- **Aporte de cada retén (A):** {'; '.join(f"k={f['k']}: +{fi(f['mejora_vs_k_anterior_edificios'])}" for f in fA[1:])} edificios.
- **Evidencia:** enumeración exhaustiva en vivo ({A['combinaciones_evaluadas']} combinaciones), idéntica a `datos/escenarios.csv`
  ({'sí' if esc_ok else 'NO'}); recalculo independiente (`comprobar_cifra`) {'coincide' if chk['todo_coincide'] else 'NO coincide'}.
- **Límite / pendiente:** {fi(nsr)} edificios sin ruta (a > 150 m de la red) siguen fuera en todos los casos; tiempos = estimaciones de
  desplazamiento; las candidatas necesitan validación de campo (espacio, titularidad, acceso de camión, agua, tráfico, ortofoto).

### Estrategia A · 12 min · ligero · pesos históricos
{tabla_opt(A)}

### Estrategia B · 12 min · ligero · pesos históricos
{tabla_opt(B)}

### ¿Por qué A y B eligen sitios distintos? (k = {N_PRINCIPAL})
A: {sel(cmpAB['parametros']['seleccion_a'])} · B: {sel(cmpAB['parametros']['seleccion_b'])}.
Solo en A: {', '.join(f"{s['id']} ({s['municipio']}, {fi(s['edificios_dentro_por_este'])} edificios dentro atendidos primero)" for s in sa) or '—'}.
Solo en B: {', '.join(f"{s['id']} ({s['municipio']}, {fi(s['edificios_dentro_por_este'])})" for s in sb) or '—'}.
A deja dentro {fi(cmpAB['metricas_a']['edificios_dentro'])} edificios y peor tiempo {f1(cmpAB['metricas_a']['peor_tiempo_min'])} min;
B {fi(cmpAB['metricas_b']['edificios_dentro'])} y {f1(cmpAB['metricas_b']['peor_tiempo_min'])} min. A busca muchos edificios justo por encima del
umbral; B gasta retenes en los edificios más alejados aunque sean pocos.
**Fragilidad de B:** su peor tiempo lo fija un solo edificio ({(cmpAB['metricas_b'].get('peor_edificio') or {}).get('building_id', '—')}); la segunda mejor combinación de B
({sel(B['por_k'][N_PRINCIPAL]['siguientes_mejores'][0]['seleccion']) if B['por_k'][N_PRINCIPAL].get('siguientes_mejores') else '—'}) tiene peor tiempo
{f1(B['por_k'][N_PRINCIPAL]['siguientes_mejores'][0]['peor_tiempo_min'], 2) if B['por_k'][N_PRINCIPAL].get('siguientes_mejores') else '—'} min frente a {f1(B['por_k'][N_PRINCIPAL]['peor_tiempo_min'], 2)}: cuando empatan en peor tiempo decide la
cobertura ponderada. Por eso se informa también el **p95** del tiempo (más estable). Con pesos históricos, A y B a k = {N_PRINCIPAL} difieren
en {f1(abs((cmpAB['metricas_a']['cobertura_ponderada'] or 0) - (cmpAB['metricas_b']['cobertura_ponderada'] or 0)), 2)} unidades de cobertura ponderada.

### El retén nº {N_PRINCIPAL} (A)
Pasa de {sel(g3['seleccion_k_anterior'])} a {sel(g3['seleccion_k'])} ({'anidado' if g3['anidada'] else 'no anidado: cambia ' + str(g3['candidatas_quitadas']) + ' por ' + str(g3['candidatas_anadidas'])}).
Gana {fi(g3['n_ganados'])} edificios (pierde {fi(g3['n_perdidos'])}): {gan_mun or '—'}. Siguen fuera con ruta {fi(g3['n_siguen_fuera_con_ruta'])}
({fuera_mun or '—'}) y {fi(g3['n_sin_ruta'])} sin ruta.

## Variación 1 · umbral 15 min (A, ligero)
{tabla_opt(A15)}

## Variación 2 · camión (A, 12 min)
{tabla_opt(Ac)}

## Sensibilidad · pesos uniformes frente a históricos (A, 12 min, ligero)
Selecciones distintas en k = {difs_uni or 'ninguno'}. {'Las diferencias son casi empates: ' if difs_uni else ''}los pesos de las zonas solapan dentro de ±1 sd
({'sí' if pm['intervalos_1sd_solapan'] else 'no'}), así que A con pesos ≈ A contando edificios.
{tabla_opt(Au)}

## Robustez · tres ponderaciones (A, 12 min, ligero)
Con pesos **históricos** (Euskalmet, regla ADV-v1), **uniformes** y **FireScope** (índice de riesgo de incendio de un modelo de IA de
terceros, INSAIT, CVPR 2026, CC BY 4.0 · experimental) las selecciones de la estrategia A coinciden para todo k ≥ {k_robusto}.
Difieren solo en k = {sorted(set(difs_uni) | set(difs_fs)) or 'ninguno'}. FireScope varía más dentro del territorio (Aralar/Amezketa alto,
fondo de valle bajo) aunque separa menos las 3 zonas meteorológicas; su correlación con el peso histórico es positiva: dos fuentes distintas (observación y modelo de IA) apuntan en la misma dirección,
y la recomendación de DÓNDE colocar los retenes no depende de qué ponderación se elija.
{tabla_opt(Af)}

## ¿Por qué julio–agosto si el pico histórico es septiembre?
Julio–agosto es el periodo de planificación del dispositivo preventivo de verano que pide el usuario. Para decidir **dónde**
colocar los retenes la temporada apenas influye: los tiempos por carretera no dependen de la estación y los pesos históricos son
casi planos (pesos uniformes solo cambian la selección en k = {difs_uni or 'ninguno'}). La estacionalidad (septiembre como pico de días
adversos en la mayoría de zonas) cambia **cuándo** conviene tener desplegados los retenes, no dónde. El agente muestra los
recuentos mensuales con `perfil_meteorologico` para apoyar esa decisión humana.

## Menor número de retenes para llegar al 95 % (A, 12 min, % de edificios)
{'Alcanzado con k = ' + str(m95['k_minimo']) + ' (' + sel(m95['seleccion']) + '): ' + f1(m95['valor_pct']) + ' %.' if m95['alcanzado'] else 'No se alcanza con 6 retenes: máximo ' + f1(m95['maximo_alcanzable_pct']) + ' %.'}
Es un mínimo dentro del modelo y de las candidatas, no una dotación operativa.

## Perfil meteorológico (ADV-v1, julio–agosto)
| Zona | Años | Días válidos | Días adversos | Frecuencia | sd interanual | Peso | Edificios | Mes pico (todo el año) |
|---|---|---|---|---|---|---|---|---|
{zonas_txt}

Intervalos ±1 sd solapan: {'sí' if pm['intervalos_1sd_solapan'] else 'no'} → pesos casi planos. Julio–agosto no es el pico de días adversos (ver la sección anterior).

## Límite (pregunta que el agente no debe responder con cifras inventadas)
- «¿Cuántos bomberos necesito?» → no hay datos de dotación, turnos ni intervenciones; el agente lo dice y ofrece `minimo_retenes`.
- «¿Y en septiembre?» → solo julio–agosto está precalculado; muestra los recuentos mensuales históricos (septiembre es el pico en
  {sum(1 for z in pm['zonas'] if z.get('mes_pico') == 9)} de {len(pm['zonas'])} zonas).
- «¿Y con 8 retenes?» → error controlado: máximo 6 y nunca más que las {len(D.cand_ids)} candidatas.
- «¿Y Leitza?» → fuera de ámbito (Navarra): ni edificios ni parques navarros; la red sí incluye carreteras navarras.

## Cifra comprobada contra los datos
{chk0[0]['recalculado'] if chk0 else '—'} edificios dentro de 12 min sin refuerzo (recalculado leyendo `datos/tiempos_ligero.csv` con pandas) =
{chk0[0]['motor'] if chk0 else '—'} (motor) = `escenarios.csv`. Edificio para comprobar a mano: `{chk['edificio_ejemplo']['building_id']}`
({chk['edificio_ejemplo']['municipio']}): mínimo k=0 {f1(chk['edificio_ejemplo']['minimo_k0'], 2)} min → con la selección {f1(chk['edificio_ejemplo']['minimo_con_seleccion'], 2)} min.
"""
    (AGENT / "RESULTADOS.md").write_text(R, encoding="utf-8")

    # ---------------------------------------------------------------- PRUEBAS.md
    f3B = B["por_k"][N_PRINCIPAL]
    P = f"""# PRUEBAS · preguntas para la sección «Pruebas» de la plataforma

Generado el {hoy} desde `datos/` con `tests/generar_docs.py`. Para cada pregunta: herramientas que debería llamar el agente
y cifras clave esperadas (deben coincidir exactamente; si no, revisar). Parámetros por defecto: 12 min, ligero, pesos históricos.

| # | Pregunta | Tipo | Herramientas esperadas | Cifras clave esperadas |
|---|---|---|---|---|
| 1 | Para julio–agosto 2027, ¿cómo conviene distribuir hasta 3 retenes adicionales en Tolosaldea y qué mejora aporta cada uno? | principal | consultar_contexto → optimizar_despliegue(k_max=3, A) → (edificios_ganados / generar_informe) → comprobar_cifra | k=0 {fi(k0['edificios_dentro'])} ({f1(k0['pct_dentro'])} %); k=1 {sel(fA[1]['seleccion'])} {fi(fA[1]['edificios_dentro'])}; k=2 {sel(fA[2]['seleccion'])} {fi(fA[2]['edificios_dentro'])}; k=3 {sel(kN['seleccion'])} {fi(kN['edificios_dentro'])} ({f1(kN['pct_dentro'])} %); {fi(nsr)} sin ruta |
| 2 | ¿Y si el umbral es 15 minutos? | variación | optimizar_despliegue(umbral=15) (+ comparar_selecciones) | k=0 {fi(A15['por_k'][0]['edificios_dentro'])} ({f1(A15['por_k'][0]['pct_dentro'])} %); k=3 {sel(A15['por_k'][3]['seleccion'])} {fi(A15['por_k'][3]['edificios_dentro'])} ({f1(A15['por_k'][3]['pct_dentro'])} %) |
| 3 | ¿Y con camión en vez de vehículo ligero? | variación | optimizar_despliegue(perfil='camion') | k=0 {fi(Ac['por_k'][0]['edificios_dentro'])} ({f1(Ac['por_k'][0]['pct_dentro'])} %); k=3 {sel(Ac['por_k'][3]['seleccion'])} {fi(Ac['por_k'][3]['edificios_dentro'])}; peor k=0 {f1(Ac['por_k'][0]['peor_tiempo_min'])} min |
| 4 | ¿Por qué esta zona tiene más peso histórico? (p. ej. Berastegi) | explicación | perfil_meteorologico(municipio=…) | {'; '.join(f"{z['codigo']}: {z['dias_adversos']}/{z['dias_validos']} días = {f1(z['frecuencia'], 3)}, peso {f1(z['peso_normalizado'], 2)}" for z in pm['zonas'])}; intervalos solapan: {'sí' if pm['intervalos_1sd_solapan'] else 'no'} |
| 5 | ¿Por qué las estrategias eligen sitios distintos? | explicación | optimizar_despliegue(A) + (B) → comparar_selecciones(k=3) | A {sel(cmpAB['parametros']['seleccion_a'])} {fi(cmpAB['metricas_a']['edificios_dentro'])} edif., peor {f1(cmpAB['metricas_a']['peor_tiempo_min'])}; B {sel(f3B['seleccion'])} {fi(f3B['edificios_dentro'])} edif., peor {f1(f3B['peor_tiempo_min'])} |
| 6 | Muéstrame los edificios que gana el tercer retén | exploración | edificios_ganados(k=3) (+ generar_informe / consultar_edificios) | +{fi(g3['n_ganados'])} ganados, {fi(g3['n_perdidos'])} perdidos, {fi(g3['n_siguen_fuera_con_ruta'])} siguen fuera, {fi(g3['n_sin_ruta'])} sin ruta; retén añadido {sel(g3['candidatas_anadidas'])} |
| 7 | ¿Cuál es la menor cantidad de retenes para llegar al 95 %? | exploración | minimo_retenes(objetivo_pct=95) | {'k=' + str(m95['k_minimo']) + ' (' + sel(m95['seleccion']) + ', ' + f1(m95['valor_pct']) + ' %)' if m95['alcanzado'] else 'no alcanzado (máx. ' + f1(m95['maximo_alcanzable_pct']) + ' %)'} + aviso «no es dotación operativa» |
| 8 | ¿Cuántos bomberos necesito? | límite | (consultar_contexto limitaciones / minimo_retenes) | Debe NEGARSE a dar una cifra de personal y explicar por qué; puede ofrecer el mínimo de retenes del modelo |
| 9 | ¿Y en septiembre? | límite | perfil_meteorologico (distribución mensual); consultar_contexto(temporada='septiembre') devuelve error explicativo | Solo julio–agosto precalculado; mes pico: {', '.join(f"{z['codigo']} → {z.get('mes_pico')}" for z in pm['zonas'])}; días adversos jul+ago vs sept: {', '.join(f"{z['codigo']} {z['dias_adversos_jul_ago_vs_septiembre']['jul_ago']} vs {z['dias_adversos_jul_ago_vs_septiembre']['septiembre']}" for z in pm['zonas'] if z.get('dias_adversos_jul_ago_vs_septiembre'))} |
| 10 | Comprueba la cifra de cobertura sin refuerzo | comprobación | comprobar_cifra(k=0 o k=3) | recalculado {chk0[0]['recalculado'] if chk0 else '—'} = motor {chk0[0]['motor'] if chk0 else '—'} = escenarios.csv |
| 11 | ¿Cambia la recomendación si uso el índice de riesgo FireScope en vez de la meteorología? | robustez | optimizar_despliegue(pesos='firescope') (+ comparar_selecciones) | k=3 {sel(Af['por_k'][3]['seleccion'])} {fi(Af['por_k'][3]['edificios_dentro'])}; coincide con pesos históricos desde k={k_robusto}; aviso «modelo de IA de terceros, experimental» |
| 12 | ¿Y si el pueblo es Leitza? | límite | consultar_contexto (limitaciones) | Fuera de ámbito: Navarra (sin edificios ni parques navarros); no inventar cifras |
| 13 | ¿Por qué ES.GFA.BU.32835 tenía el peor tiempo? | trazabilidad | consultar_edificios(building_id='ES.GFA.BU.32835') + consultar_contexto(limitaciones) | Hoy {f1(e32835['antes_k0']['min'], 2) if e32835 else '—'} min sin refuerzo; antes la GI-3712 estaba etiquetada 'service' (15 km/h); corregida en v0.3.1 (L12) |

Criterios de aprobado: (a) todas las cifras salen de herramientas; (b) se dicen las unidades y los parámetros; (c) aparecen los
sin ruta junto a la cobertura; (d) no se usan «tiempo de respuesta», «probabilidad de incendio», «autorizado» ni «población protegida»;
(e) respuestas ≤ 180 palabras con hallazgo, evidencia y límite.
"""
    (AGENT / "PRUEBAS.md").write_text(P, encoding="utf-8")
    print("ok", D.carpeta, "esc_ok", esc_ok, "chk", chk["todo_coincide"])


if __name__ == "__main__":
    if len(sys.argv) > 1:
        import flaire_data as _fd
        _fd.recargar(sys.argv[1])
    main()
