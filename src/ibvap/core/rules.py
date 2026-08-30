"""Rule engine - Phase 4."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ibvap.core.geometry import point_in_polygon

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


@dataclass
class LoiterState:
    enter_ts: float | None = None
    dwell_triggered: bool = False


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

    def check_tripwire(self, track_id: int, footpoint: tuple[float, float], timestamp: float) -> list[dict]:
        events: list[dict] = []
        for tw_id, tw in self.tripwires.items():
            st = self._trip_state.setdefault(track_id, {}).setdefault(tw_id, TripwireState())
            side = _side(footpoint, tw.p1, tw.p2)
            if not st.armed:
                if st.last_side is not None and abs(side - st.last_side) > tw.hysteresis:
                    st.armed = True
                else:
                    continue
            if st.last_side is None:
                st.last_side = side
                continue
            crossed = (st.last_side * side) < 0
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
            else:
                st.last_side = side
        return events

    def check_zones(self, track_id: int, footpoint: tuple[float, float], timestamp: float) -> list[dict]:
        events: list[dict] = []
        for zone in self.zones:
            zid = zone["id"]
            poly = zone["polygon"]
            inside = point_in_polygon(footpoint[0], footpoint[1], poly)
            ls = self._loiter_state.setdefault(track_id, {}).setdefault(zid, LoiterState())
            if inside:
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
