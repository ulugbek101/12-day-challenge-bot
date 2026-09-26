"""Tiny in-process guards against double taps on buttons with side effects.
One bot container only, so process-local dicts are sufficient."""
from __future__ import annotations

import time
from collections.abc import Hashable

_last: dict[Hashable, float] = {}
_succeeded: dict[Hashable, float] = {}


def _prune(store: dict[Hashable, float], now: float) -> None:
    if len(store) > 10_000:
        cutoff = now - 120
        for key in [k for k, v in store.items() if v < cutoff]:
            store.pop(key, None)


def too_soon(key: Hashable, seconds: float = 3.0) -> bool:
    """True if the same key was seen less than `seconds` ago (any outcome)."""
    now = time.monotonic()
    last = _last.get(key)
    _last[key] = now
    _prune(_last, now)
    return last is not None and now - last < seconds


def mark_success(key: Hashable) -> None:
    now = time.monotonic()
    _succeeded[key] = now
    _prune(_succeeded, now)


def succeeded_recently(key: Hashable, seconds: float = 10.0) -> bool:
    """For retry-style buttons: skip a repeat right after a success (a double tap),
    but never block retrying after a failure."""
    at = _succeeded.get(key)
    return at is not None and time.monotonic() - at < seconds


def reset() -> None:
    _last.clear()
    _succeeded.clear()
