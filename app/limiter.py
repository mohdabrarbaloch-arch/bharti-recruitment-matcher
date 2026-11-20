"""Rate limiting as a FastAPI dependency.

This started as a slowapi decorator and had to be replaced. The decorator wraps
the view function, and FastAPI then resolves the string annotations from
``from __future__ import annotations`` against the *wrapper's* module globals —
slowapi's, not ours. ``UserCreate`` could not be resolved, so FastAPI fell back
to treating the request body as a query parameter and every POST returned 422.

A dependency has none of that problem: FastAPI inspects the real function
signature, and the limiter runs as part of normal dependency resolution.

NOTE: this module deliberately does NOT use ``from __future__ import
annotations``. FastAPI resolves a dependency's annotations against
``callable.__globals__``, and a bound method has no ``__globals__`` — so a
string annotation on ``__call__`` cannot be resolved and ``request: Request``
becomes a required query parameter. Real annotation objects avoid that
entirely. The builtin generics used below are native in 3.11, so nothing is
lost by dropping the future import.

The window is a fixed 60 seconds with a per-key counter. It is per-process, so
N workers means N times the limit — Redis is the fix and is noted in the README.
"""

import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

#: key -> timestamps of recent hits, oldest first.
_HITS: dict[str, deque[float]] = defaultdict(deque)

#: Cap on tracked keys, so a flood of distinct IPs cannot grow the dict without
#: bound. When it is exceeded we drop the idle keys rather than the whole thing,
#: which keeps recent limits intact.
_MAX_KEYS = 10_000


def _client_key(request: Request) -> str:
    """Identify the caller.

    Behind a proxy the socket address is the proxy, so X-Forwarded-For is
    preferred when present. Only the first entry is used: the rest of the
    header is attacker-controlled.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _prune(now: float) -> None:
    if len(_HITS) <= _MAX_KEYS:
        return
    stale = [k for k, v in _HITS.items() if not v or now - v[-1] > 60]
    for key in stale:
        _HITS.pop(key, None)


@dataclass(eq=False)
class RateLimit:
    """Dependency enforcing ``times`` requests per ``seconds`` per client.

    ``eq=False`` is load-bearing. FastAPI keys its dependency cache by the
    callable, so a dependency object must be hashable. A plain dataclass
    defines ``__eq__`` and therefore drops ``__hash__``, which made every
    request raise ``TypeError: unhashable type: 'RateLimit'``. Identity
    equality is also the correct semantics here: two limiters with the same
    numbers are still two separate limits.

    Usage::

        @router.post("/login", dependencies=[Depends(RateLimit(10, 60))])
    """

    times: int
    seconds: int = 60
    scope: str = ""

    def __call__(self, request: Request) -> None:
        now = time.monotonic()
        key = f"{self.scope}:{_client_key(request)}"
        hits = _HITS[key]

        # Slide the window: drop anything older than the cutoff.
        cutoff = now - self.seconds
        while hits and hits[0] < cutoff:
            hits.popleft()

        if len(hits) >= self.times:
            retry_after = max(1, int(self.seconds - (now - hits[0])))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Rate limit exceeded: {self.times} requests per "
                    f"{self.seconds}s. Retry in {retry_after}s."
                ),
                headers={"Retry-After": str(retry_after)},
            )

        hits.append(now)
        _prune(now)


def reset_limits() -> None:
    """Clear all counters. Used by tests so one test cannot rate-limit another."""
    _HITS.clear()
