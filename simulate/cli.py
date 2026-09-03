"""Command line of the simulation: ``python -m simulate [run|show|selftest] ...``.

``run`` (default) searches every dataset with both versions, writes data/sim/<run-id>/ and prints a
terminal view of at most --max-lines lines.  ``show`` prints the first N routes of a routes file
(or opens it in ``less -S``).  ``selftest`` runs the built-in checks without pytest.
"""
from __future__ import annotations

import argparse
import multiprocessing
import os
import shlex
import shutil
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from simulate import analyze, datasets, report, synth, worker
from simulate.progress import Progress

DEFAULT_OUT_DIR = datasets.PROJECT_ROOT / 'data' / 'sim'
SUBCOMMANDS = ('run', 'show', 'selftest')


# --- argument parsing ----------------------------------------------------------------------------------

def parse_seeds(text: str) -> List[int]:
    """``0-19`` or ``0,3,7`` or ``0-4,9`` -> sorted unique ints."""
    seeds = set()
    for part in text.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            lo, hi = part.split('-', 1)
            lo_i, hi_i = int(lo), int(hi)
            if hi_i < lo_i:
                raise argparse.ArgumentTypeError(f"seed range {part!r} is empty")
            seeds.update(range(lo_i, hi_i + 1))
        else:
            seeds.add(int(part))
    if not seeds:
        raise argparse.ArgumentTypeError("no seeds given")
    return sorted(seeds)


def parse_gaps(text: str) -> List[Tuple[float, float]]:
    """``1-12,1-24`` -> [(1.0, 12.0), (1.0, 24.0)]."""
    gaps = []
    for part in text.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' not in part:
            raise argparse.ArgumentTypeError(f"gap {part!r} must look like MIN-MAX (hours)")
        lo, hi = part.split('-', 1)
        lo_f, hi_f = float(lo), float(hi)
        if lo_f < 0 or hi_f <= lo_f:
            raise argparse.ArgumentTypeError(f"gap {part!r}: need 0 <= MIN < MAX")
        gaps.append((lo_f, hi_f))
    if not gaps:
        raise argparse.ArgumentTypeError("no gaps given")
    return gaps


def parse_modes(text: str) -> List[str]:
    modes = [m.strip() for m in text.split(',') if m.strip()]
    bad = [m for m in modes if m not in ('rt', 'ow')]
    if bad or not modes:
        raise argparse.ArgumentTypeError(f"scenarios must be a comma list of rt/ow, got {text!r}")
    return modes


def parse_focus(text: str) -> Tuple[str, float, float, str]:
    """``rt:1-24:calendar`` -> ('rt', 1.0, 24.0, 'calendar')."""
    try:
        mode, gap, cap = text.split(':')
        (lo, hi), = parse_gaps(gap)
    except (ValueError, argparse.ArgumentTypeError) as exc:
        raise argparse.ArgumentTypeError(f"focus must look like rt:1-24:calendar, got {text!r} ({exc})")
    if mode not in ('rt', 'ow'):
        raise argparse.ArgumentTypeError(f"focus mode must be rt or ow, got {mode!r}")
    return mode, lo, hi, cap


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='python -m simulate',
                                     description='Bug-impact simulation: original vs fixed core/route_find.py')
    sub = parser.add_subparsers(dest='command')

    run = sub.add_parser('run', help='run the simulation (default command)')
    run.add_argument('--seeds', type=parse_seeds, default=parse_seeds('0-19'), help='synthetic seeds, default 0-19')
    run.add_argument('--no-synth', action='store_true', help='skip synthetic networks')
    run.add_argument('--real', nargs='*', type=Path, default=None,
                     help='scan files (.pkl or .json); default data/current/graph.pkl and flight_graph.json')
    run.add_argument('--no-real', action='store_true', help='skip the real scans')
    run.add_argument('--start', default='Dortmund', help='start city (default Dortmund)')
    run.add_argument('--scenarios', type=parse_modes, default=['rt', 'ow'], help='comma list of rt,ow')
    run.add_argument('--gaps', type=parse_gaps, default=parse_gaps('1-12,1-24'), help='layover windows, e.g. 1-12,1-24')
    run.add_argument('--max-flights', type=int, default=5)
    run.add_argument('--flex-km', type=float, default=0.0)
    run.add_argument('--transfer-speed', type=float, default=50.0, help='km/h for self-transfers (flex_km > 0)')
    run.add_argument('--daily-cap', type=int, default=3, help='Wizz booking rule: flights per day')
    run.add_argument('--cap-mode', choices=['calendar', 'rolling24', 'both'], default='calendar',
                     help="cap mode reported next to 'none' (default calendar)")
    run.add_argument('--sample', type=int, default=10, help='random missed routes per real dataset in the terminal')
    run.add_argument('--random-seed', type=int, default=0, help='seed of the sample')
    run.add_argument('--focus', type=parse_focus, default=None,
                     help='scenario/cap for extremes, sample and flat files: mode:min-max:cap (default rt:1-24:<cap-mode>)')
    run.add_argument('--focus-dataset', default=None, help='dataset name for the flat route files (default first real)')
    run.add_argument('--run-id', default=None, help='output folder name (default timestamp)')
    run.add_argument('--out-dir', type=Path, default=DEFAULT_OUT_DIR)
    run.add_argument('--write-synth-routes', action='store_true', help='also write route files for synthetic nets')
    run.add_argument('--show', type=int, default=0, help='additionally print the first N missed routes (focus)')
    run.add_argument('--pager', action='store_true', help='open routes_missed.txt of the focus in less -S afterwards')
    run.add_argument('--max-lines', type=int, default=report.TERMINAL_MAX_LINES)
    run.add_argument('--jobs', type=int, default=max(1, min(8, os.cpu_count() or 1)),
                     help='parallel worker processes over datasets (default: min(8, CPUs); 1 = in-process)')
    run.add_argument('--synth-spokes', type=int, default=synth.SynthParams().n_spokes)
    run.add_argument('--synth-edges', type=int, default=synth.SynthParams().target_edges)
    run.add_argument('--synth-base-date', default=synth.SynthParams().base_date)

    show = sub.add_parser('show', help='print the first N routes of a routes file')
    show.add_argument('target', help='routes file, run directory or run id under --out-dir')
    show.add_argument('--file', default='routes_missed.txt', help='file inside a run directory (default routes_missed.txt)')
    show.add_argument('--show', type=int, default=30, help='number of routes to print (default 30)')
    show.add_argument('--pager', action='store_true', help='open the file in less -S instead')
    show.add_argument('--out-dir', type=Path, default=DEFAULT_OUT_DIR)

    sub.add_parser('selftest', help='run the built-in checks (copy fidelity, cap semantics, generator invariants)')
    return parser


