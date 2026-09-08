# IBVAP — Intelligent Border Video Analytics Platform

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python: 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.141-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-19-61DAFB.svg?logo=react&logoColor=black)](https://react.dev/)
[![ONNX Runtime](https://img.shields.io/badge/ONNX_Runtime-DirectML-005CED.svg)](https://onnxruntime.ai/)
[![Vite](https://img.shields.io/badge/Vite-7-646CFF.svg?logo=vite&logoColor=white)](https://vitejs.dev/)

> **IBVAP** is an enterprise-grade, software-defined edge video analytics and tactical surveillance platform engineered for border defense, perimeter security, critical infrastructure monitoring, and high-throughput checkpoint analysis.

---

## Architecture Overview

\                                  +---------------------------------------+
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
        |      \GET /stream\ (Live MJPEG)       |      \GET /observations\ (HUD & Tracks)  |
        +----------------------------------------+-----------------------------------------+
                                                 |
                                                 v
        +----------------------------------------------------------------------------------+
        |                            IBVAP Tactical Cockpit UI                             |
        |  (React 19, Tailwind CSS v4, Lucide Icons, Sub-pixel EMA Smoothing, Theater Mode)   |
        +----------------------------------------------------------------------------------+
\
---

## Key Features

- **Multi-Source Ingestion & Protocol Normalization**:
  - Seamlessly handles RTSP, RTSPS, HTTP/HTTPS, MJPEG, and video footage playback.
  - Native smartphone camera integration: automatically detects and normalizes **DroidCam** (\:4747\) and **IP Webcam** (\:8080\) feeds to \/video\ with transient socket retry resilience.
- **Hardware-Accelerated Computer Vision**:
  - **YOLO26 (YOLOv8)** ONNX model for high-confidence person and vehicle detection with DirectML GPU acceleration and CPU fallback.
  - **YuNet & SFace Biometrics**: 5-point facial landmark detection, quality assessment (blur, illumination, pose), and 128D feature embedding for suspect identification.
  - **PaddleOCR ANPR**: Automatic license plate recognition with spatial vehicle-plate fusion.
- **Advanced Spatial Tracking & Deduplication**:
  - Centroid and ByteTrack-style tracking with velocity-adaptive smoothing and sub-pixel deadbands.
  - Multi-tier deduplication: suppresses ghost duplicate tracks, resolves cross-class spatial conflicts, and unifies overlapping boxes with IoU and containment analysis.
- **Tactical Cockpit & Geofencing**:
  - Low-latency tactical grid with theater solo mode, infrared/low-light night vision indicators, and live target inspection.
  - Interactive polygon perimeter drawing with real-time intrusion alarms.
  - Watchlist management with tiered alerts (\CRITICAL\, \HIGH\, \MEDIUM\, \LOW\).
- **Defensive Engineering & Zero-Trust Security**:
  - Strict SSRF policy enforcement with configurable CIDR allowlists (protects internal subnets).
  - DNS-rebinding defense and credentials encryption (Fernet / AES-GCM).
  - Zero-copy JPEG packet passthrough to minimize CPU utilization.

---

## Tech Stack

| Layer | Technologies |
|---|---|
| **Backend** | Python 3.12+, FastAPI, Uvicorn, SQLAlchemy (Async), Pydantic v2 |
| **Computer Vision** | OpenCV, PyAV (FFmpeg 7), ONNX Runtime (DirectML / CPU), PaddleOCR |
| **Frontend** | React 19, TypeScript, Vite 7, Tailwind CSS v4, TanStack Query, Lucide Icons |
| **Testing & Tooling** | Pytest, Pytest-Asyncio, Ruff, Pyright, Playwright, UV |

---

## Getting Started

### Prerequisites
- **Python**: \>= 3.12, < 3.14- **Node.js**: \>= 20.x- **uv**: Modern fast Python package manager (\pip install uv\ or \curl -LsSf https://astral.sh/uv/install.sh | sh\)

### 1. Installation

Clone the repository:
\\ash
git clone https://github.com/ReallyNotbaka/IBVAP.git
cd IBVAP
\
Install backend dependencies:
\\ash
uv sync --all-extras
\
Install frontend dependencies:
\\ash
cd frontend
npm install
cd ..
\
---

### 2. Running the Platform

#### Running Backend
\\ash
uv run uvicorn ibvap.api.app:app --host 0.0.0.0 --port 8000 --reload
\API Documentation will be available at:
- Swagger UI: \http://localhost:8000/docs- ReDoc: \http://localhost:8000/redoc
#### Running Frontend (Development)
\\ash
cd frontend
npm run dev
\Open \http://localhost:5173\ in your browser.

#### Building for Production
\\ash
cd frontend
npm run build
cd ..
uv run uvicorn ibvap.api.app:app --host 0.0.0.0 --port 8000
\FastAPI automatically serves the precompiled SPA frontend when \rontend/dist\ is present.

---

## Connecting Video Streams

### Wi-Fi Smartphone Cameras
1. Launch **DroidCam** or **IP Webcam** on your mobile device connected to the same local Wi-Fi.
2. Open the IBVAP Cockpit (\http://localhost:5173\) and click **Connect Camera**.
3. Enter the device IP (e.g., .80.5.52\) and port (ļ7\ for DroidCam or \8080\ for IP Webcam).
4. The system automatically configures the protocol to \http\, targets the stream endpoint \/video\, and permits local private subnets (.0.0.0/8\, 92.168.0.0/16\, z.16.0.0/12\).
5. Click **Test Connection** to inspect stream metrics and **Save & Monitor** to begin live analysis.

### Standard CCTV / RTSP Feeds
- Enter standard RTSP URLs (e.g., tsp://admin:password@192.168.1.100:554/h264Preview_01_main\).
- Credentials are encrypted at rest and redacted from logging and telemetry surfaces.

---

## Verification & Testing

Run full backend unit tests:
\\ash
uv run pytest -q
\
Run static type checking and linting:
\\ash
uv run ruff check .
uv run pyright src/
\
Run frontend typecheck and end-to-end Playwright tests:
\\ash
cd frontend
npm run typecheck
npx playwright test
cd ..
\
---

## Project Structure

\IBVAP/
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
├── docs/                         # Architecture Decision Records (ADRs) & threat models
├── tests/                        # Pytest backend test suite (172+ test cases)
└── pyproject.toml                # Project dependencies & metadata
\
---

## License

This project is licensed under the terms of the GNU Affero General Public License v3.0 ([AGPL-3.0](LICENSE)).
