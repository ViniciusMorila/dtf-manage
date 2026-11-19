"""72 hour offline grace period.

This is an APP decision. The API contract recommends never releasing use on a
network failure; the grace only applies when the API is unreachable, never
after a refusal from the server. It is measured from the last successful
validation, on the server clock (servidor_agora) advanced by the local clock,
and it is not counted when the local clock looks rolled back.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import time

from dtf_manager.models.license import LicenseInfo, LicenseStatus, format_timestamp, parse_timestamp
from dtf_manager.services.license_store import LicenseSnapshot, LicenseStoreError

GRACE_PERIOD = timedelta(hours=72)
CLOCK_TOLERANCE = timedelta(minutes=5)         # local clock vs. high-water / monotonic clock
SERVER_SKEW_TOLERANCE = timedelta(minutes=10)  # local clock vs. last server time


def utc_now():
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class GraceDecision:
    allowed: bool
    reason: str   # ok, no_cache, not_active, expired, grace_exhausted, clock_rolled_back
    remaining: timedelta | None = None
    info: LicenseInfo | None = None
    server_now: str | None = None


class OfflineGrace:
    def __init__(self, store, *, clock=utc_now, monotonic=time.monotonic):
        self.store = store
        self._clock = clock
        self._monotonic = monotonic
        self._anchor = None   # (local wall clock, monotonic) of the last validation in this process

    def record_success(self, status: LicenseStatus):
        """Persist a validation the server just confirmed (any HTTP 200)."""
        now = self._clock()
        previous = self._load()
        high = now
        if previous is not None:
            high = max(now, parse_timestamp(previous.high_water) or now)
        self._anchor = (now, self._monotonic())
        try:
            self.store.save(LicenseSnapshot(status.info, status.server_now,
                                            format_timestamp(now), format_timestamp(high)))
        except LicenseStoreError:
            pass  # the server already authorized; only the offline grace is lost

    def clear(self):
        self._anchor = None
        try:
            self.store.delete()
        except LicenseStoreError:
            pass

    def _load(self):
        try:
            return self.store.load()
        except LicenseStoreError:
            return None

    def evaluate(self):
        snapshot = self._load()
        if snapshot is None:
            return GraceDecision(False, "no_cache")
        if not snapshot.info.active:
            return GraceDecision(False, "not_active")
        now = self._clock()
        validated = parse_timestamp(snapshot.validated_at)
        high = parse_timestamp(snapshot.high_water)
        server = parse_timestamp(snapshot.server_now)
        # A clock set back (compared to what the app already saw, to the last
        # server time, or to the monotonic clock) never counts as grace.
        if now < high - CLOCK_TOLERANCE or now < server - SERVER_SKEW_TOLERANCE:
            return GraceDecision(False, "clock_rolled_back")
        elapsed = max(now - validated, timedelta(0))
        if self._anchor is not None:
            wall0, mono0 = self._anchor
            elapsed_mono = timedelta(seconds=self._monotonic() - mono0)
            if (now - wall0) + CLOCK_TOLERANCE < elapsed_mono:
                return GraceDecision(False, "clock_rolled_back")
            elapsed = max(elapsed, elapsed_mono)
        info = snapshot.info
        expiry = parse_timestamp(info.data_expiracao)
        if not info.vitalicia and expiry is not None and server + elapsed >= expiry:
            return GraceDecision(False, "expired", info=info, server_now=snapshot.server_now)
        if elapsed >= GRACE_PERIOD:
            return GraceDecision(False, "grace_exhausted", info=info, server_now=snapshot.server_now)
        try:  # raise the high-water mark so a later rollback is detected across restarts
            if now > high:
                self.store.save(LicenseSnapshot(info, snapshot.server_now, snapshot.validated_at,
                                                format_timestamp(now)))
        except LicenseStoreError:
            pass
        return GraceDecision(True, "ok", GRACE_PERIOD - elapsed, info, snapshot.server_now)
