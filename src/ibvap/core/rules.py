"""Rule engine - Phase 4."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ibvap.core.geometry import intersect, point_in_polygon

TripDirection = Literal["outside_to_inside", "inside_to_outside", "both"]


@dataclass(frozen=True)
class Tripwire:
    id: str
    name: str
    p1: tuple[float, float]
    p2: tuple[float, float]
    direction: TripDirection = "both"
    hysteresis: float = 0.02


def _side(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


@dataclass
class TripwireState:
    last_side: float | None = None
    armed: bool = True
    last_cross: float = 0.0
    last_pos: tuple[float, float] | None = None


@dataclass
class LoiterState:
    enter_ts: float | None = None
    dwell_triggered: bool = False
    outside_streak: int = 0


class RuleEngine:
    def __init__(
        self,
        zones: list[dict] | None = None,
        tripwires: list[Tripwire] | None = None,
        loiter_seconds: float = 10.0,
        cooldown_seconds: float = 5.0,
    ) -> None:
        self.zones = zones or []
        self.tripwires = {tw.id: tw for tw in (tripwires or [])}
        self.loiter_seconds = loiter_seconds
        self.cooldown_seconds = cooldown_seconds
        self._trip_state: dict[int, dict[str, TripwireState]] = {}
        self._loiter_state: dict[int, dict[str, LoiterState]] = {}
        self._last_event_at: dict[str, float] = {}

    def reset(self) -> None:
        """Clear per-track dwell/side state. Call on stream epoch bumps:
        tracker IDs restart at 1, so a new track 1 must never inherit the
        previous track 1's dwell time or tripwire side.
        """
        self._trip_state.clear()
        self._loiter_state.clear()
        self._last_event_at.clear()

    def check_tripwire(self, track_id: int, footpoint: tuple[float, float], timestamp: float) -> list[dict]:
        events: list[dict] = []
        for tw_id, tw in self.tripwires.items():
            # get() chains avoid constructing a TripwireState default on every
            # per-track-per-frame call (setdefault evaluates its default eagerly).
            per_track = self._trip_state.get(track_id)
            if per_track is None:
                per_track = self._trip_state[track_id] = {}
            st = per_track.get(tw_id)
            if st is None:
                st = per_track[tw_id] = TripwireState()
            # Canonical orientation: endpoint order is a drawing detail and
            # must not flip sides (and hence directional filtering).
            a, b = (tw.p1, tw.p2) if tw.p1 <= tw.p2 else (tw.p2, tw.p1)
            side = _side(footpoint, a, b)
            if not st.armed:
                if st.last_side is not None and abs(side - st.last_side) > tw.hysteresis:
                    st.armed = True
                else:
                    continue
            if st.last_side is None or st.last_pos is None:
                st.last_side = side
                st.last_pos = footpoint
                continue
            # A side flip alone is not a crossing (walking around the
            # segment's end flips the infinite-line side): the movement
            # segment must actually intersect the tripwire segment.
            crossed = (st.last_side * side) < 0 and intersect(st.last_pos, footpoint, a, b)
            if crossed:
                direction_ok = (
                    tw.direction == "both"
                    or (tw.direction == "outside_to_inside" and st.last_side > 0 and side < 0)
                    or (tw.direction == "inside_to_outside" and st.last_side < 0 and side > 0)
                )
                if direction_ok:
                    dedup = (
                        f"trip:{tw_id}:{track_id}:{int(timestamp // self.cooldown_seconds)}"
                        if self.cooldown_seconds > 0
                        else f"trip:{tw_id}:{track_id}:{timestamp}"
                    )
                    if self._should_emit(dedup, timestamp):
                        events.append({"type": "tripwire_cross", "tripwire_id": tw_id, "direction": tw.direction})
                        st.armed = False
                        st.last_cross = timestamp
                st.last_side = side
                st.last_pos = footpoint
            else:
                st.last_side = side
                st.last_pos = footpoint
        return events

    def check_zones(self, track_id: int, footpoint: tuple[float, float], timestamp: float) -> list[dict]:
        events: list[dict] = []
        for zone in self.zones:
            zid = zone["id"]
            poly = zone["polygon"]
            inside = point_in_polygon(footpoint[0], footpoint[1], poly)
            # Same setdefault-alloc avoidance as check_tripwire.
            per_track_loiter = self._loiter_state.get(track_id)
            if per_track_loiter is None:
                per_track_loiter = self._loiter_state[track_id] = {}
            ls = per_track_loiter.get(zid)
            if ls is None:
                ls = per_track_loiter[zid] = LoiterState()
            if inside:
                ls.outside_streak = 0
                if ls.enter_ts is None:
                    ls.enter_ts = timestamp
                dwell = timestamp - ls.enter_ts
                if dwell >= self.loiter_seconds and not ls.dwell_triggered:
                    dedup = (
                        f"loiter:{zid}:{track_id}:{int(timestamp // self.cooldown_seconds)}"
                        if self.cooldown_seconds > 0
                        else f"loiter:{zid}:{track_id}:{timestamp}"
                    )
                    if self._should_emit(dedup, timestamp):
                        events.append({"type": "loitering", "zone_id": zid, "dwell": dwell})
                        ls.dwell_triggered = True
            else:
                # Hysteresis: one stray outside frame (edge jitter, YOLO wobble)
                # must not zero seconds of dwell. Reset only after 3
                # consecutive outside frames (~0.3s at 10fps).
                ls.outside_streak += 1
                if ls.outside_streak >= 3:
                    ls.enter_ts = None
                    ls.dwell_triggered = False
        return events

    def _should_emit(self, dedup: str, now: float) -> bool:
        if self.cooldown_seconds <= 0:
            self._last_event_at[dedup] = now
            return True
        last = self._last_event_at.get(dedup)
        if last is not None and (now - last) < self.cooldown_seconds:
            return False
        self._last_event_at[dedup] = now
        return True

    def explain(self, event: dict) -> dict:
        return {
            "rule": event.get("type"),
            "observed": event,
            "threshold": self.loiter_seconds if event.get("type") == "loitering" else "tripwire direction",
        }
