# IBVAP Design Spec: Modular Tiling Cockpit Frontend Redo

- **Date:** 2026-08-30
- **Status:** Draft — pending user approval
- **Author:** Muse Spark (OpenCode)
- **Scope:** Redo frontend workflow for phone-as-CCTV (DroidCam) with modular N-box adaptive tiling, unified operations cockpit, fixing connect dead-end and tab-hopping.
- **Traceability:** REQ-01..REQ-24 (§29), spec §24 page list; hackathon PS absolute base
- **Build:** React 19.2.8 + Vite 7.1.9 + TypeScript 5.7 strict + Tailwind 4.1.13 + TanStack Query 5.102.2

---

## 1. Executive Summary & Goals

**Problem:** Current frontend at `frontend/src/App.tsx:13` shows duplicate navigation (`sidebar` + `topbar` with same 5 items) and forces `EmptyState` (`frontend/src/pages/EmptyState.tsx:1` — standalone 2-CTA onboarding) inside the `app-shell` at `/` → double chrome. `ConnectPhone` (`frontend/src/pages/ConnectPhone.tsx:21`) only calls `POST /api/v1/cameras/test` and never `POST /api/v1/cameras` → dead-end; `Monitor` (`frontend/src/pages/Monitor.tsx:11`) fetches `/api/v1/cameras`+`/events` raw without TanStack caching, health, or error states, and lives on a separate route from `Alerts`/`Health` placeholders (`frontend/src/pages/Alerts.tsx:1`, `Health.tsx:1`). Users with 1-4 DroidCam phones (`http://IP:4747/video` or `/mjpegfeed`) must hop `Overview → Monitor → Connect → Alerts → Health` and still see synthetic preview. Playwright `frontend/tests/app.spec.ts:19` still expects old `/cameras`/`/events` routes → CI failure.

**Goal:** One modular cockpit that scales with `N` phones: `N=0` → onboarding, `N=1` → one centered player, `N=2` → 2 boxes, `N=3` → 3 boxes, `N=4` → 2×2, `N=5-6` → 3×2, `>6` → virtualized scroll — all fit in viewport without tab hops. Every PS bullet (Human/Vehicle/Face/ANPR/Fence/Suspicious/Night/Alerts/Logging) is one toggle or rail away on the same page. Judges see the full border-outpost story in a single screenshot; phones remain `REQ-02 smartphone_ip_webcam` substitutes for `REQ-01` CCTV with zero proprietary hardware.

**Design Language:** *Operations Glass* — modern, hackathon-polished. Light shell `#f4f7f6` with `teal #0f766e → #115e59` accent (keep `frontend/src/index.css:1` tokens), Inter `sans-serif`, `rounded-2xl / 16px / 12px`, `backdrop-blur 12-18px`, soft shadow `0 18px 40px rgba(15,23,42,0.08)`, dark `slate-900` players for contrast, monospaced health metrics, `motion-reduce` aware. Minimal Chrome, maximal video.

---

## 2. Component Design

### 2.1 Routing & App Shell (`frontend/src/App.tsx`, `frontend/src/components/Navbar.tsx` → `Topbar.tsx`)

- **Dual-mode shell:**
  - `mode=onboarding` when `useCameras()` → `[]`: render **only** `EmptyState` (no shell chrome). Preserves its header/footer, 2 prominent CTAs `data-testid="cta-connect-phone"` → open modal + `data-testid="cta-use-footage"` → `/use/footage` placeholder, and subdued `Other IP camera options` disclosure.
  - `mode=cockpit` when `cameras.length > 0`: render `Topbar` + `Main` grid + `BottomAlertRail` + `HealthDrawer`/`SystemBar`. Remove `sidebar` entirely (`frontend/src/index.css:1` delete `.app-shell` 260px column, `.sidebar`, `.sidebar-nav`).
