# explorer – Hop-für-Hop-Routen-Explorer

Interaktive Karte für die Wizz-Scans in `data/current/` (`graph.pkl`, `flight_graph.json`, beide nur
gelesen). Statt Routen aufzuzählen wird ein **zeitgeordneter Flug-DAG** gebaut und per **dynamischer
Programmierung rückwärts** gezählt – deshalb braucht der Explorer kein Flug-Limit.
`core/route_find.py` und `simulate/` bleiben unverändert.

```bash
.venv-sim/bin/python -m explorer build     # Scans -> data/explorer/*.json
.venv-sim/bin/python -m explorer serve     # UI auf http://127.0.0.1:8765/
.venv-sim/bin/python -m explorer archive   # was im Scan-Archiv liegt, dichteste Fenster
.venv-sim/bin/python -m explorer selftest  # 29 Prüfungen
```

`serve` baut fehlende Bundles automatisch. Optionen: `--port`, `--host`, `--bundle-dir`, `--open`,
`--verbose`, `--no-build`, bei `build` zusätzlich `--scan`, `--out-dir`, `--no-original`.

## Alt gegen Neu vergleichen

`build` erzeugt pro Scan **zwei** Bundles:

| Bundle | Inhalt |
|---|---|
| `pkl-2025-03` | alle Flüge – das, was die gefixte Suche findet |
| `pkl-2025-03-original` | nur je der früheste Flug pro Strecke – genau das, was `core/route_find.py` je gesehen hat |

Der Originalcode iteriert über `graph[a][b].values()` und bekommt die ganze Flugliste als einen Wert,
benutzt also immer nur `flights[0]`. Die gefixte Suche auf dem reduzierten Graphen liefert deshalb
exakt die Routenmenge des Originals; `test_first_flight_view_equals_the_original_search` prüft das
gegen `simulate/route_find_original.py`.

Mit `?scan=<id>` lässt sich ein Bundle direkt aufrufen, zwei Tabs zeigen dann Alt und Neu
nebeneinander:

```
http://127.0.0.1:8765/?scan=pkl-2025-03-original
http://127.0.0.1:8765/?scan=pkl-2025-03
```

Ab Dortmund, Rundreise 1–24 h, Cap 3 calendar:

| Scan | Original | Fix |
|---|---|---|
| März 2025 (graph.pkl) | 158 One-way, 0 Rundreisen | 5.158 One-way, 27 Rundreisen |
| Oktober 2024 (flight_graph.json) | 2.303 One-way, 10 Rundreisen | 3.252.626 One-way, 19.713 Rundreisen |

## Wie gezählt wird

Knoten = ein konkreter Flug. Kante f → g heißt: g startet in der Stadt, in der f landet, und
`ank(f) + min_gap ≤ ab(g) ≤ ank(f) + max_gap`. Das ist exakt die Nachfolgerregel von
`simulate/route_find_fixed.py` mit `flex_km = 0`. Abflugzeiten wachsen entlang jedes Pfades streng,
der Graph ist also azyklisch.

`route_find` speichert **jeden gültigen Präfix**, deshalb gilt für einen Präfix P:

```
one_way(P)    = 1 + Σ über erlaubte Anschlüsse g von one_way(P + g)
round_trip(P) = [letzte Stadt von P ist Rückkehr-Stadt] + Σ über g von round_trip(P + g)
```

Memoisiert über `(Flug, Cap-Zustand, Restflüge)`. Ohne Cap sind das ein paar hundert Zustände, mit
`rolling24` ein paar tausend – der ganze Lauf dauert im Browser Millisekunden.

**Buchungsregel** wie `simulate/booking_cap.py`, aber inkrementell als Zustand:

| Modus | Regel | Zustand |
|---|---|---|
| `calendar` | höchstens `cap` Abflüge pro **lokalem Kalendertag des Abflughafens** | `(Tag, Anzahl)` |
| `rolling24` | nie `cap + 1` Abflüge in einem Fenster **kürzer als 24 h** | die Abflüge im laufenden 24-h-Fenster (höchstens `cap`) |
| `none` | kein Cap | – |