# --- run -----------------------------------------------------------------------------------------------------

def _listdict(stats: dict) -> dict:
    """Lists -> {'0': .., '1': ..} so ``analyze.aggregate`` can take medians per position."""
    return {k: ({str(i): v for i, v in enumerate(val)} if isinstance(val, list) and val and
                all(isinstance(x, (int, float)) for x in val) else val) for k, val in stats.items()}


def cmd_run(args: argparse.Namespace) -> int:
    started = time.monotonic()
    run_id = args.run_id or datetime.now().strftime('%Y%m%d-%H%M%S')
    run_dir = args.out_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    cap_modes = ['none'] + (['calendar', 'rolling24'] if args.cap_mode == 'both' else [args.cap_mode])
    scenarios = [analyze.Scenario(mode, lo, hi) for mode in args.scenarios for lo, hi in args.gaps]
    if args.focus is None:
        focus_scenario = analyze.Scenario('rt', 1, 24) if analyze.Scenario('rt', 1, 24) in scenarios else scenarios[0]
        focus_cap = cap_modes[1] if len(cap_modes) > 1 else cap_modes[0]
    else:
        mode, lo, hi, focus_cap = args.focus
        focus_scenario = analyze.Scenario(mode, lo, hi)
        if focus_scenario not in scenarios:
            raise SystemExit(f"--focus scenario {focus_scenario.key} is not among the scenarios {[s.key for s in scenarios]}")
        if focus_cap not in cap_modes:
            raise SystemExit(f"--focus cap {focus_cap!r} is not among the cap modes {cap_modes}")
    if args.max_flights < 1:
        raise SystemExit("--max-flights must be >= 1")
    if args.daily_cap < 1:
        raise SystemExit("--daily-cap must be >= 1")

    preferences = datasets.load_preferences()
    city_data, country_data = preferences['city'], preferences['country']
    distances = datasets.load_distances()
    params = analyze.SearchParams(start=args.start, max_flights=args.max_flights, flex_km=args.flex_km,
                                  transfer_speed_kmh=args.transfer_speed, distances_file=datasets.DISTANCES_FILE)

    all_datasets: List[datasets.Dataset] = []
    synth_params = synth.SynthParams(n_spokes=args.synth_spokes, target_edges=args.synth_edges,
                                     base_date=args.synth_base_date)
    if not args.no_synth:
        all_datasets += datasets.make_synth_datasets(args.seeds, synth_params, datasets.distance_lookup_from_files())
    if not args.no_real:
        real_files = args.real if args.real else list(datasets.DEFAULT_REAL_FILES)
        all_datasets += datasets.load_real_datasets(real_files)
    if not all_datasets:
        raise SystemExit("nothing to do: both --no-synth and --no-real given")
    for ds in all_datasets:
        if args.start not in ds.graph:
            raise SystemExit(f"start city {args.start!r} is not in dataset {ds.name} ({ds.source})")
    real_names = [ds.name for ds in all_datasets if ds.kind == 'real']
    synth_names = [ds.name for ds in all_datasets if ds.kind == 'synth']
    n_days = max(len(ds.stats['flights_by_day']) for ds in all_datasets)
    focus_dataset = args.focus_dataset or (real_names[0] if real_names else all_datasets[0].name)
    if focus_dataset not in {ds.name for ds in all_datasets}:
        raise SystemExit(f"--focus-dataset {focus_dataset!r} unknown; datasets: {[ds.name for ds in all_datasets]}")

    settings = {
        'start': args.start, 'scenarios': [s.key for s in scenarios], 'max_flights': args.max_flights,
        'flex_km': args.flex_km, 'transfer_speed_kmh': args.transfer_speed, 'daily_cap': args.daily_cap,
        'cap_modes': cap_modes, 'n_days': n_days, 'seeds': args.seeds if not args.no_synth else [],
        'real_files': [ds.source for ds in all_datasets if ds.kind == 'real'], 'sample': args.sample,
        'random_seed': args.random_seed, 'focus': {'dataset': focus_dataset, 'scenario': focus_scenario.key, 'cap': focus_cap},
        'synth_params': synth.params_to_dict(synth_params) if not args.no_synth else None,
        'jobs': args.jobs,
    }

    jobs = []
    for ds in all_datasets:
        if ds.kind == 'synth' and ds.flight_json is not None:
            synth_dir = run_dir / 'synth' / ds.name
            synth_dir.mkdir(parents=True, exist_ok=True)
            report.write_summary_json(synth_dir / 'flight_graph.json', ds.flight_json)
        route_dir = run_dir / ds.kind / ds.name if (ds.kind == 'real' or args.write_synth_routes) else None
        jobs.append(worker.Job(dataset=ds, scenarios=scenarios, params=params, cap_modes=cap_modes,
                               daily_cap=args.daily_cap, n_days=n_days, city_data=city_data,
                               country_data=country_data, distances=distances, run_id=run_id,
                               route_dir=route_dir, keep_comparisons=ds.kind == 'real'))
    n_workers = max(1, min(args.jobs, len(jobs)))
    job_results = _run_jobs(jobs, n_workers, len(scenarios))
    results: Dict[str, Dict[str, Dict[str, dict]]] = {r.name: r.results for r in job_results}
    comparisons: Dict[Tuple[str, str, str], analyze.Comparison] = {
        (r.name, scenario_key, cap): comparison
        for r in job_results for (scenario_key, cap), comparison in r.comparisons.items()}
    day0_by_dataset: Dict[str, date] = {r.name: r.day0 for r in job_results}

    aggregate_synth = {sc.key: {cap: analyze.aggregate([results[n][sc.key][cap] for n in synth_names])
                                for cap in cap_modes} for sc in scenarios} if synth_names else {}
    network_aggregate = analyze.aggregate([_listdict(ds.stats) for ds in all_datasets if ds.kind == 'synth']) \
        if synth_names else {}

    files: Dict[str, Path] = {}
    focus_key = (focus_dataset, focus_scenario.key, focus_cap)
    if focus_key in comparisons:
        flat = report.write_comparison_files(
            run_dir, comparisons[focus_key], distances, day0_by_dataset[focus_dataset],
            [f"dataset: {focus_dataset}", f"scenario: {focus_scenario.label}", f"cap: {focus_cap}",
             f"start: {args.start}", f"max_flights: {args.max_flights}", f"run: {run_id}"])
        files.update(flat)
    files['summary.json'] = run_dir / 'summary.json'
    files['summary.md'] = run_dir / 'summary.md'
    files['real/'] = run_dir / 'real'
    if synth_names:
        files['synth/'] = run_dir / 'synth'

    summary = {
        'run': {'run_id': run_id, 'created': datetime.now().isoformat(timespec='seconds'),
                'command': ' '.join(shlex.quote(a) for a in ['python', '-m', 'simulate'] + sys.argv[1:]),
                'settings': settings, 'seconds': round(time.monotonic() - started, 1)},
        'scenarios': [{'key': s.key, 'label': s.label, 'mode': s.mode, 'min_gap_hours': s.min_gap_hours,
                       'max_gap_hours': s.max_gap_hours} for s in scenarios],
        'cap_modes': cap_modes,
        'datasets': {ds.name: {'kind': ds.kind, 'seed': ds.seed, 'source': ds.source, 'stats': ds.stats}
                     for ds in all_datasets},
        'results': results,
        'aggregate_synth': aggregate_synth,
        'network_aggregate_synth': network_aggregate,
        'focus': settings['focus'],
        'files': {k: str(v) for k, v in files.items()},
    }
    summary['run']['seconds'] = round(time.monotonic() - started, 1)
    report.write_summary_json(files['summary.json'], summary)
    report.write_summary_md(files['summary.md'], summary, real_names)

    samples = {}
    for name in real_names:
        comparison = comparisons[(name, focus_scenario.key, focus_cap)]
        samples[name] = (report.sample_missed(comparison, args.sample, args.random_seed), len(comparison.missed_routes))
    lines = report.render_terminal(summary, real_names, settings['focus'], samples, files, distances,
                                   day0_by_dataset, max_lines=args.max_lines)
    if args.show > 0 and focus_key in comparisons:
        comparison = comparisons[focus_key]
        lines.append('')
        lines.append(report._rule(f"Erste {min(args.show, len(comparison.missed_routes))} verpasste Routen ({focus_dataset}, "
                                  f"{focus_scenario.label}, cap {focus_cap})"))
        for i, route in enumerate(comparison.missed_routes[:args.show]):
            lines.append(report.route_line(i + 1, route, distances, day0_by_dataset[focus_dataset], comparison.missed_info[i]))
        if len(lines) > args.max_lines:
            lines = lines[:args.max_lines - 1] + [f"... gekürzt auf {args.max_lines} Zeilen; siehe {files.get('routes_missed.txt')}"]
    print('\n'.join(lines))
    if args.pager and 'routes_missed.txt' in files:
        return open_pager(files['routes_missed.txt'])
    return 0


