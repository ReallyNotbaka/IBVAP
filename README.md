<div align="center">

# 🛡️ IBVAP
### Intelligent Border Video Analytics Platform

**Next-generation, software-defined edge surveillance & tactical video analytics for critical border defense and perimeter security.**

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-0052CC.svg?style=for-the-badge)](https://www.gnu.org/licenses/agpl-3.0)
[![Python: 3.12+](https://img.shields.io/badge/Python-3.12+-3776AB.svg?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.141-009688.svg?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React 19](https://img.shields.io/badge/React-19-20232A.svg?style=for-the-badge&logo=react&logoColor=61DAFB)](https://react.dev/)
[![ONNX Runtime](https://img.shields.io/badge/ONNX_Runtime-DirectML-005CED.svg?style=for-the-badge&logo=windows&logoColor=white)](https://onnxruntime.ai/)
[![Vite](https://img.shields.io/badge/Vite-7-646CFF.svg?style=for-the-badge&logo=vite&logoColor=white)](https://vitejs.dev/)
[![TailwindCSS v4](https://img.shields.io/badge/Tailwind_CSS-v4-38B2AC.svg?style=for-the-badge&logo=tailwind-css&logoColor=white)](https://tailwindcss.com/)

[Key Capabilities](#-key-capabilities) •
[System Architecture](#-system-architecture) •
[Tactical UI Preview](#-tactical-cockpit-preview) •
[Quick Start](#-quick-start) •
[Camera Integration](#-camera-integration-guide) •
[API Reference](#-api-endpoints) •
[Documentation](#-documentation)

</div>

---

## 🎯 Executive Overview

**IBVAP** is an enterprise-grade tactical surveillance engine designed for real-time threat classification, suspect re-identification, vehicle tracking, and automated perimeter violation alerting. Engineered specifically for edge compute nodes, it delivers ultra-low latency inference using DirectML GPU acceleration with intelligent zero-copy streaming pipelines.

---

## 🖼️ Tactical Cockpit Preview

<div align="center">

| Tactical Surveillance Grid | Theater Focus & Target Inspector |
|:---:|:---:|
| ![Tactical Grid](docs/assets/cockpit-overview.png) | ![Theater Focus](docs/assets/theater-mode.png) |
| *Multi-camera situational overview with real-time HUD overlays* | *Expanded solo theater mode with deep target biometric inspection* |

| Smart Device Onboarding Wizard | Biometric Watchlist & Enrollment |
|:---:|:---:|
| ![Device Connection](docs/assets/device-connection.png) | ![Biometric Watchlist](docs/assets/watchlist-biometrics.png) |
| *Multi-stage stream probing with automated protocol normalization* | *128D facial vector database with tiered threat level alerting* |

</div>

---

## ⚡ Key Capabilities

- **🚀 High-Throughput Hardware-Accelerated CV**:
  - **YOLO26 / YOLOv8 Detection**: Real-time identification of persons and vehicles powered by ONNX Runtime with DirectML GPU acceleration and graceful CPU fallback.
  - **YuNet & SFace Biometrics**: 5-point facial landmark tracking, illumination/blur quality gating, and 128D cosine distance embedding matching.
  - **PaddleOCR ANPR**: Edge-optimized vehicle license plate character extraction and spatial association.
- **📡 Universal Source Ingestion & Normalization**:
  - Native RTSP, RTSPS, HTTP, HTTPS, MJPEG, and offline evidence playback.
  - Automatic detection and normalization for mobile camera streams (**DroidCam** `:4747`, **IP Webcam** `:8080`) to `/video` with transient socket retry resilience.
- **🎯 Intelligent Spatial Tracking & Multi-Tier Deduplication**:
  - Centroid & ByteTrack-style multi-object tracking with velocity-adaptive sub-pixel smoothing.
  - Ghost track suppression eliminates stale boxes; IoU and containment analysis unify overlapping detections.
- **🛡️ Tactical Perimeter Fencing & Watchlists**:
  - Interactive polygon perimeter drawing with real-time Ray-Casting intrusion detection.
  - Tiered suspect classification: `CRITICAL` (instant alert & lock), `HIGH`, `MEDIUM`, and `LOW`.
- **🔒 Zero-Trust Defense & Network Security**:
  - Strict SSRF policy engine with customizable CIDR allowlists (e.g., `10.0.0.0/8`, `192.168.0.0/16`).
  - DNS-rebinding protection and AES-GCM encrypted credential vault.

---

## 🏗️ System Architecture

```
                                  +---------------------------------------+
                                  |     Edge Cameras & Video Sources      |
                                  |  (RTSP / RTSPS / MJPEG / Smartphone)  |
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                  +---------------------------------------+
                                  |      Core Demuxer & Probe Engine      |
                                  |   (PyAV, FFmpeg, SSRF Policy Defense) |
                                  +-------------------+-------------------+
                                                      |
                         +----------------------------+---------------------------+
                         |                                                        |
                         v                                                        v
        +---------------------------------+                      +---------------------------------+
        |     Low-Latency MJPEG Pipe      |                      |  Deep Learning Analysis Thread  |
        |  (Zero-copy packet extraction)  |                      |   (Sampled Stride, DirectML)    |
        +----------------+----------------+                      +----------------+----------------+
                         |                                                        |
                         |                                      +-----------------+-----------------+
                         |                                      |                 |                 |
                         |                                      v                 v                 v
                         |                              +---------------+ +---------------+ +---------------+
                         |                              | YOLO26/DirectML| | YuNet & SFace | |   PaddleOCR   |
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
                         v                                               v
        +----------------------------------------------------------------------------------+
        |                               FastAPI REST & SSE API                             |
        |      GET /stream (Live MJPEG)         |      GET /observations (HUD & Tracks)    |
        +----------------------------------------+-----------------------------------------+
                                                 |
                                                 v
        +----------------------------------------------------------------------------------+
        |                            IBVAP Tactical Cockpit UI                             |
        |  (React 19, Tailwind CSS v4, Lucide Icons, Sub-pixel EMA Smoothing, Theater Mode)   |
        +----------------------------------------------------------------------------------+
```

---

## 🛠️ Tech Stack Matrix

| Layer | Technologies | Key Role |
|---|---|---|
| **Core Backend** | Python 3.12+, FastAPI, Uvicorn, Pydantic v2 | Asynchronous microservices & SSE stream dispatch |
| **Media Demuxing**| PyAV (FFmpeg 7), OpenCV | Sub-millisecond stream probing and zero-copy packet slicing |
| **Inference Engine** | ONNX Runtime (DirectML / CPU) | Accelerated edge execution for YOLO26 architectures |
| **Biometrics** | OpenCV YuNet & SFace ONNX | 5-point facial landmarking & 128D feature representation |
| **ANPR Engine** | PaddleOCR, OpenCV | Automatic license plate detection and OCR character extraction |
| **Cockpit Frontend**| React 19, TypeScript, Vite 7, Tailwind CSS v4 | High-density tactical surveillance UI |
| **Data & Storage** | SQLAlchemy Async, SQLite, Alembic | Durable events ledger, audit trails, and suspect store |
| **Quality Control** | Pytest, Pytest-Asyncio, Ruff, Pyright, Playwright | Comprehensive unit, linting, type, and end-to-end testing |

---

## 🚀 Quick Start

### Prerequisites
- **Python**: `>= 3.12, < 3.14`
- **Node.js**: `>= 20.x`
- **uv**: Ultra-fast Python package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh` or `pip install uv`)

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/ReallyNotbaka/IBVAP.git
cd IBVAP

# Install backend dependencies with all hardware accelerators
uv sync --all-extras

# Install frontend dependencies
cd frontend
npm install
cd ..
```

---

### 2. Running in Development

```bash
# Terminal 1: Launch Backend API Server (port 8000)
uv run uvicorn ibvap.api.app:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: Launch Tactical Frontend Cockpit (port 5173)
cd frontend
npm run dev
```

Visit **`http://localhost:5173`** to access the live dashboard.
Interactive OpenAPI docs are available at **`http://localhost:8000/docs`**.

---

### 3. Production Deployment

```bash
# Build the production single-page application
cd frontend
npm run build
cd ..

# FastAPI automatically mounts and serves frontend/dist
uv run uvicorn ibvap.api.app:app --host 0.0.0.0 --port 8000
```

---

## 📹 Camera Integration Guide

### 📱 Wi-Fi Mobile Cameras (DroidCam / IP Webcam)
1. Install **DroidCam** or **IP Webcam** on any iOS or Android phone connected to your local Wi-Fi.
2. Open the IBVAP Cockpit and click **Connect Camera**.
3. Input the device IP (e.g. `10.80.5.52`) and port (`4747` for DroidCam, `8080` for IP Webcam).
4. The system automatically:
   - Sets protocol to `http`.
   - Targets the live endpoint `/video`.
   - Permits your local subnet (`10.0.0.0/8`, `192.168.0.0/16`, `172.16.0.0/12`) through SSRF policy.
5. Click **Test Connection** to inspect stream metrics and **Save & Monitor**.

### 🎥 Standard RTSP / CCTV Infrastructure
- Provide full RTSP connection strings:
  ```
  rtsp://admin:secret@192.168.1.120:554/live/ch0
  ```
- All credentials are encrypted in-memory and at rest (AES-GCM/Fernet) and permanently redacted from client-facing logs and diagnostics.

---

## 🔌 API Endpoints

| Method | Route | Description |
|---|---|---|
| `GET` | `/api/v1/cameras` | List all active cameras and observed streaming states |
| `POST` | `/api/v1/cameras` | Register and provision a new camera feed |
| `POST` | `/api/v1/cameras/test` | Non-destructive multi-stage probe of raw camera endpoint |
| `GET` | `/api/v1/cameras/{id}/stream` | High-frequency multipart/x-mixed-replace MJPEG feed |
| `GET` | `/api/v1/cameras/{id}/observations` | Real-time AI detections, track states, faces, and plates |
| `GET` | `/api/v1/cameras/{id}/health` | Stream diagnostics, decode errors, and frame latency telemetry |
| `PUT` | `/api/v1/cameras/{id}/fence` | Configure virtual perimeter polygon coordinate fence |
| `GET` | `/api/v1/watchlist` | Retrieve enrolled suspect biometric profiles |
| `POST` | `/api/v1/watchlist` | Enroll new suspect with photo and threat classification |
| `GET` | `/api/v1/alerts/stream` | Server-Sent Events (SSE) firehose for security alerts |

---

## 🧪 Verification & Testing

```bash
# Run full backend test suite (172 tests)
uv run pytest -q

# Run static analysis and linting
uv run ruff check .
uv run pyright src/

# Run frontend unit & Playwright E2E suites
cd frontend
npm run typecheck
npx playwright test
cd ..
```

---

## 📁 Repository Structure

```
IBVAP/
├── src/ibvap/
│   ├── api/
│   │   ├── app.py                # FastAPI application setup & SPA routing
│   │   └── routes/
│   │       ├── cameras.py        # Stream demuxing, worker threads, HUD observations
│   │       ├── alerts.py         # Real-time threat alarms & SSE dispatch
│   │       ├── watchlist.py      # Facial suspect registry & biometrics
│   │       └── uploads.py        # Offline footage analysis & evidence exports
│   ├── core/
│   │   ├── probe.py              # PyAV format negotiation & URL normalization
│   │   ├── detector.py           # ONNX YOLO26 DirectML/CPU object detector
│   │   ├── tracker.py            # Centroid & ByteTrack multi-object tracker
│   │   ├── face.py               # YuNet face detector & SFace recognizer
│   │   ├── pipeline.py           # Synchronous/sampled analytics coordinator
│   │   └── ssrf.py               # Network perimeter & CIDR security validator
│   └── main.py                   # CLI entrypoint
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── CameraTile.tsx    # Live HUD, target boxes, sub-pixel EMA filter
│   │   │   ├── ConnectModal.tsx  # Multi-stage probe & camera onboarding dialog
│   │   │   └── Topbar.tsx        # Tactical navigation & status indicators
│   │   ├── pages/
│   │   │   ├── Cockpit.tsx       # Multi-grid surveillance dashboard
│   │   │   └── Watchlist.tsx     # Suspect enrollment & biometric management
│   │   └── lib/api.ts            # Client API client & types
│   └── tests/                    # Playwright visual & operational test suites
├── docs/
│   ├── assets/                   # Architectural diagrams & UI screenshots
│   ├── threat-model.md           # Formal STRIDE threat modeling & security controls
│   ├── deployment.md             # Production edge deployment manual
│   ├── benchmarks.md             # Latency & throughput performance metrics
│   ├── traceability.md           # Requirements-to-code traceability matrix
│   └── adr/                      # Architecture Decision Records
├── tests/                        # Pytest backend test suite (172+ test cases)
└── pyproject.toml                # Project dependencies & metadata
```

---

## 📚 Technical Documentation

Explore detailed engineering specifications in the [`docs/`](docs/) directory:
- [🛡️ Threat Model & Security Posture](docs/threat-model.md)
- [⚡ Latency & Edge Performance Benchmarks](docs/benchmarks.md)
- [📦 Production Deployment Manual](docs/deployment.md)
- [📋 Architectural Traceability Matrix](docs/traceability.md)
- [🏛️ Architectural Decision Records (ADRs)](docs/adr/)

---

## ⚖️ License

This project is licensed under the terms of the GNU Affero General Public License v3.0 ([AGPL-3.0](LICENSE)).