Die Anteile pro Hop beziehen sich immer auf die **Fortsetzungen**: Nenner ist die Summe über alle
erlaubten nächsten Flüge, deshalb summieren sich die Städteanteile auf 100 %.

## Archiv: mehrere Scans desselben Tages zusammenlegen

`data/archives/flight_graph/` enthält 366 Dateien, davon 330 brauchbare Scans über 154 Flugtage vom
30.09.2024 bis 15.03.2025, zusammen 66.098 eindeutige Flüge auf 1.515 Strecken. Jeder Flugtag wurde
im Median vier Mal gescannt, der 18.12.2024 sogar 22 Mal. Jeder Scan ist eine Momentaufnahme
desselben Flugplans, und weil einzelne Abrufe fehlschlagen, hat jeder Scan Lücken. Die Vereinigung
aller Snapshots eines Tages ist deshalb deutlich vollständiger als jeder einzelne Scan.

```bash
python -m explorer archive                       # Übersicht und dichteste Fenster
python -m explorer build --archive-daily         # eine Datei je Flugtag -> Datumsregler in der UI
python -m explorer build --archive-best 3        # die 3 dichtesten 4-Tage-Fenster als feste Bundles
python -m explorer build --archive-window 2024-12-17 --archive-days 4
```

Mit `--archive-daily` entsteht `archive-days.json` plus eine kleine Datei je Flugtag (154 Stück,
zusammen 6,5 MB). Alle Tagesdateien teilen sich dieselbe Städte-Tabelle, ein Städte-Index bedeutet
also überall dasselbe, und das Zusammenlegen ist ein Aneinanderhängen. Im Scan-Menü erscheint dann
**„Archiv: 154 Flugtage frei wählbar"** mit einem Datumsregler, einer Fensterlänge von 2 bis 6 Tagen
und einem Schalter für die Originalcode-Sicht. Der Browser lädt nur die Tage, die das Fenster
braucht, merkt sie sich und baut den Graphen selbst zusammen. Direktlink: `?scan=__archive__`.
`test_browser_assembles_the_same_window_as_python` prüft, dass das Ergebnis exakt dem Python-Merge
entspricht.

Was die Vereinigung ist und was nicht: sie ist die Menge der Flüge, die an diesem Tag irgendwann
angeboten wurden. Sie ist **kein** konsistenter Flugplan. Ein zwischen zwei Scans gestrichener Flug
bleibt drin, ein umgelegter Flug kann zweimal auftauchen. Zum Erkunden des Möglichen ist das richtig,
zum Buchen nicht.

Datenqualität: 232 Einträge landen vor ihrem Abflug, weil bei Nachtflügen das Ankunftsdatum nicht
hochgezählt wurde. Alle 232 stecken im allerersten Scan vom 30.09.2024, jeder spätere Scan ist
sauber. `load_days` verwirft solche Einträge und zählt sie, statt zu raten.

Ab Dortmund, Rundreise 1–24 h, ohne Cap:

| Datensatz | Flüge | Strecken | One-way | Rundreisen |
|---|---|---|---|---|
| `graph.pkl`, ein März-Scan | 1.019 | 631 | 6.753 | 31 |
| dieselben 4 Tage aus dem Archiv zusammengelegt | 1.629 | 886 | 457.719 | 1.089 |
| 17.–20.12.2024 zusammengelegt, 73 Scans | 2.561 | 1.002 | 239.127.407 | 893.951 |

## Oberfläche

- **Karte**: Leaflet mit OpenStreetMap-Kacheln, wenn die Bibliothek geladen werden konnte, sonst
  automatisch die eingebaute SVG-Karte (Web-Mercator, Gradnetz, alle Städte des Scans als blasse
  Punkte zur Orientierung, ziehen und Mausrad zum Zoomen). Umschalten oben rechts.
