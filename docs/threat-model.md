# IBVAP Threat Model — Phase 0 Seed

**Date:** 2026-08-30
**Status:** Draft — expands in Phase 2 security work (§21)
**System:** IBVAP modular monolith (API + camera worker + durable-job worker + frontend + PG + MediaMTX)
**Trust boundary:** Public internet ↔ IBVAP API/WS ↔ Camera VLAN ↔ PG ↔ Object store ↔ C2 webhook

> Risk ratings are Phase 0 estimates (L/M/H). Full STRIDE + CVSS after Phase 2 SSRF/Upload hardening.

---

## 1. Attacker Types (spec §21 enumerated)

Compromised camera, malicious stream, hostile uploaded media, SSRF/DNS rebinding actor, parser vuln exploiter, credential thief, cross-tenant attacker, WS/Webhook abuser, insider, evidence tamperer, object-store exposure, model poisoner, adversarial pattern, dependency compromise, GPU/disk exhaustion, offline-edge theft, unsafe updater.

---

## 2. Assets & Impact

- **Camera credentials, PG credentials, JWT/session, webhook secrets, evidence (clips/snapshots), face embeddings, plate strings, audit logs, model weights**
- Impact H if exfiltrated/tampered — border operations compromise.

---

## 3. Threats & Mitigations (spec §21 required controls)

| ID | Threat / Vector | Attack Surface | Impact | Mitigation (spec-mapped) | Status Ph0 |
|----|----------------|----------------|--------|---------------------------|------------|
| T-01 | SSRF via `camera_url` — attacker-supplied internal IP to hit metadata `169.254.169.254`, loopback `127.0.0.1`, link-local `169.254.0.0/16`, multicast, control-plane DB/storage | `POST /api/v1/cameras/test`, `POST /api/v1/cameras` `endpoint` | H | §21.1: scheme allowlist (`rtsp,rtsps,http,https`), **site-specific CIDR allowlist**, hostname/port allowlists, strict URL parser, split credential fields (no creds in URL), **DNS resolve + validate every A/AAAA**, DNS-rebinding guard, **revalidate on reconnect**, redirect disabled default, metadata/loopback/link-local/multicast/control-plane block, **restricted worker netns + egress firewall**, timeouts/resource limits, redacted diagnostics | Seed; Phase 2 implements |
| T-02 | DNS rebinding — initial DNS ok, reconnect resolves to internal | Reconnect loop | H | Pin resolved IP set from "resolve DNS" step; pin TTL; re-validate on every `RECONNECTING` epoch; compare `stream_epoch` | Seed |
| T-03 | Credential theft / URL leakage — creds in URL logged, audit, PG, WS, metrics | Any URL handling | H | **Separate credential fields**, masked controls, `credential_references` FK + envelope encryption, **never persist URL with creds**, redact in diagnostics (§25 no raw frames/creds), short-lived playback sessions | Seed |
| T-04 | Malicious stream — fuzzer RTSP interleave extremal SPS/PPS, billion-laughs SDP, heap spray JPEG | `av.open` / demux | H | Limits: `max_packet_size, max_header_size, max_frame_size, decode_timeout`, capped concat for SPS/PPS (spec §10 queue limits), sandboxed `av` container, ASAN build for fuzz, no shell interpolation, `dnspython` timeouts | Seed |
| T-05 | Hostile uploaded media — polyglot MP4/zip-bomb, XXE in mp4 box xml, parser LPE (FFmpeg vuln) | `/api/v1/uploads/*` | H | Upload quarantine dir, **streaming SHA-256**, magic + container validation, **sandboxed FFmpeg probe** (`Network=None` seccomp), CPU/RAM/PID/timeout limits, size/duration/resolution/stream-count quotas, generated object names (no client path), atomic promote, multipart cleanup, optional ClamAV, no network in parser sandbox (§21.2) | Seed |
| T-06 | Cross-tenant / RBAC bypass — tenant A reads camera B | Every `site_id`/`org_id` scoped route | H | OIDC-ready auth, RBAC + site/camera scope enum, row-level `org_id` FK + policy, interceptor on repository + route, property-based cross-org property tests | Seed |
| T-07 | Path traversal via evidence export / upload filename | `evidence_assets.path` | M | Generated UUIDv7 object names, no client filesystem path, `Path(name).name` + block `..`, serve via signed URL only | Seed |
| T-08 | WebSocket subscription escalation — client subscribes to other org's `camera_id` | `GET /api/v1/ws` `SUBSCRIBE {camera_id}` | H | Auth on connect (token), authorize each `SUBSCRIBE` against `user.scoped_roles`, per-client bounded queue (64), drop not bypass | Seed |
| T-09 | Webhook replay / forgery — attacker replays signed C2 POST | C2 endpoint | M | HMAC-SHA256 with `timestamp + nonce/delivery_id + keyId + body digest`; **timestamp window 5 min**, nonce cache (Redis/PG `processed_nonces` TTL 24h), key rotation, optional mTLS, allowlisted endpoints, strict redirect policy, response-size limit (§22) | Seed |
| T-10 | Insider abuse — guard bulk-exports evidence, changes retention legal hold | Admin APIs | H | Audit `AUDIT` table (immutable), RBAC `auditor` role, retention/legal-hold delete requires 2-person `legal_hold` flag; every export logged with actor + `correlation_id`; evidence redaction pipeline separate | Seed |
| T-11 | Evidence tampering — clips rewritten, hash not checked | Object store / FS | H | Manifest: `sha256(snapshot), sha256(clip), sha256(original)`, remux no-transcode where possible, **verify checksum on C2 sync** (§23 step 5), append-only evidence table (no UPDATE), store in S3 with `ObjectLock` or FS immutability | Seed |
| T-12 | Object-store exposure — public bucket for evidence | S3 bucket policy | H | Private bucket, presigned URL only (short-lived), no `public-read`, block-public-access, CORS strict, `Content-Disposition: attachment` | Seed |
| T-13 | Model poisoning — trojaned `.pt`/`.onnx` from hub | Weights fetch | H | **Never silent download in prod** (§4); `ModelManager._is_valid_onnx_model` input-dependent graph check; verify `sha256` against registry; pin `ultralytics` version; scan SBOM (see below); signed attestation if Enterprise | Seed |
| T-14 | Adversarial pattern — printed shirt fools detector | Camera view | L | Explainable rules (confidence + quality flags), human review gate, do not auto-act on low-confidence; optional adversarial training later (not Phase 1) | Deferred |
| T-15 | Dependency compromise — hijacked `paddlex` wheel | Supply chain | M | `uv.lock` committed + `uv lock --check` in CI, SBOM CycloneDX, `pip-audit`/OSV scan, `sigstore` attestation for `pydantic`/`fastapi` releases (sigstore entry in PyPI file details) | Seed |
| T-16 | GPU/disk exhaustion — camera 4K@60fps floods VRAM/disk | Ingest | M | Bounded queues with drop metrics (§10), storage thresholds Normal→Emergency (§23) with upload-stop→reduce evidence→keep legal-hold policy, `gpu_mem_limit` cap, thermal throttle, per-camera priority (Critical/Standard/Low) | Seed |
| T-17 | Offline edge theft — disk stolen with evidence | Remote box | H | Full-disk encryption (LUKS), evidence envelope encryption (KMS-bound key rotation), tamper-evident audit hash chain, `CLOCK_UNSTABLE` detection (§7 state) | Seed |
| T-18 | Unsafe update / rollback — malicious OTAP | Update channel | H | Signed image digests (`image@sha256:…` pinned in compose), no runtime Docker socket mount, migration `upgrade→downgrade→upgrade` test, diagnostic bundles include `sbom + lock + manifest` | Seed |