- **Topbar** (`components/Topbar.tsx`, replaces `Navbar.tsx:1`):
  - Left: brand `IB` mark + `IBVAP • Operations` + `Live` pill (`status-pill` with dot).
  - Center/right: `eyebrow: Live operations` + dynamic `h1` (Cockpit / Alerts / Health) + nav `Cockpit (/), Alerts (/alerts), Health (/health)` (3 items only) + primary button `Add phone camera`.
  - Props: `cameras.length` badge, `storage_pressure` banner slot.
- **Routes:**
  - `/` → `Cockpit` (adaptive grid).
  - `/connect/phone` → opens `ConnectModal` over cockpit (deep link preserved, close → `/`).
  - `/alerts`, `/health` → full-page drill-downs **and** cockpit rails (rails are primary, pages are deep dives).
  - `/monitor`, `/overview` → redirect 301 to `/` (legacy).
  - `*` → `EmptyState`.
- **Grid container:** `display: grid; grid-template-columns: repeat(auto-fit, minmax(320px,1fr)); gap: 1rem;` with `auto-rows: minmax(0, 1fr)`; constrain `max-height: calc(100vh - topbar - rails - 2rem)`; `place-content: center` for `N=1`. Breakpoints: `N=1` centered `max-w-[1100px] mx-auto`, `N=2` 2-col, `N=3` 3-col ≥1024px else 2+1, `N=4` 2×2, `N=5-6` 3×2, `>6` `overflow-auto` + pagination controls (`Prev/Next`, page dots).
- **Files touched:** `frontend/src/App.tsx:1`, `frontend/src/components/Topbar.tsx` (new), `frontend/src/index.css:1` (remove sidebar, add grid + drawer), `frontend/tests/app.spec.ts:11` (update nav expectations).

### 2.2 Camera Tiles (`frontend/src/components/CameraTile.tsx`, `OverlayCanvas.tsx`, `TileHealth.tsx`)

- **Player:** `img src={endpoint}` for `http(s)` MJPEG; if `endpoint` requires Basic Auth (`username`/`password` from `POST /api/v1/cameras`), use `fetch` with `Authorization: Basic ...` → `blob` → `URL.createObjectURL` fallback (avoids leaking creds in DOM). For `rtsp(s)://` show per-tile placeholder `Live player — WHEP/HLS when MediaMTX available` + `Test connection` retry. `data-testid="live-player-{id}"`, `aspect-video`, `rounded-2xl`, `overflow-hidden`, `bg-slate-900`.
- **Chrome overlay:**
  - Top bar: `name • observed_state STREAMING • epoch {stream_epoch}` + `dot` health; bottom bar: per-tile metrics `Last frame 120ms • Analysis 12 FPS • Inference 18ms` + `queue_drops` warn.
  - Staleness fade: if `last_frame_age > 2000ms` lower overlay opacity, amber border.
- **PS overlays (SVG absolute, normalized `[0,1]` → `clientRect`):**
  - Human/Vehicle: `detectorProvider` boxes (`person`, `car`, `bus`, `truck`, `motorcycle`, `bicycle`) + `tracker_id` + `confidence` (from `src/ibvap/core/detector.py` ONNX, `src/ibvap/core/tracker.py` ByteTrack).
  - Face: YuNet 5 landmarks + blur/pose chip; identity candidate shown only if `enable_face_identity=true` (privacy gate `traceability.md:26`).
  - ANPR: `plate_observations` chip `MH02XX1234 • 0.92 • day` (`src/ibvap/core/anpr.py` contour+consensus).
  - Fence/Tripwire: polygon/directional arrow from `zones`/`tripwires` (`src/ibvap/core/geometry.py` normalized coords, `≥3` non-coincident verts, no self-intersection).
  - Suspicious: loitering/repeated-crossing badge + `explain` panel (`ruleVersion`, `facts`, `thresholds` from `src/ibvap/core/rules.py`).
  - Night: luminance badge `0.18 • CLAHE on • motion 0.42` (`src/ibvap/core/night.py`).
