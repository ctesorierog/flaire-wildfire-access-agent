# RESULTADOS · respuesta de referencia

Generado el 2026-10-02 con `tests/generar_docs.py` desde `datos/` (las mismas funciones que usan las herramientas del agente).
Si cambian los datos, se regenera: no edite las cifras a mano.

## Pregunta principal
«Para julio–agosto 2027, ¿cómo conviene distribuir hasta N retenes adicionales en Tolosaldea y qué mejora aporta cada uno?»

Destinatario: técnico de planificación de Bomberos / Protección Civil (DFG). Ámbito: 3.331 edificios residenciales a ≤100 m de bosque
o matorral en los 28 municipios; 9 parques existentes; 10 lugares candidatos de estudio. Basado en 4 temporadas
históricas (2019, 2020, 2022, 2023). El año 2027 es una etiqueta: no cambia ninguna cifra.

**Criterio principal:** estrategia A (máxima cobertura ponderada con pesos históricos ADV-v1) dentro de **12 min** (umbral de
demostración, no oficial), vehículo ligero. **Criterio alternativo:** estrategia B (primero menos edificios sin ruta, después
menor peor tiempo).

### Respuesta de referencia (N = 3)
- **Hallazgo:** con 3 retenes en CAND-01, CAND-02, CAND-03 los edificios dentro de 12 min pasan de 2.712
  (81,4 %) a 3.187 (95,7 %): +475 edificios;
  la cobertura ponderada pasa de 78,8 % a 95,0 %; el peor tiempo estimado de 20,5
  a 17,4 min.
- **Aporte de cada retén (A):** k=1: +246; k=2: +104; k=3: +125; k=4: +30; k=5: +29; k=6: +21 edificios.
- **Evidencia:** enumeración exhaustiva en vivo (848 combinaciones), idéntica a `datos/escenarios.csv`
  (sí); recalculo independiente (`comprobar_cifra`) coincide.
- **Límite / pendiente:** 47 edificios sin ruta (a > 150 m de la red) siguen fuera en todos los casos; tiempos = estimaciones de
  desplazamiento; las candidatas necesitan validación de campo (espacio, titularidad, acceso de camión, agua, tráfico, ortofoto).

### Estrategia A · 12 min · ligero · pesos históricos
| k | Retenes (municipio) | Edificios dentro | % dentro | % ponderada | Peor tiempo (min) | Sin ruta | +edif. vs k-1 | Reutiliza k-1 | Empates |
|---|---|---|---|---|---|---|---|---|---|
| 0 | — | 2.712 | 81,4 | 78,8 | 20,5 | 47 |  |  | 1 |
| 1 | CAND-02 (Amezketa) | 2.958 | 88,8 | 87,8 | 20,5 | 47 | +246 | sí | 1 |
| 2 | CAND-02 (Amezketa), CAND-03 (Berastegi) | 3.062 | 91,9 | 91,9 | 20,5 | 47 | +104 | sí | 1 |
| 3 | CAND-01 (Asteasu), CAND-02 (Amezketa), CAND-03 (Berastegi) | 3.187 | 95,7 | 95,0 | 17,4 | 47 | +125 | sí | 1 |
| 4 | CAND-01 (Asteasu), CAND-02 (Amezketa), CAND-03 (Berastegi), CAND-04 (Lizartza) | 3.217 | 96,6 | 96,2 | 17,4 | 47 | +30 | sí | 1 |
| 5 | CAND-01 (Asteasu), CAND-02 (Amezketa), CAND-03 (Berastegi), CAND-04 (Lizartza), CAND-05 (Bidania-Goiatz) | 3.246 | 97,5 | 97,2 | 17,4 | 47 | +29 | sí | 1 |
| 6 | CAND-01 (Asteasu), CAND-02 (Amezketa), CAND-03 (Berastegi), CAND-04 (Lizartza), CAND-05 (Bidania-Goiatz), CAND-08 (Anoeta) | 3.267 | 98,1 | 97,9 | 15,2 | 47 | +21 | sí | 1 |

