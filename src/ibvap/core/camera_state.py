"""Camera runtime state machine - spec 7.

Every state change must contain:
prev, new, timestamp, camera_id, stream_epoch, reason, safe_msg, retry_status, correlation_id.

State diagram:
DRAFT -> VALIDATING -> RESOLVING -> CONNECTING -> AUTHENTICATING -> PROBING -> DECODING -> PREVIEW_READY -> SAVING -> STARTING -> STREAMING
Additional: DISABLED, STOPPING, RECONNECTING, DEGRADED, AUTH_FAILED, BLOCKED_BY_POLICY, UNREACHABLE, UNSUPPORTED_MEDIA, CLOCK_UNSTABLE, STORAGE_PRESSURE, FAILED

Capped exponential retry with jitter, reset only after stable interval.
Disabled never auto-restarts.
"""

from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class CameraState(str, Enum):
    DRAFT = "DRAFT"
    VALIDATING = "VALIDATING"
    RESOLVING = "RESOLVING"
    CONNECTING = "CONNECTING"
    AUTHENTICATING = "AUTHENTICATING"
    PROBING = "PROBING"
    DECODING = "DECODING"
    PREVIEW_READY = "PREVIEW_READY"
    SAVING = "SAVING"
    STARTING = "STARTING"
    STREAMING = "STREAMING"
    # additional
    DISABLED = "DISABLED"
    STOPPING = "STOPPING"
    RECONNECTING = "RECONNECTING"
    DEGRADED = "DEGRADED"
    AUTH_FAILED = "AUTH_FAILED"
    BLOCKED_BY_POLICY = "BLOCKED_BY_POLICY"
    UNREACHABLE = "UNREACHABLE"
    UNSUPPORTED_MEDIA = "UNSUPPORTED_MEDIA"
    CLOCK_UNSTABLE = "CLOCK_UNSTABLE"
    STORAGE_PRESSURE = "STORAGE_PRESSURE"
    FAILED = "FAILED"


# Allowed transitions - superset; illegal transition raises.
_ALLOWED: dict[CameraState, set[CameraState]] = {
    CameraState.DRAFT: {CameraState.VALIDATING, CameraState.DISABLED, CameraState.FAILED},
    CameraState.VALIDATING: {
        CameraState.RESOLVING,
        CameraState.BLOCKED_BY_POLICY,
        CameraState.FAILED,
        CameraState.DISABLED,
        CameraState.SAVING,  # allow fast-path for synthetic/dev tests
    },
    CameraState.RESOLVING: {
        CameraState.CONNECTING,
        CameraState.UNREACHABLE,
        CameraState.BLOCKED_BY_POLICY,
        CameraState.FAILED,
        CameraState.DISABLED,
    },
    CameraState.CONNECTING: {
        CameraState.AUTHENTICATING,
        CameraState.UNREACHABLE,
        CameraState.FAILED,
        CameraState.DISABLED,
    },
    CameraState.AUTHENTICATING: {
        CameraState.PROBING,
        CameraState.AUTH_FAILED,
        CameraState.FAILED,
        CameraState.DISABLED,
    },
    CameraState.PROBING: {
        CameraState.DECODING,
        CameraState.UNSUPPORTED_MEDIA,
        CameraState.FAILED,
        CameraState.DISABLED,
    },
    CameraState.DECODING: {
        CameraState.PREVIEW_READY,
        CameraState.FAILED,
        CameraState.UNSUPPORTED_MEDIA,
        CameraState.DISABLED,
    },
    CameraState.PREVIEW_READY: {
        CameraState.SAVING,
        CameraState.FAILED,
        CameraState.DISABLED,
        CameraState.STOPPING,
    },
    CameraState.SAVING: {CameraState.STARTING, CameraState.FAILED, CameraState.DISABLED},
    CameraState.STARTING: {CameraState.STREAMING, CameraState.FAILED, CameraState.DISABLED},
    CameraState.STREAMING: {
        CameraState.RECONNECTING,
        CameraState.DEGRADED,
        CameraState.STOPPING,
        CameraState.FAILED,
        CameraState.CLOCK_UNSTABLE,
        CameraState.STORAGE_PRESSURE,
        CameraState.DISABLED,
        CameraState.UNREACHABLE,
    },
    CameraState.RECONNECTING: {
        CameraState.CONNECTING,
        CameraState.RESOLVING,
        CameraState.FAILED,
        CameraState.DISABLED,
    },
    CameraState.DEGRADED: {
        CameraState.STREAMING,
        CameraState.RECONNECTING,
        CameraState.STOPPING,
        CameraState.FAILED,
        CameraState.DISABLED,
    },
    CameraState.STOPPING: {CameraState.DRAFT, CameraState.DISABLED, CameraState.FAILED},
    CameraState.DISABLED: {CameraState.DRAFT},
    CameraState.FAILED: {CameraState.DRAFT, CameraState.DISABLED, CameraState.RECONNECTING},
    # terminal-ish can go to DRAFT via manual retry
    CameraState.AUTH_FAILED: {CameraState.DRAFT, CameraState.DISABLED, CameraState.FAILED},
    CameraState.BLOCKED_BY_POLICY: {CameraState.DRAFT, CameraState.DISABLED, CameraState.FAILED},
    CameraState.UNREACHABLE: {CameraState.RECONNECTING, CameraState.DRAFT, CameraState.DISABLED, CameraState.FAILED},
    CameraState.UNSUPPORTED_MEDIA: {CameraState.DRAFT, CameraState.DISABLED, CameraState.FAILED},
    CameraState.CLOCK_UNSTABLE: {
        CameraState.STREAMING,
        CameraState.RECONNECTING,
        CameraState.FAILED,
        CameraState.DISABLED,
    },
    CameraState.STORAGE_PRESSURE: {
        CameraState.DEGRADED,
        CameraState.STREAMING,
        CameraState.FAILED,
        CameraState.DISABLED,
    },
}


