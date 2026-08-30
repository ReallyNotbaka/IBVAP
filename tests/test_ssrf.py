from __future__ import annotations

import ipaddress

import pytest

from ibvap.core.ssrf import (
    DEFAULT_POLICY,
    SSRFPolicy,
    validate_endpoint,
    validate_resolved_ips,
)


def test_blocked_scheme() -> None:
    policy = DEFAULT_POLICY
    with pytest.raises(Exception) as ei:
        validate_endpoint("ftp://example.com/video", policy)
    assert "blocked_scheme" in str(ei.value) or hasattr(ei.value, "code")


def test_credential_in_url_blocked() -> None:
    with pytest.raises(Exception) as ei:
        validate_endpoint("http://user:pass@example.com/video", DEFAULT_POLICY)
    assert getattr(ei.value, "code", "") == "credential_in_url"


def test_loopback_blocked() -> None:
    policy = DEFAULT_POLICY
    # validate_resolved_ips should block 127.0.0.1
    with pytest.raises(Exception) as ei:
        validate_resolved_ips(["127.0.0.1"], policy)
    assert getattr(ei.value, "code", "") == "blocked_address"


def test_link_local_blocked() -> None:
    with pytest.raises(Exception) as ei:
        validate_resolved_ips(["169.254.0.5"], DEFAULT_POLICY)
    assert getattr(ei.value, "code", "") == "blocked_address"


def test_metadata_blocked() -> None:
    with pytest.raises(Exception) as ei:
        validate_resolved_ips(["169.254.169.254"], DEFAULT_POLICY)
    assert getattr(ei.value, "code", "") == "blocked_address"


def test_private_without_allowlist_blocked() -> None:
    with pytest.raises(Exception) as ei:
        validate_resolved_ips(["192.168.1.10"], DEFAULT_POLICY)
    assert getattr(ei.value, "code", "") == "blocked_private"


def test_private_with_allowlist_allowed() -> None:
    policy = SSRFPolicy(
        allowed_schemes=frozenset({"http", "https", "rtsp", "rtsps"}),
        allowed_hosts=None,
        allowed_ports=None,
        site_cidr_allowlist=(ipaddress.ip_network("192.168.1.0/24"),),
    )
    # should not raise
    validate_resolved_ips(["192.168.1.10"], policy)


def test_public_allowed_when_not_blocked() -> None:
    policy = DEFAULT_POLICY
    # 8.8.8.8 is public and not blocked
    validate_resolved_ips(["8.8.8.8"], policy)


def test_validate_endpoint_allows_http() -> None:
    parsed = validate_endpoint("http://192.168.1.10:8080/video", DEFAULT_POLICY)
    assert parsed.hostname == "192.168.1.10"