### Estrategia B · 12 min · ligero · pesos históricos
| k | Retenes (municipio) | Edificios dentro | % dentro | % ponderada | Peor tiempo (min) | Sin ruta | +edif. vs k-1 | Reutiliza k-1 | Empates |
|---|---|---|---|---|---|---|---|---|---|
| 0 | — | 2.712 | 81,4 | 78,8 | 20,5 | 47 |  |  | 1 |
| 1 | CAND-01 (Asteasu) | 2.837 | 85,2 | 82,0 | 18,9 | 47 | +125 | sí | 1 |
| 2 | CAND-02 (Amezketa), CAND-10 (Zizurkil) | 3.077 | 92,4 | 90,9 | 17,0 | 47 | +240 | no | 1 |
| 3 | CAND-02 (Amezketa), CAND-03 (Berastegi), CAND-10 (Zizurkil) | 3.181 | 95,5 | 95,0 | 16,6 | 47 | +104 | sí | 1 |
| 4 | CAND-02 (Amezketa), CAND-03 (Berastegi), CAND-04 (Lizartza), CAND-10 (Zizurkil) | 3.211 | 96,4 | 96,2 | 15,7 | 47 | +30 | sí | 1 |
| 5 | CAND-01 (Asteasu), CAND-02 (Amezketa), CAND-03 (Berastegi), CAND-04 (Lizartza), CAND-06 (Villabona) | 3.229 | 96,9 | 96,5 | 14,7 | 47 | +18 | no | 1 |
| 6 | CAND-01 (Asteasu), CAND-02 (Amezketa), CAND-03 (Berastegi), CAND-04 (Lizartza), CAND-06 (Villabona), CAND-07 (Orendain) | 3.229 | 96,9 | 96,5 | 14,6 | 47 | +0 | sí | 1 |

### ¿Por qué A y B eligen sitios distintos? (k = 3)
A: CAND-01, CAND-02, CAND-03 · B: CAND-02, CAND-03, CAND-10.
Solo en A: CAND-01 (Asteasu, 305 edificios dentro atendidos primero).
Solo en B: CAND-10 (Zizurkil, 524).
A deja dentro 3.187 edificios y peor tiempo 17,4 min;
B 3.181 y 16,6 min. A busca muchos edificios justo por encima del
umbral; B gasta retenes en los edificios más alejados aunque sean pocos.
**Fragilidad de B:** su peor tiempo lo fija un solo edificio (ES.GFA.BU.41377); la segunda mejor combinación de B
(CAND-02, CAND-03, CAND-06) tiene peor tiempo
16,55 min frente a 16,55: cuando empatan en peor tiempo decide la
cobertura ponderada. Por eso se informa también el **p95** del tiempo (más estable). Con pesos históricos, A y B a k = 3 difieren
en 1,49 unidades de cobertura ponderada.

### El retén nº 3 (A)
Pasa de CAND-02, CAND-03 a CAND-01, CAND-02, CAND-03 (anidado).
Gana 125 edificios (pierde 0): Asteasu 78, Larraul 25, Zizurkil 12, Alkiza 10. Siguen fuera con ruta 97
(Zizurkil 6, Alkiza 19, Orexa 24, Bidania-Goiatz 22, Albiztur 9, Tolosa 8, Lizartza 6, Aduna 2, Villabona 1) y 47 sin ruta.

## Variación 1 · umbral 15 min (A, ligero)
| k | Retenes (municipio) | Edificios dentro | % dentro | % ponderada | Peor tiempo (min) | Sin ruta | +edif. vs k-1 | Reutiliza k-1 | Empates |
|---|---|---|---|---|---|---|---|---|---|
| 0 | — | 3.148 | 94,5 | 94,2 | 20,5 | 47 |  |  | 1 |
| 1 | CAND-02 (Amezketa) | 3.209 | 96,3 | 96,3 | 20,5 | 47 | +61 | sí | 1 |
| 2 | CAND-02 (Amezketa), CAND-10 (Zizurkil) | 3.271 | 98,2 | 97,9 | 17,0 | 47 | +62 | sí | 1 |
| 3 | CAND-02 (Amezketa), CAND-03 (Berastegi), CAND-10 (Zizurkil) | 3.280 | 98,5 | 98,2 | 16,6 | 47 | +9 | sí | 1 |
| 4 | CAND-02 (Amezketa), CAND-03 (Berastegi), CAND-04 (Lizartza), CAND-10 (Zizurkil) | 3.283 | 98,6 | 98,3 | 15,7 | 47 | +3 | sí | 1 |
| 5 | CAND-01 (Asteasu), CAND-02 (Amezketa), CAND-03 (Berastegi), CAND-04 (Lizartza), CAND-06 (Villabona) | 3.284 | 98,6 | 98,4 | 14,7 | 47 | +1 | no | 1 |
| 6 | CAND-01 (Asteasu), CAND-02 (Amezketa), CAND-03 (Berastegi), CAND-04 (Lizartza), CAND-06 (Villabona), CAND-07 (Orendain) | 3.284 | 98,6 | 98,4 | 14,6 | 47 | +0 | sí | 1 |

