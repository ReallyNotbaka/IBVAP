"""C2 Webhook Dispatcher and System Settings Engine."""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

from ibvap.core.ssrf import SSRFError, SSRFPolicy, resolve_and_validate, validate_endpoint

SETTINGS_PATH = Path("data/settings.json")
logger = logging.getLogger(__name__)

# Task 1 P0: webhook egress policy — http(s) only, no redirects. Destination is
# controlled via IP denial (loopback/link-local/multicast/metadata/private all
# blocked at resolve time), not via ports: explicit non-camera ports (e.g.
# :8443) pass the structural check and are pinned below. allowed_ports=None
# keeps the camera-default gate for validate_endpoint; "blocked_port" is
# downgraded to pass-through in _parse_webhook_url (fix-round 1: replaces the
# wasteful frozenset(range(1, 65536))).
_WEBHOOK_POLICY = SSRFPolicy(
    allowed_schemes=frozenset({"http", "https"}),
    allowed_hosts=None,
    allowed_ports=None,
    site_cidr_allowlist=(),
    allow_redirects=False,
)


def _parse_webhook_url(url: str) -> urllib.parse.ParseResult:
    """Structural webhook validation. Raises SSRFError on denial."""
    try:
        return validate_endpoint(url, _WEBHOOK_POLICY)
    except SSRFError as e:
        if e.code != "blocked_port":
            raise
        # Webhook policy pins destination, not port: credential / scheme /
        # literal-IP / metadata checks above already passed, so re-parse without
        # the camera port allowlist and let DNS/IP validation decide below.
        clean = url.strip().strip('"').strip("'")
        parsed = urllib.parse.urlparse(clean)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
            raise SSRFError("invalid_url", "URL must include scheme and host") from None
        return parsed


def resolve_webhook_url(url: str) -> tuple[str, list[str]]:
    """Validate + resolve a webhook URL. Returns (url, validated IPs).

    Raises SSRFError on any denial, including transient DNS failure (callers
    map to 400 / failure — no save-time leniency, fix-round 1). DNS cache is
    bypassed so every call revalidates current records (rebinding-safe).
    """
    parsed = _parse_webhook_url(url)
    ips = resolve_and_validate(parsed.hostname or "", _WEBHOOK_POLICY, timeout=3.0, bypass_cache=True)
    return url, ips


def validate_webhook_url(url: str, *, resolve_dns: bool = True) -> str:
    """SSRF-guard a C2 webhook URL. Raises SSRFError on denial (Task 1 P0)."""
    if resolve_dns:
        resolve_webhook_url(url)
    else:
        _parse_webhook_url(url)
    return url


def pin_url_to_ip(url: str, ip: str) -> str:
    """Rewrite a webhook URL's host to a validated IP literal (pure helper).

    Webhook URLs never carry userinfo (validate_endpoint rejects credentials
    in URL), so only host/port are rebuilt. IPv6 literals are bracketed.
    """
    parsed = urllib.parse.urlparse(url)
    host = f"[{ip}]" if ":" in ip and not ip.startswith("[") else ip
    port = f":{parsed.port}" if parsed.port is not None else ""
    return urllib.parse.urlunparse(parsed._replace(netloc=f"{host}{port}"))


async def _post_webhook(url: str, payload: dict[str, Any], timeout_s: float) -> httpx.Response:
    """POST JSON to an SSRF-validated webhook URL (Task 1 P0 fix-round 1).

    DNS is re-resolved (no cache) immediately before egress. Plain-http targets
    are pinned to the validated IP with the original Host header, closing the
    resolve→connect TOCTOU window. For https the TLS handshake must see the
    hostname (SNI + cert verification), so IP pinning would break verification;
    https therefore revalidates-then-posts with a residual TOCTOU window —
    ACCEPTED RISK (operator-configured URL + per-call revalidation + no
    redirects; see SDD ledger note). Raises SSRFError on policy denial.
    """
    _, ips = resolve_webhook_url(url)
    parsed = urllib.parse.urlparse(url)
    target, headers = url, None
    if parsed.scheme.lower() == "http" and ips:
        target = pin_url_to_ip(url, ips[0])
        headers = {"Host": parsed.hostname or ""}
    async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=False) as client:
        return await client.post(target, json=payload, headers=headers)