---

## 4. Trust Boundaries & Data Flows

```
[Attacker on Internet] --(TLS)--> [IBVAP API/WS] --(Unix socket / loopback)--> [Camera Worker (netns: camera-VLAN only)]
                                      │
                   ┌──────────────────┼──────────────────┐
                   v                  v                  v
               [PostgreSQL]      [Object Store]      [C2 HTTPS]
               (outbox, audit)   (evidence FS/S3)    (HMAC + allowlist)
```

- **Camera worker netns** has egress only to allowlisted `camera CIDR` + `mediamtx` + `postgres`. Cannot reach internet or API secrets.
- **Parser sandbox** (FFmpeg/paddle) has `Network=None`, seccomp `--cap-drop ALL`, `readOnlyRootfs`.
- **API** never holds camera creds in env; fetched from encrypted vault on demand.

---

## 5. Security Headers & Controls (§21)

- **Auth:** OIDC-ready (Authlib), session `httponly + secure + samesite=lax`, CSRF where applicable, login throttling, rate limits per IP+user.
- **CORS:** strict allowlist (origin must match `frontend_url` config), not `*` (prototype uses `allow_origins=["*"]` — must fix).
- **TLS:** `sslmode=verify-full` for PG; webhook TLS verify on (with cert pin optional).
- **Headers:** `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Content-Security-Policy: default-src 'self'`.
- **Secrets rotation:** `envelope encryption` via `pgcrypto` + external KMS (env `IBVAP_KMS_KEY_ID`); `POST /api/v1/system/rotate-keys` with audit.

---

## 6. Verification Before Phase 2

- [ ] `cargo-audit`-style dependency scan (`pip-audit` or `osv-scanner`) on `uv.lock` — add to CI per §31.
- [ ] `gitleaks`/`truffleHog` sweep for committed camera URLs/secrets (prototype had `yolo11n.pt` binaries; check `.gitignore` covers `*.pt`, `data/db/*.db`, `models/*.onnx` placeholders).
- [ ] Container `docker scout`/`trivy` scan committed SBOM.

---

*This threat model is consumed by `verification-before-completion` skill before marking Phase 2 complete (all security tests §26 must pass).*
