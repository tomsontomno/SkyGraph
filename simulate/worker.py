"""Per-dataset work unit (runs in the main process or in a multiprocessing worker)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from simulate import analyze, datasets, report
from simulate import route_find_fixed, route_find_original


@dataclass
class Job:
    dataset: datasets.Dataset
    scenarios: List[analyze.Scenario]
    params: analyze.SearchParams
    cap_modes: List[str]
    daily_cap: int
    n_days: int
    city_data: dict
    country_data: dict
    distances: dict
    run_id: str
    route_dir: Optional[Path]          # where to write route files (None = don't write)
    keep_comparisons: bool             # return Comparison objects (needed for terminal samples)


@dataclass
class JobResult:
    name: str
    results: Dict[str, Dict[str, dict]] = field(default_factory=dict)      # scenario -> cap -> stats
    comparisons: Dict[Tuple[str, str], analyze.Comparison] = field(default_factory=dict)
    day0: Optional[date] = None
    written: List[Path] = field(default_factory=list)


def sanity(stats: dict, dataset: str, scenario: str, cap: str) -> None:
    """The two searches must be nested and every missed route must contain an invisible flight."""
    where = f"{dataset} / {scenario} / cap {cap}"
    if stats['n_orig_not_in_fixed'] != 0:
        raise AssertionError(f"{where}: {stats['n_orig_not_in_fixed']} original routes are missing in the fixed search")
    mc = stats['missed_class']
    if mc['n'] and mc['with_invisible'] != mc['n']:
        raise AssertionError(f"{where}: {mc['n'] - mc['with_invisible']} missed routes contain no invisible flight")


def process(job: Job, progress=None) -> JobResult:
    """Search + compare one dataset for every scenario and cap mode.

    Precondition: ``job.dataset.stats['day0']`` set (datasets.py guarantees it); ``progress`` (optional)
    has ``step(message)``.  Postcondition: ``JobResult.results`` holds JSON-serialisable stats for every
    (scenario, cap); route files were written under ``job.route_dir`` when given.
    """
    ds = job.dataset
    day0 = date.fromisoformat(ds.stats['day0'])
    out = JobResult(name=ds.name, day0=day0)
    for scenario in job.scenarios:
        if progress is not None:
            progress.step(f"{ds.name} {scenario.key} original")
        orig_routes = analyze.run_search(route_find_original, ds.graph, scenario, job.params)
        if progress is not None:
            progress.step(f"{ds.name} {scenario.key} fixed")
        fixed_routes = analyze.run_search(route_find_fixed, ds.graph, scenario, job.params)
        orig = analyze.prepare(orig_routes, day0, job.city_data, job.country_data)
        fixed = analyze.prepare(fixed_routes, day0, job.city_data, job.country_data)
        leg_cache: Dict[int, dict] = {}
        out.results[scenario.key] = {}
        for cap in job.cap_modes:
            comparison = analyze.compare(
                ds.graph, orig, fixed, day0=day0, n_days=job.n_days, max_flights=job.params.max_flights,
                invisible_share=ds.stats['invisible_share'], cap=job.daily_cap, cap_mode=cap,
                distances=job.distances, city_data=job.city_data, leg_cache=leg_cache)
            sanity(comparison.stats, ds.name, scenario.key, cap)
            out.results[scenario.key][cap] = comparison.stats
            if job.keep_comparisons:
                out.comparisons[(scenario.key, cap)] = comparison
            if job.route_dir is not None:
                header = [f"dataset: {ds.name} ({ds.source})", f"scenario: {scenario.label}",
                          f"cap: {cap}" + (f" ({job.daily_cap}/day)" if cap != 'none' else ''),
                          f"start: {job.params.start}", f"max_flights: {job.params.max_flights}", f"run: {job.run_id}"]
                written = report.write_comparison_files(job.route_dir / f"{scenario.key}_{cap}", comparison,
                                                        job.distances, day0, header)
                out.written += list(written.values())
    return out


def process_quiet(job: Job) -> JobResult:
    """Pool entry point (no progress object crosses the process boundary)."""
    return process(job, progress=None)
