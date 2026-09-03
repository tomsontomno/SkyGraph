"""Bug-impact simulation for core/route_find.py (SkyGraph).

Runs the ORIGINAL search (simulate.route_find_original, verbatim copy of core/route_find.py)
against the FIXED search (simulate.route_find_fixed) on seedable synthetic Wizz-style networks
and on the real scans in data/current/, and reports which routes the bug hid.

Entry point: ``python -m simulate`` (see ``python -m simulate --help``).
"""
