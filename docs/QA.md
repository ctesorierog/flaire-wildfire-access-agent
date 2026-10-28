# Q&A drill (PLAN 10.8)

Twenty questions for after the 2-minute talk: P1–P10 from a Diputación wildfire planner (planner-critic), M1–M10 from an MIT City Science researcher (mit-researcher-critic), ordered by danger within each set. Each one has the answer to say out loud (1–3 sentences), the trap to avoid, and the evidence behind it.

Every number below comes from one read-only script. Re-run it before the talk:

```
conda run -n flaire python pipeline/qa_evidence.py
```

Its output (27 Oct 2026) is pasted at the end as blocks **E1–E9**. Each answer names the block it rests on. A few facts come from files outside the script; for those, the file and line are given.

---

## Planner questions

**P1. "At SPEIS's own 15-minute target you already reach 94.5 %. Why pick 12 and show a big gain?"**
- Say: "You're right, at 15 minutes it's 94.5 % today and 98.5 % with three crews, so the gain shrinks as the line moves. We show 12 because the gaps are clearest there, and the two sites we defend win at 10, 12 and 15. Your target is under 15 minutes, met in 83 % of 2025 call-outs across all incident types."
- Trap: "12 is stricter on purpose" and nothing after it. Show all three thresholds.
- Evidence: E1 (light 10/12/15 rows). SPEIS target: SPEIS *Memoria anual 2025*, p. 35.

**P2. "Your 95.7 % needs Casa Camineros (CAND-01). What's left without it?"**
- Say: "Amezketa and Berastegi plus CAND-10 reach 3,181 buildings instead of 3,187, a 6-building difference. So CAND-01 isn't what the result depends on, and the third site is your call."
- Trap: defending CAND-01, or adding "under every weighting".
- Evidence: E1, light 12 min row: pick 01+02+03 = 3,187, runner-up 02+03+10 = 3,181, margin 6.

**P3. "Bajo and Alto Deba are near 65 %. Why Tolosaldea? And your provincial file says 82.3 %, not 81.4 %."**
- Say: "Tolosaldea isn't the worst comarca. It's 4th of 7, and we started there because it was the hackathon's area. The 82.3 % includes Legorreta, which is in the comarca but not in our 28-municipality study area: take out its 196 buildings and you get exactly 2,712 of 3,331, 81.4 %. The Deba valleys may look worse than they are, because we have no Bizkaia stations; we haven't tested how much."
- Trap: improvising the gap, or claiming Tolosaldea is the worst.
- Evidence: E2 (comarca table, the Legorreta split, the "No stations outside Gipuzkoa" limit).

**P4. "A retén patrols; it isn't parked waiting. What do your 12 minutes measure?"**
- Say: "They measure the estimated driving time from a fixed base, not a response time. The sites are study points, not authorised bases: nobody has checked shelter, water, turning space, radio or landowner permission. Each site record lists six field checks still to do."
- Trap: "it's like adding a station."
- Evidence: `reports/fichas_candidatas_v03.md:7` ("Ser candidata no significa estar autorizada ni validada… 6 comprobaciones pendientes de campo"). E2 limits ("not response time (no turnout)").

**P5. "Most road speeds are assumed and there's no turnout time. Why believe a 12-minute line?"**
- Say: "Believe it as a comparison, not as a stopwatch. We ran 12 end-to-end checks with separate code, four of them on routes, and all 12 match. But nobody has driven them. As a sanity check, Parque de Oria's real mean outward trip in 2025 was 10.2 minutes over 640 call-outs, but that's a park-wide average, not validation."
- Trap: calling the 10.2 min "validation".
- Evidence: E8 ("Hand checks: 12/12 match"). `reports/linker_validation.md:373` (§7, "end to end, independent code paths": 4 `H-route-*`, the rest baseline, brute-force and optimizer checks). SPEIS *Memoria anual 2025*, p. 40.

**P6. "My crews drive pickups, the parks drive heavy engines. Which vehicle is your answer for?"**
- Say: "The 95.7 % is light vehicles. With trucks, today is 65.4 % within 12 minutes and three crews take it to 88.2 %. The third site changes to CAND-08, and Amezketa and Berastegi are still in."
- Trap: quoting 95.7 % for every vehicle.
- Evidence: E1, truck 12 min row: 2,177 (65.4 %) → 2,937 (88.2 %), pick 02+03+08, margin 17.

