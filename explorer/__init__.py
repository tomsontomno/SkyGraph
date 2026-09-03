"""Hop-by-hop route explorer for the Wizz scans in data/current/ (read-only).

Instead of enumerating routes it builds a time-ordered flight DAG (node = one concrete flight, edge =
a legal connection) and counts continuations with a backward dynamic program, so no flight limit is
needed.  Search semantics follow simulate/route_find_fixed.py, the booking cap follows
simulate/booking_cap.py.  core/route_find.py and simulate/ are untouched.

    python -m explorer build     # scans -> data/explorer/*.json
    python -m explorer serve     # local UI at http://127.0.0.1:8765/
"""
