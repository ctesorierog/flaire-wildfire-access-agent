# Agente flAIr FINAL · cambios respecto a la v3 (3 de octubre de 2026)

**Qué es:** la v3 probada, adaptada a la carpeta de datos nueva `agentes/flAIr datos FINAL/` (19 archivos).
**Pregunta nueva:** ¿dónde colocar hasta N retenes preventivos adicionales para las viviendas del borde forestal de Tolosaldea, y en qué días de riesgo activarlos?

**Código:** `agentes/agente_flair_final/`, con 5 archivos.
- `ejecucion.py` es el de la plantilla. Ya está en la plataforma y no se toca.
- No subas `__pycache__/`.

**Pruebas:** en `tests_final/`. No se suben.

## 1. Cambios por archivo

### `flaire_data.py` (88 KB) · la capa de datos
- **Busca la carpeta de datos en este orden:**
  1. `./agentes/flAIr datos FINAL/` (la plataforma ejecuta desde la raíz del workspace);
  2. la carpeta hermana del código;
  3. `./datos/`.

  El archivo que la identifica es `edificios_prioridad.csv`.
- **Lee `edificios_prioridad.csv` con las columnas nuevas.**
  - `sin_ruta` es «sí» o «no».
  - `prioridad`, `motivo_prioridad`, `puntos_*` y `fs_*`.
  - Ya no lee `edificios.csv`, `meteo_perfil.csv`, `meteo_dias_adversos.csv` ni `auditoria.json`.
- **Pesos.**
  - `prioridad` es el **valor por defecto** y usa la columna `peso_optimizador`.
  - `uniforme`.
  - `meteo` y `firescope` usan las columnas `*_sensibilidad` y se etiquetan como **solo sensibilidad**.
- **Edificios de prioridad Alta en todos los resultados.** Cada cobertura, cada fila del optimizador, cada comparación y cada comprobación incluye:
  - `alta_dentro` y `pct_alta_dentro`;
  - `alta_sin_ruta` y `alta_fuera_con_ruta`;
  - `dentro_por_prioridad` y `viviendas_dentro`.
- **`escenarios.csv` no tiene la ponderación «prioridad».** Cuando falta, se añade `nota_escenarios`: la cifra calculada en vivo es la referencia.
  `comprobar` hace además un recálculo independiente y compara con `cifras_clave_persona1.json` (49 y 177 viviendas Alta).
- **Funciones nuevas:**
  - `prioridad()`: resumen, municipios, lista, edificio, reglas y referencias;
  - `referencias()`: FireScope e incendios previos, solo como referencia;
  - `reglas_prioridad()`, `metodologia()` y `diccionario()`;
  - `_meteo_resumen()`.
- **`perfil_meteo()` se ha reescrito para todo el año.** Da:
  - los días de riesgo por mes y por zona, y por año;
  - la prueba de zonas (`meteo_test_zonas.csv`);
  - el episodio de Bera–Aiako Harria;
  - la lista de días, que se puede filtrar por mes, año, tipo y fechas.
- **`optimizar()` acepta `objetivo_pct` y `metrica`** («edificios», «ponderada» o «alta»). Sustituye a la herramienta `minimo_retenes`; se mantiene `minimo_k()` por compatibilidad.
- **`fuera_umbral()` y `edificios_ganados()` se pueden filtrar por clase de prioridad.**
- **`contexto()` ya no tiene el parámetro `temporada`** ni el enfoque de julio y agosto. Ahora es más corto: los detalles están en sus propios apartados.

### `tools.py` (18 KB)
- **10 herramientas** (ver el apartado 2).
- **Se quitan:**
  - `minimo_retenes`, que ahora es `objetivo_pct` dentro de `optimizar_despliegue`;
  - `edificios_ganados`, que ahora es `modo='ganados'` dentro de `consultar_edificios`.
- **Se añaden:**
  - `consultar_prioridad`;
  - `ejecutar_codigo`, copiada de la plantilla, con `from ejecucion import execute_program` diferido y el error devuelto como «ERROR DE EJECUCIÓN: …».
