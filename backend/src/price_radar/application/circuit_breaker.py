"""Per-domain circuit breaker backed by Redis hashes.

Prevents wasting resources (Celery workers, Playwright browsers) on
domains that are consistently failing (CAPTCHAs, IP bans, downtime).

State machine::

    CLOSED ──(N failures)──► OPEN ──(timeout expires)──► HALF_OPEN
       ▲                       ▲                            │
       │                       │                            │
       └──(success)────────────┘──(failure)─────────────────┘
                               │
                           HALF_OPEN──(success)──► CLOSED

- **CLOSED**: Normal operation — all requests are allowed.
- **OPEN**: All requests are rejected immediately.  The domain is
  considered broken.  Transitions to HALF_OPEN after the timeout.
- **HALF_OPEN**: Allows exactly one *probe* request.  On success →
  CLOSED.  On failure → OPEN (with exponential backoff).

Redis storage (one hash per domain)::

    circuit:amazon.com → {
        "state":          "closed" | "open" | "half_open",
        "failure_count":  "3",
        "last_failure_at": "1739800000.0",
        "opened_at":      "1739800000.0",
        "next_retry_at":  "1739803600.0",
        "backoff_multiplier": "1",
    }

Usage::

    from price_radar.application.circuit_breaker import DomainCircuitBreaker

    cb = DomainCircuitBreaker(redis_client)
    if cb.allow_request("bestbuy.com"):
        # ... do the fetch
        cb.record_success("bestbuy.com")
    else:
        # circuit is OPEN — skip
        pass
"""

from __future__ import annotations

import enum
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── Redis key prefix ─────────────────────────────────────────────────────
_REDIS_KEY_PREFIX = "circuit:"

# ── Default configuration ────────────────────────────────────────────────
DEFAULT_FAILURE_THRESHOLD = 5       # failures before opening
DEFAULT_RECOVERY_TIMEOUT = 3600.0   # seconds before first half-open probe (1h)
DEFAULT_MAX_RECOVERY_TIMEOUT = 86400.0  # max backoff cap (24h)
DEFAULT_BACKOFF_FACTOR = 2.0        # exponential multiplier


# ── CircuitState enum ────────────────────────────────────────────────────

