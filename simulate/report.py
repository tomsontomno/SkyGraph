"""Output side of the simulation: route files, summary.json, summary.md and the terminal view.

Terminal rule: never more than TERMINAL_MAX_LINES lines per invocation; everything complete goes
to files under data/sim/<run-id>/.
"""
from __future__ import annotations

import json
import random
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from simulate.analyze import Comparison, local_day, missed_tag
from simulate.routefmt import format_route_light

TERMINAL_MAX_LINES = 150
RULE = '─'
#: A real dataset with fewer fixed routes than this is too small to judge the depth hypothesis on.
MIN_ROUTES_FOR_VERDICT = 30


def hypothesis_verdict(summary: dict, scenario_key: str, cap: str, real_names: Sequence[str]) -> str:
    """'bestätigt' when both pooled ratios (3+ vs 1-2 flights, day 2+ vs day 0-1) exceed 1.

    Judged on the synthetic median when synthetic nets exist (20 nets beat one scan), otherwise on
    the real datasets that have at least MIN_ROUTES_FOR_VERDICT fixed routes.
    """
    agg = _get(summary['aggregate_synth'], scenario_key, cap, default={})
    ratios = [_get(agg, 'depth_test', 'ratio_depth', 'median'), _get(agg, 'depth_test', 'ratio_day', 'median')]
    basis = 'synth-Median'
    if not agg:
        ratios = []
        for name in real_names:
            s = _get(summary['results'], name, scenario_key, cap, default={})
            if (s.get('n_fixed') or 0) >= MIN_ROUTES_FOR_VERDICT:
                ratios += [_get(s, 'depth_test', 'ratio_depth'), _get(s, 'depth_test', 'ratio_day')]
        basis = f"echte Scans mit ≥{MIN_ROUTES_FOR_VERDICT} Routen"
    known = [r for r in ratios if r is not None]
    if not known:
        return 'keine belastbaren Daten'
    if all(r > 1 for r in known):
        return f"bestätigt ({basis})"
    if all(r <= 1 for r in known):
        return f"widerlegt ({basis})"
    return f"teilweise: Tiefe {'ja' if known[0] > 1 else 'nein'}, Tag {'ja' if len(known) > 1 and known[1] > 1 else 'nein'} ({basis})"


# --- number formatting ---------------------------------------------------------------------------------

def fmt_num(value, digits: int = 0) -> str:
    if value is None:
        return '–'
    if digits == 0:
        return f"{int(round(value))}"
    return f"{value:.{digits}f}"


def fmt_agg(agg: Optional[dict], digits: int = 0) -> str:
    """``median [min–max]`` for an aggregate leaf, '–' when absent."""
    if not agg:
        return '–'
    return f"{fmt_num(agg['median'], digits)} [{fmt_num(agg['min'], digits)}–{fmt_num(agg['max'], digits)}]"


def fmt_factor(value) -> str:
    return '–' if value is None else f"x{value:.1f}"


def _get(d: dict, *path, default=None):
    for key in path:
        if not isinstance(d, dict) or key not in d:
            return default
        d = d[key]
    return d


# --- route files -----------------------------------------------------------------------------------------

def route_line(index: int, route, distances: dict, day0: date, info: Optional[dict] = None) -> str:
    tag = f"flights={len(route)} last_dep=T{local_day(route[-1][2][0], day0)}"
    if info is not None:
        tag += ' ' + missed_tag(info)
    return f"{index:6d}  {format_route_light(route, distances)}  | {tag}"


