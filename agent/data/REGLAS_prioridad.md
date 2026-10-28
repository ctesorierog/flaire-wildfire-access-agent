# Reglas de la prioridad territorial (Persona 1) · PRIO-v1

> **Qué es:** una **prioridad de planificación** para ordenar qué viviendas del borde forestal conviene revisar o proteger primero.
> **Qué NO es:** no predice incendios, no es una probabilidad de incendio y no mide el riesgo real de una casa concreta.

## Ámbito
- **Piloto:** Tolosaldea, 28 municipios (límites oficiales de geoEuskadi).
- **Conjunto de análisis:** 3.331 edificios **residenciales** (uso en B5M) a **≤ 100 m** de bosque o matorral (Mapa Forestal del País Vasco 2024), con 10.651 viviendas.
- **Fuera del conjunto** quedan los edificios no residenciales, los que tienen uso desconocido y los que están a más de 100 m.
  Hay 252 edificios con nombre de caserío y uso desconocido a ≤ 100 m. **No entran**, pero si fueran viviendas, 70 serían de prioridad Alta.

## Componentes y puntos
| Componente | Regla | Puntos |
|---|---|---|
| 1 · Distancia a la vegetación | dentro o 0–25 m = 3 · 25–50 m = 2 · 50–100 m = 1 | 1–3 |
| 2 · Tipo de vegetación más cercana | nivel 3 (matorral, plantación de coníferas, eucalipto) = 2 · nivel 2 (masas mixtas, plantación de frondosas) = 1 · nivel 1 (frondosa natural, bosque de galería, conífera natural) = 0 | 0–2 |
| 3 · Acceso actual en vehículo ligero desde el parque más cercano (9 parques, 0 retenes extra) | > 15 min o sin ruta = 3 · 12–15 = 2 · 8–12 = 1 · ≤ 8 = 0 | 0–3 |
| 4 · Meteorología histórica | 0 para todos: las zonas no se distinguen con los datos de 2018–2023 | 0 |

- **Clases:** **Alta ≥ 6** · **Media 4–5** · **Baja ≤ 3**.
- **Pesos:** `peso_prioridad` (Alta = 3, Media = 2, Baja = 1, divididos por la media para que la media sea 1) sirve para el ranking y los mapas.
- **Peso del optimizador:** `peso_optimizador` es igual, pero **sin el componente de acceso**, porque el optimizador ya mide el acceso. Así no se cuenta dos veces.

## Cifras clave (ver `cifras_clave_persona1.json`)
- **Clases:** Alta 243 (283 viviendas) · Media 961 · Baja 2.127.
- **Dónde están las Alta:** Asteasu 43, Amezketa 35 y Abaltzisketa 28 (el 32 % del municipio).
- **Alta sin ruta por carretera:** 34. Ningún retén las mejora: necesitan otra medida, como el acceso o la autoprotección.
- **Con 3 retenes** (CAND-01 Asteasu, CAND-02 Amezketa y CAND-03 Berastegi), las viviendas Alta a ≤ 12 min pasan de **49 a 177**.

## Meteorología (todo el año)
- **Dos reglas exploratorias** (no son FWI): **calor seco** (Tmax ≥ 25 °C, HR ≤ 40 % y 3 días previos sin lluvia) y **viento sur seco**
  (≥ 3 h de viento del sur ≥ 3 m/s con HR ≤ 50 %, y 3 días previos sin lluvia).
- **Días de riesgo:** unos 26 al año. Julio y agosto solo tienen el **14 %**, febrero–abril el **32 %** y septiembre–octubre el **31 %**.
- **Las zonas no se distinguen.** Por eso la meteorología dice **cuándo**, no **dónde**: conviene activar los retenes en días de riesgo y no fijarlos en julio y agosto.
- **Comprobación:** la regla de viento sur detecta el incendio de Bera–Aiako Harria (19–21 de febrero de 2021).

## Referencias externas (no suman puntos)
- **FireScope (INSAIT):**
  - La puntuación va de 0 a 100 (`fs_puntuacion_0_100`), con la leyenda oficial: < 25 Seguro · 25–50 Bajo · 50–75 Moderado · ≥ 75 Alto.
  - En el conjunto de análisis, el 93 % es Bajo y el 7 % Moderado. Coincide en la tendencia (más alto en el sureste, en el Aralar), pero es demasiado suave para decidir vivienda a vivienda.
- **Incendios anteriores (capa de FireScope, aproximada):**
  - Dentro de Tolosaldea solo hay un incendio cartografiado: Amezketa 2019, unas 39 ha. Casi todo lo quemado está en Navarra.
  - Hay incendios de 2021 a 2026 a entre 0,45 y 1,6 km de viviendas Alta de Berastegi.

## Cómo debe hablar el agente
- **Siempre:** decir que es una prioridad de planificación, dar las cifras con su fuente y mencionar los límites que tengan que ver con la pregunta.
- **Nunca:**
  - hablar de «probabilidad de incendio» ni de «riesgo real» de una casa;
  - sumar FireScope a la prioridad;
  - inventar cifras de personal o de tiempos de respuesta reales.
- **Decisiones del equipo** (decirlo así): el umbral de 100 m, las bandas de distancia, los niveles de vegetación, los cortes de las clases y los umbrales meteorológicos.
- **Límites:**
  - los tiempos son estimados, con velocidades supuestas en el 85 % de las vías, y no son tiempos de respuesta;
  - solo hay 3 estaciones meteorológicas, todas de valle;
  - no hay parques de Navarra en el modelo;
  - el uso de B5M es desconocido en muchos edificios;
  - el tipo de vegetación no es un modelo de combustible.
