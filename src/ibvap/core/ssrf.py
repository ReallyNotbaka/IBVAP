"""SSRF checks for camera URLs.

Cameras are pretty much always on private IPs (192.168.x, 10.x etc) so we
can't just block private ranges outright. Caller passes in the site's
allowed CIDRs and we check every resolved IP against that. Also blocks
loopback, link-local, multicast and the cloud metadata IP.
Call resolve_and_validate on every connect/reconnect - DNS can change.
"""

from __future__ import annotations

import ipaddress
import socket
import threading
import time
import urllib.parse
from dataclasses import dataclass

# Blocked networks per spec 21.1 - always deny
_BLOCKED_NETS = [
    ipaddress.ip_network("127.0.0.0/8"),  # loopback
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("224.0.0.0/4"),  # multicast
    ipaddress.ip_network("ff00::/8"),
    ipaddress.ip_network("255.255.255.255/32"),  # broadcast
    # cloud metadata endpoints
    ipaddress.ip_network("169.254.169.254/32"),
    ipaddress.ip_network("fd00:ec2::254/128"),
]

# Control-plane / storage that must never be reachable from camera worker
_CONTROL_PLANE_NETS = [
    # loopback already above; add typical k8s / DB private ranges if configured via policy
]

# Camera-relevant ports allowed by default; override via SSRFPolicy.allowed_ports.
_DEFAULT_ALLOWED_PORTS: frozenset[int] = frozenset({80, 443, 554, 8554, 4747, 8080, 8000})


@dataclass(frozen=True)
class SSRFPolicy:
    """Site-scoped SSRF policy."""

    allowed_schemes: frozenset[str]
    allowed_hosts: frozenset[str] | None  # None = any host allowed if IP passes
    allowed_ports: frozenset[int] | None  # None = any port
    site_cidr_allowlist: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]
    blocked_nets: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = tuple(_BLOCKED_NETS)
    allow_redirects: bool = False


DEFAULT_POLICY = SSRFPolicy(
    allowed_schemes=frozenset({"rtsp", "rtsps", "http", "https"}),
    allowed_hosts=None,
    allowed_ports=_DEFAULT_ALLOWED_PORTS,
    site_cidr_allowlist=(),
)

# Short-TTL DNS cache to avoid redundant getaddrinfo on repeated probes.
# Raw IPs are cached; policy validation re-runs on every call so CIDR/block
# decisions always reflect the current policy (rebinding-safe within TTL).
_DNS_CACHE: dict[str, tuple[list[str], float]] = {}
_DNS_CACHE_TTL = 30.0
_DNS_CACHE_LOCK = threading.Lock()


class SSRFError(ValueError):
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


def _parse_strict(raw: str) -> urllib.parse.ParseResult:
    # Strict parser - reject credentials embedded in URL
    if "@" in raw.split("?")[0].split("#")[0]:
        # url contains userinfo before host - spec says separate credential fields
        raise SSRFError("credential_in_url", "Credentials must be provided separately, not in URL")
    try:
        parsed = urllib.parse.urlparse(raw)
    except Exception:
        raise SSRFError("invalid_url", "Invalid endpoint URL") from None
    if not parsed.scheme or not parsed.hostname:
        raise SSRFError("invalid_url", "URL must include scheme and host")
    return parsed


def _check_scheme(parsed: urllib.parse.ParseResult, policy: SSRFPolicy) -> None:
    if parsed.scheme.lower() not in policy.allowed_schemes:
        raise SSRFError("blocked_scheme", f"Scheme '{parsed.scheme}' is not allowed")


def _check_host_and_port(parsed: urllib.parse.ParseResult, policy: SSRFPolicy) -> None:
    host = parsed.hostname or ""
    # Explicit metadata-endpoint guard (host-based, before DNS).
    if is_metadata_endpoint(host):
        raise SSRFError("blocked_address", "Resolved address is blocked (metadata endpoint)")
    # If host is an IP literal, enforce blocked categories up-front
    # (unspecified/loopback/link-local/multicast/reserved + configured blocked nets).
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        if is_metadata_endpoint(host, str(literal_ip)):
            raise SSRFError("blocked_address", "Resolved address is blocked (metadata endpoint)")
        if (
            literal_ip.is_unspecified
            or literal_ip.is_loopback
            or literal_ip.is_link_local
            or literal_ip.is_multicast
            or literal_ip.is_reserved
        ):
            raise SSRFError("blocked_address", f"Resolved address {literal_ip} is blocked (reserved range)")
        blocked = _ip_blocked(literal_ip, policy)
        if blocked:
            raise SSRFError("blocked_address", f"Resolved address {literal_ip} is blocked ({blocked})")
    if policy.allowed_hosts is not None and host.lower() not in {h.lower() for h in policy.allowed_hosts}:
        raise SSRFError("blocked_host", "Host is not in allowlist")
    # Deny sensitive ports by default; explicit policy.allowed_ports overrides.
    # When allowed_ports is None (legacy callers), fall back to _DEFAULT_ALLOWED_PORTS.
    effective_ports = policy.allowed_ports if policy.allowed_ports is not None else _DEFAULT_ALLOWED_PORTS
    port = parsed.port
    # if port not explicit, default ports are implied - check implicit?
    if port is not None and port not in effective_ports:
        raise SSRFError("blocked_port", "Port is not in allowlist")


