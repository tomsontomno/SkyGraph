"""Datasets for the simulation: real scans from data/current/ (read-only) and synthetic networks."""
from __future__ import annotations

import json
import pickle
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import networkx as nx

from simulate import synth

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "current"
DISTANCES_FILE = DATA_DIR / "distances.json"
EDGES_FILE = DATA_DIR / "edges.json"
PREFERENCES_FILE = DATA_DIR / "preferences.json"
GRAPH_PKL = DATA_DIR / "graph.pkl"
FLIGHT_GRAPH_JSON = DATA_DIR / "flight_graph.json"
DEFAULT_REAL_FILES = (GRAPH_PKL, FLIGHT_GRAPH_JSON)


@dataclass
class Dataset:
    """One flight graph plus provenance.  ``kind`` is 'synth' or 'real'."""
    name: str
    kind: str
    graph: nx.DiGraph
    source: str
    seed: Optional[int] = None
    flight_json: Optional[synth.FlightJson] = None
    stats: dict = field(default_factory=dict)


def _validate_graph(graph: nx.DiGraph, source: str) -> None:
    """Every edge must carry a non-empty ``flights`` list of ``[dep, arr]`` ISO strings with offsets."""
    if not isinstance(graph, nx.DiGraph):
        raise ValueError(f"{source}: expected an nx.DiGraph, got {type(graph).__name__}")
    if graph.number_of_edges() == 0:
        raise ValueError(f"{source}: graph has no edges")
    for a, b, attrs in graph.edges(data=True):
        flights = attrs.get('flights')
        if not isinstance(flights, list) or not flights:
            raise ValueError(f"{source}: edge {a} -> {b} has no 'flights' list")
        for flight in flights:
            if not (isinstance(flight, list) and len(flight) == 2 and all(isinstance(t, str) for t in flight)):
                raise ValueError(f"{source}: edge {a} -> {b} has a malformed flight {flight!r}")
            for text in flight:
                if datetime.fromisoformat(text).utcoffset() is None:
                    raise ValueError(f"{source}: flight time {text!r} carries no UTC offset")


def load_real_graph(path: Path) -> nx.DiGraph:
    """Load a scan: ``.pkl`` (pickled DiGraph) or ``.json`` (flight_graph.json layout).

    Precondition: file exists and matches one of the two layouts.  Postcondition: validated DiGraph.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"scan file not found: {path}")
    if path.suffix == '.pkl':
        with path.open('rb') as handle:
            graph = pickle.load(handle)
    elif path.suffix == '.json':
        with path.open('r', encoding='utf-8') as handle:
            graph = synth.to_graph(json.load(handle))
    else:
        raise ValueError(f"unsupported scan file type {path.suffix!r} (expected .pkl or .json): {path}")
    _validate_graph(graph, str(path))
    return graph


def real_dataset_name(path: Path, graph: nx.DiGraph) -> str:
    """Short, unique label: ``<stem>-<YYYY-MM>`` of the first scan day, e.g. ``pkl-2025-03``."""
    day0 = min(datetime.fromisoformat(f[0]).date() for _, _, attrs in graph.edges(data=True) for f in attrs['flights'])
    return f"{path.suffix.lstrip('.')}-{day0.strftime('%Y-%m')}"


def load_real_datasets(paths: List[Path]) -> List[Dataset]:
    datasets: List[Dataset] = []
    for path in paths:
        graph = load_real_graph(path)
        name = real_dataset_name(Path(path), graph)
        if any(d.name == name for d in datasets):
            name = f"{name}-{len(datasets)}"
        datasets.append(Dataset(name=name, kind='real', graph=graph, source=str(path),
                                stats=synth.network_stats(graph, synth.HUB_WEIGHTS)))
    return datasets


def distance_lookup_from_files(paths=(EDGES_FILE, DISTANCES_FILE)) -> Optional[synth.DistanceLookup]:
    """Great-circle distances (km) from the project's tables, first hit wins; None if no table exists."""
    tables: List[Dict[str, Dict[str, float]]] = []
    for path in paths:
        path = Path(path)
        if path.exists():
            with path.open('r', encoding='utf-8') as handle:
                tables.append(json.load(handle))
    if not tables:
        return None

    def lookup(a: str, b: str) -> Optional[float]:
        for table in tables:
            value = table.get(a, {}).get(b)
            if isinstance(value, (int, float)) and value > 0:
                return float(value)
        return None

    return lookup


def make_synth_datasets(seeds: List[int], params: synth.SynthParams,
                        distance_lookup: Optional[synth.DistanceLookup]) -> List[Dataset]:
    datasets: List[Dataset] = []
    for seed in seeds:
        flight_json = synth.generate_network(seed, params, distance_lookup)
        graph = synth.to_graph(flight_json)
        _validate_graph(graph, f"synth seed {seed}")
        datasets.append(Dataset(name=f"synth-{seed:02d}", kind='synth', graph=graph, source=f"seed={seed}",
                                seed=seed, flight_json=flight_json,
                                stats=synth.network_stats(graph, params.hub_weights)))
    return datasets


def load_preferences(path: Path = PREFERENCES_FILE) -> dict:
    """``{'city': {...}, 'country': {...}}`` from preferences.json; empty maps if the file is missing."""
    path = Path(path)
    if not path.exists():
        return {'city': {}, 'country': {}}
    with path.open('r', encoding='utf-8') as handle:
        data = json.load(handle)
    if 'city' not in data or 'country' not in data:
        raise ValueError(f"{path}: expected top-level keys 'city' and 'country'")
    return data


def load_distances(path: Path = DISTANCES_FILE) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    with path.open('r', encoding='utf-8') as handle:
        return json.load(handle)
