"""Tiny in-process guard against double taps on buttons with side effects
(sending messages to clients, minting links). One bot container only, so a
process-local dict is sufficient."""
from __future__ import annotations

import time
from collections.abc import Hashable

_last: dict[Hashable, float] = {}


def too_soon(key: Hashable, seconds: float = 3.0) -> bool:
    now = time.monotonic()
    last = _last.get(key)
    _last[key] = now
    if len(_last) > 10_000:
        cutoff = now - 60
        for k in [k for k, v in _last.items() if v < cutoff]:
            _last.pop(k, None)
    return last is not None and now - last < seconds