def _ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, policy: SSRFPolicy) -> str | None:
    for net in policy.blocked_nets:
        if ip in net:
            return f"blocked_network:{net}"
    for net in _CONTROL_PLANE_NETS:
        if ip in net:
            return f"control_plane:{net}"
    return None


def _ip_allowed_by_site(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, policy: SSRFPolicy) -> bool:
    # If no allowlist, private nets are blocked by default EXCEPT we already blocked loopback/link-local/multicast.
    # But per spec, legitimate cameras use private nets, so if allowlist empty we DENY private otherwise would be too permissive.
    # Caller must provide site_cidr_allowlist to permit private ranges.
    if ip.is_private:
        if not policy.site_cidr_allowlist:
            return False
        return any(ip in net for net in policy.site_cidr_allowlist)
    # Public IPs: allow if not blocked (unless control-plane nets)
    return True


def validate_endpoint(raw_url: str, policy: SSRFPolicy = DEFAULT_POLICY) -> urllib.parse.ParseResult:
    """Validate URL string against SSRF policy. Returns parsed URL if ok, else raises SSRFError.

    Callers must also resolve DNS and call validate_resolved_ips for the hostname.
    """
    parsed = _parse_strict(raw_url)
    _check_scheme(parsed, policy)
    _check_host_and_port(parsed, policy)
    # DNS resolution + per-IP checks are separate (needs network); _parse_strict ensures no creds-leak.
    return parsed


def validate_resolved_ips(ips: list[str], policy: SSRFPolicy = DEFAULT_POLICY) -> None:
    """Validate every resolved A/AAAA string. Raise SSRFError if any fails.

    Use after socket.getaddrinfo. For DNS-rebinding defense, call again on every reconnect.
    """
    if not ips:
        raise SSRFError("unreachable", "Hostname did not resolve")
    for ip_str in ips:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            raise SSRFError("invalid_ip", f"Resolved IP '{ip_str}' is invalid") from None
        blocked = _ip_blocked(ip, policy)
        if blocked:
            raise SSRFError("blocked_address", f"Resolved address {ip} is blocked ({blocked})")
        if not _ip_allowed_by_site(ip, policy):
            raise SSRFError(
                "blocked_private",
                f"Private address {ip} not in site CIDR allowlist",
            )


def resolve_and_validate(host: str, policy: SSRFPolicy = DEFAULT_POLICY, timeout: float = 3.0) -> list[str]:
    """Resolve host and validate all returned IPs. Returns list of IP strings.

    Avoid mutating the process-wide socket timeout. DNS resolution itself has no per-call timeout
    in the stdlib, while the actual stream connection should enforce timeouts at the I/O layer.
    Successful lookups are cached briefly (TTL) to avoid redundant socket/DNS IO on
    repeated probes; cached IPs are still re-validated against the current policy.
    """
    _ = timeout
    now = time.monotonic()
    with _DNS_CACHE_LOCK:
        cached = _DNS_CACHE.get(host)
        if cached is not None and (now - cached[1]) < _DNS_CACHE_TTL:
            ips = list(cached[0])
            # Re-validate against current policy (policy may differ per site).
            try:
                validate_resolved_ips(ips, policy)
            except SSRFError:
                # Stale/blocked under new policy — drop cache entry and re-resolve.
                _DNS_CACHE.pop(host, None)
                raise
            return ips
    try:
        infos = socket.getaddrinfo(host, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise SSRFError("dns_failed", f"DNS resolution failed for {host}: {e}") from e
    ips: list[str] = list(dict.fromkeys(str(info[4][0]) for info in infos))
    validate_resolved_ips(ips, policy)
    with _DNS_CACHE_LOCK:
        _DNS_CACHE[host] = (list(ips), now)
    return ips


def is_metadata_endpoint(host: str, ip_str: str | None = None) -> bool:
    """Quick check for known cloud metadata hosts/IPs."""
    low = host.lower()
    if low in {"169.254.169.254", "metadata.google.internal", "metadata.google", "instance-data"}:
        return True
    if ip_str:
        try:
            ip = ipaddress.ip_address(ip_str)
            if ip in ipaddress.ip_network("169.254.169.254/32"):
                return True
        except ValueError:
            pass
    return False
