"""Getting home again: the stranding analysis must judge only what it can actually judge."""
from __future__ import annotations

import math

from explorer import strand
from explorer.dp import FlightNetwork
from explorer.tests import fixtures

HOME = frozenset({'Dortmund'})

# Dortmund -> Sofia -> back, and Dortmund -> Ohrid as a dead end with no departure at all.
# The last day is deliberately far enough out that the early landings can be judged.
NETWORK = [
    ('Dortmund', 'Sofia', '2025-03-10T08:00:00+01:00', '2025-03-10T11:00:00+02:00'),
    ('Sofia', 'Dortmund', '2025-03-10T20:00:00+02:00', '2025-03-10T22:00:00+01:00'),
    ('Dortmund', 'Ohrid', '2025-03-10T09:00:00+01:00', '2025-03-10T11:30:00+01:00'),
    ('Dortmund', 'Sofia', '2025-03-14T08:00:00+01:00', '2025-03-14T11:00:00+02:00'),
    ('Sofia', 'Dortmund', '2025-03-14T20:00:00+02:00', '2025-03-14T22:00:00+01:00'),
]


def _network(edges=NETWORK) -> FlightNetwork:
    return FlightNetwork.from_graph(fixtures.graph_from(edges))


def test_dead_end_is_found_and_the_way_home_is_timed():
    report = strand.analyse(_network(), HOME, 1, 18, horizon_hours=24)
    # Sofia on the 10th can fly home the same evening; Ohrid never can.  The landings on the 14th
    # are too close to the end of the data and must not be judged at all.
    assert report.landings_judged == 2, report.landings_judged
    assert report.stranded == 1, 'Ohrid has no departure, so that landing is a dead end'
    assert report.late == 0
    assert len(report.hours) == 1
    # the clock runs until you are home, not until you take off: landing Sofia 11:00+02 (09:00 UTC),
    # home Dortmund 22:00+01 (21:00 UTC) is twelve hours, of which nine are waiting
    assert 11.5 < report.hours[0] < 12.5, report.hours
    assert report.flights == [1]
    assert dict((city, bad) for city, _, bad in report.worst_cities) == {'Ohrid': 1}
    assert 0.49 < report.risk < 0.51


def test_end_of_data_is_never_counted_as_stranded():
    """A landing shortly before the scan stops says nothing about the real world."""
    wide = strand.analyse(_network(), HOME, 1, 18, horizon_hours=24)
    narrow = strand.analyse(_network(), HOME, 1, 18, horizon_hours=200)
    assert wide.landings_judged > narrow.landings_judged == 0, (wide.landings_judged, narrow.landings_judged)
    assert narrow.risk == 0.0 and not narrow.hours


def test_patience_can_only_help():
    """A wider connection window may only ever reduce the number of dead ends."""
    graph = fixtures.real_graph('json')
    network = FlightNetwork.from_graph(graph)
    impatient = strand.analyse(network, HOME, 1, 12, horizon_hours=24)
    patient = strand.analyse(network, HOME, 1, 36, horizon_hours=24)
    assert patient.landings_judged == impatient.landings_judged
    assert patient.stranded <= impatient.stranded, (patient.stranded, impatient.stranded)


def test_report_lines_stay_short_and_factual():
    report = strand.analyse(_network(), HOME, 1, 18, horizon_hours=24)
    lines = strand.format_report(report, 'Testlauf')
    assert lines[0] == 'Testlauf'
    assert any('ohne Weg nach Hause' in line for line in lines)
    assert all(len(line) < 200 for line in lines)
    assert len(lines) <= 9

    empty = strand.analyse(_network(), HOME, 1, 18, horizon_hours=500)
    assert 'keine Landung' in strand.format_report(empty, 'Leerlauf')[0]


def test_invalid_arguments_are_refused():
    network = _network()
    for kwargs in ({'home': frozenset()}, {'min_gap_hours': 5, 'max_gap_hours': 5},
                   {'horizon_hours': 0}):
        arguments = {'home': HOME, 'min_gap_hours': 1, 'max_gap_hours': 18, 'horizon_hours': 24}
        arguments.update(kwargs)
        try:
            strand.analyse(network, **arguments)
        except ValueError:
            continue
        raise AssertionError(f"analyse accepted invalid arguments: {kwargs}")


def test_percentile_is_monotonic():
    report = strand.analyse(FlightNetwork.from_graph(fixtures.real_graph('json')), HOME, 1, 24,
                            horizon_hours=24)
    assert report.hours, 'the real scan must produce at least one way home'
    values = [report.percentile(p) for p in (10, 50, 90, 99)]
    assert values == sorted(values), values
    assert not math.isnan(values[0])
