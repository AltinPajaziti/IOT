# IoTH — Traffic Intelligence Platform

Real-time vehicle detection from live Prishtina traffic cameras using **YOLOv8** computer vision, a **Python FastAPI** detection service, a **.NET 9 Web API** persistence layer, and two **Angular** frontends — a live camera dashboard and an interactive map client with an AI-powered chatbot.

---

## Table of Contents

- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Project Structure](#project-structure)
- [Running the Platform](#running-the-platform)
  - [1 · Python Backend (port 8000)](#1--python-backend-port-8000)
  - [2 · NET Traffic API (port 5050)](#2--net-traffic-api-port-5050)
  - [3 · Angular Live Dashboard (port 4200)](#3--angular-live-dashboard-port-4200)
  - [4 · Angular Map Client (port 4201)](#4--angular-map-client-port-4201)
  - [Start Everything at Once](#start-everything-at-once)
  - [Stop Everything](#stop-everything)
- [Configured Cameras](#configured-cameras)
- [API Reference](#api-reference)
  - [Python Backend API](#python-backend-api)
  - [.NET Traffic API](#net-traffic-api)
  - [TrafficBot Chat API](#trafficbot-chat-api)
- [Features](#features)
- [Refreshing Stream URLs](#refreshing-stream-urls)
- [Adding a New Camera](#adding-a-new-camera)
- [Notes](#notes)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      Camera Sources                          │
│           Gjirafa HLS Streams (.m3u8)                        │
└───────────────────────┬──────────────────────────────────────┘
                        │ OpenCV
                        ▼
┌──────────────────────────────────────────────────────────────┐
│           Python FastAPI Backend  :8000                      │
│  ┌─────────────────┐  ┌──────────┐  ┌─────────────────────┐ │
│  │  YOLOv8 Detector│  │ Tracker  │  │  TrafficBot /chat   │ │
│  │  (cars/trucks/  │  │ (IoU +   │  │  (OpenAI gpt-4o-    │ │
│  │   buses/motos)  │  │ velocity)│  │   mini + fallback)  │ │
│  └────────┬────────┘  └──────────┘  └─────────────────────┘ │
│           │ MJPEG annotated stream                           │
└───────────┼──────────────────────────────────────────────────┘
            │ polls every 1 min
            ▼
┌──────────────────────────────────────────────────────────────┐
│           .NET 9 Web API  :5050                              │
│  ┌──────────────────────┐   ┌──────────────────────────────┐ │
│  │  SnapshotPollerService│   │  SQL Server LocalDB          │ │
│  │  (background worker) │──▶│  TrafficWatch › dbo.Snapshots│ │
│  └──────────────────────┘   └──────────────────────────────┘ │
└──────────────────────────────────┬───────────────────────────┘
                                   │ REST
          ┌────────────────────────┴────────────────────┐
          ▼                                             ▼
┌──────────────────────┐                 ┌──────────────────────────────┐
│  frontend  :4200     │                 │  traffic-client  :4201       │
│  Angular 20          │                 │  Angular 21                  │
│  Live camera dashboard│                │  Leaflet map + AI chatbot    │
│  MJPEG feed, charts  │                 │  density polylines, alerts   │
└──────────────────────┘                 └──────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Computer vision | Python 3.10+, **YOLOv8n** (Ultralytics), OpenCV |
| Detection backend | **FastAPI**, Uvicorn, NumPy, Pillow, httpx |
| AI chatbot | **OpenAI gpt-4o-mini** with rule-based local fallback |
| Persistence API | **.NET 9**, ASP.NET Core, **Entity Framework Core 9** |
| Database | **SQL Server LocalDB** (`TrafficWatch`) |
| Live dashboard | **Angular 20**, Chart.js 4.5, SCSS |
| Map client | **Angular 21**, **Leaflet** 1.9, SCSS |
| Multi-object tracking | Custom IoU tracker with velocity prediction |

---

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.10+ | with `pip` |
| Node.js | 18+ | with `npm` |
| .NET SDK | 9.0 | verify with `dotnet --version` |
| SQL Server LocalDB | any | ships with Visual Studio / VS Build Tools |

---

## Project Structure

```
IOT/
├── backend/                  Python FastAPI — YOLO detection, MJPEG stream, AI chat
│   ├── main.py               App entry point, CORS, lifespan hooks
│   ├── config.py             Camera configs, YOLO settings, density thresholds
│   ├── camera_manager.py     Dual-thread camera reader + YOLO worker
│   ├── detector.py           Thread-safe YOLOv8 singleton, bounding-box overlay
│   ├── tracker.py            IoU multi-object tracker with coasting & velocity
│   ├── routes/
│   │   ├── traffic.py        Traffic REST endpoints + MJPEG stream
│   │   └── chat.py           TrafficBot AI chat endpoint
│   ├── find_streams.py       Helper: scrape Gjirafa for .m3u8 URLs
│   ├── extract_streams.py    Helper: Playwright headless stream extraction
│   └── requirements.txt
│
├── traffic-api/              .NET 9 Web API — polls Python, stores to SQL Server
│   ├── Program.cs
│   ├── Controllers/SnapshotsController.cs
│   ├── Models/TrafficSnapshot.cs
│   ├── Data/TrafficDbContext.cs
│   ├── Services/SnapshotPollerService.cs
│   └── traffic-api.csproj
│
├── frontend/                 Angular 20 — live camera dashboard          (port 4200)
│   └── src/app/
│       ├── services/traffic.ts
│       └── pages/traffic-monitor/
│
├── traffic-client/           Angular 21 — map view + TrafficBot          (port 4201)
│   └── src/app/
│       ├── services/
│       │   ├── traffic-api.service.ts
│       │   └── chatbot.service.ts
│       ├── pages/map/
│       └── components/chatbot/
│
└── README.md
```

---

## Running the Platform

### 1 · Python Backend (port 8000)

```powershell
cd backend

# First time only — create virtual environment
python -m venv .venv
.venv\Scripts\activate

# First time only — install dependencies
# (YOLOv8n weights ~6 MB download automatically on first run)
pip install -r requirements.txt

# Start
.venv\Scripts\uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

> **Swagger UI:** http://localhost:8000/docs

---

### 2 · .NET Traffic API (port 5050)

Polls the Python backend every **1 minute**, stores snapshots to SQL Server, and exposes REST endpoints for the map client.

```powershell
cd traffic-api

# First time only
dotnet restore

# Start (creates TrafficWatch DB automatically on first run)
dotnet run
```

> **API root:** http://localhost:5050  
> **Database:** `(localdb)\MSSQLLocalDB` → `TrafficWatch` → `dbo.Snapshots`

---

### 3 · Angular Live Dashboard (port 4200)

Live MJPEG camera feed with vehicle count stat cards and a Chart.js breakdown bar chart.

```powershell
cd frontend

# First time only
npm install

# Start
npm start
```

> **Dashboard:** http://localhost:4200

---

### 4 · Angular Map Client (port 4201)

Interactive Leaflet map with traffic density route overlays, camera sensor markers, live alerts, and the TrafficBot AI chatbot. Data refreshes every **60 seconds**.

```powershell
cd traffic-client

# First time only
npm install

# Start
npm start
```

> **Map view:** http://localhost:4201

---

### Start Everything at Once

Open **four separate PowerShell terminals** and run one command in each:

```powershell
# Terminal 1 — Python backend
cd backend
.venv\Scripts\uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2 — .NET Traffic API
cd traffic-api
dotnet run

# Terminal 3 — Angular live dashboard
cd frontend
npm start

# Terminal 4 — Angular map client
cd traffic-client
npm start
```

Or launch all four in background windows at once (development only):

```powershell
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd backend; .venv\Scripts\uvicorn main:app --reload --host 0.0.0.0 --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd traffic-api; dotnet run"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd frontend; npm start"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd traffic-client; npm start"
```

---

### Stop Everything

```powershell
Get-Process python*, dotnet, node -ErrorAction SilentlyContinue | Stop-Process -Force
```

---

## Configured Cameras

| ID | Name | Street | Gjirafa page |
|----|------|--------|--------------|
| `pejton` | Pejton | Rr. Agim Ramadani, Pejton | https://video.gjirafa.com/slow-tv-pejton |
| `pejton2` | Pejton 2 | Rr. Agim Ramadani, Pejton | https://video.gjirafa.com/slow-tv-pejton-2 |
| `tokbashqe` | Tokbashqe | Rr. Tokbashqe | https://video.gjirafa.com/slow-tv-tokbashqe |

---

## API Reference

### Python Backend API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/api/traffic/cameras` | List all configured cameras |
| GET | `/api/traffic/stats/{cameraId}` | Latest YOLO stats snapshot (auto-starts worker) |
| GET | `/api/traffic/stream/{cameraId}` | MJPEG annotated live stream |
| GET | `/api/traffic/history/{cameraId}` | Rolling in-memory stats history |
| POST | `/api/traffic/start/{cameraId}` | Start a camera detection worker |
| POST | `/api/traffic/stop/{cameraId}` | Stop a camera detection worker |
| POST | `/api/traffic/upload` | Upload a local `.mp4` for offline YOLO testing |

---

### .NET Traffic API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/snapshots/latest` | Latest snapshot per camera |
| GET | `/api/snapshots/history/{cameraId}?hours=3` | Time-series history for one camera |
| GET | `/api/snapshots/summary` | Aggregated vehicle totals across all cameras |

---

### TrafficBot Chat API

```
POST /api/chat
Content-Type: application/json

{
  "message": "Which route has the most traffic?",
  "snapshots": [ ...current snapshot array from .NET API... ]
}
```

The chatbot is **traffic-scoped**: it answers questions about Pejton, Pejton 2, and Tokbashqe routes (vehicle counts, congestion, density, summaries). For greetings and off-topic messages it responds naturally without returning traffic data. It uses **OpenAI gpt-4o-mini** with a local rule-based fallback when the API is unavailable.

**Example prompts:**
- `"Hello"` → friendly greeting
- `"Which route has the most traffic?"` → comparison across routes
- `"Is Pejton congested right now?"` → density status for Pejton
- `"Give me a full traffic summary"` → full breakdown of all routes
- `"How many vehicles are on Tokbashqe?"` → vehicle count for that route

---

## Features

### Real-time Vehicle Detection
- Live HLS stream ingestion from Gjirafa cameras via OpenCV
- **YOLOv8n** detects cars, trucks, buses, and motorcycles
- **IoU-based multi-object tracker** with stable IDs, coasting, and velocity prediction
- Dual-thread architecture per camera (frame reader + YOLO inference) with a global inference lock for serial GPU/CPU usage
- MJPEG output with annotated bounding boxes, counts overlay, and FPS

### Density Classification

| Level | Condition |
|-------|-----------|
| 🟢 Low | ≤ 5 vehicles |
| 🟡 Medium | 6 – 15 vehicles |
| 🔴 High | > 15 vehicles |

### Data Pipeline
- .NET background service polls Python every **1 minute** per active camera
- Snapshots are persisted to **SQL Server LocalDB** with GPS coordinates
- Snapshots older than **24 hours** are pruned automatically on each cycle
- DB and table are created automatically on first `.NET` startup via `EnsureCreated()` — no migrations needed

### Map Client (`traffic-client`)
- **Leaflet** map centered on Prishtina with CARTO Voyager tiles
- Custom pulsing camera sensor markers showing live vehicle counts
- **Route polylines** colored by real-time density
- Live alert banners for Medium/High density routes
- Inspector panel per camera with vehicle-type breakdown and density progress bars
- Countdown timer showing seconds until next data refresh

### Live Dashboard (`frontend`)
- Camera selector across all configured streams
- Live MJPEG feed rendered in an `<img>` tag — zero buffering
- Stat cards + Chart.js bar chart for per-type vehicle breakdown
- **Video upload** for offline YOLO testing (creates a virtual camera session)

### AI Chatbot — TrafficBot
- Floating chat widget embedded in the map client
- **Context-aware**: receives live snapshot data so answers reflect current conditions
- **Conversational**: responds to greetings and casual input naturally; only surfaces traffic data when traffic questions are asked
- **OpenAI gpt-4o-mini** as primary model; automatic local rule-based fallback if unreachable
- Quick-prompt chips for common traffic queries

---

## Refreshing Stream URLs

Gjirafa HLS `.m3u8` URLs expire periodically. To get a fresh URL:

**Chrome DevTools (recommended):**
1. Open the Gjirafa camera page (e.g. https://video.gjirafa.com/slow-tv-pejton)
2. Open DevTools → **Network** → filter by `m3u8`
3. Press **Play** on the video — the request appears in the network log
4. Copy the full URL and paste it into `stream_url` in `backend/config.py`

**yt-dlp:**
```bash
pip install yt-dlp
yt-dlp -g https://video.gjirafa.com/slow-tv-pejton
```

---

## Adding a New Camera

1. **Register the camera** — add a `CameraConfig` entry in `backend/config.py`:
   ```python
   CameraConfig(
       id="newroute",
       name="New Route",
       location="Rr. Example",
       city="Prishtina",
       stream_url="https://...stream.m3u8",
       gjirafa_page="https://video.gjirafa.com/slow-tv-newroute",
       active=True
   )
   ```

2. **Add GPS coordinates** — add an entry to the `CameraCoords` dictionary in `traffic-api/Services/SnapshotPollerService.cs`:
   ```csharp
   ["newroute"] = (42.6640, 21.1655)
   ```

3. Restart the Python backend and the .NET API. The new camera will appear in the dashboard, map, and chatbot context automatically.

---

## Notes

- YOLOv8n weights (~6 MB) download automatically on the first Python backend start.
- The .NET API polls **all active cameras**, not just running ones — snapshots are stored even when YOLO streams are idle.
- The map client refreshes from the .NET API every **60 seconds**; a live countdown is shown in the sidebar.
- OpenAI API key is currently stored directly in `backend/routes/chat.py` — move it to an environment variable (e.g. `OPENAI_API_KEY`) before deploying to any shared or production environment.