**P7. "Why your own risk-day rule and not FWI? Did it ever match a real fire?"**
- Say: "It's a simple weather rule (dry heat or dry south wind) on three Euskalmet stations, 2018–2023. It isn't FWI and it isn't fire probability, and we haven't checked it against fire records. It only tells you when the weather was risky, and only 14 % of those days fall in July–August."
- Trap: calling it "fire risk".
- Evidence: E4 (rule, years, Jul–Aug 0.138, limits).

**P8. "Which buildings? Sheds, farmhouses? And are those 'homes' people?"**
- Say: "They're 3,331 residential buildings in the official cadastre (B5M) within 100 m of forest or scrub in the 2024 Forest Map. That's buildings, not people: they hold 10,651 dwellings. Forty-seven have no road route at all, 34 of them high-priority, so 'Alta 49 → 177' is out of the 209 we can reach."
- Trap: "homes" with no denominator, or "people protected".
- Evidence: E3 (3,331, 10,651 dwellings, 47 no route, 34 Alta, 209 reachable, Alta 49 today). Alta 177 with 3 crews: `tests/test_map_data.py` (pinned, passing).

**P9. "Amezketa and Berastegi border Navarra. Did you count Navarra's resources?"**
- Say: "No. Navarra's roads are in the network, but its stations aren't origins, because we have no official data on them. So border villages may look worse than they are. Not modelled doesn't mean absent."
- Trap: "they don't cross the border."
- Evidence: E2 limit ("No stations outside Gipuzkoa"). `reports/linker_validation.md` §0 ("Navarra parks are not origins (no official data)").

**P10. "Who reruns this next March when the Forest Map or the roads change?"**
- Say: "Today one person, from raw data, with a rebuild test that pins the headline numbers. It isn't automated and it isn't handed over to anyone. That's exactly what a pilot with your team would decide."
- Trap: "it's automated."
- Evidence: Track A suite, `conda run -n flaire python -m pytest -q -p no:cacheprovider tests` → 71 passed with the pipeline rebuilt from raw; 64 passed and 11 skipped on a fresh clone (28 Oct).

## Researcher questions

**M1. "If I delete the chatbot, what can the planner no longer do?"**
- Say: "Nothing in the optimum changes. That comes from an exhaustive search, not from the LLM. What the agent adds is the conversation: 'what does the third crew add, who's still left out, show me the site', with every number from a tool call and a source and a limit next to it."
- Trap: "the AI optimizes the crews."
- Evidence: E6 (exhaustive, 848 combinations). The agent doesn't import `optimizer.py`: `tools.py` calls `flaire_data.py`, a separate numpy implementation of the same rule (Strategy A, same tie-break) that gives the same numbers (its `escenarios.csv` at k = 3 matches E1). Say "same rule, checked twice", not "the same code".

**M2. "Has any of this been checked against real fires or response records?"**
- Say: "Not against fires: 92 of the 98 past fires in our dataset are in Navarra and the source is undocumented, so we chose not to overlay them. Inside the model, 12 of 12 end-to-end checks with separate code match, four of them on routes. Oria's 10.2-minute average is a sanity reference only."
- Trap: calling anything "validated".
- Evidence: FireScope's "Previous Wildfires" layer (92 of 98 pieces in Navarra; not published here: no licence). E8 (12/12). SPEIS *Memoria anual 2025*, p. 40.

**M3. "You picked candidate sites from the uncovered clusters. Isn't 95.7 % built in?"**
- Say: "Partly, yes. The sites come from clustering the 572 reachable buildings over 12 minutes, so they're built to fix those gaps. The rule never uses the optimizer's objective, though. Our claim is narrower than 95.7 %: Amezketa and Berastegi are picked under every threshold and vehicle, and the third site isn't stable."
- Trap: defending 95.7 % as a finding.
- Evidence: E7 (rule heading "no usa el objetivo del optimizador"; 619 over 12 min, 47 no route → 572, DBSCAN). E1 (02+03 in every pick).

**M4. "Your weighting is supposed to reflect fire weather. Does it change anything?"**
- Say: "Barely. In the priority score the weather term is zero for every building, so it's inert. The separate weather weights range only from 0.81 to 1.30 across three zones. They change the pick in 9 of 42 cases, by at most 80 buildings or 1.4 points of weighted coverage. So we don't claim robustness across weightings."
- Trap: "same sites under every weighting", or the opposite overclaim "the weights do nothing at all".
- Evidence: E3 (`puntos_meteo` min 0 max 0; `peso_meteo_sensibilidad` 0.81–1.30, 3 distinct). E8 ("9 of 42", "nearly flat").

