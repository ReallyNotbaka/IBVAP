<div align="center">

# IBVAP
### Intelligent Border Video Analytics Platform

**Software-defined edge video analytics platform for multi-camera perimeter surveillance, intrusion detection, and tactical situational awareness.**

[![Python: 3.12](https://img.shields.io/badge/Python-3.12-3776AB.svg?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.141-009688.svg?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React 19](https://img.shields.io/badge/React-19-20232A.svg?style=flat-square&logo=react&logoColor=61DAFB)](https://react.dev/)
[![ONNX Runtime](https://img.shields.io/badge/ONNX_Runtime-1.24+-005CED.svg?style=flat-square&logo=windows&logoColor=white)](https://onnxruntime.ai/)
[![Vite](https://img.shields.io/badge/Vite-7-646CFF.svg?style=flat-square&logo=vite&logoColor=white)](https://vitejs.dev/)
[![TailwindCSS](https://img.shields.io/badge/Tailwind_CSS-v4-38B2AC.svg?style=flat-square&logo=tailwind-css&logoColor=white)](https://tailwindcss.com/)

[System Overview](#system-overview) •
[Architecture](#architecture) •
[Core Capabilities](#core-capabilities) •
[Quick Start](#quick-start) •
[Camera Integration](#camera-integration) •
[API Reference](#api-reference) •
[Verification](#verification--testing)

</div>

---

## System Overview

**IBVAP** is an automated video analytics and sensor fusion platform built for border security, facility perimeters, and remote observation posts. It ingests video feeds from standard RTSP cameras, mobile devices, or recorded footage, runs computer vision inference (object detection, facial biometrics, license plate recognition), and evaluates spatial rules (virtual tripwires and restricted zones).

Events are persisted to a durable database, displayed in real-time on an operator dashboard, and optionally relayed to external Command & Control (C2) webhooks with forensic snapshot packages.

---

## Architecture

```
                                  +---------------------------------------+
                                  |     Edge Cameras & Video Sources      |
                                  |  (RTSP / RTSPS / MJPEG / Video Files) |
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                  +---------------------------------------+
                                  |      Core Demuxer & Ingestion         |
                                  |   (PyAV, FFmpeg, SSRF Policy Defense) |
                                  +-------------------+-------------------+
                                                      |
                         +----------------------------+---------------------------+
                         |                                                        |
                         v                                                        v
        +---------------------------------+                      +---------------------------------+
        |     Low-Latency MJPEG Pipe      |                      |  Deep Learning Analysis Thread  |
        |  (Zero-copy packet extraction)  |                      |   (Bounded Queues, Stride Skip) |
        +----------------+----------------+                      +----------------+----------------+
                         |                                                        |
                         |                                      +-----------------+-----------------+
                         |                                      |                 |                 |
                         |                                      v                 v                 v
                         |                              +---------------+ +---------------+ +---------------+
                         |                              |  YOLO (ONNX)  | | YuNet & SFace | |   PaddleOCR   |
                         |                              | Person/Vehicle| | Face Biometric| |  License Plate |
                         |                              +-------+-------+ +-------+-------+ +-------+-------+
                         |                                      |                 |                 |
                         |                                      +--------+--------+-----------------+
                         |                                               |
                         |                                               v
                         |                               +---------------------------------+
                         |                               |   Centroid & Biometric Tracker  |
                         |                               | (Hungarian Association, NMS)    |
                         |                               +---------------+-----------------+
                         |                                               |
                         |                                               v
                         |                               +---------------------------------+
                         |                               |   Rules & Watchlist Evaluator   |
                         |                               | (Virtual Fence, Threat Levels)  |
                         |                               +---------------+-----------------+
                         |                                               |
                         |                                               v
                         |                               +---------------------------------+
                         |                               |   Evidence & Outbox Dispatch    |
                         |                               | (Snapshots, Crops, C2 Relay)    |
                         |                               +---------------+-----------------+
                         |                                               |
                         v                                               v
        +----------------------------------------------------------------------------------+
        |                               FastAPI Application                                |
        |   GET /cameras/{id}/stream (MJPEG)     |    GET /cameras/{id}/observations       |
        |   GET /events                          |    GET /evidence/{id}/snapshot          |
        +----------------------------------------+-----------------------------------------+
                                                 |
                                                 v
        +----------------------------------------------------------------------------------+
        |                             Operator Dashboard (SPA)                             |
        |   React 19, TypeScript, Vite 7, Tailwind CSS v4, Tactical Radar, Incident Center |
        +----------------------------------------------------------------------------------+
```

---

## Core Capabilities

- **Multi-Model Computer Vision Pipeline**:
  - **Object Detection**: Persons and vehicles detected via ONNX Runtime (DirectML GPU or CPU).
  - **Facial Landmarking & Recognition**: OpenCV YuNet 5-point face detection and SFace 128-dimensional embedding generation.
  - **Automated Number Plate Recognition (ANPR)**: PaddleOCR text extraction with character confusion normalization (`O/0`, `I/1`, `B/8`, `Z/2`, `S/5`) and 30-second sighting deduplication.
- **Tracking & Spatial Rules**:
  - Multi-object centroid tracker with velocity smoothing and trajectory history.
  - Interactive polygon perimeter fencing and line tripwires evaluated via ray-casting.
  - Loitering detection with configurable dwelling cooldown windows.
- **2D Bird's-Eye-View (BEV) Radar**:
  - Planar homography projection mapping camera image coordinates onto ground plane metrics.
  - 4-point visual calibration with geometric presets (Lane, Gate, Sector, Custom) and optical azimuth alignment.
- **Forensic Evidence Capture**:
  - Full-frame JPEG snapshots and target-cropped images saved on alert emission.
  - Bounded FIFO disk storage policy to prevent storage exhaustion.
  - Interactive forensic dossier viewer with image download and watchlist enrollment.
- **Command & Control (C2) Integration**:
  - Configurable webhook relay for asynchronous JSON event dispatch with snapshot URLs.
  - Ping test tool measuring round-trip connection latency in milliseconds.
- **Durable Persistence & Startup Restore**:
  - Automatic fallback to WAL-mode SQLite when PostgreSQL is not configured.
  - Automatic restoration of active cameras, geofences, and outbox history on application reboot.
- **Network Security & SSRF Protection**:
  - Strict IP address validation and configurable CIDR allowlists.
  - Credential encryption at rest and in memory with permanent log redaction.

---

## Tech Stack

| Layer | Technologies | Role |
|---|---|---|
| **Backend Framework** | Python 3.12, FastAPI, Uvicorn, Pydantic v2 | REST API, lifecycle management, route dispatch |
| **Media Demuxing** | PyAV (FFmpeg), OpenCV | Stream probing, RTSP negotiation, packet decoding |
| **Inference Engines** | ONNX Runtime, OpenCV DNN, PaddleOCR | YOLO detection, YuNet/SFace biometrics, ANPR |
| **Database** | SQLAlchemy Async, SQLite (WAL mode), PostgreSQL | Relational persistence, transactional outbox |
| **Frontend Dashboard** | React 19, TypeScript, Vite 7, Tailwind CSS v4 | Operator cockpit, radar modal, alerts console |
| **Testing & Quality** | Pytest, Pytest-Asyncio, Ruff | Unit, integration, chaos/soak, and lint testing |

---

## Quick Start

### Prerequisites
- **Python**: `>= 3.12, < 3.14`
- **Node.js**: `>= 20.x`
- **uv**: Python package manager (`pip install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`)

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/ReallyNotbaka/IBVAP.git
cd IBVAP

# Install backend dependencies
uv sync --all-extras

# Install frontend dependencies
cd frontend
npm install
cd ..
```

---

### 2. Development Mode

```bash
# Terminal 1: Start Backend API (port 8000)
uv run uvicorn ibvap.api.app:create_app --factory --host 0.0.0.0 --port 8000 --reload

# Terminal 2: Start Frontend Dev Server (port 5173)
cd frontend
npm run dev
```

Open `http://localhost:5173` in your browser. API documentation is available at `http://localhost:8000/docs`.

---

### 3. Production Build

```bash
# Build the single-page application
cd frontend
npm run build
cd ..

# Run the unified server (FastAPI serves static frontend from dist/)
uv run uvicorn ibvap.api.app:create_app --factory --host 0.0.0.0 --port 8000
```

---

## Camera Integration

### Network Cameras & RTSP Feeds
Connect standard IP cameras by providing the RTSP connection string:
```
rtsp://username:password@192.168.1.100:554/stream1
```
Credentials are encrypted at rest and redacted from telemetry.

### Mobile Cameras (DroidCam / IP Webcam)
1. Install **DroidCam** or **IP Webcam** on a mobile device on the same local network.
2. In the dashboard, click **Add Camera**.
3. Input the device IP and port (`4747` for DroidCam, `8080` for IP Webcam).
4. The system automatically configures the `/video` endpoint and checks the local subnet allowlist.

### Recorded Video Files
Recorded footage (`.mp4`, `.mkv`, `.avi`) can be ingested via the **Use Footage** page for offline forensic replay, zone testing, and scrubber analysis.

---

## API Reference

### Camera Management
| Method | Route | Description |
|---|---|---|
| `GET` | `/api/v1/cameras` | List configured cameras and operational states |
| `POST` | `/api/v1/cameras` | Register and provision a new camera |
| `POST` | `/api/v1/cameras/test` | Probe and test stream metrics for an endpoint |
| `GET` | `/api/v1/cameras/{id}/stream` | MJPEG video stream |
| `GET` | `/api/v1/cameras/{id}/observations` | Current bounding boxes, tracks, and biometric data |
| `GET` | `/api/v1/cameras/{id}/health` | Decode errors, FPS, and frame latency telemetry |
| `PUT` | `/api/v1/cameras/{id}/fence` | Update virtual perimeter fence coordinates |

### Tactical & Radar
| Method | Route | Description |
|---|---|---|
| `GET` | `/api/v1/tactical/radar` | 2D Bird's-Eye-View radar sectors and projected blips |
| `POST` | `/api/v1/tactical/radar/calibrate` | Calibrate 4-point homography ground plane matrix |
| `GET` | `/api/v1/tactical/sitrep` | Generate STANAG-formatted military situation report |
| `GET` | `/api/v1/tactical/dossiers` | Cross-camera target handover timelines |

### Evidence & Forensics
| Method | Route | Description |
|---|---|---|
| `GET` | `/api/v1/evidence/{event_id}/snapshot` | Retrieve full-frame forensic JPEG snapshot |
| `GET` | `/api/v1/evidence/{event_id}/crop` | Retrieve target-cropped JPEG image |

### Watchlist & ANPR
| Method | Route | Description |
|---|---|---|
| `GET` | `/api/v1/watchlist` | List enrolled suspect faces and flagged license plates |
| `POST` | `/api/v1/watchlist/enroll` | Enroll a person with facial reference image |
| `POST` | `/api/v1/watchlist/enroll-plate` | Enroll a vehicle license plate on the hotlist |
| `GET` | `/api/v1/anpr/sightings` | Search historical vehicle sightings log |

### System & C2 Configuration
| Method | Route | Description |
|---|---|---|
| `GET` | `/api/v1/system/settings` | Read runtime C2 webhook and sensitivity settings |
| `POST` | `/api/v1/system/settings` | Update C2 webhook and sensitivity settings |
| `POST` | `/api/v1/system/webhook/test` | Dispatch test alert ping to verify external webhook |

---

## Verification & Testing

```bash
# Run backend test suite (324+ tests)
uv run pytest -q

# Run Python linter
uv run ruff check src tests

# Run frontend build and TypeScript validation
cd frontend
npm run build
```

---

## Directory Structure

```
IBVAP/
├── src/ibvap/
│   ├── api/
│   │   ├── app.py                # FastAPI factory and SPA router
│   │   └── routes/
│   │       ├── anpr.py           # License plate sightings
│   │       ├── cameras.py        # Stream workers and camera CRUD
│   │       ├── events.py         # Incident ledger and filters
│   │       ├── evidence.py       # Snapshot and crop retrieval
│   │       ├── health.py         # Subsystem diagnostics
│   │       ├── settings.py       # C2 webhook and runtime settings
│   │       ├── tactical.py       # Radar and SITREP generator
│   │       └── watchlist.py      # Face and plate enrollment
│   ├── core/
│   │   ├── anpr.py               # ANPR sightings and deduplication
│   │   ├── detector.py           # ONNX YOLO detector provider
│   │   ├── dispatcher.py         # C2 webhook dispatcher
│   │   ├── evidence.py           # Snapshot capture and storage
│   │   ├── face.py               # YuNet and SFace biometrics
│   │   ├── homography.py         # 2D BEV radar projection
│   │   ├── pipeline.py           # Per-camera analytics pipeline
│   │   ├── tracker.py            # Centroid multi-object tracker
│   │   ├── watchlist.py          # Fuzzy plate and biometric matcher
│   │   └── zone_engine.py        # Polygon and tripwire evaluation
│   ├── db.py                     # SQLite / PostgreSQL engine
│   └── services/
│       ├── persistence.py        # Boot restoration and DB synchronization
│       └── stream_worker.py      # Camera capture and worker isolation
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── CameraTile.tsx    # Stream view and HUD overlay
│   │   │   ├── EvidenceModal.tsx # Forensic snapshot lightbox
│   │   │   ├── RadarCalibrationModal.tsx # 4-point perspective tuner
│   │   │   ├── SettingsModal.tsx # C2 relay and sensitivity tuner
│   │   │   ├── TacticalRadarModal.tsx    # 2D radar display
│   │   │   └── WatchlistModal.tsx        # Face and plate enrollment
│   │   ├── pages/
│   │   │   ├── Alerts.tsx        # Incident console with CSV export
│   │   │   ├── Cockpit.tsx       # Multi-grid surveillance dashboard
│   │   │   └── Health.tsx        # Hardware telemetry monitor
│   │   └── lib/
│   │       ├── api.ts            # Client HTTP functions
│   │       └── audio.ts          # Synthesized Web Audio alerts
├── tests/                        # Pytest suite (324+ tests)
└── pyproject.toml                # Project dependencies
```

---

## License

This project is licensed under the GNU Affero General Public License v3.0 ([AGPL-3.0](LICENSE)).
