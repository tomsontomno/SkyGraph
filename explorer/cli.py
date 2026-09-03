"""Command line of the explorer: ``python -m explorer [build|serve|selftest]``."""
from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path
from typing import List, Optional

from explorer import build as build_mod
from explorer import server as server_mod

SUBCOMMANDS = ('build', 'serve', 'selftest', 'archive', 'export')


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='python -m explorer',
        description='Hop-für-Hop-Routen-Explorer für die Wizz-Scans in data/current/ (nur lesend)')
    sub = parser.add_subparsers(dest='command')

    build = sub.add_parser('build', help='Scans in Browser-Bundles übersetzen')
    build.add_argument('--scan', dest='scans', nargs='*', type=Path, default=None,
                       help='Scan-Dateien (.pkl/.json); Standard: data/current/graph.pkl und flight_graph.json')
    build.add_argument('--out-dir', type=Path, default=build_mod.BUNDLE_DIR)
    build.add_argument('--no-original', action='store_true',
                       help='keine zusätzlichen "-original"-Bundles (Sicht des Originalcodes: je erster Flug)')
    build.add_argument('--archive-best', type=int, default=0, metavar='N',
                       help='zusätzlich die N dichtesten Archiv-Fenster bauen (Snapshots pro Flugtag zusammengelegt)')
    build.add_argument('--archive-window', dest='archive_windows', nargs='*', default=None, metavar='YYYY-MM-DD',
                       help='zusätzlich diese Archiv-Fenster bauen (Startdatum)')
    build.add_argument('--archive-days', type=int, default=4, metavar='N',
                       help='Länge eines Archiv-Fensters in Tagen (Standard 4)')
    build.add_argument('--archive-only', action='store_true', help='nur Archiv-Fenster bauen')
    build.add_argument('--archive-daily', action='store_true',
                       help='eine Datei je Archiv-Flugtag bauen; die UI stellt daraus jedes Fenster frei zusammen')

    export = sub.add_parser('export', help='UI und Bundles in einen statischen Ordner legen (Vercel & Co.)')
    export.add_argument('--out-dir', type=Path, default=build_mod.PROJECT_ROOT / 'data' / 'site')
    export.add_argument('--bundle-dir', type=Path, default=build_mod.BUNDLE_DIR)

    archive = sub.add_parser('archive', help='Archiv-Scans auswerten (was liegt da, wie dicht ist welcher Tag)')
    archive.add_argument('--windows', type=int, default=10, metavar='N', help='N dichteste Fenster zeigen')
    archive.add_argument('--days', type=int, default=4, metavar='N', help='Fensterlänge in Tagen')

    serve = sub.add_parser('serve', help='UI lokal ausliefern')
    serve.add_argument('--host', default='127.0.0.1')
    serve.add_argument('--port', type=int, default=8765)
    serve.add_argument('--bundle-dir', type=Path, default=build_mod.BUNDLE_DIR)
    serve.add_argument('--no-build', action='store_true', help='nicht automatisch bauen, wenn Bundles fehlen')
    serve.add_argument('--open', dest='open_browser', action='store_true', help='Browser öffnen')
    serve.add_argument('--verbose', action='store_true', help='jede HTTP-Anfrage loggen')

    sub.add_parser('selftest', help='eingebaute Prüfungen ausführen (DP gegen Aufzählung, JS gegen Python)')
    return parser


