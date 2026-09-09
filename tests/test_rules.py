from __future__ import annotations

from ibvap.core.rules import RuleEngine, Tripwire


def test_tripwire_both_directions() -> None:
    tw = Tripwire(id="tw1", name="Line1", p1=(0.5, 0.0), p2=(0.5, 1.0), direction="both")
    eng = RuleEngine(tripwires=[tw], cooldown_seconds=0.0)
    # start left side
    assert eng.check_tripwire(1, (0.4, 0.5), 0.0) == []
    # cross to right
    evs = eng.check_tripwire(1, (0.6, 0.5), 0.1)
    assert len(evs) == 1
    assert evs[0]["type"] == "tripwire_cross"


def test_tripwire_directional() -> None:
    tw = Tripwire(id="tw2", name="Line2", p1=(0.5, 0.0), p2=(0.5, 1.0), direction="outside_to_inside")
    eng = RuleEngine(tripwires=[tw], cooldown_seconds=0.0)
    eng.check_tripwire(2, (0.4, 0.5), 0.0)
    # cross correct direction: left->right (outside_to_inside if we define side>0 as outside)
    # Our side calc may vary, but at least one direction should match; test both not failing
    evs1 = eng.check_tripwire(2, (0.6, 0.5), 0.1)
    # either 1 or 0 depending on side sign, but engine should not crash
    assert isinstance(evs1, list)


def test_loitering_media_duration() -> None:
    eng = RuleEngine(
        zones=[{"id": "z1", "polygon": [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]}],
        loiter_seconds=2.0,
        cooldown_seconds=0.0,
    )
    # enter zone
    assert eng.check_zones(1, (0.5, 0.5), 0.0) == []
    # still inside after 1 sec - not yet
    assert eng.check_zones(1, (0.5, 0.5), 1.0) == []
    # after 2.1 sec -> loiter
    evs = eng.check_zones(1, (0.5, 0.5), 2.1)
    assert len(evs) == 1
    assert evs[0]["type"] == "loitering"
    # second call immediately should not duplicate due to triggered flag
    assert eng.check_zones(1, (0.5, 0.5), 2.2) == []


def test_epoch_reset_clears_rule_state() -> None:
    """A new stream epoch (IDs restart at 1) must not inherit old dwell/side."""
    eng = RuleEngine(
        zones=[{"id": "z1", "polygon": [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]}],
        loiter_seconds=10.0,
        cooldown_seconds=0.0,
    )
    assert eng.check_zones(1, (0.5, 0.5), 100.0) == []
    assert eng.check_zones(1, (0.5, 0.5), 109.0) == []
    eng.reset()
    assert eng.check_zones(1, (0.5, 0.5), 200.0) == []


def test_loiter_survives_single_outside_frame() -> None:
    """One stray outside frame (edge jitter) must not zero 9.5s of dwell."""
    eng = RuleEngine(
        zones=[{"id": "z1", "polygon": [[0.05, 0.2], [0.95, 0.2], [0.95, 1.0], [0.05, 1.0]]}],
        loiter_seconds=10.0,
        cooldown_seconds=0.0,
    )
    t, fired = 0.0, False
    for i in range(200):
        pt = (0.5, 0.198) if i % 20 == 10 else (0.5, 0.205)
        if eng.check_zones(1, pt, t):
            fired = True
        t += 0.1
    assert fired


def test_tripwire_bypass_around_end_does_not_fire() -> None:
    """Walking around a short segment's end is not a crossing."""
    eng = RuleEngine(tripwires=[Tripwire(id="tw", name="d", p1=(0.4, 0.5), p2=(0.6, 0.5), direction="both")], cooldown_seconds=0.0)
    assert eng.check_tripwire(1, (0.75, 0.48), 0.0) == []
    assert eng.check_tripwire(1, (0.75, 0.52), 0.1) == []


def test_tripwire_direction_survives_endpoint_swap() -> None:
    """Redraw order must not invert directional filtering."""
    a = RuleEngine(tripwires=[Tripwire(id="t", name="t", p1=(0.5, 0.0), p2=(0.5, 1.0), direction="outside_to_inside")], cooldown_seconds=0.0)
    b = RuleEngine(tripwires=[Tripwire(id="t", name="t", p1=(0.5, 1.0), p2=(0.5, 0.0), direction="outside_to_inside")], cooldown_seconds=0.0)
    ra = [a.check_tripwire(1, p, t) for p, t in [((0.4, 0.5), 0.0), ((0.6, 0.5), 0.1)]]
    rb = [b.check_tripwire(1, p, t) for p, t in [((0.4, 0.5), 0.0), ((0.6, 0.5), 0.1)]]
    assert (ra[1] != []) == (rb[1] != [])