- **Punktgröße** = Anteil der akzeptablen Vollrouten über diesen Hop (Fläche proportional zum Anteil).
- **Tooltip**: Anzahl Flüge, Anteil Rundreise, Anteil One-way, offene Rückwege, neues Land.
- **Klick auf Stadt** → die konkreten Flüge, **Klick auf Flug** → Hop gesetzt. Breadcrumb im
  Light-Format von `print_routes`, dazu Zurück und Zurücksetzen.
- **Einstellungen sofort wirksam**: Scan, Modus, Startstadt und Rückkehr-Stadt je mit **Radius in
  km**, min/max Gap, optionales Flug-Limit, Tages-Cap mit `calendar`/`rolling24`/ohne, neue Länder
  hervorheben. Wird eine Einstellung enger, wird die Route auf ihren längsten noch gültigen Präfix
  gekürzt.
- **Radius statt Mehrfachauswahl**: eine Stadt plus Umkreis ergibt die Menge der Start- bzw.
  Rückkehr-Städte, Entfernung als Großkreis über die Koordinaten in `coords.py`. Das Panel nennt die
  getroffenen Städte und wie viele davon im Scan überhaupt Abflüge haben. Beispiel Frankfurt:
  150 km trifft Cologne (137 km) und Karlsruhe/Baden-Baden (144 km), 200 km zusätzlich Stuttgart,
  Dortmund und Nuremberg.
- Gerechnet wird komplett im Browser (`static/dp.js`); der Server liefert nur Dateien aus.

## Netzzugriff

Der Server bindet auf 127.0.0.1 und ruft nichts ab. Die einzigen externen Anfragen kommen aus dem
Browser: die OpenStreetMap-Kacheln und Leaflet vom CDN. Ohne beides funktioniert die Seite
vollständig über die SVG-Karte.

## Module

| Datei | Inhalt |
|---|---|
| `dp.py` | Flug-DAG, Cap-Zustände, Rückwärts-DP (Referenz für die Tests) |
| `coords.py` | Koordinaten für alle 181 Städtenamen beider Scans; fehlt eine, bricht `build` mit Liste ab |
| `build.py` | Scan → Browser-Bundle (`data/explorer/*.json`) |
| `server.py` | lokaler Static-Server, zwei Wurzeln, kein Directory-Listing, kein Traversal |
| `cli.py` | `build` / `serve` / `selftest` |
| `static/dp.js` | dieselbe DP im Browser (gegen `dp.py` getestet) |
| `static/map.js` | Leaflet- und SVG-Renderer hinter einer Schnittstelle |
| `static/app.js` | Zustand, Rendering, Interaktion |
| `tests/` | DP gegen Aufzählung, JS gegen Python, UI headless unter node, Koordinaten, Bundle, Server |

## Was die Tests belegen

- `test_dp`: Die DP-Zahlen stimmen exakt mit `simulate/route_find_fixed.py` + `booking_cap`
  überein – auf einem Synth-Netz, auf dem echten Scan, mit und ohne Flug-Limit, für alle drei
  Cap-Modi und für Caps 1/2/3. Anteile summieren pro Hop auf 100 %.
- `test_dp.test_timezones_across_midnight`: Eine Rundreise mit vier Abflügen innerhalb von zehn
  Stunden, die über lokale Mitternacht und zwei Zeitzonen läuft. `calendar` mit Cap 3 lässt sie zu,
  `rolling24` nicht, und Cap 2 auf Kalendertagen lehnt sie ab – das pinnt die Tagesgruppierung auf
  das lokale Datum des Abflughafens statt auf UTC.
- `test_js`: `static/dp.js` liefert für dasselbe Bundle dieselben Zahlen wie `dp.py`.
- `test_ui`: `static/app.js` läuft headless unter node gegen einen DOM-Stub. Geprüft werden
  Rendering, Klick auf Stadt und Flug, Zurück, Zurücksetzen, Kartenwechsel, der Breadcrumb gegen
  `simulate/routefmt.py` und die angezeigten Summen gegen `dp.py`.