## Variación 2 · camión (A, 12 min)
| k | Retenes (municipio) | Edificios dentro | % dentro | % ponderada | Peor tiempo (min) | Sin ruta | +edif. vs k-1 | Reutiliza k-1 | Empates |
|---|---|---|---|---|---|---|---|---|---|
| 0 | — | 2.177 | 65,4 | 61,8 | 25,0 | 47 |  |  | 1 |
| 1 | CAND-02 (Amezketa) | 2.500 | 75,0 | 73,7 | 25,0 | 47 | +323 | sí | 1 |
| 2 | CAND-02 (Amezketa), CAND-08 (Anoeta) | 2.785 | 83,6 | 81,5 | 21,3 | 47 | +285 | sí | 1 |
| 3 | CAND-02 (Amezketa), CAND-03 (Berastegi), CAND-08 (Anoeta) | 2.937 | 88,2 | 87,4 | 21,3 | 47 | +152 | sí | 1 |
| 4 | CAND-02 (Amezketa), CAND-03 (Berastegi), CAND-05 (Bidania-Goiatz), CAND-08 (Anoeta) | 3.072 | 92,2 | 92,2 | 21,3 | 47 | +135 | sí | 1 |
| 5 | CAND-02 (Amezketa), CAND-03 (Berastegi), CAND-04 (Lizartza), CAND-05 (Bidania-Goiatz), CAND-08 (Anoeta) | 3.123 | 93,8 | 94,2 | 21,3 | 47 | +51 | sí | 1 |
| 6 | CAND-01 (Asteasu), CAND-02 (Amezketa), CAND-03 (Berastegi), CAND-04 (Lizartza), CAND-05 (Bidania-Goiatz), CAND-08 (Anoeta) | 3.191 | 95,8 | 95,8 | 18,6 | 47 | +68 | sí | 1 |

## Sensibilidad · pesos uniformes frente a históricos (A, 12 min, ligero)
Selecciones distintas en k = [2]. Las diferencias son casi empates: los pesos de las zonas solapan dentro de ±1 sd
(sí), así que A con pesos ≈ A contando edificios.
| k | Retenes (municipio) | Edificios dentro | % dentro | % ponderada | Peor tiempo (min) | Sin ruta | +edif. vs k-1 | Reutiliza k-1 | Empates |
|---|---|---|---|---|---|---|---|---|---|
| 0 | — | 2.712 | 81,4 | 81,4 | 20,5 | 47 |  |  | 1 |
| 1 | CAND-02 (Amezketa) | 2.958 | 88,8 | 88,8 | 20,5 | 47 | +246 | sí | 1 |
| 2 | CAND-01 (Asteasu), CAND-02 (Amezketa) | 3.083 | 92,5 | 92,5 | 17,4 | 47 | +125 | sí | 1 |
| 3 | CAND-01 (Asteasu), CAND-02 (Amezketa), CAND-03 (Berastegi) | 3.187 | 95,7 | 95,7 | 17,4 | 47 | +104 | sí | 1 |
| 4 | CAND-01 (Asteasu), CAND-02 (Amezketa), CAND-03 (Berastegi), CAND-04 (Lizartza) | 3.217 | 96,6 | 96,6 | 17,4 | 47 | +30 | sí | 1 |
| 5 | CAND-01 (Asteasu), CAND-02 (Amezketa), CAND-03 (Berastegi), CAND-04 (Lizartza), CAND-05 (Bidania-Goiatz) | 3.246 | 97,5 | 97,5 | 17,4 | 47 | +29 | sí | 1 |
| 6 | CAND-01 (Asteasu), CAND-02 (Amezketa), CAND-03 (Berastegi), CAND-04 (Lizartza), CAND-05 (Bidania-Goiatz), CAND-08 (Anoeta) | 3.267 | 98,1 | 98,1 | 15,2 | 47 | +21 | sí | 1 |