@dataclass
class SystemSettings:
    c2_webhook_url: str | None = None
    c2_webhook_enabled: bool = False
    c2_min_severity: str = "HIGH"  # ALL | HIGH | CRITICAL
    detection_confidence_threshold: float = 0.45
    loiter_cooldown_seconds: float = 10.0
    evidence_retention_days: int = 90


_CURRENT_SETTINGS = SystemSettings()


def load_settings() -> SystemSettings:
    """Load settings from JSON file into memory."""
    global _CURRENT_SETTINGS
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            _CURRENT_SETTINGS = SystemSettings(
                c2_webhook_url=data.get("c2_webhook_url"),
                c2_webhook_enabled=bool(data.get("c2_webhook_enabled", False)),
                c2_min_severity=data.get("c2_min_severity", "HIGH"),
                detection_confidence_threshold=float(data.get("detection_confidence_threshold", 0.45)),
                loiter_cooldown_seconds=float(data.get("loiter_cooldown_seconds", 10.0)),
                evidence_retention_days=int(data.get("evidence_retention_days", 90)),
            )
        except Exception as e:
            logger.warning("Failed to load settings from %s: %s", SETTINGS_PATH, e)
    return _CURRENT_SETTINGS


def save_settings(new_settings: SystemSettings) -> None:
    """Persist settings to data/settings.json."""
    global _CURRENT_SETTINGS
    _CURRENT_SETTINGS = new_settings
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(asdict(new_settings), indent=2), encoding="utf-8")
    except Exception as e:
        logger.error("Failed to save settings: %s", e)


def get_settings() -> SystemSettings:
    """Get active runtime settings."""
    return _CURRENT_SETTINGS


async def dispatch_c2_webhook(event: dict[str, Any], base_url: str = "") -> bool:
    """Send alert payload to configured C2 webhook."""
    settings = get_settings()
    if not settings.c2_webhook_enabled or not settings.c2_webhook_url:
        return False

    etype = str(event.get("event_type", "")).lower()
    is_critical = "watchlist" in etype or "suspect" in etype
    is_high = "intrusion" in etype or "line" in etype

    if settings.c2_min_severity == "CRITICAL" and not is_critical:
        return False
    if settings.c2_min_severity == "HIGH" and not (is_critical or is_high):
        return False

    severity = "CRITICAL" if is_critical else ("HIGH" if is_high else "MEDIUM")

    snap_url = event.get("snapshot_url")
    crop_url = event.get("crop_url")
    if snap_url and not snap_url.startswith("http"):
        snap_url = f"{base_url}{snap_url}"
    if crop_url and not crop_url.startswith("http"):
        crop_url = f"{base_url}{crop_url}"

    payload = {
        "event_id": event.get("id"),
        "event_type": event.get("event_type"),
        "severity": severity,
        "camera_id": event.get("camera_id"),
        "zone_id": event.get("zone_id"),
        "timestamp": event.get("created_at"),
        "explanation": event.get("explanation"),
        "confidence": event.get("confidence"),
        "snapshot_url": snap_url,
        "crop_url": crop_url,
    }

    try:
        # Task 1 P0: SSRF-validated + pinned egress via _post_webhook (DNS may rebind).
        resp = await _post_webhook(settings.c2_webhook_url, payload, 3.0)
        return resp.status_code < 400
    except SSRFError as e:
        logger.warning("C2 webhook dispatch blocked by SSRF policy: %s", e.code)
        return False
    except Exception as exc:
        logger.warning("C2 webhook dispatch failed: %s", exc)
        return False


async def test_webhook_connection(url: str) -> dict[str, Any]:
    """Send test alert ping to verify external C2 webhook endpoint.

    Raises SSRFError on policy denial (route maps to 400) — validated inside
    _post_webhook immediately before egress.
    """
    test_payload = {
        "event_type": "c2_connection_test",
        "severity": "INFO",
        "message": "IBVAP Command & Control Webhook Operational Test",
        "timestamp": time.time(),
    }
    t0 = time.perf_counter()
    try:
        resp = await _post_webhook(url, test_payload, 5.0)
    except SSRFError:
        raise
    except Exception as e:
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        return {
            "success": False,
            "status_code": 0,
            "elapsed_ms": elapsed_ms,
            "message": f"Connection failed: {str(e)}",
        }
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    return {
        "success": resp.status_code < 400,
        "status_code": resp.status_code,
        "elapsed_ms": elapsed_ms,
        "message": (f"Server responded with {resp.status_code} in {elapsed_ms}ms" if resp.status_code < 400 else f"HTTP error {resp.status_code}"),
    }