**M5. "How stable is the answer, and by how much does the third site win?"**
- Say: "Across six scenarios (light and truck at 10, 12 and 15 minutes), Amezketa and Berastegi are in every best trio. The third site changes between CAND-01, 08 and 10, and wins by 3 to 19 buildings. At our headline it's 6."
- Trap: rounding 6 buildings up to "robust", or adding "and weighting".
- Evidence: E1 (all six rows, margins 19/6/3/6/17/10). The table is in `app/data/stability.json`, pinned by `tests/test_stability.py`. (`audit_seat2.py`, cited in the 19 Oct review, is not in the repo: E9.)

**M6. "Who are the 4.3 % you leave out, and is that fair?"**
- Say: "That's 144 buildings. Forty-seven have no road route at all, 34 of them high-priority, and no crew site fixes that; it's an access problem, not a crew problem. And these are buildings, not residents: we have no data on who lives there or how vulnerable they are."
- Trap: "Alta 49 → 177" with no denominator, or "people protected".
- Evidence: E1 (3,331 − 3,187 = 144). E3 (47, 34, 209). a forest-track sensitivity run in an internal review (9 within 12 min, 19 within 15).

**M7. "How do you stop the agent from inventing numbers? Has it ever?"**
- Say: "Every number has to come from a tool call, and we check each one against the data. In the run on our slide it got one wrong: it called Asteasu 'mostly high-priority' from a 15-row sample, and it's really half. We caught that after the run by re-counting with its tool, and the screenshot leaves that line out."
- Trap: "it catches its own errors", or citing tests that aren't in the repo.
- Evidence: `docs/transcripts/2026-10-27_1057_agent_final.md:20` (39 Alta, 30 Media, 9 Baja; "checked after the run"). E9 (`tests_final/` not in repo).

**M8. "Exhaustive or greedy? What exactly is the objective?"**
- Say: "Exhaustive: all 848 combinations of 0 to 6 of the 10 sites. We maximise covered buildings, with ties broken by worst travel time. On this area a greedy pick reaches the same coverage for 1 to 6 crews, but that's 10 sites. It says nothing yet about a provincial pool."
- Trap: "it scales."
- Evidence: E6 (848; Strategy A line). `tests/test_greedy.py` → `4 passed`.

**M9. "Can someone reproduce this tomorrow, and are you allowed to publish it?"**
- Say: "The pipeline rebuilds from raw data, and a test suite pins the headline numbers. All 25 datasets in our sources file have a licence, and 23 have a checksum. Two sources aren't listed there yet, FireScope and the SPEIS annual report, so the licence trail isn't complete."
- Trap: "everything is licensed and traced."
- Evidence: E5 (25 rows; no FireScope, no SPEIS). `grep -ci sha reports/sources.csv` → `23` (missing: SRC-IGN-ESATLAS-PROV, SRC-FLAIRE-P4-V01). P10 test run.

**M10. "Does this transfer to another region, to ambulances, to floods?"**
- Say: "To the rest of Gipuzkoa, partly: we computed today's coverage for all 25,323 exposed buildings in the province, 82.6 % within 12 minutes. The same engine works with any origins and buildings, but the inputs here are specific to this area: the 100 m forest rule, the B5M cadastre and our candidate sites. Ambulances or floods are a hypothesis, not a result."
- Trap: stating "the same engine could place ambulances" as a result.
- Evidence: E2 (province totals). `deck/script.md` slide 6 says it as a hypothesis.

---

---

## Evidence output (27 Oct 2026)

`conda run -n flaire python pipeline/qa_evidence.py`