## Robustez · tres ponderaciones (A, 12 min, ligero)
Con pesos **históricos** (Euskalmet, regla ADV-v1), **uniformes** y **FireScope** (índice de riesgo de incendio de un modelo de IA de
terceros, INSAIT, CVPR 2026, CC BY 4.0 · experimental) las selecciones de la estrategia A coinciden para todo k ≥ 3.
Difieren solo en k = [2]. FireScope varía más dentro del territorio (Aralar/Amezketa alto,
fondo de valle bajo) aunque separa menos las 3 zonas meteorológicas; su correlación con el peso histórico es positiva: dos fuentes distintas (observación y modelo de IA) apuntan en la misma dirección,
y la recomendación de DÓNDE colocar los retenes no depende de qué ponderación se elija.
| k | Retenes (municipio) | Edificios dentro | % dentro | % ponderada | Peor tiempo (min) | Sin ruta | +edif. vs k-1 | Reutiliza k-1 | Empates |
|---|---|---|---|---|---|---|---|---|---|
| 0 | — | 2.712 | 81,4 | 75,9 | 20,5 | 47 |  |  | 1 |
| 1 | CAND-02 (Amezketa) | 2.958 | 88,8 | 87,1 | 20,5 | 47 | +246 | sí | 1 |
| 2 | CAND-01 (Asteasu), CAND-02 (Amezketa) | 3.083 | 92,5 | 91,4 | 17,4 | 47 | +125 | sí | 1 |
| 3 | CAND-01 (Asteasu), CAND-02 (Amezketa), CAND-03 (Berastegi) | 3.187 | 95,7 | 95,2 | 17,4 | 47 | +104 | sí | 1 |
| 4 | CAND-01 (Asteasu), CAND-02 (Amezketa), CAND-03 (Berastegi), CAND-04 (Lizartza) | 3.217 | 96,6 | 96,3 | 17,4 | 47 | +30 | sí | 1 |
| 5 | CAND-01 (Asteasu), CAND-02 (Amezketa), CAND-03 (Berastegi), CAND-04 (Lizartza), CAND-05 (Bidania-Goiatz) | 3.246 | 97,5 | 97,2 | 17,4 | 47 | +29 | sí | 1 |
| 6 | CAND-01 (Asteasu), CAND-02 (Amezketa), CAND-03 (Berastegi), CAND-04 (Lizartza), CAND-05 (Bidania-Goiatz), CAND-08 (Anoeta) | 3.267 | 98,1 | 97,8 | 15,2 | 47 | +21 | sí | 1 |

## ¿Por qué julio–agosto si el pico histórico es septiembre?
Julio–agosto es el periodo de planificación del dispositivo preventivo de verano que pide el usuario. Para decidir **dónde**
colocar los retenes la temporada apenas influye: los tiempos por carretera no dependen de la estación y los pesos históricos son
casi planos (pesos uniformes solo cambian la selección en k = [2]). La estacionalidad (septiembre como pico de días
adversos en la mayoría de zonas) cambia **cuándo** conviene tener desplegados los retenes, no dónde. El agente muestra los
recuentos mensuales con `perfil_meteorologico` para apoyar esa decisión humana.

## Menor número de retenes para llegar al 95 % (A, 12 min, % de edificios)
Alcanzado con k = 3 (CAND-01, CAND-02, CAND-03): 95,7 %.
Es un mínimo dentro del modelo y de las candidatas, no una dotación operativa.

## Perfil meteorológico (ADV-v1, julio–agosto)
| Zona | Años | Días válidos | Días adversos | Frecuencia | sd interanual | Peso | Edificios | Mes pico (todo el año) |
|---|---|---|---|---|---|---|---|---|
| C026 Berastegi | 2019;2020;2022;2023 | 248 | 21 | 0,0847 | 0,0358 | 1,302 | 864 | 9 |
| C029 Zizurkil | 2019;2020;2022;2023 | 248 | 13 | 0,0524 | 0,0358 | 0,806 | 1.880 | 9 |
| C058 Bidania | 2019;2020;2022;2023 | 235 | 18 | 0,0766 | 0,0230 | 1,178 | 587 | 9 |

Intervalos ±1 sd solapan: sí → pesos casi planos. Julio–agosto no es el pico de días adversos (ver la sección anterior).

## Límite (pregunta que el agente no debe responder con cifras inventadas)
- «¿Cuántos bomberos necesito?» → no hay datos de dotación, turnos ni intervenciones; el agente lo dice y ofrece `minimo_retenes`.
- «¿Y en septiembre?» → solo julio–agosto está precalculado; muestra los recuentos mensuales históricos (septiembre es el pico en
  3 de 3 zonas).
- «¿Y con 8 retenes?» → error controlado: máximo 6 y nunca más que las 10 candidatas.
- «¿Y Leitza?» → fuera de ámbito (Navarra): ni edificios ni parques navarros; la red sí incluye carreteras navarras.

## Cifra comprobada contra los datos
2712 edificios dentro de 12 min sin refuerzo (recalculado leyendo `datos/tiempos_ligero.csv` con pandas) =
2712 (motor) = `escenarios.csv`. Edificio para comprobar a mano: `ES.GFA.BU.44893`
(Asteasu): mínimo k=0 17,10 min → con la selección 0,49 min.
