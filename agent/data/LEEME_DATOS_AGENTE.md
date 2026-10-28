# Datos del agente flAIre · carpeta completa (3 de octubre de 2026)

Esta carpeta es **todo lo que el agente necesita leer**: 19 archivos de datos y documentación, 2,2 MB en total, ninguno de más de 1,1 MB.
Sustituye **por completo** a la carpeta `agentes/flaire/datos/` actual.
Antes de subirla, ejecuta `python check_datos_agente.py`: debe decir **OK**.

## 1. Inventario
| Archivo | Responsable | Filas | Para qué |
|---|---|---|---|
| `edificios_prioridad.csv` | Persona 1 | 3.331 | Las viviendas: prioridad, puntos, motivo, pesos, tiempo actual, FireScope e incendios |
| `municipios.csv` + `municipios.geojson` | Persona 1 | 28 | Resumen por municipio y mapa |
| `meteo_mensual.csv` · `meteo_anual.csv` · `meteo_dias_riesgo.csv` · `meteo_test_zonas.csv` · `meteo_estaciones.csv` | Persona 1 | — | Meteorología de todo el año (calor seco y viento sur) |
| `incendios_previos.csv` | Persona 1 | 98 | Incendios cartografiados de 2018 a 2026 (referencia aproximada) |
| `cifras_clave_persona1.json` | Persona 1 | — | Las cifras listas para citar |
| `tiempos_ligero.csv` · `tiempos_camion.csv` | Persona 2 | 3.331 × 19 orígenes | Minutos estimados desde cada parque y candidata |
| `parques.csv` · `candidatos.csv` | Persona 2 | 10 · 10 | Orígenes: 9 parques en la base y 10 sitios de estudio |
| `escenarios.csv` | Persona 2 | 252 | Resultados del optimizador ya calculados (A/B × k 0–6 × 10/12/15 min × ligero/camión × 3 pesos) |
| `fuentes.csv` | los dos | 19 | Fuentes, licencias y fechas, con columna `responsable` |
| `metodologia.csv` | los dos | 38 | Parámetros y reglas (clave / valor / explicación), actualizado con la prioridad y la meteorología de todo el año |
| `REGLAS_prioridad.md` · `DICCIONARIO_datos.md` | los dos | — | Reglas, columnas y cómo debe hablar el agente |

## 2. Qué desaparece de la plataforma (y por qué)
| Archivo antiguo | Qué pasa |
|---|---|
| `edificios.csv` | Lo sustituye `edificios_prioridad.csv`. |
| `meteo_perfil.csv`, `meteo_dias_adversos.csv` | Eran solo de julio y agosto. Los sustituyen `meteo_mensual.csv` y `meteo_dias_riesgo.csv`. |
| `auditoria.json` | Era el recuento de filas de la v0.3.1. Lo sustituye `cifras_clave_persona1.json`; Persona 2 puede regenerarlo si lo quiere. |
| `fuentes.csv`, `metodologia.csv`, `meteo_mensual.csv`, `meteo_anual.csv`, `municipios.csv` | Se **sobrescriben** con las versiones nuevas, que tienen el mismo nombre. |

## 3. Cambios de nombre que el código del agente debe recoger
El código actual (`flaire_data.py`) lee `edificios.csv`. Con estos datos hay que cambiar estas columnas:

| Antes (`edificios.csv`) | Ahora (`edificios_prioridad.csv`) |
|---|---|
| `t_base_ligero`, `t_base_camion` | `t_base_ligero_min`, `t_base_camion_min` |
| `estado_ruta` («calculado» o «sin_ruta: snap>150m») | `sin_ruta` («sí» o «no») |
| `veg_clase_cercana` (inglés) | `vegetacion_cercana` (español) + `tipo_veg_nivel` |
| `peso_meteo`, `peso_firescope` | `peso_meteo_sensibilidad`, `peso_firescope_sensibilidad` (solo sensibilidad) |
| `freq_adversa`, `fs_indice`, `residencial_regla`, `snap_m` | eliminadas (se describen en `metodologia.csv` y `meteo_*`) |
| — | **nuevas:** `prioridad`, `peso_prioridad`, `peso_optimizador`, `motivo_prioridad`, `puntos_*`, `fs_puntuacion_0_100`, `fs_clase`, `banda_*`, `t_segundo_parque_ligero_min`, `dist_incendio_previo_aprox_m` |

En el optimizador, el peso recomendado es **`peso_optimizador`**, la prioridad sin acceso, para no contar el acceso dos veces.

## 4. Lo que todavía puede faltar (de Persona 2)
1. **`escenarios.csv` con la ponderación «prioridad»** (`peso_optimizador`). No es imprescindible, porque el optimizador del agente calcula en vivo, pero sirve para comprobar las cifras.
   Valores esperados: `data/priority/entrega_persona2/valores_esperados_optimizador.csv`.
2. **Si Persona 2 añade sitios nuevos** (por ejemplo, Aritzeta), cambian tres archivos: aparece una columna nueva en `tiempos_*.csv`, una fila nueva en `candidatos.csv` y hay que regenerar `escenarios.csv`.
   Se calcula con `rutas_flaire.py nuevo` (kit de rutas; no incluido en el repo público).
3. **Si Persona 2 cambia los tiempos,** hay que volver a generar `edificios_prioridad.csv`, porque el componente de acceso depende de ellos.
   El script es `pipeline/priority/datos_agente_persona1.py` y después `datos_agente_completo.py`. Me lo dices y lo hago.

## 5. Cuándo subirlo
**Solo junto con el código nuevo del agente.** La v3 actual lee `edificios.csv` y los `meteo_*` antiguos: si los borras antes, deja de funcionar.

Orden:
1. Mover a la papelera los archivos antiguos de `agentes/flaire/datos/` (se pueden recuperar).
2. Subir esta carpeta.
3. Actualizar `STUDIO_CONTEXT_FILES` en `main.py`.
4. Pasar *Comprobar preparación* y crear una versión nueva.
