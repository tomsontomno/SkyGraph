"""Single overwriting progress line (no log spam)."""
from __future__ import annotations

import sys
import time


class Progress:
    """Writes ``\\r<message>`` to stderr on a TTY; prints nothing otherwise (except ``finish``).

    Invariant: at most one line of terminal output exists at any time; ``finish`` ends it."""

    def __init__(self, total: int, enabled: bool = True):
        self.total = max(1, total)
        self.done = 0
        self.enabled = enabled and sys.stderr.isatty()
        self.started = time.monotonic()
        self._last_len = 0

    def step(self, message: str) -> None:
        self.done += 1
        if not self.enabled:
            return
        elapsed = time.monotonic() - self.started
        text = f"[{self.done}/{self.total}] {elapsed:5.1f}s  {message}"
        pad = max(0, self._last_len - len(text))
        sys.stderr.write('\r' + text + ' ' * pad)
        sys.stderr.flush()
        self._last_len = len(text)

    def finish(self) -> None:
        if self.enabled:
            sys.stderr.write('\r' + ' ' * self._last_len + '\r')
            sys.stderr.flush()