- **Controls:** Global overlay bar `Human | Vehicle | Face | Plate | Zone | Suspicious | Night | Minimal/Operational/Diagnostic` (per `Monitor.tsx:9` but now global + per-tile override persisted in `localStorage`). `Operational` = all except diagnostic chips; `Minimal` = boxes only; `Diagnostic` = plus `trackId`, `direction`, `zoneId`, `luminance`.
- **Interaction:** Click tile → `solo` (span 2 cols on large screens, rail shows per-camera events); `Esc` exits solo. Hover shows zone editor preview. Keyboard: `Tab` cycles tiles, arrows navigate grid.
- **Files:** new `CameraTile.tsx`, `OverlayCanvas.tsx`, `TileHealth.tsx`; deprecate logic in `frontend/src/pages/Monitor.tsx:1` (keep file as re-export for redirect); extend `frontend/src/lib/api.ts:1` with `fetchCameras`, `fetchCameraHealth(cameraId)`.

### 2.3 Connect Flow (`frontend/src/components/ConnectModal.tsx`)

- **Modal steps** (same as `ConnectPhone.tsx:21` but not a route):
  1. Prepare (6 bullets, collapsible, includes `Avoid exposing stream to public internet`).
  2. Enter: `Stream URL` (`data-testid="stream-url"`), `Toggle auth` (`data-testid="toggle-auth"`) → `username`/`password` fields, `Test connection` (`data-testid="test-connection"` disabled if `!url`). Payload: `{endpoint:url, username:..., password:..., site_cidr_allowlist:["10.0.0.0/8","172.16.0.0/12","192.168.0.0/16"]}` → `POST /api/v1/cameras/test` (SSRF via `src/ibvap/core/ssrf.py`).
  3. Testing: map `stages[]` (`Validating address → Resolving host → Checking reachability → Negotiating stream → Probing media`) with `status ok/failed/running` colors; show `safe_message` + `reason_code` in amber/emerald box `data-testid="test-result"`.
  4. Preview & Save: if `result==="ok"` && `probe`: show live `<img>` preview + grid `Codec/Resolution/FPS` (`result.probe.width×height`, `codec`, `fps`); primary `Add camera → Go to cockpit` (`data-testid="continue"`) does `POST /api/v1/cameras` (credentials envelope via `src/ibvap/core/credentials.py`), invalidates `useCameras`, closes modal; secondary `Edit connection`.
- **On failure:** `result!=="ok"` → `Edit connection` back to step 2, no auto-add.
- **Add-another:** `Topbar` `Add phone camera` + empty-state CTA both open modal; `N+1` retiled instantly via optimistic update.
- **Files:** new `ConnectModal.tsx`, `ConnectPhone.tsx:1` → thin wrapper opening modal + `navigate("/")`; `lib/api.ts:1` add `testCamera(payload)`, `createCamera(payload)`, `fetchCameras()`.

### 2.4 Alerts & Health Rails (`frontend/src/components/AlertRail.tsx`, `HealthBar.tsx`)

- **Bottom Alert Rail** (docked, collapsible `Show 5 / Show all`): `GET /api/v1/events?limit=5` (TanStack), `severity` → `badge good/warn/danger`, `event_type • camera_id • zone_id • confidence`. `explain` on hover: `ruleVersion`, `facts`, `thresholds`. `View all alerts` expands rail to 20 or navigates `/alerts` full page (full page keeps `severity/state/site/camera/explain/confidence/assignee/actions` inbox from `traceability.md:29` REQ-14). Critical banner is non-obstructive top toast, not blocking player (REQ-14 `rail limited to 5`, `non-obstructive`).
- **Health:** Per-tile chips + global `SystemBar` footer: `GET /api/v1/health` + `GET /api/v1/cameras/{id}/health` → `last_frame_age`, `source/analysis FPS`, `decode_errors`, `queue_drops`, `reconnect_count`, `stream_epoch`, `storage_pressure` (`Normal→Emergency`). Emergency shows banner `Storage pressure: Emergency — cleanup paused for legal-hold` (REQ-20 never delete `legal_hold`/`unsynced critical`). Degraded chips amber/red.
- **A11y:** rails `aria-live="polite"`, `aria-label="Recent events"`, keyboard `Tab` + `Enter` to expand.

