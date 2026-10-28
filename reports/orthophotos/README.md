# Ortofotos de las candidatas CAND-01 a CAND-04

Comprobación sobre ortofoto de las candidatas (27 oct 2026). El resultado de cada sitio está en una línea «Ortofoto» de `../fichas_candidatas_v03.md`.

- **Fuente:** geoEuskadi, servicio WMS de ortofotos `https://www.geo.euskadi.eus/WMS_ORTOARGAZKIAK`, capa `ORTO_2025`. Descargadas el 27 oct 2026.
- **Licencia:** uso permitido con la mención de autoría «Eusko Jaurlaritza / Gobierno Vasco. geoEuskadi» (condiciones de acceso del propio servicio, GetCapabilities). Cualquier diapositiva que use estas imágenes debe llevar esa mención.
- **Qué muestra cada imagen:** 120 × 120 m centrados en el punto de la candidata (coordenadas de `agent/data/candidatos.csv`, EPSG:25830), 800 × 800 px (0,15 m/px). Cruz roja = punto de la candidata; barra amarilla = 20 m. La cruz y la barra se añadieron después de la descarga.
- **Cómo repetirlo:** una petición GetMap por sitio:
  `https://www.geo.euskadi.eus/WMS_ORTOARGAZKIAK?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&LAYERS=ORTO_2025&STYLES=&CRS=EPSG:25830&BBOX=<x-60>,<y-60>,<x+60>,<y+60>&WIDTH=800&HEIGHT=800&FORMAT=image/jpeg`

| Imagen | Sitio | Resultado |
| --- | --- | --- |
| `CAND-01_120m.jpg` | Casa Camineros, Asteasu | ✗ solo la casa, sin patio ni aparcamiento |
| `CAND-02_120m.jpg` | Aparcamiento, Amezketa | ✓ aparcamiento asfaltado real |
| `CAND-03_120m.jpg` | Aparcamiento, Berastegi | ✓ aparcamiento asfaltado real |
| `CAND-04_120m.jpg` | Insalus agua, Lizartza | ~ patio de planta privada, ocupado por palés |
