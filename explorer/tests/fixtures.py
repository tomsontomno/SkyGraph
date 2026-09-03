"""Shared fixtures for the explorer checks."""
from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import List, Tuple

import networkx as nx

from simulate import datasets, synth

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def graph_from(edges: List[Tuple[str, str, str, str]]) -> nx.DiGraph:
    """Build a flight graph from ``(origin, dest, departure_iso, arrival_iso)`` tuples."""
    graph = nx.DiGraph()
    for origin, dest, dep, arr in edges:
        if not graph.has_edge(origin, dest):
            graph.add_edge(origin, dest, flights=[])
        graph[origin][dest]['flights'].append([dep, arr])
    for _, _, attrs in graph.edges(data=True):
        attrs['flights'].sort(key=lambda f: f[0])
    return graph


def midnight_graph() -> nx.DiGraph:
    """A four flight round trip whose legality depends on how days are counted.

    Departures in UTC are 19:00, 00:00, 03:00, 05:00 - four inside ten hours, so ``rolling24`` with
    cap 3 rejects the loop.  In local calendar days they are 13.03, 14.03, 14.03, 14.03, so
    ``calendar`` with cap 3 accepts it.  In UTC calendar days they would be 13., 13., 14., 14., so a
    cap of 2 on local days must still reject the loop - that is what pins the grouping to the local
    date of the departure airport.
    """
    return graph_from([
        ('Dortmund', 'Bucharest', '2025-03-13T20:00:00+01:00', '2025-03-14T00:30:00+02:00'),
        ('Bucharest', 'Sofia', '2025-03-14T02:00:00+02:00', '2025-03-14T03:00:00+02:00'),
        ('Sofia', 'Vienna', '2025-03-14T05:00:00+02:00', '2025-03-14T05:00:00+01:00'),
        ('Vienna', 'Dortmund', '2025-03-14T06:00:00+01:00', '2025-03-14T07:30:00+01:00'),
    ])


def small_synth_graph(seed: int = 0) -> nx.DiGraph:
    """A small synthetic Wizz-style net (from simulate.synth, so it is seedable and offline)."""
    return synth.to_graph(synth.generate_network(seed, synth.SynthParams(n_spokes=20, target_edges=110), None))


def real_graph(which: str = 'pkl') -> nx.DiGraph:
    """One of the real scans in data/current/ (read-only)."""
    if which == 'pkl':
        with datasets.GRAPH_PKL.open('rb') as handle:
            return pickle.load(handle)
    if which == 'json':
        with datasets.FLIGHT_GRAPH_JSON.open('r', encoding='utf-8') as handle:
            return synth.to_graph(json.load(handle))
    raise ValueError(f"unknown scan {which!r}, expected 'pkl' or 'json'")