def cmd_build(args: argparse.Namespace) -> int:
    from explorer import archive as archive_mod

    scans = args.scans if args.scans else list(build_mod.DEFAULT_SCANS)
    wants_archive = args.archive_best > 0 or args.archive_windows or args.archive_daily
    if args.archive_only and not wants_archive:
        print("--archive-only ohne --archive-best/--archive-window: nichts zu bauen.", file=sys.stderr)
        return 2
    try:
        built = [] if args.archive_only else build_mod.build_all(scans, args.out_dir,
                                                                 with_original=not args.no_original)
        if wants_archive:
            index = archive_mod.load_days()
            starts = list(args.archive_windows or [])
            if args.archive_best > 0:
                ranked = archive_mod.windows(index, args.archive_days)
                starts += [window[0] for window, _ in ranked[:args.archive_best]
                           if window[0] not in starts]
            unknown = [s for s in starts if s not in index.days]
            if unknown:
                print(f"Diese Tage liegen nicht im Archiv: {', '.join(unknown)}", file=sys.stderr)
                return 2
            if starts:
                built += build_mod.build_archive_windows(starts, args.archive_days, args.out_dir,
                                                         with_original=not args.no_original, index=index)
            if args.archive_daily:
                manifest = build_mod.build_archive_day_bundles(index, args.out_dir)
                stats = manifest['stats']
                print(f"Archiv-Tagesdateien: {stats['flightDays']} Tage, {stats['uniqueFlights']:,} Flüge, "
                      f"{stats['cities']} Städte -> {args.out_dir / build_mod.ARCHIVE_MANIFEST}")
            build_mod.write_index(built, args.out_dir)
    except build_mod.MissingCoordinates as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (FileNotFoundError, KeyError, ValueError) as exc:
        print(f"Archiv nicht verwendbar: {exc}", file=sys.stderr)
        return 2
    print(f"{len(built)} Bundle(s) in {args.out_dir}")
    print(f"{'Scan':<24} {'Quelle':<32} {'Städte':>7} {'Strecken':>9} {'Flüge':>7} {'Tage':>5} {'Größe':>7}")
    for info in built:
        stats = info['stats']
        print(f"{info['scan']:<24} {info['source']:<32} {stats['cities']:>7} {stats['edges']:>9} "
              f"{stats['flights']:>7} {info['days']:>5} {info['bytes'] / 1024:>6.0f}K")
    print("Start: python -m explorer serve")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    try:
        info = build_mod.export_site(args.out_dir, args.bundle_dir)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"Statische Seite in {info['dir']}")
    print(f"  {len(info['assets'])} Asset(s), {len(info['bundles'])} Bundle-Datei(en), "
          f"{info['bytes'] / 1e6:.1f} MB gesamt")
    print("\nDeploy:")
    print(f"  cd {info['dir']} && npx vercel deploy --prod")
    print("  (oder den Ordner bei Netlify/Cloudflare Pages ablegen – es ist reines HTML/JS/JSON)")
    print("\nHinweis: die Bundles enthalten deine gescannten Flugdaten. Auf Vercel ist die Seite")
    print("öffentlich, solange du sie nicht per Vercel Authentication/Password schützt.")
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    from explorer import archive as archive_mod

    try:
        index = archive_mod.load_days()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    info = archive_mod.summary(index)
    if not info['flight_days']:
        print("Das Archiv enthält keine brauchbaren Scans.", file=sys.stderr)
        return 2
    print(f"Archiv: {info['files_used']} brauchbare Scans ({info['files_skipped']} übersprungen), "
          f"{info['entries_read']:,} Flugeinträge gelesen, {info['entries_dropped']} verworfen "
          f"(Ankunft vor Abflug)")
    print(f"Flugtage: {info['flight_days']} von {info['first_day']} bis {info['last_day']}  ·  "
          f"{info['unique_flights']:,} eindeutige Flüge  ·  {info['routes']:,} Strecken  ·  "
          f"{info['cities']} Städte")
    print(f"Scans pro Flugtag: Median {info['median_scans_per_day']}, Maximum {info['max_scans_per_day']}")
    if info['dropped_files']:
        for name, count in sorted(info['dropped_files'].items(), key=lambda kv: -kv[1])[:3]:
            print(f"  verworfen: {count} Einträge aus {name}")
    ranked = archive_mod.windows(index, args.days)
    print(f"\nDichteste {args.days}-Tage-Fenster (Flüge nach Zusammenlegen aller Snapshots):")
    print(f"{'Start':<12}{'Ende':<12}{'Flüge':>7}{'Scans':>7}")
    for window, count in ranked[:max(0, args.windows)]:
        scans = sum(index.scans_per_day.get(day, 0) for day in window)
        print(f"{window[0]:<12}{window[-1]:<12}{count:>7,}{scans:>7}")
    print(f"\nBauen mit: python -m explorer build --archive-best 3")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    bundle_dir = args.bundle_dir
    if not (bundle_dir / 'index.json').is_file():
        if args.no_build:
            print(f"Keine Bundles in {bundle_dir}; erst 'python -m explorer build' laufen lassen.", file=sys.stderr)
            return 2
        print(f"Keine Bundles in {bundle_dir} – baue sie jetzt.")
        try:
            build_mod.build_all(build_mod.DEFAULT_SCANS, bundle_dir)
        except build_mod.MissingCoordinates as exc:
            print(str(exc), file=sys.stderr)
            return 2
    url = f"http://{args.host}:{args.port}/"
    if args.open_browser:
        webbrowser.open(url)
    try:
        server_mod.serve(bundle_dir, host=args.host, port=args.port, verbose=args.verbose)
    except OSError as exc:
        print(f"Port {args.port} auf {args.host} nicht verfügbar: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    from explorer.tests.runner import run_all
    outcomes = run_all()
    for name, ok, message in outcomes:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  {message}")
    failed = sum(1 for _, ok, _ in outcomes if not ok)
    print(f"{len(outcomes) - failed}/{len(outcomes)} Prüfungen bestanden")
    return 1 if failed else 0


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        build_parser().print_help()
        return 0
    if argv[0] not in SUBCOMMANDS and argv[0] not in ('-h', '--help'):
        argv.insert(0, 'build')
    args = build_parser().parse_args(argv)
    if args.command is None:
        build_parser().print_help()
        return 0
    handlers = {'build': cmd_build, 'serve': cmd_serve, 'selftest': cmd_selftest,
                'archive': cmd_archive, 'export': cmd_export}
    return handlers[args.command](args)