def _run_jobs(jobs: List[worker.Job], n_workers: int, n_scenarios: int) -> List[worker.JobResult]:
    """Run every job, in-process (fine-grained progress) or in a process pool (progress per dataset).
    Postcondition: results in the same order as ``jobs``; a failing job aborts the run with its error."""
    if n_workers <= 1:
        progress = Progress(total=len(jobs) * n_scenarios * 2)
        try:
            return [worker.process(job, progress) for job in jobs]
        finally:
            progress.finish()
    progress = Progress(total=len(jobs))
    by_name: Dict[str, worker.JobResult] = {}
    try:
        with multiprocessing.get_context('forkserver' if hasattr(os, 'fork') else 'spawn').Pool(n_workers) as pool:
            for result in pool.imap_unordered(worker.process_quiet, jobs):
                by_name[result.name] = result
                progress.step(f"{result.name} fertig ({len(by_name)}/{len(jobs)} Datensätze, {n_workers} Prozesse)")
    finally:
        progress.finish()
    return [by_name[job.dataset.name] for job in jobs]


# --- show ----------------------------------------------------------------------------------------------------

def resolve_target(target: str, file_name: str, out_dir: Path) -> Path:
    """A routes file, a run directory, or a run id under ``out_dir`` -> the routes file."""
    path = Path(target)
    if path.is_file():
        return path
    if path.is_dir():
        return path / file_name
    candidate = out_dir / target
    if candidate.is_dir():
        return candidate / file_name
    raise SystemExit(f"cannot resolve {target!r}: not a file, directory or run id under {out_dir}")


