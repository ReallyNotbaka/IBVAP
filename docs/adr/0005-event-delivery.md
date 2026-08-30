# ADR-0005: Event Delivery — PostgreSQL Outbox + Signed C2 Webhook

- **Status:** Accepted (Phase 0)
- **Date:** 2026-08-30
- **Spec:** §5 Reliability & storage, §6 Architecture, §16–17 Events/evidence, §22 C2 Integration, §23 Remote/offline, §25 Observability

## Context

Spec requires:

- Every qualified event is an **atomic DB transaction** that writes `event + initial alert + evidence job + outbox entry` (spec §17 + §6 diagram).
- Delivery is **at-least-once, ordered, idempotent** to both local WebSocket clients and external C2 webhooks, surviving WAN loss and MediaMTX/storage restarts.
- C2 contract must be **versioned JSON Schema, signed (HMAC-SHA256 or reviewed scheme), timestamp/nonce/keyId/canonical digest, rotating secret, optional mTLS, allowlisted endpoints, redirect-strict, timeout + response-size capped** (§22).
- Local frames are **bounded queues (intentional drops)** — but **events/outbox are durable, never silently dropped** (§5/10).

Prototype `attempt` uses `src/sentinel/events/storage.py` SQLite WAL + `src/sentinel/events/bus.py` WAL dual-delivery + `src/sentinel/events/webhooks.py` retry — not the PG transactional outbox required. It also lacks evidence manifests, clip ring buffer, and outbox back-pressure metrics.

## Decision

### 1. Reliability pattern: Transactional Outbox (PostgreSQL)

```sql
-- single transaction (§17)
BEGIN;
  INSERT INTO events (...) VALUES (...) RETURNING id;
  INSERT INTO alerts (...) VALUES (...) RETURNING id;
  INSERT INTO evidence_jobs (event_id, required, ...);
  INSERT INTO outbox (id, topic, payload, headers, available_at) VALUES (...);
COMMIT;
-- relay reads outbox FOR UPDATE SKIP LOCKED, delivers, marks done/DLQ
```

Tables (per spec §18 — subset that covers this ADR):

- `outbox(id uuid7 PK, topic text, payload jsonb, headers jsonb, status enum('pending','inflight','done','deadletter'), attempts int, next_attempt_at timestamptz, created_at, delivered_at, dedup_key text UNIQUE)`
- `webhook_deliveries(id, outbox_id FK, endpoint_id FK, attempt int, status, http_code, error_redacted, delivered_at, retry_after)`
- `events` + `alerts` + `evidence_assets` (ring buffer + manifest/hash as §17)

Relay:
- Poll `SELECT ... WHERE status='pending' AND next_attempt_at <= now() ORDER BY created_at LIMIT N FOR UPDATE SKIP LOCKED` (lease `N`).
- In-memory per-destination bounded queue is **NOT** the outbox; the PG table is the durable queue.

### 2. WebSocket (local, authenticated)

- Endpoint `GET /api/v1/ws` authenticated via short-lived token (not credential leakage).
- Per-client bounded queue (`max_size=64`, `drop=oldest-overlay`). **Overlay `observation.update` may coalesce/drop**; `event.created/updated`, `alert.updated` are **durable — clients resync via REST cursor** if dropped (spec §20: "Events and alerts must remain durable and recoverable through REST").
- Versioned envelope: `schema_version, message_id, message_type, timestamp, sequence, camera_id, site_id, stream_epoch, correlation_id, payload` — mirrors spec §20 list.
- Messages: `camera.state, camera.health, observation.update, event.created/updated, alert.updated, job.updated, storage.pressure, system.degraded, resync.required, heartbeat`.

### 3. C2 Webhook (signed HTTPS)

Spec §22 adapter is generic, versioned — do NOT claim named C2 product without contract.

CAD:
```
IBVAP outbox → signer (canonical JSON + body digest + timestamp/nonce/delivery_id/keyId) → HMAC-SHA256 → HTTPS POST
             → verifier on C2 (allowlisted URL, mTLS optional) → 2xx = done, 5xx/429 = retry with backoff, 4xx = dead-letter (non-retryable)
```