def write_routes_file(path: Path, header: Sequence[str], routes: Sequence, distances: dict, day0: date,
                      infos: Optional[Sequence[dict]] = None) -> None:
    """Write one route per line (light format + tag).  Precondition: ``infos`` parallel to ``routes``
    when given.  Postcondition: file exists, first lines are ``# ``-prefixed header lines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as handle:
        for line in header:
            handle.write(f"# {line}\n")
        handle.write(f"# {len(routes)} routes\n")
        for i, route in enumerate(routes):
            info = infos[i] if infos is not None else None
            handle.write(route_line(i + 1, route, distances, day0, info) + '\n')


def write_comparison_files(directory: Path, comparison: Comparison, distances: dict, day0: date,
                           header: Sequence[str]) -> Dict[str, Path]:
    files = {
        'routes_original.txt': (comparison.orig_routes, None),
        'routes_fixed.txt': (comparison.fixed_routes, None),
        'routes_missed.txt': (comparison.missed_routes, comparison.missed_info),
    }
    written = {}
    for name, (routes, infos) in files.items():
        path = directory / name
        write_routes_file(path, list(header) + [f"file: {name}"], routes, distances, day0, infos)
        written[name] = path
    return written


def sample_missed(comparison: Comparison, n: int, seed: int) -> List[Tuple[int, object, dict]]:
    """Deterministic random sample of missed routes: ``(index_in_missed_file, route, info)``."""
    total = len(comparison.missed_routes)
    if total == 0 or n <= 0:
        return []
    picks = sorted(random.Random(seed).sample(range(total), min(n, total)))
    return [(i + 1, comparison.missed_routes[i], comparison.missed_info[i]) for i in picks]


# --- summary.json ----------------------------------------------------------------------------------------

def write_summary_json(path: Path, summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=1, default=_json_default)


def _json_default(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"cannot serialise {type(value).__name__}")


# --- terminal ----------------------------------------------------------------------------------------------

def _rule(title: str, width: int = 110) -> str:
    text = f"{RULE * 2} {title} "
    return text + RULE * max(0, width - len(text))


def _pct_row(values: Sequence[Optional[float]]) -> str:
    return '|'.join(fmt_num(v) for v in values)


def _scenario_block(summary: dict, scenario: dict, real_names: Sequence[str]) -> List[str]:
    key = scenario['key']
    cap_modes = summary['cap_modes']
    agg_sc = summary['aggregate_synth'].get(key, {})
    results = summary['results']
    max_flights = summary['run']['settings']['max_flights']
    n_days = summary['run']['settings']['n_days']
    has_synth = bool(agg_sc)
    lines = [_rule(scenario['label'])]

    head = f"{'Cap':<10}"
    if has_synth:
        head += f"{'Synth Orig → Fix (Median [Min–Max])':<44}{'Faktor':<20}{'Verpasst%':<14}"
    for name in real_names:
        head += f"| {name}: Orig→Fix Faktor Verpasst%  "
    lines.append(head.rstrip())
    for cap in cap_modes:
        row = f"{cap:<10}"
        if has_synth:
            a = agg_sc.get(cap, {})
            row += (f"{fmt_agg(a.get('n_orig')) + ' → ' + fmt_agg(a.get('n_fixed')):<44}"
                    f"{fmt_agg(a.get('factor'), 1):<20}{fmt_agg(a.get('pct_missed')):<14}")
        for name in real_names:
            s = _get(results, name, key, cap, default={})
            pct = s.get('pct_missed')
            row += (f"| {fmt_num(s.get('n_orig'))}→{fmt_num(s.get('n_fixed'))} "
                    f"{fmt_factor(s.get('factor'))} {fmt_num(pct) + '%' if pct is not None else '–'}  ")
        lines.append(row.rstrip())

    flights_label = '|'.join(str(k) for k in range(1, max_flights + 1))
    days_label = '|'.join(f"T{d}" for d in range(n_days))
    for cap in cap_modes:
        parts = []
        if has_synth:
            a = agg_sc.get(cap, {})
            parts.append('synth ' + _pct_row([_get(a, 'by_flights', str(k), 'pct_missed', 'median')
                                              for k in range(1, max_flights + 1)]))
        for name in real_names:
            s = _get(results, name, key, cap, default={})
            parts.append(f"{name} " + _pct_row([_get(s, 'by_flights', str(k), 'pct_missed')
                                                for k in range(1, max_flights + 1)]))
        expected_src = agg_sc.get(cap, {}) if has_synth else _get(results, real_names[0], key, cap, default={})
        expected = [_get(expected_src, 'by_flights', str(k), 'expected_pct_missed', 'median')
                    if has_synth else _get(expected_src, 'by_flights', str(k), 'expected_pct_missed')
                    for k in range(1, max_flights + 1)]
        parts.append('Erwartung 1-(1-p)^k ' + _pct_row(expected))
        lines.append(f"Verpasst% nach Flügen ({flights_label}) {cap:<9} " + ' · '.join(parts))
    for cap in cap_modes:
        parts = []
        if has_synth:
            a = agg_sc.get(cap, {})
            parts.append('synth ' + _pct_row([_get(a, 'by_day', str(d), 'pct_missed', 'median') for d in range(n_days)]))
        for name in real_names:
            s = _get(results, name, key, cap, default={})
            parts.append(f"{name} " + _pct_row([_get(s, 'by_day', str(d), 'pct_missed') for d in range(n_days)]))
        lines.append(f"Verpasst% nach Tag ({days_label}) {cap:<9} " + ' · '.join(parts))

    for cap in cap_modes:
        parts = []
        if has_synth:
            a = agg_sc.get(cap, {})
            parts.append(f"synth {fmt_factor(_get(a, 'depth_test', 'ratio_depth', 'median'))}"
                         f"/{fmt_factor(_get(a, 'depth_test', 'ratio_day', 'median'))}")
        for name in real_names:
            s = _get(results, name, key, cap, default={})
            small = (s.get('n_fixed') or 0) < MIN_ROUTES_FOR_VERDICT
            parts.append(f"{name} {fmt_factor(_get(s, 'depth_test', 'ratio_depth'))}"
                         f"/{fmt_factor(_get(s, 'depth_test', 'ratio_day'))}{' (n<' + str(MIN_ROUTES_FOR_VERDICT) + ')' if small else ''}")
        lines.append(f"Hypothese (3+ vs 1–2 Flüge / Tag2+ vs Tag0–1) {cap:<9} " + ' · '.join(parts)
                     + f" → {hypothesis_verdict(summary, key, cap, real_names)}")

    for cap in cap_modes:
        src = agg_sc.get(cap, {}) if has_synth else _get(results, real_names[0], key, cap, default={})
        label = 'synth-Median' if has_synth else real_names[0]
        mc = src.get('missed_class', {})
        if has_synth:
            pos = [_get(mc, 'first_invisible_pos_hist_pct', str(k), 'median') for k in range(1, max_flights + 1)]
            later, new_it, prefix, inv = (_get(mc, 'pct_later_day_any', 'median'), _get(mc, 'pct_new_itinerary', 'median'),
                                          _get(mc, 'pct_prefix_known', 'median'), _get(mc, 'pct_with_invisible', 'median'))
        else:
            pos = [_get(mc, 'first_invisible_pos_hist_pct', str(k)) for k in range(1, max_flights + 1)]
            later, new_it, prefix, inv = (mc.get('pct_later_day_any'), mc.get('pct_new_itinerary'),
                                          mc.get('pct_prefix_known'), mc.get('pct_with_invisible'))
        lines.append(f"Verpasste Routen ({cap}, {label}): unsichtbarer Flug {fmt_num(inv)}% · erste unsichtbare Pos "
                     f"{flights_label}: {_pct_row(pos)}% · Später-Tag-Flug {fmt_num(later)}% · neue Städtefolge "
                     f"{fmt_num(new_it)}% · Präfix bekannt {fmt_num(prefix)}%")
    return lines


def _extremes_block(summary: dict, name: str, scenario_key: str, cap: str) -> List[str]:
    s = _get(summary['results'], name, scenario_key, cap, default={})
    scenario_label = next((sc['label'] for sc in summary['scenarios'] if sc['key'] == scenario_key), scenario_key)
    lines = [_rule(f"Extremwerte {name}, {scenario_label}, cap {cap}  (* = vom Original verpasst)")]
    for key, entry in s.get('extremes', {}).items():
        label = entry['label']
        for side, tag in (('orig', 'Orig'), ('fixed', 'Fix ')):
            e = entry.get(side)
            if e is None:
                lines.append(f"{label:<44} {tag} –: keine Route")
                continue
            star = '*' if e.get('is_missed') else ''
            value = e['value']
            value_str = f"{value:.1f}" if isinstance(value, float) and not float(value).is_integer() else f"{int(value)}"
            lines.append(f"{label:<44} {tag} {value_str}{star}: {e['route']}")
    return lines


def _sample_block(name: str, scenario_label: str, cap: str, sample, n_missed: int, seed: int,
                  distances: dict, day0: date) -> List[str]:
    lines = [_rule(f"Stichprobe verpasster Routen {name}, {scenario_label}, cap {cap}: "
                   f"{len(sample)} von {n_missed} (seed {seed})")]
    for index, route, info in sample:
        lines.append(f"#{index:<5d} {format_route_light(route, distances)}  | {missed_tag(info)}")
    if not sample:
        lines.append("(keine verpassten Routen)")
    return lines


def render_terminal(summary: dict, real_names: Sequence[str], focus: dict, samples: dict,
                    files: Dict[str, Path], distances: dict, day0_by_dataset: Dict[str, date],
                    max_lines: int = TERMINAL_MAX_LINES) -> List[str]:
    """Assemble the terminal view; hard-capped at ``max_lines`` (a notice replaces the overflow)."""
    run = summary['run']
    settings = run['settings']
    synth_names = [n for n, d in summary['datasets'].items() if d['kind'] == 'synth']
    net = summary.get('network_aggregate_synth', {})
    lines = [
        f"SkyGraph Bug-Impact  run {run['run_id']}  |  {len(synth_names)} Synth-Netze + {len(real_names)} echte Scans"
        f"  |  Start {settings['start']}, max {settings['max_flights']} Flüge, flex {settings['flex_km']} km, "
        f"Cap {settings['daily_cap']} ({', '.join(m for m in summary['cap_modes'] if m != 'none') or '–'})",
    ]
    net_parts = []
    if synth_names:
        net_parts.append(f"synth Median {fmt_num(_get(net, 'n_cities', 'median'))} Städte, "
                         f"{fmt_num(_get(net, 'n_edges', 'median'))} Strecken, {fmt_num(_get(net, 'n_flights', 'median'))} Flüge, "
                         f"{fmt_num(100 * (_get(net, 'invisible_share', 'median') or 0))}% unsichtbar")
    for name in real_names:
        st = summary['datasets'][name]['stats']
        net_parts.append(f"{name}: {st['n_cities']}/{st['n_edges']}/{st['n_flights']}, "
                         f"{fmt_num(100 * st['invisible_share'])}% unsichtbar, Tag0 {st['day0']}")
    lines.append('Netze: ' + ' | '.join(net_parts))
    lines.append('')
    for scenario in summary['scenarios']:
        lines += _scenario_block(summary, scenario, real_names)
        lines.append('')
    for name in real_names:
        lines += _extremes_block(summary, name, focus['scenario'], focus['cap'])
        lines.append('')
    scenario_label = next((sc['label'] for sc in summary['scenarios'] if sc['key'] == focus['scenario']),
                          focus['scenario'])
    for name in real_names:
        sample, n_missed = samples.get(name, ([], 0))
        lines += _sample_block(name, scenario_label, focus['cap'], sample, n_missed, run['settings']['random_seed'],
                               distances, day0_by_dataset[name])
        lines.append('')
    lines.append(_rule('Dateien'))
    for label, path in files.items():
        lines.append(f"{label:<18} {path}")
    if len(lines) > max_lines:
        keep = max_lines - 1
        lines = lines[:keep] + [f"... {len(lines) - keep} weitere Zeilen unterdrückt (Terminal-Limit {max_lines}); "
                                f"alles steht in {files.get('summary.md', 'summary.md')}"]
    return lines


# --- summary.md --------------------------------------------------------------------------------------------

def _md_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> List[str]:
    out = ['| ' + ' | '.join(headers) + ' |', '|' + '|'.join('---' for _ in headers) + '|']
    for row in rows:
        out.append('| ' + ' | '.join(str(c) for c in row) + ' |')
    return out


def write_summary_md(path: Path, summary: dict, real_names: Sequence[str]) -> None:
    run = summary['run']
    settings = run['settings']
    max_flights, n_days = settings['max_flights'], settings['n_days']
    cap_modes = summary['cap_modes']
    results = summary['results']
    agg = summary['aggregate_synth']
    synth_names = [n for n, d in summary['datasets'].items() if d['kind'] == 'synth']
    has_synth = bool(synth_names)
    md: List[str] = [f"# SkyGraph Bug-Impact-Simulation – run {run['run_id']}", '',
                     f"Erstellt {run['created']}  ", f"Kommando: `{run['command']}`", '',
                     '## Einstellungen', '']
    for k, v in settings.items():
        md.append(f"- {k}: {v}")
    md += ['', '## Netze', '']
    rows = []
    if has_synth:
        net = summary['network_aggregate_synth']
        rows.append([f"synth ({len(synth_names)} Seeds, Median [Min–Max])", fmt_agg(net.get('n_cities')),
                     fmt_agg(net.get('n_edges')), fmt_agg(net.get('n_flights')),
                     fmt_agg({k: 100 * v for k, v in net['invisible_share'].items()} if net.get('invisible_share') else None, 1),
                     fmt_agg(net.get('hub_weight_spearman'), 2), '–'])
    for name in real_names:
        st = summary['datasets'][name]['stats']
        rows.append([f"{name} ({summary['datasets'][name]['source']})", st['n_cities'], st['n_edges'], st['n_flights'],
                     f"{100 * st['invisible_share']:.1f}", fmt_num(st.get('hub_weight_spearman'), 2), st['day0']])
    md += _md_table(['Datensatz', 'Städte', 'Strecken', 'Flüge', 'unsichtbar %', 'Hub-Spearman', 'Tag 0'], rows)
    if has_synth:
        net = summary['network_aggregate_synth']
        md += ['', 'Synth: Flüge pro Tag (Median) ' + ', '.join(
            f"T{i}={fmt_num(_get(net, 'flights_by_day', str(i), 'median'))}" for i in range(n_days)) +
               '; sichtbar pro Tag (Median) ' + ', '.join(
            f"T{i}={fmt_num(100 * (_get(net, 'visible_share_by_day', str(i), 'median') or 0))}%" for i in range(n_days))]
    for name in real_names:
        st = summary['datasets'][name]['stats']
        md.append(f"{name}: Flüge pro Tag {st['flights_by_day']}, unsichtbar pro Tag {st['invisible_by_day']}, "
                  f"Flüge pro Strecke {st['flights_per_edge']}, Hub-Hub/Hub-Spoke/Spoke-Spoke "
                  f"{st['edges_hub_hub']}/{st['edges_hub_spoke']}/{st['edges_spoke_spoke']}, "
                  f"Reziprozität {st['reciprocity']}")

    for scenario in summary['scenarios']:
        key = scenario['key']
        md += ['', f"## Szenario {scenario['label']}", '']
        for cap in cap_modes:
            md += [f"### Cap: {cap}", '']
            a = _get(agg, key, cap, default={})
            rows = []
            if has_synth:
                rows.append(['synth Median [Min–Max]', fmt_agg(a.get('n_orig')), fmt_agg(a.get('n_fixed')),
                             fmt_agg(a.get('factor'), 2), fmt_agg(a.get('pct_missed'), 1),
                             fmt_agg(_get(a, 'reach', 'n_end_only_fixed')), fmt_agg(_get(a, 'reach', 'n_visited_only_fixed'))])
            for name in real_names:
                s = _get(results, name, key, cap, default={})
                rows.append([name, s.get('n_orig'), s.get('n_fixed'), fmt_num(s.get('factor'), 2), fmt_num(s.get('pct_missed'), 1),
                             _get(s, 'reach', 'n_end_only_fixed'), _get(s, 'reach', 'n_visited_only_fixed')])
            md += _md_table(['Datensatz', 'Orig', 'Fix', 'Faktor', 'Verpasst %', 'Endstädte nur Fix', 'Städte nur Fix'], rows)
            md += ['', '**Tiefen-Effekt nach Anzahl Flüge** (Verpasst % = verpasste / Fix-Routen)', '']
            headers = ['Flüge'] + (['synth Fix (Med)', 'synth Verpasst % (Med [Min–Max])'] if has_synth else []) + \
                      ['Erwartung 1-(1-p)^k %'] + [f"{n} Orig/Fix/Verpasst %" for n in real_names]
            rows = []
            for k in range(1, max_flights + 1):
                row = [k]
                if has_synth:
                    row += [fmt_agg(_get(a, 'by_flights', str(k), 'fixed')), fmt_agg(_get(a, 'by_flights', str(k), 'pct_missed'), 1)]
                    row.append(fmt_agg(_get(a, 'by_flights', str(k), 'expected_pct_missed'), 1))
                else:
                    row.append(fmt_num(_get(results, real_names[0], key, cap, 'by_flights', str(k), 'expected_pct_missed'), 1))
                for name in real_names:
                    b = _get(results, name, key, cap, 'by_flights', str(k), default={})
                    row.append(f"{b.get('orig')}/{b.get('fixed')}/{fmt_num(b.get('pct_missed'), 1)}")
                rows.append(row)
            md += _md_table(headers, rows)
            md += ['', '**Tiefen-Effekt nach Kalendertag des letzten Abflugs**', '']
            headers = ['Tag'] + (['synth Fix (Med)', 'synth Verpasst % (Med [Min–Max])'] if has_synth else []) + \
                      [f"{n} Orig/Fix/Verpasst %" for n in real_names]
            rows = []
            for d in range(n_days):
                row = [f"T{d}"]
                if has_synth:
                    row += [fmt_agg(_get(a, 'by_day', str(d), 'fixed')), fmt_agg(_get(a, 'by_day', str(d), 'pct_missed'), 1)]
                for name in real_names:
                    b = _get(results, name, key, cap, 'by_day', str(d), default={})
                    row.append(f"{b.get('orig')}/{b.get('fixed')}/{fmt_num(b.get('pct_missed'), 1)}")
                rows.append(row)
            md += _md_table(headers, rows)
            for name in real_names:
                s = _get(results, name, key, cap, default={})
                md += ['', f"Kreuztabelle {name}: Flüge × Tag letzter Abflug (verpasst/Fix, Verpasst %)", '']
                rows = []
                for k in range(1, max_flights + 1):
                    row = [k]
                    for d in range(n_days):
                        c = _get(s, 'by_flights_day', f"{k}x{d}", default={})
                        row.append(f"{c.get('missed', 0)}/{c.get('fixed', 0)} ({fmt_num(c.get('pct_missed'))}%)")
                    rows.append(row)
                md += _md_table(['Flüge \\ Tag'] + [f"T{d}" for d in range(n_days)], rows)
            md += ['', '**Hypothesen-Test** (Verpasst % gepoolt)', '']
            rows = []
            if has_synth:
                dt = a.get('depth_test', {})
                rows.append(['synth Median', fmt_agg(dt.get('pct_missed_3plus'), 1), fmt_agg(dt.get('pct_missed_1to2'), 1),
                             fmt_agg(dt.get('ratio_depth'), 2), fmt_agg(dt.get('pct_missed_day2plus'), 1),
                             fmt_agg(dt.get('pct_missed_day01'), 1), fmt_agg(dt.get('ratio_day'), 2)])
            for name in real_names:
                dt = _get(results, name, key, cap, 'depth_test', default={})
                rows.append([name, fmt_num(dt.get('pct_missed_3plus'), 1), fmt_num(dt.get('pct_missed_1to2'), 1),
                             fmt_num(dt.get('ratio_depth'), 2), fmt_num(dt.get('pct_missed_day2plus'), 1),
                             fmt_num(dt.get('pct_missed_day01'), 1), fmt_num(dt.get('ratio_day'), 2)])
            md += _md_table(['Datensatz', '3+ Flüge', '1–2 Flüge', 'Faktor', 'Tag 2+', 'Tag 0–1', 'Faktor'], rows)
            md += ['', '**Art der verpassten Routen** (Anteile in % der verpassten Routen)', '']
            fields = [('pct_with_invisible', 'enthält unsichtbaren Flug'), ('pct_later_day_any', 'mind. ein Später-Tag-Flug derselben Strecke'),
                      ('pct_later_day_all', 'alle unsichtbaren Flüge sind Später-Tag-Flüge'), ('pct_same_day_only', 'nur Gleicher-Tag-spätere Flüge'),
                      ('pct_only_last_leg_invisible', 'nur letzter Flug unsichtbar'), ('pct_prefix_known', 'Präfix (Route ohne letzten Flug) kannte das Original'),
                      ('pct_new_itinerary', 'Städtefolge im Original gar nicht vorhanden')]
            rows = []
            for field, label in fields:
                row = [label]
                if has_synth:
                    row.append(fmt_agg(_get(a, 'missed_class', field), 1))
                for name in real_names:
                    row.append(fmt_num(_get(results, name, key, cap, 'missed_class', field), 1))
                rows.append(row)
            for k in range(1, max_flights + 1):
                row = [f"erste unsichtbare Position = {k}"]
                if has_synth:
                    row.append(fmt_agg(_get(a, 'missed_class', 'first_invisible_pos_hist_pct', str(k)), 1))
                for name in real_names:
                    row.append(fmt_num(_get(results, name, key, cap, 'missed_class', 'first_invisible_pos_hist_pct', str(k)), 1))
                rows.append(row)
            for k in range(1, max_flights + 1):
                row = [f"Position {k} unsichtbar (Routen mit ≥{k} Flügen)"]
                if has_synth:
                    row.append(fmt_agg(_get(a, 'missed_class', 'invisible_share_by_position', str(k), 'pct'), 1))
                for name in real_names:
                    row.append(fmt_num(_get(results, name, key, cap, 'missed_class', 'invisible_share_by_position', str(k), 'pct'), 1))
                rows.append(row)
            md += _md_table(['Merkmal'] + (['synth Median [Min–Max]'] if has_synth else []) + list(real_names), rows)
            md += ['', '**Extremwerte**', '']
            if has_synth:
                labels = _extreme_labels(results, real_names, key, cap)
                rows = [[labels.get(ekey, ekey), fmt_agg(_get(entry, 'orig', 'value'), 1), fmt_agg(_get(entry, 'fixed', 'value'), 1)]
                        for ekey, entry in _get(a, 'extremes', default={}).items()]
                md += ['synth (Median [Min–Max] des Metrikwerts):', ''] + _md_table(['Metrik', 'Orig', 'Fix'], rows)
            for name in real_names:
                s = _get(results, name, key, cap, default={})
                md += ['', f"{name} (* = vom Original verpasst):", '']
                rows = []
                for ekey, entry in s.get('extremes', {}).items():
                    cells = [entry['label']]
                    for side in ('orig', 'fixed'):
                        e = entry.get(side)
                        if e is None:
                            cells.append('keine Route')
                        else:
                            star = '*' if e.get('is_missed') else ''
                            extra = f" (neue Länder: {', '.join(e['new_country_names'])})" if ekey == 'most_new_countries' and e['new_country_names'] else ''
                            cells.append(f"**{e['value']}{star}** {e['route']}{extra}")
                    rows.append(cells)
                md += _md_table(['Metrik', 'Orig', 'Fix'], rows)
                unknown = s.get('unknown_cities') or []
                if unknown:
                    md.append(f"\nStädte ohne Eintrag in preferences.json (zählen nicht als Land): {', '.join(unknown)}")
            md += ['', '**Erreichbarkeit** (nur mit dem Fix)', '']
            for name in real_names:
                r = _get(results, name, key, cap, 'reach', default={})
                md.append(f"- {name}: Endstädte nur Fix ({r.get('n_end_only_fixed')}): "
                          f"{', '.join(r.get('end_only_fixed', [])) or '–'}; Städte überhaupt nur Fix "
                          f"({r.get('n_visited_only_fixed')}): {', '.join(r.get('visited_only_fixed', [])) or '–'}")
            md.append('')
    md += ['## Dateien', ''] + [f"- {label}: `{p}`" for label, p in summary['files'].items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(md) + '\n', encoding='utf-8')


def _extreme_labels(results: dict, real_names: Sequence[str], key: str, cap: str) -> Dict[str, str]:
    for name in real_names:
        s = _get(results, name, key, cap, default={})
        if s.get('extremes'):
            return {k: v['label'] for k, v in s['extremes'].items()}
    for name, per_dataset in results.items():
        s = _get(per_dataset, key, cap, default={})
        if s.get('extremes'):
            return {k: v['label'] for k, v in s['extremes'].items()}
    return {}
