from datetime import datetime, timedelta
from enum import Enum

from domain.enums import Priority
from domain.exceptions import (
    InvalidStateTransitionError,
    MissingSLAError,
    ValidationError,
)


class SLAEvent(Enum):
    RESPONSE_WARNING = "RESPONSE_WARNING"
    RESPONSE_BREACH = "RESPONSE_BREACH"
    RESOLUTION_WARNING = "RESOLUTION_WARNING"
    RESOLUTION_BREACH = "RESOLUTION_BREACH"


class SLAPolicy:
    """Maps each priority to (response target, resolution target)."""

    def __init__(self, targets):
        self._targets = dict(targets)

    @classmethod
    def default(cls):
        return cls({
            Priority.P1: (timedelta(minutes=5), timedelta(minutes=30)),
            Priority.P2: (timedelta(minutes=15), timedelta(hours=2)),
            Priority.P3: (timedelta(hours=1), timedelta(hours=8)),
            Priority.P4: (timedelta(hours=4), timedelta(hours=24)),
        })

    def has_targets_for(self, priority):
        return priority in self._targets

    def targets_for(self, priority):
        if priority not in self._targets:
            raise MissingSLAError(f"No SLA configured for {priority.name}")
        return self._targets[priority]


class SLATracker:
    def __init__(self, created_at, priority, policy, clock, warning_ratio=0.8):
        if created_at.tzinfo is None:
            raise ValidationError("created_at must be timezone-aware")
        if not 0 < warning_ratio < 1:
            raise ValidationError("warning_ratio must be between 0 and 1")
        self._created_at = created_at
        self._priority = priority
        self._policy = policy
        self._clock = clock
        self._warning_ratio = warning_ratio
        self._paused_total = timedelta(0)
        self._paused_at = None
        self._response_elapsed = None
        self._resolution_elapsed = None
        self._flags = set()
        self._targets()  # fail early if no SLA can be found

    # ---------- saving and loading ----------
    def snapshot(self):
        """Plain data (strings, numbers, lists) that can be stored in a database."""
        return {
            "created_at": self._created_at.isoformat(),
            "priority": self._priority.name,
            "warning_ratio": self._warning_ratio,
            "paused_total_seconds": self._paused_total.total_seconds(),
            "paused_at": self._paused_at.isoformat() if self._paused_at else None,
            "response_elapsed_seconds": (
                None if self._response_elapsed is None
                else self._response_elapsed.total_seconds()
            ),
            "resolution_elapsed_seconds": (
                None if self._resolution_elapsed is None
                else self._resolution_elapsed.total_seconds()
            ),
            "flags": sorted(flag.name for flag in self._flags),
        }

    @classmethod
    def restore(cls, data, policy, clock):
        """Rebuild a tracker from snapshot() data (for example after a restart)."""
        try:
            created_at = datetime.fromisoformat(data["created_at"])
            priority = Priority[data["priority"]]
            warning_ratio = float(data.get("warning_ratio", 0.8))
            paused_total = timedelta(seconds=float(data["paused_total_seconds"]))
            paused_at = cls._parse_optional_time(data.get("paused_at"))
            response = cls._parse_optional_seconds(data.get("response_elapsed_seconds"))
            resolution = cls._parse_optional_seconds(
                data.get("resolution_elapsed_seconds")
            )
            flags = {SLAEvent[name] for name in data.get("flags", [])}
        except (KeyError, ValueError, TypeError) as error:
            raise ValidationError(f"Invalid SLA snapshot: {error}") from error
        if paused_total < timedelta(0):
            raise ValidationError("paused_total_seconds cannot be negative")

        tracker = cls(created_at, priority, policy, clock, warning_ratio)
        tracker._paused_total = paused_total
        tracker._paused_at = paused_at
        tracker._response_elapsed = response
        tracker._resolution_elapsed = resolution
        tracker._flags = flags
        return tracker

    @staticmethod
    def _parse_optional_time(value):
        if value is None:
            return None
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError("timestamps in a snapshot must be timezone-aware")
        return parsed

    @staticmethod
    def _parse_optional_seconds(value):
        if value is None:
            return None
        seconds = float(value)
        if seconds < 0:
            raise ValueError("elapsed seconds cannot be negative")
        return timedelta(seconds=seconds)

    # ---------- reading ----------
    @property
    def priority(self):
        return self._priority

    @property
    def is_paused(self):
        return self._paused_at is not None

    @property
    def used_default_policy(self):
        return not self._policy.has_targets_for(self._priority)

    def response_deadline(self):
        return self._created_at + self._targets()[0]

    def resolution_deadline(self):
        now = self._clock.now()
        extra = self._paused_total
        if self._paused_at is not None:
            extra += now - self._paused_at
        return self._created_at + self._targets()[1] + extra

    def is_response_breached(self):
        return self._current_response_elapsed() > self._targets()[0]

    def is_resolution_breached(self):
        return self._current_resolution_elapsed() > self._targets()[1]

    # ---------- changing ----------
    def record_acknowledged(self):
        if self._response_elapsed is None:
            self._response_elapsed = self._clock.now() - self._created_at

    def record_resolved(self):
        if self._resolution_elapsed is None:
            self._resolution_elapsed = self._effective_elapsed(self._clock.now())

    def record_reopened(self):
        # SLA continues after a reopen: clear the resolved mark and keep counting
        self._resolution_elapsed = None

    def pause(self):
        if self._paused_at is not None:
            raise InvalidStateTransitionError("SLA clock is already paused")
        self._paused_at = self._clock.now()

    def resume(self):
        if self._paused_at is None:
            raise InvalidStateTransitionError("SLA clock is not paused")
        self._paused_total += self._clock.now() - self._paused_at
        self._paused_at = None

    def change_priority(self, new_priority):
        """Deadlines are recomputed from the ORIGINAL creation time."""
        old = self._priority
        self._priority = new_priority
        try:
            self._targets()
        except MissingSLAError:
            self._priority = old
            raise

    def evaluate(self):
        """Return each warning/breach exactly once, even if called late."""
        response_target, resolution_target = self._targets()
        events = []

        response_elapsed = self._current_response_elapsed()
        if SLAEvent.RESPONSE_BREACH not in self._flags:
            if response_elapsed > response_target:
                self._flags.update({SLAEvent.RESPONSE_BREACH, SLAEvent.RESPONSE_WARNING})
                events.append(SLAEvent.RESPONSE_BREACH)
            elif (
                self._response_elapsed is None
                and SLAEvent.RESPONSE_WARNING not in self._flags
                and response_elapsed >= response_target * self._warning_ratio
            ):
                self._flags.add(SLAEvent.RESPONSE_WARNING)
                events.append(SLAEvent.RESPONSE_WARNING)

        resolution_elapsed = self._current_resolution_elapsed()
        if SLAEvent.RESOLUTION_BREACH not in self._flags:
            if resolution_elapsed > resolution_target:
                self._flags.update({SLAEvent.RESOLUTION_BREACH, SLAEvent.RESOLUTION_WARNING})
                events.append(SLAEvent.RESOLUTION_BREACH)
            elif (
                self._resolution_elapsed is None
                and SLAEvent.RESOLUTION_WARNING not in self._flags
                and resolution_elapsed >= resolution_target * self._warning_ratio
            ):
                self._flags.add(SLAEvent.RESOLUTION_WARNING)
                events.append(SLAEvent.RESOLUTION_WARNING)

        return events

    # ---------- internals ----------
    def _targets(self):
        if self._policy.has_targets_for(self._priority):
            return self._policy.targets_for(self._priority)
        return SLAPolicy.default().targets_for(self._priority)

    def _effective_elapsed(self, now):
        end = self._paused_at if self._paused_at is not None else now
        return (end - self._created_at) - self._paused_total

    def _current_response_elapsed(self):
        if self._response_elapsed is not None:
            return self._response_elapsed
        return self._clock.now() - self._created_at

    def _current_resolution_elapsed(self):
        if self._resolution_elapsed is not None:
            return self._resolution_elapsed
        return self._effective_elapsed(self._clock.now())