Canonical body: deterministic JSON key sort + compact `separators=(',',':')` + `utf-8`.

Headers (example):
```
X-IBVAP-Signature: sha256=<hex hmac>
X-IBVAP-Timestamp: 2026-08-30T15:30:00Z
X-IBVAP-Nonce: <delivery_id>
X-IBVAP-Key-Id: k1
X-IBVAP-Idempotency-Key: <stable event_id>
Idempotency-Key: <same>
Content-Type: application/json
```

- Payload schema: versioned `v1` JSON Schema; fields: `event_id (uuid7), delivery_id, idempotency_key, correlation_id, camera_id, site_id, rule_name/version, model_provenance{artifact_id,version,sha256}, confidence, uncertainty, geometry(normalized), thresholds{observed/value}` + evidence manifest references (signed URLs, not raw bytes).
- Security: rotating `endpoint_secret` per C2 integration (`integrations.endpoint_secret` encrypted via envelope, `pgcrypto` or KMS); key rotation via `X-IBVAP-Key-Id` header; HMAC key never in logs.
- Retry: exponential backoff with jitter (`base 5s * 2^attempt + jitter`), bounded `Retry-After` header respected (max 5 min), cutoff after `max_retries` → `deadletter`; audited replay (`POST /api/v1/integrations/{id}/deliveries/{delivery_id}/replay` — admin only, audit logged).

### 4. Durability vs Latency split

| Stream | Durability | Latency budget | Drop policy |
|--------|------------|----------------|-------------|
| Raw frames (demux→sampling→inference) | none (memory) | <400ms queue age | drop oldest stale |
| Qualified events/alerts/outbox | **PG durable, idempotent `dedup_key = camera_id:rule_id:track_id:window`** | durable, bounded relay lag | never drop; back-pressure via storage-pressure thresholds |
| WebSocket overlay | best-effort | <150ms | coalesce/drop stale |
| Evidence (snapshot PNG + clip MP4) | FS/S3 durable + manifest SHA-256 | p95 <2s after event §25 | degrade: stop uploads first (§23) |

Offline mode (§23): relay pauses `C2` deliveries; PG outbox counts/types/bytes/oldest item exposed via `metrics.outbox_backlog{item_type}` + `outbox_oldest_age_seconds`. On reconnect: metadata→snapshots→clips order; multipart resume + checksum.

## Alternatives Considered

| Alt | Why rejected |
|-----|--------------|
| Direct webhook without outbox (fire-and-forget) | Not durable under WAN loss; violates §6 "outbox entry" atomicity |
| Redis Streams / Kafka as event bus | Spec §5 forbids for events — PG outbox is primary; Redis would be second durable store |
| Celery/Redis for frame transport | Forbidden per §5 frames embargo |

## Consequences

- Relay is a **separate worker** (`durable-job worker` §6) — not the API process (`API process must not execute permanent stream-processing loops`).
- Need envelope encryption for webhook secrets (§21) and audit table for `replay`/`delivery` events.
- Outbox relay metrics join OTEL dashboard (`outbox_backlog_items`, `outbox_oldest_age_seconds`, `integration_retries_total`).

## Validation (Phase 5 gate)

- Integration: `test_event_outbox_atomicity` — crash between PG commit and relay must show no double delivery via `idempotency_key`.
- Security: webhook replay test with stale timestamp/nonce must be rejected.
- Chaos: `WAN loss` → outbox backlog grows; reconnect → items drain idempotently.

## Upgrade Path

- Schema version `v1 → v2` via additive JSON Schema (`anyOf` migration); old deliveries replay with v1 envelope.
- Add second relay shard when backlog `p99 next_attempt_at` exceeds 60s.

---

*References:* spec §17/20/22/23, `attempt/src/sentinel/events/webhooks.py` prior retry pattern, transactional outbox pattern (Chris Richardson).