def open_pager(path: Path) -> int:
    if shutil.which('less') is None:
        raise SystemExit(f"'less' is not installed; open the file yourself: {path}")
    if not sys.stdout.isatty():
        print(f"(no TTY, pager skipped) {path}")
        return 0
    return subprocess.call(['less', '-S', str(path)])


def cmd_show(args: argparse.Namespace) -> int:
    path = resolve_target(args.target, args.file, args.out_dir)
    if not path.exists():
        raise SystemExit(f"file not found: {path}")
    if args.pager:
        return open_pager(path)
    shown = 0
    with path.open('r', encoding='utf-8') as handle:
        for line in handle:
            line = line.rstrip('\n')
            if line.startswith('#'):
                print(line)
                continue
            if shown >= args.show:
                break
            print(line)
            shown += 1
    print(f"({shown} Routen gezeigt; Datei: {path})")
    return 0


# --- selftest ------------------------------------------------------------------------------------------------

def cmd_selftest(args: argparse.Namespace) -> int:
    from simulate.tests.runner import run_all
    outcomes = run_all()
    for name, ok, message in outcomes:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  {message}")
    failed = sum(1 for _, ok, _ in outcomes if not ok)
    print(f"{len(outcomes) - failed}/{len(outcomes)} checks passed")
    return 1 if failed else 0


# --- entry -----------------------------------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in SUBCOMMANDS and argv[0] not in ('-h', '--help'):
        argv.insert(0, 'run')
    args = build_parser().parse_args(argv)
    handlers = {'run': cmd_run, 'show': cmd_show, 'selftest': cmd_selftest}
    return handlers[args.command](args)