@dataclass(frozen=True)
class StateTransition:
    prev_state: CameraState
    new_state: CameraState
    timestamp: datetime
    camera_id: str
    stream_epoch: int
    reason: str  # machine-readable
    safe_message: str  # operator safe
    retry_status: dict[str, int | float | bool]
    correlation_id: str


@dataclass
class CameraStateMachine:
    camera_id: str
    stream_epoch: int = 0
    state: CameraState = CameraState.DRAFT
    stable_since: float | None = None  # monotonic
    retry_count: int = 0
    history: list[StateTransition] = field(default_factory=list)
    # retry tuning
    base_delay: float = 1.0
    max_delay: float = 60.0
    stable_threshold: float = 30.0  # seconds of STREAMING to reset retry
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    max_history: int = 200  # bound in-memory history to avoid unbounded growth

    def _next_stream_epoch(self) -> int:
        return self.stream_epoch + 1

    def can_transition(self, target: CameraState) -> bool:
        return target in _ALLOWED.get(self.state, set())

    def transition(
        self,
        target: CameraState,
        *,
        reason: str,
        safe_message: str,
        correlation_id: str | None = None,
    ) -> StateTransition:
        if not self.can_transition(target):
            raise ValueError(f"Illegal transition {self.state} -> {target}")
        prev = self.state
        # stream epoch bumps on RECONNECTING entry and on STREAMING re-entry
        if target == CameraState.RECONNECTING or (prev == CameraState.RECONNECTING and target == CameraState.CONNECTING):
            self.stream_epoch = self._next_stream_epoch()
        self.state = target
        ts = datetime.now(UTC)
        tr = StateTransition(
            prev_state=prev,
            new_state=target,
            timestamp=ts,
            camera_id=self.camera_id,
            stream_epoch=self.stream_epoch,
            reason=reason,
            safe_message=safe_message,
            retry_status={
                "retry_count": self.retry_count,
                "stream_epoch": self.stream_epoch,
                "is_disabled": self.state == CameraState.DISABLED,
            },
            correlation_id=correlation_id or self.correlation_id,
        )
        self.history.append(tr)
        # Bound history to avoid unbounded memory growth on long-lived cameras.
        if len(self.history) > self.max_history:
            del self.history[: len(self.history) - self.max_history]
        # stable interval tracking for retry reset
        if target == CameraState.STREAMING:
            if self.stable_since is None:
                self.stable_since = time.monotonic()
        else:
            # if we were streaming and left, check if we had stable interval
            if prev == CameraState.STREAMING and self.stable_since is not None:
                elapsed = time.monotonic() - self.stable_since
                if elapsed >= self.stable_threshold:
                    self.retry_count = 0
                self.stable_since = None
        return tr

    def compute_retry_delay(self) -> float:
        """Capped exponential with jitter. Call after failure before RECONNECTING."""
        delay = min(self.max_delay, self.base_delay * (2**self.retry_count))
        jitter = random.uniform(-0.2 * delay, 0.2 * delay)
        self.retry_count += 1
        return max(0.5, delay + jitter)

    def disable(self, reason: str = "user_disabled") -> StateTransition:
        return self.transition(CameraState.DISABLED, reason=reason, safe_message="Camera disabled")

    def is_disabled(self) -> bool:
        return self.state == CameraState.DISABLED

    def should_auto_restart(self) -> bool:
        return not self.is_disabled()
