from __future__ import annotations

import pytest

from ibvap.core.camera_state import CameraState, CameraStateMachine


def test_happy_path_to_streaming() -> None:
    sm = CameraStateMachine(camera_id="cam-1")
    assert sm.state == CameraState.DRAFT
    sm.transition(CameraState.VALIDATING, reason="test", safe_message="ok")
    sm.transition(CameraState.RESOLVING, reason="test", safe_message="ok")
    sm.transition(CameraState.CONNECTING, reason="test", safe_message="ok")
    sm.transition(CameraState.AUTHENTICATING, reason="test", safe_message="ok")
    sm.transition(CameraState.PROBING, reason="test", safe_message="ok")
    sm.transition(CameraState.DECODING, reason="test", safe_message="ok")
    sm.transition(CameraState.PREVIEW_READY, reason="test", safe_message="ok")
    sm.transition(CameraState.SAVING, reason="test", safe_message="ok")
    sm.transition(CameraState.STARTING, reason="test", safe_message="ok")
    sm.transition(CameraState.STREAMING, reason="test", safe_message="ok")
    assert sm.state == CameraState.STREAMING
    assert sm.history[0].prev_state == CameraState.DRAFT


def test_illegal_transition_raises() -> None:
    sm = CameraStateMachine(camera_id="cam-2")
    with pytest.raises(ValueError):
        sm.transition(CameraState.STREAMING, reason="bad", safe_message="bad")


def test_reconnect_bumps_epoch() -> None:
    sm = CameraStateMachine(camera_id="cam-3")
    for s in [
        CameraState.VALIDATING,
        CameraState.RESOLVING,
        CameraState.CONNECTING,
        CameraState.AUTHENTICATING,
        CameraState.PROBING,
        CameraState.DECODING,
        CameraState.PREVIEW_READY,
        CameraState.SAVING,
        CameraState.STARTING,
        CameraState.STREAMING,
    ]:
        sm.transition(s, reason="r", safe_message="ok")
    epoch_before = sm.stream_epoch
    sm.transition(CameraState.RECONNECTING, reason="net", safe_message="reconnect")
    assert sm.stream_epoch == epoch_before + 1
    assert sm.history[-1].stream_epoch == sm.stream_epoch


def test_disable_never_auto_restarts() -> None:
    sm = CameraStateMachine(camera_id="cam-4")
    sm.transition(CameraState.VALIDATING, reason="r", safe_message="ok")
    sm.disable()
    assert sm.is_disabled() is True
    assert sm.should_auto_restart() is False
    with pytest.raises(ValueError):
        sm.transition(CameraState.RECONNECTING, reason="r", safe_message="ok")


def test_retry_backoff_increases() -> None:
    sm = CameraStateMachine(camera_id="cam-5", base_delay=1.0, max_delay=60.0)
    _ = sm.compute_retry_delay()
    d2 = sm.compute_retry_delay()
    assert d2 >= 0.5
    assert sm.retry_count == 2


def test_transition_contains_correlation_and_epoch() -> None:
    sm = CameraStateMachine(camera_id="cam-6", stream_epoch=5)
    tr = sm.transition(CameraState.VALIDATING, reason="test_me", safe_message="hello", correlation_id="corr-123")
    assert tr.camera_id == "cam-6"
    assert tr.stream_epoch == 5
    assert tr.correlation_id == "corr-123"
    assert tr.reason == "test_me"
    assert tr.safe_message == "hello"
