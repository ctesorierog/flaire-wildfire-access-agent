# Claim check · web app screenshots (27 Oct 2026, evening)

Screens (1920×1080 unless stated), all from the local web app (`app/`), model `claude-opus-5-5`:

| File | Shows | Slide |
| --- | --- | --- |
| `deck/screens/app_home.png` | Home: Abaltzisketa photo, headline, ask box, 81.4 % | 1 (photo [GAP]) or 3 |
| `deck/screens/app_map_today.png` | Map today, nothing asked yet | 2 ("today" map [GAP]) |
| `deck/screens/app_first_crew.png` | F1 answer + coverage bars + map relit at CAND-02 (+ F2 below) | 3 |
| `deck/screens/app_site_cand02.png` | Same, with the CAND-02 orthophoto callout open | 4 |
| `deck/screens/app_when_strip.png` (970×770 close-up) | F2 answer + 52-week risk strip | 5 ("summer" [GAP]) |

Raw run: `transcripts/chat_mvqptejlr3i2c.json` (F1 14.5 s, 4 tool calls; F2 9.2 s, 1 tool call). Every number on the screens was checked against the data, not the agent:

| Claim on screen | Checked against | Verdict |
| --- | --- | --- |
| Today 2,712 of 3,331 within 12 min, 81.4 %; "the other 619" | `map.json` rule pinned by `test_map_data.py` (2,712); 3,331 − 2,712 = 619 | ✓ |
| With CAND-02: +246, 2,958 (88.8 %) | same test (2,958); recomputed from `tiempos_ligero.csv` on 27 Oct (`docs/transcripts/2026-10-27_chat_screens.md`) | ✓ |
| Alta 49 → 119 of 243 | same test (49 / 119); 243 Alta in `edificios_prioridad.csv` | ✓ |
| "La mejor de las 10 candidatas, sin empate" | optimizer k = 1: next best CAND-01 = 2,837 | ✓ |
| Coverage bars 2,712 → 2,958 of 3,331; 49 → 119 of 243 | computed in the page from `map.json`, same rule | ✓ |
| CAND-02 "Usable: real car park", orthophoto, credit | 10.4 review in `fichas_candidatas_v03.md`; geoEuskadi credit on screen | ✓ |
| Risk day = dry heat or dry south wind; "unos 26 al año" (2018–2023) | paso3 rule; 26.3 (`cifras_clave_persona1.json`) / 26.4 (`weekly_calendar.json`, rounding) | ✓ |
| Feb–Apr 32 %, Sep–Oct 31 %, Jul–Aug 14 % (answer and strip caption) | `weekly_calendar.json`, pinned by `test_weekly_calendar.py` against `cifras_clave_persona1.json` | ✓ |
| Strip: 52 weeks, Jul–Aug outlined | `weekly_calendar.json` weeks with main month 7 or 8 | ✓ |

No soft or false claims in the visible text this time. The agent's wording varies run to run; the slides quote this run.

Licences on screen: the home photo carries «Abaltzisketa, Joxemai · CC BY-SA 4.0 · Wikimedia Commons» (bottom right); the CAND-02 callout carries the geoEuskadi credit. A slide that crops either credit away must add it in the footer.
How these were made: Playwright with a forced 1920×1080 CSS layout, captured at 4000–4800 px through the DevTools protocol and shrunk to 1920×1080 (never enlarged). The browser had a stuck page zoom, so normal screenshots came out 1280×720.