```
E1 stability.json (exhaustive, 120 combinations of 3, every building weight 1)
  light 10 min  today 2207 (66.3 %)  pick 02+03+08 2985 (89.6 %)  runner-up 02+03+10 2966  ties 1  margin 19
  light 12 min  today 2712 (81.4 %)  pick 01+02+03 3187 (95.7 %)  runner-up 02+03+10 3181  ties 1  margin 6
  light 15 min  today 3148 (94.5 %)  pick 02+03+10 3280 (98.5 %)  runner-up 02+03+06 3277  ties 2  margin 3
  truck 10 min  today 1827 (54.8 %)  pick 02+03+10 2570 (77.2 %)  runner-up 02+03+06 2564  ties 1  margin 6
  truck 12 min  today 2177 (65.4 %)  pick 02+03+08 2937 (88.2 %)  runner-up 02+05+08 2920  ties 1  margin 17
  truck 15 min  today 2776 (83.3 %)  pick 01+02+03 3200 (96.1 %)  runner-up 02+03+10 3190  ties 1  margin 10

E2 gipuzkoa_baseline.json: province totals and the Tolosaldea row
  province: 20908 of 25323 (82.6 %), no route 325
  BAJO DEBA      6 munis  1513/2314 (65.4 %)
  ALTO DEBA      8 munis  2191/3309 (66.2 %)
  UROLA KOSTA   11 munis  2453/3116 (78.7 %)
  TOLOSALDEA    29 munis  2903/3527 (82.3 %)
  GOIERRI       21 munis  3482/3987 (87.3 %)
  DONOSTIALDEA  11 munis  6610/7265 (91.0 %)
  BAJO BIDASOA   2 munis  1756/1805 (97.3 %)
  comarca row: 29 munis (3527, 2903); study area: 28 munis (3331, 2712)
  in comarca, not in study: Legorreta 196 buildings, 191 within 12
  limits: ['Estimated road travel time, not response time (no turnout).', 'No stations outside Gipuzkoa: border municipalities can look worse than they are.', 'Buildings, not people: dwellings are given for context.']

E3 edificios_prioridad.csv (FINAL agent data)
  buildings 3331, municipalities 28, dwellings 10651
  priority {'Baja': 2127, 'Media': 961, 'Alta': 243}
  no route 47, of them Alta 34, Alta with a route 209
  Alta within 12 min today (light) 49; worst time 20.5 min
  puntos_meteo: min 0 max 0
  peso_meteo_sensibilidad: min 0.81 max 1.30, distinct 3

E4 weekly_calendar.json
  rule CS-v1 OR VS-v1, years [2018, 2023], stations ['Berastegi', 'Zizurkil', 'Bidania']
  risk days/year 26.4, shares {'feb_apr': 0.324, 'jul_aug': 0.138, 'sep_oct': 0.312}
  limits: ['Exploratory project rules, not FWI and not fire probability.', 'Only 6 years: single weeks are noisy. Read the seasons, not one week.', 'Not checked against fire records; it shows when the weather was risky, not when fires happened.', "Seasonal staffing only: the sites don't change by week (the 3 zones can't be told apart)."]

E5 sources.csv
  rows 25; mentions firescope: False; mentions speis/memoria: False

E6 optimizer.py
  combinations of 10 sites for k = 0..6: 848; for k = 3: 120
  - Strategy A: maximise weighted coverage (tie: covered count, worst time).

E7 fichas_candidatas_v03.md, selection rule
  ## Regla de selección (transparente, no usa el objetivo del optimizador)
  2. **Demanda**: edificios del conjunto de análisis (residencial ∧ ≤ 100 m de bosque/matorral del Mapa Forestal 2024) con tiempo base (9 parques, vehículo ligero) > 12 min: **619** (47 sin ruta por enganche > 150 m; se reportan pero no orientan la selección porque ninguna candidata arregla su enganche) → **572** edificios. Agrupados con DBSCAN (eps 2 km, mín. 5 edificios): 6 clusters + 4 edificios aislados. Cluster **
  (cluster −1 = edificios aislados según DBSCAN)

E8 linker_validation.md
  Hand checks: **12/12 match**
  different selection in 9 of 42 (threshold, profile, k) cases; where they differ the uniform choice covers at most 80 more buildings and the weighted choice gains at most 1.41 pp of weighted coverage
  Weights are nearly flat (0.81–1.30, within inter-annual noise)

E9 repo facts
  tests_final/ exists: False
  audit_seat2.py exists: False
```

Not done in this drill (PLAN 10.8 lets these be cut first): the end-to-end trace of one Abaltzisketa building, and the hand check of the 6 `validation_routes.csv` routes.

## Skeptic check (27 Oct 2026)

The skeptic agent re-ran the evidence script (the output matches the block above), recomputed all six E1 rows from the raw travel-time CSVs without project code, and confirmed 144 / 47 / 34 / 209 / 10,651, Legorreta, Alta 49 → 177, 92 of 98 fires in Navarra, every cited line, Track A `69 passed` and `test_greedy` `4 passed`. **No number was false.** It found three wrong descriptions of the evidence: "routes checked by hand", "the agent calls the same engine", and "a checksum on every source". It also found four overstatements: "near-ties", "the same answer" for greedy, the Bizkaia cause stated as fact, and 83 % without "all incident types". All seven are fixed above.
