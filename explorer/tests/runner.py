"""pytest-free runner for the built-in checks (used by ``python -m explorer selftest``)."""
from __future__ import annotations

import inspect
import traceback
from typing import Callable, List, Tuple

from explorer.tests import test_archive, test_bundle, test_dp, test_js, test_ui


def collect() -> List[Tuple[str, Callable[[], None]]]:
    tests = []
    for module in (test_dp, test_js, test_ui, test_bundle, test_archive):
        for name, func in inspect.getmembers(module, inspect.isfunction):
            if name.startswith('test_') and func.__module__ == module.__name__:
                tests.append((f"{module.__name__.rsplit('.', 1)[-1]}.{name}", func))
    return tests


def run_all() -> List[Tuple[str, bool, str]]:
    """Run every check; returns (name, passed, message).  Never raises - a failure is reported with
    the tail of its traceback so the summary always lists every check."""
    outcomes = []
    for name, func in collect():
        try:
            func()
        except Exception as exc:  # reported, not swallowed: the message carries the failing assertion
            tail = traceback.format_exc().strip().splitlines()[-1]
            outcomes.append((name, False, f"{type(exc).__name__}: {exc} ({tail})"))
        else:
            outcomes.append((name, True, ''))
    return outcomes
