# simulate – Bug-Impact-Simulation für `core/route_find.py`

Vergleicht die **originale** Routensuche (Kopie von `core/route_find.py`, Bug erhalten) mit einer
**gefixten** Kopie auf synthetischen Wizz-Netzen und auf den echten Scans in `data/current/`
(`graph.pkl`, `flight_graph.json`). `core/route_find.py` selbst bleibt unverändert; `data/current/`
wird nur gelesen.

Der Bug: `graph[a][b].values()` liefert die gesamte `flights`-Liste als einzigen Wert, die Suche
sieht deshalb pro Strecke nur `flights[0]`, den frühesten Flug. Der Fix iteriert über
`graph[a][b]['flights']`. Beide Kopien haben zusätzlich einen identischen Tiefen-Cap
(`max_flights`), der semantisch `filter_routes_by_flights` entspricht (`selftest` prüft das).

## Umgebung

Der Repo-`.venv` ist auf dieser Maschine nicht lauffähig (Exec format error). Die Simulation läuft
mit `.venv-sim` (Python 3.14 + networkx 3.6.1, offline aus einer lokalen Kopie installiert):

```bash
.venv-sim/bin/python -m simulate selftest
.venv-sim/bin/python -m simulate run
```

Jede andere Umgebung mit `networkx` funktioniert genauso (`python -m simulate ...`).

## Befehle

```bash
python -m simulate run                       # Standardlauf: Seeds 0-19 + beide echten Scans
python -m simulate run --seeds 0-4 --jobs 1  # kleiner, in-process mit feiner Fortschrittszeile
python -m simulate run --cap-mode rolling24  # Buchungsregel als rollierendes 24-h-Fenster
python -m simulate run --cap-mode both --focus ow:1-24:none --sample 20 --random-seed 7
python -m simulate run --scenarios ow --gaps 2-10 --max-flights 4 --start Budapest
python -m simulate show data/sim/<run-id> --show 40            # erste 40 verpasste Routen
python -m simulate show data/sim/<run-id> --file routes_fixed.txt --pager   # less -S
python -m simulate selftest
```

Standard-Settings: Start Dortmund, `min_time_gap_hours=1`, `max_time_gap_hours=12|24`,
`max_flights=5`, `flex_km=0`, Cap 3 Flüge/Tag (`calendar`). Berichtet wird immer ohne Cap und mit
dem gewählten Cap-Modus.

## Ausgabe

Terminal: höchstens `--max-lines` (150) Zeilen – Tabelle pro Szenario (Synth-Median [Min–Max] und
beide echten Scans), Tiefen-Effekt nach Flügen und Kalendertag inklusive kombinatorischer Erwartung
`1-(1-p)^k`, Hypothesen-Test, Klassifikation der verpassten Routen, Extremwert-Routen im
Light-Format, Stichprobe verpasster Routen, Dateipfade.

`data/sim/<run-id>/`:

- `routes_original.txt`, `routes_fixed.txt`, `routes_missed.txt` – Fokus-Datensatz/-Szenario/-Cap
  (Standard: `graph.pkl`, rt 1–24 h, calendar), eine Route pro Zeile mit Tag
  (`flights=…, last_dep=T…, inv_pos=…, later_day=…, new_itin=…, prefix_known=…`).
- `real/<datensatz>/<szenario>_<cap>/routes_*.txt` – dieselben Dateien für jeden echten Scan,
  jedes Szenario und jeden Cap-Modus.
- `synth/synth-XX/flight_graph.json` – das erzeugte Netz im Scanner-Format (mit
  `--write-synth-routes` auch die Routen-Dateien).
- `summary.json` – alle Zahlen pro Datensatz/Szenario/Cap plus Median/Min/Max über die Synth-Netze.
- `summary.md` – vollständiger Bericht mit allen Tabellen, Kreuztabellen und Extremwert-Routen.

## Module

| Datei | Inhalt |
|---|---|
| `route_find_original.py` | Kopie von `core/route_find.py` + Tiefen-Cap (Bug bleibt) |
| `route_find_fixed.py` | Kopie + Tiefen-Cap + Fix |
| `synth.py` | seedbarer Netzgenerator (Hub-Gewichte, Tagesverteilung, Offsets aus dem echten Scan) |
| `datasets.py` | Laden der echten Scans, Bau der Datensätze |
| `booking_cap.py` | Buchungsregel `calendar` / `rolling24` (Offsets aus dem ISO-String) |
| `analyze.py` | Vergleich Original vs. Fix, Klassifikation, Extremwerte, Aggregation |
| `worker.py` | Arbeitseinheit pro Datensatz (auch im Prozess-Pool) |
| `report.py` | Terminalansicht, Routen-Dateien, `summary.json`, `summary.md` |
| `cli.py` | `run` / `show` / `selftest` |
| `tests/` | Kopie-Treue, Cap-Äquivalenz, Original ⊆ Fix, Buchungsregel, Generator-Invarianten, Light-Format |