- **`ETAPA = 7`:** decide qué herramientas se activan en cada paso del despliegue.
- **`mapas` se importa dentro de `generar_informe`.** Así, `mapas.py` solo hace falta desde el paso 7.

### `mapas.py` (33 KB) · el informe
- **Se mantiene:**
  - los 2 mapas sincronizados;
  - el gráfico y las tablas;
  - el manifiesto JSON.
- **En los mapas:**
  - las viviendas se colorean por prioridad (Alta, Media o Baja);
  - un **halo oscuro** marca las que quedan fuera del umbral;
  - un **halo gris** marca las que no tienen ruta.
- **Gráficos y tablas:**
  - un gráfico nuevo con las «Alta dentro (de 243)» para las estrategias A y B, además del % de edificios;
  - la tabla tiene una fila nueva con las Alta, que pasan de 49 a 177;
  - la tabla de retenes tiene una columna nueva con las «Alta que atiende primero»;
  - un bloque nuevo, «**Cuándo activar**», con las barras de días de riesgo por mes.
- **Título:** «Plan preventivo flAIre · Tolosaldea <año>».
- **Tamaño:** unos 262 KB, muy por debajo del límite de 2 MB.

### `instrucciones.py` (5 KB)
El prompt se ha reescrito y ahora tiene 4.400 caracteres (antes, 6.700).

- **La pregunta:** la nueva.
- **Orden para elegir herramienta:**
  1. el contexto, solo en el primer turno;
  2. la prioridad;
  3. **dónde**: optimizar, luego cobertura o comparar, luego comprobar;
  4. **cuándo**: la meteorología;
  5. el informe;
  6. `ejecutar_codigo`, solo si no hay otra herramienta que responda.
- **Reglas de «Cómo debe hablar el agente»** (de `REGLAS_prioridad.md`):
  - es una prioridad de planificación;
  - nunca hablar de «probabilidad de incendio» ni de «riesgo real»;
  - nunca sumar FireScope;
  - no inventar personal ni tiempos de respuesta reales;
  - las decisiones son del equipo;
  - decir los límites.
- **El sub-agente revisor (`REVISION`)** se ha actualizado.

### `main.py` (4 KB)
- `AGENT_NAME = "Agente flAIr FINAL"`, con 8 iteraciones, memoria activada y sin internet.
- **`STUDIO_CONTEXT_FILES`** es una lista literal con los 19 archivos de `agentes/flAIr datos FINAL/` y **no incluye documentos del agente**.
- **Tolera el despliegue por pasos:**
  - si todavía no hay `instrucciones.py`, usa un prompt provisional;
  - si `tools.py` es el de la plantilla, solo activa `ejecutar_codigo`.
- **El sub-agente revisor** (`USAR_SUBAGENTE_REVISION = False`) se mantiene y busca sus herramientas por su nombre.

## 2. Herramientas finales (10)
| # | Herramienta | Qué hace |
|---|---|---|
| 1 | `consultar_contexto` | Marco del análisis: pregunta, ámbito, prioridad, parques y candidatas, «cuándo». Apartados: fuentes · metodología · limitaciones · diccionario · referencias · reglas |
| 2 | `consultar_prioridad` | Prioridad de planificación: recuentos por clase (243 / 961 / 2.127), municipios, lista con motivo, ficha, reglas y referencias |
| 3 | `perfil_meteorologico` | Días de riesgo de todo el año por mes, zona y año; prueba de zonas; Bera–Aiako Harria 2021; lista de días |
| 4 | `calcular_cobertura` | Cobertura en vivo de una selección o de la mejor con k retenes: edificios, Alta, ponderada, peor tiempo, sin ruta y municipios |
| 5 | `optimizar_despliegue` | Óptimo exhaustivo de k = 0 a 6 (estrategias A y B), con Alta dentro por k; con `objetivo_pct`, el menor k (buscado en las 848 combinaciones según la métrica) |
| 6 | `comparar_selecciones` | Dos despliegues lado a lado (por defecto, la mejor A frente a la mejor B con k = 3), con las Alta |
| 7 | `consultar_edificios` | Ficha de un edificio · los que quedan fuera (filtro por prioridad) · `modo='ganados'`: lo que aporta el k-ésimo retén |
| 8 | `generar_informe` | Informe HTML con los mapas por prioridad y los gráficos, más el manifiesto |
| 9 | `comprobar_cifra` | Recálculo independiente frente al motor, `escenarios.csv`, las cifras clave del equipo y el manifiesto |
| 10 | `ejecutar_codigo` | La herramienta de la plantilla, para explorar libremente los CSV |