---

## 3. Data Flow & Execution Sequence

```
1. useCameras() [TanStack Query, key: ["cameras"], poll 5s or WS /ws]
   GET /api/v1/cameras → {id, name, endpoint, observed_state, stream_epoch}[] → drives N tiling + onboarding switch
       │
2. ConnectModal: POST /api/v1/cameras/test → {result, reason_code, safe_message, stages[], probe{width,height,fps,codec}}
   on ok → POST /api/v1/cameras {endpoint, username, password, site_cidr_allowlist}
       │        ↓ (credentials encrypted, SSRF validated)
       └─► invalidates ["cameras"] → grid retiled N+1

3. Per tile:
   img fetch (MJPEG)  ─┬─► OverlayCanvas (SVG boxes from GET /api/v1/events?camera_id=... + WS push)
                       └─► TileHealth (GET /api/v1/cameras/{id}/health poll 3s)

4. Cockpit rails:
   BottomAlertRail: GET /api/v1/events?limit=5 (or WS event broadcast)
   SystemBar: GET /api/v1/health (storage, queue, fps)
```

Fallback: if `API_BASE` (`frontend/src/lib/api.ts:1`) unreachable → show `Offline • retrying` pill, keep last-known cameras/events with staleness fade, retry `queryFn` with exponential backoff (TanStack `retry: 3`).

---

## 4. Verification Plan

1. **Types & Build:** `npm run build` (`tsc -b && vite build`) clean; `npm run typecheck` 0 errors strict; `uv run ruff check .` + `pyright` 0 (unchanged backend).
2. **Playwright:** update `frontend/tests/app.spec.ts:11` to:
   - `loads home with zero cameras → shows EmptyState 2 CTAs, no topbar`
   - `Add phone → Test → Preview → Save → tile appears in cockpit` (mock `POST /api/v1/cameras/test` 200 + `POST /api/v1/cameras` 201)
   - `N=1,2,3,4 tiling` (mock 1-4 cameras, assert grid columns/count + `data-testid="live-player-*"`)
   - `Alert rail shows 5 newest, expand to All` (mock events)
   - `Health chips show FPS/queue, stale fade after 2s`
   Run `npx playwright test` on `preview` (4173) green.
3. **Manual SIH demo:** 2 DroidCam phones on same WiFi (`http://192.168.x.x:4747/video`), add both via modal → 2 tiles side-by-side, toggle `Human/Vehicle/Face/Plate/Zone/Night` → boxes appear (mock detector ok), trigger zone intrusion → alert rail adds event.
4. **Regression:** `npm run build` + `playwright` must pass before merge; no AGPL detector bundle change.
5. **Docs:** update `docs/traceability.md:24` `frontend/dist` evidence; keep `PHASE_0_REPORT.md` YOLO gate note.

---

## 5. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Many phones (>6) overload CPU (ONNX 27ms) | FPS drop | Cap grid to 6 visible + paginate; health shows `queue_drops` + `degradation banner` (REQ-22 fair share); doc 2-phone recommended for laptop demo |
| DroidCam MJPEG auth header not via `img src` | Preview fails | Use blob fetch fallback with `Basic` header; show `safe_message` with `reason_code` |
| SSRF bypass via DNS rebind | High | Keep `site_cidr_allowlist` + `src/ibvap/core/ssrf.py` alt-IP/redirect checks on both test+create |
| Stale overlay misleads judges | Medium | Fade boxes via `overlay_staleness` metric, show `fresh/130ms` chip |

---

## 6. Out of Scope

- Upload footage wizard ` /use/footage` stays placeholder (Phase 2 quarantine→promote) — not needed for phone demo.
- Zone/tripwire editor is preview-only (Konva/SVG) — full drawing is Phase later; show static `Restricted` polygon.
- Face identity gallery enrollment remains gated (`enable_face_identity=false` default).