class CircuitState(str, enum.Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# ── CircuitStatus data class ─────────────────────────────────────────────

@dataclass
class CircuitStatus:
    """Snapshot of a domain's circuit breaker state."""

    domain: str
    state: CircuitState
    failure_count: int
    last_failure_at: float | None
    opened_at: float | None
    next_retry_at: float | None
    backoff_multiplier: int


# ── DomainCircuitBreaker ─────────────────────────────────────────────────

class DomainCircuitBreaker:
    """Per-domain circuit breaker backed by Redis hashes.

    Args:
        redis_client: A ``redis.Redis`` (sync) instance.  When ``None``,
            the circuit breaker operates in **no-op** mode (always allows
            requests) — useful for tests and local dev without Redis.
        failure_threshold: Number of consecutive failures before opening
            the circuit (default 5).
        recovery_timeout: Seconds before the first HALF_OPEN probe after
            the circuit opens (default 3600 = 1 hour).
        max_recovery_timeout: Maximum backoff cap (default 86400 = 24h).
        backoff_factor: Multiplier for exponential backoff on repeated
            HALF_OPEN failures (default 2.0 → 1h, 2h, 4h, 8h, 16h, 24h).
    """

    def __init__(
        self,
        redis_client: object | None = None,
        *,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        recovery_timeout: float = DEFAULT_RECOVERY_TIMEOUT,
        max_recovery_timeout: float = DEFAULT_MAX_RECOVERY_TIMEOUT,
        backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    ) -> None:
        self._redis = redis_client
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._max_recovery_timeout = max_recovery_timeout
        self._backoff_factor = backoff_factor

    # ── Public API ───────────────────────────────────────────────────

    def allow_request(self, domain: str) -> bool:
        """Check if a request to *domain* is allowed.

        Returns:
            ``True`` if the circuit is CLOSED or HALF_OPEN (probe).
            ``False`` if OPEN (request should be skipped).
        """
        if self._redis is None:
            return True

        state = self._get_state_from_redis(domain)

        if state == CircuitState.CLOSED:
            return True

        if state == CircuitState.OPEN:
            # Check if recovery timeout has expired → transition to HALF_OPEN
            next_retry = self._get_float(domain, "next_retry_at")
            if next_retry is not None and time.time() >= next_retry:
                self._set_state(domain, CircuitState.HALF_OPEN)
                logger.info(
                    "Circuit breaker %s: OPEN → HALF_OPEN (probe allowed)",
                    domain,
                )
                return True
            return False

        if state == CircuitState.HALF_OPEN:
            # Only one probe at a time — allow it
            return True

        return False  # pragma: no cover

    def record_success(self, domain: str) -> None:
        """Record a successful request.

        Resets the circuit to CLOSED regardless of current state.
        """
        if self._redis is None:
            return

        key = f"{_REDIS_KEY_PREFIX}{domain}"
        self._redis.hset(key, mapping={  # type: ignore[union-attr]
            "state": CircuitState.CLOSED.value,
            "failure_count": "0",
            "backoff_multiplier": "1",
        })
        # Remove transient fields
        self._redis.hdel(key, "opened_at", "next_retry_at")  # type: ignore[union-attr]

        state_before = self._get_state_from_redis(domain)
        if state_before != CircuitState.CLOSED:
            logger.info(
                "Circuit breaker %s: %s → CLOSED (success)",
                domain,
                state_before.value,
            )

    def record_failure(self, domain: str) -> None:
        """Record a failed request.

        - CLOSED: increments failure_count; opens circuit at threshold.
        - HALF_OPEN: immediately reopens with increased backoff.
        """
        if self._redis is None:
            return

        now = time.time()
        key = f"{_REDIS_KEY_PREFIX}{domain}"
        state = self._get_state_from_redis(domain)

        # Increment failure count
        new_count = self._redis.hincrby(key, "failure_count", 1)  # type: ignore[union-attr]
        self._redis.hset(key, "last_failure_at", str(now))  # type: ignore[union-attr]

        if state == CircuitState.CLOSED:
            if new_count >= self._failure_threshold:
                self._open_circuit(domain, now, backoff_multiplier=1)
                logger.warning(
                    "Circuit breaker %s: CLOSED → OPEN after %d failures",
                    domain,
                    new_count,
                )

        elif state == CircuitState.HALF_OPEN:
            # Probe failed — reopen with increased backoff
            multiplier = self._get_int(domain, "backoff_multiplier") or 1
            new_multiplier = multiplier + 1
            self._open_circuit(domain, now, backoff_multiplier=new_multiplier)
            logger.warning(
                "Circuit breaker %s: HALF_OPEN → OPEN (probe failed, "
                "backoff multiplier=%d)",
                domain,
                new_multiplier,
            )

        # If already OPEN, just update last_failure_at (no state change)

    def get_status(self, domain: str) -> CircuitStatus:
        """Get the full status of a domain's circuit breaker."""
        if self._redis is None:
            return CircuitStatus(
                domain=domain,
                state=CircuitState.CLOSED,
                failure_count=0,
                last_failure_at=None,
                opened_at=None,
                next_retry_at=None,
                backoff_multiplier=1,
            )

        return CircuitStatus(
            domain=domain,
            state=self._get_state_from_redis(domain),
            failure_count=self._get_int(domain, "failure_count") or 0,
            last_failure_at=self._get_float(domain, "last_failure_at"),
            opened_at=self._get_float(domain, "opened_at"),
            next_retry_at=self._get_float(domain, "next_retry_at"),
            backoff_multiplier=self._get_int(domain, "backoff_multiplier") or 1,
        )

    def get_open_domains(self) -> list[str]:
        """Return all domains with OPEN circuits.

        Scans Redis for ``circuit:*`` keys and filters for ``state=open``.
        Used by the ``probe_broken_domains`` periodic task.
        """
        if self._redis is None:
            return []

        domains: list[str] = []
        cursor = 0
        prefix = _REDIS_KEY_PREFIX
        while True:
            cursor, keys = self._redis.scan(  # type: ignore[union-attr]
                cursor=cursor,
                match=f"{prefix}*",
                count=100,
            )
            for key in keys:
                key_str = key if isinstance(key, str) else key.decode()
                domain = key_str[len(prefix):]
                state_val = self._redis.hget(key_str, "state")  # type: ignore[union-attr]
                if state_val == CircuitState.OPEN.value or state_val == CircuitState.OPEN.value.encode():
                    domains.append(domain)
            if cursor == 0:
                break

        return domains

    def reset(self, domain: str) -> None:
        """Clear all circuit breaker data for a domain (useful for tests)."""
        if self._redis is not None:
            self._redis.delete(f"{_REDIS_KEY_PREFIX}{domain}")  # type: ignore[union-attr]

    # ── Internal helpers ─────────────────────────────────────────────

    def _get_state_from_redis(self, domain: str) -> CircuitState:
        """Read the current state from Redis (defaults to CLOSED)."""
        key = f"{_REDIS_KEY_PREFIX}{domain}"
        raw = self._redis.hget(key, "state")  # type: ignore[union-attr]
        if raw is None:
            return CircuitState.CLOSED
        val = raw if isinstance(raw, str) else raw.decode()
        try:
            return CircuitState(val)
        except ValueError:
            return CircuitState.CLOSED

    def _set_state(self, domain: str, state: CircuitState) -> None:
        """Set the circuit state in Redis."""
        key = f"{_REDIS_KEY_PREFIX}{domain}"
        self._redis.hset(key, "state", state.value)  # type: ignore[union-attr]

    def _open_circuit(
        self, domain: str, now: float, *, backoff_multiplier: int
    ) -> None:
        """Transition to OPEN state with exponential backoff timeout."""
        timeout = min(
            self._recovery_timeout * (self._backoff_factor ** (backoff_multiplier - 1)),
            self._max_recovery_timeout,
        )
        key = f"{_REDIS_KEY_PREFIX}{domain}"
        self._redis.hset(key, mapping={  # type: ignore[union-attr]
            "state": CircuitState.OPEN.value,
            "opened_at": str(now),
            "next_retry_at": str(now + timeout),
            "backoff_multiplier": str(backoff_multiplier),
        })
        # Set a TTL so stale keys don't linger forever (2x max timeout)
        self._redis.expire(  # type: ignore[union-attr]
            key, int(self._max_recovery_timeout * 2) + 3600,
        )

    def _get_float(self, domain: str, field: str) -> float | None:
        """Read a float field from the Redis hash."""
        key = f"{_REDIS_KEY_PREFIX}{domain}"
        raw = self._redis.hget(key, field)  # type: ignore[union-attr]
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def _get_int(self, domain: str, field: str) -> int | None:
        """Read an int field from the Redis hash."""
        key = f"{_REDIS_KEY_PREFIX}{domain}"
        raw = self._redis.hget(key, field)  # type: ignore[union-attr]
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