## 3. Despliegue por pasos
Los datos ya están en `agentes/flAIr datos FINAL/`. En cada paso hay que subir lo que se indica a `agentes/agente_flair_final/`. Después:
1. pasar «Comprobar preparación»;
2. crear una versión;
3. hacer una pregunta de prueba.

**Los pasos 4 a 6 solo cambian una línea de `tools.py`:** `ETAPA = 4`, `5` o `6`. Puedes editarla en la plataforma o volver a subir el archivo.
Al terminar, `ETAPA` debe quedar en `7`, que es el valor del archivo entregado.

| Paso | Qué subir (además de lo anterior) | Herramientas activas | Pregunta de prueba |
|---|---|---|---|
| **1** · `main.py` con `STUDIO_CONTEXT_FILES` | `main.py`. Se queda el `tools.py` de la plantilla. | 1: `ejecutar_codigo` | «Lee REGLAS_prioridad.md y dime cuántas viviendas Alta hay» |
| **2** · instrucciones | `instrucciones.py` | 1 | (el prompt ya nombra herramientas que llegan después; es normal) |
| **3** · `consultar_prioridad` | `flaire_data.py` (completo, una sola vez) y `tools.py` con `ETAPA = 3` | 2 | «¿Cuántas viviendas Alta hay y dónde?» → 243; Asteasu 43, Amezketa 35, Abaltzisketa 28 |
| **4** · `calcular_cobertura` y `comprobar_cifra` | `tools.py` con `ETAPA = 4` | 4 | «Cobertura con CAND-01;CAND-02;CAND-03» → 3.187 (95,7 %), 177 Alta; comprobación correcta |
| **5** · `optimizar_despliegue`, `comparar_selecciones` y `consultar_edificios` | `tools.py` con `ETAPA = 5` | 7 | «¿Dónde pongo 3 retenes?» → CAND-01, 02 y 03; ponderada 94,7 %; a 15 min, CAND-02, 03 y 10 |
| **6** · `perfil_meteorologico` y contexto/referencias | `tools.py` con `ETAPA = 6` | 9 | «¿Cuándo activarlos?» → unos 26,3 días al año; feb–abr 32 %, sep–oct 31 %, jul–ago 14 %; zonas no distinguibles |
| **7** · `generar_informe` y mapas | `mapas.py` y `tools.py` con `ETAPA = 7` | 10 | «Genera el informe con 3 retenes» → HTML de unos 262 KB; después, comprobar con el manifiesto |

Las pruebas confirman que el agente funciona tras cada paso solo con los archivos de ese paso (`test_despliegue_por_pasos_queda_ejecutable[1-7]`).

## 4. Pruebas
Se ejecutan desde `ws_final`: `cd ws_final && python -m pytest -q tests_final` (la carpeta de trabajo es la raíz, como en la plataforma).
- **Resultado:** **68 correctas** con pandas 3.0 y langchain 1.4. Con pandas 2.2.3 y numpy 2.1, parecido a Pyodide 0.27, **66 correctas y 2 omitidas** (las 2 necesitan langchain).
- **Qué cubren:**
  - **Cifras esperadas:** todas las filas de `valores_esperados_optimizador.csv` (A, ligero, 12 y 15 min, k = 0 a 6) y las 49 / 177 viviendas Alta.
  - **Recuentos y meteorología:** las clases y sus viviendas, 26,3 días, 14 / 32 / 31 % y Bera–Aiako Harria.
  - **Referencias:** FireScope (93 / 7 %) e incendios previos.
  - **Ponderaciones antiguas:** coinciden con `escenarios.csv` en las 3 (uniforme, meteo y firescope).
  - **Paquete:** como máximo 10 herramientas, que existan los archivos de `STUDIO_CONTEXT_FILES`, como máximo 4 MB por archivo, ningún import prohibido, y el HTML como máximo de 2 MB y sin recursos externos.
  - **Funcionamiento:** una llamada de humo a cada herramienta con los valores por defecto, los errores de entrada, el agente construido con un modelo falso y el sub-agente.

