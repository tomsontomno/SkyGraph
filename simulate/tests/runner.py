"""pytest-free runner for the built-in checks (used by ``python -m simulate selftest``)."""
from __future__ import annotations

import inspect
import traceback
from typing import Callable, List, Tuple

from simulate.tests import test_copies, test_semantics


def collect() -> List[Tuple[str, Callable[[], None]]]:
    tests = []
    for module in (test_copies, test_semantics):
        for name, func in inspect.getmembers(module, inspect.isfunction):
            if name.startswith('test_') and func.__module__ == module.__name__:
                tests.append((f"{module.__name__.rsplit('.', 1)[-1]}.{name}", func))
    return tests


def run_all() -> List[Tuple[str, bool, str]]:
    """Run every test; returns (name, passed, message) - never raises, failures carry the traceback tail."""
    outcomes = []
    for name, func in collect():
        try:
            func()
        except Exception as exc:  # report, don't abort: the summary line must list every check
            tail = traceback.format_exc().strip().splitlines()[-1]
            outcomes.append((name, False, f"{type(exc).__name__}: {exc} ({tail})"))
        else:
            outcomes.append((name, True, ''))
    return outcomes