## 5. Riesgos y decisiones abiertas
- **`escenarios.csv` no tiene la ponderación «prioridad».** No es imprescindible, porque el agente calcula en vivo y `comprobar_cifra` recalcula. Si Persona 2 la añade, la comparación se activa sola.
- **Las selecciones son robustas:** con k = 3, las 4 ponderaciones eligen CAND-01, 02 y 03. Con k = 4, la ponderación «prioridad» elige CAND-05 y las otras 3 eligen CAND-04, que es casi un empate (3.216 edificios y 183 Alta frente a 3.217 y 184).
- **Paso 2:** el prompt nombra herramientas que todavía no existen hasta el paso 7. Si el modelo intenta llamarlas, recibe un error de herramienta. Para evitarlo, se puede subir `instrucciones.py` junto con el paso 3.
- **No se han creado `RESULTADOS.md` ni `PRUEBAS.md` del agente.** Si se crean, hay que añadirlos a `STUDIO_CONTEXT_FILES`.
- **Tamaño de las salidas:** las listas tienen un máximo de 50 filas por llamada. Las salidas por defecto ocupan como máximo unos 10.000 caracteres (`consultar_edificios`, con `limite=15`, unos 9.200).

## 6. Revisión del juez (91/100) · correcciones aplicadas
1. **Mínimo de retenes (`objetivo_pct`).**
   - Antes, el mínimo se leía en la curva de la estrategia A.
   - Ahora, para cada k, se buscan en **todas las combinaciones** (848) las que maximizan la métrica elegida («edificios», «alta» o «ponderada»).
   - La salida da la selección, el valor, la curva `curva_mejor_por_k` y `maximo_alcanzable_pct`, calculado del mismo modo.
   - La estrategia ya no influye en el mínimo.
   - Resultados con la métrica «alta» (12 min, ligero):

     | Objetivo | Resultado |
     |---|---|
     | 80 % | k = 6 (con k = 5, 194/243 = 79,8 %) |
     | 82 % | k = 6, con CAND-01, 02, 03, 04, 05 y 10: 200/243 = 82,3 % (antes salía «no alcanzado») |
     | 85 % | no se alcanza: el máximo es 82,3 % |

   - El máximo de viviendas Alta con k = 4 es 187.
2. **Listas recortadas a 50 filas:** `limite` en `consultar_prioridad` y `consultar_edificios`, y `top_dias` en `perfil_meteorologico`.
   Si se pide más, la salida lo dice con `lista_truncada` y explica cómo ver el resto: con filtros o con `ejecutar_codigo`.
   Las salidas por defecto ocupan como máximo unos 10.000 caracteres.
3. **`instrucciones.py`:** la pregunta «¿Qué Alta quedan fuera con N retenes?» ahora se responde con `consultar_edificios(prioridad='Alta', k=N)`. Con k = 3 quedan 32 fuera con ruta y 34 sin ruta.
4. **`comprobar_cifra`:** `k = -1` significa «no indicado» y se usa 3, igual que en las otras herramientas.
5. **Etiquetas:**
   - el municipio ya no se repite en las candidatas ni en los parques: «Aparcamiento sin nombre (Amezketa)»;
   - la ponderación `meteo` se etiqueta como «legado jul-ago, solo sensibilidad».

**Pruebas nuevas:**
- el contraejemplo del juez, comprobado por fuerza bruta: 187 Alta con k = 4 y 200 con k = 6;
- el máximo por métrica frente a las curvas de A y B;
- el recorte de las listas y el tamaño de las salidas;
- `comprobar_cifra(k=-1)`, las etiquetas y el ejemplo del prompt.
