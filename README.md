# IoTH – Traffic Intelligence Platform

Real-time vehicle detection from Prishtina traffic cameras using **YOLOv8** + **FastAPI** + **.NET 9 Web API** + **Angular 20**.

```
ioth/
├── backend/          Python FastAPI — YOLO detection, MJPEG stream, live stats
├── frontend/         Angular 20 — live camera dashboard with MJPEG feed  (port 4200)
├── traffic-api/      .NET 9 Web API — polls backend, stores to SQL Server (port 5050)
├── traffic-client/   Angular 20 — map view with traffic density visuals   (port 4201)
└── traffic-monitoring-realistic.html   Reference UI mockup
```

---

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.10+ | with `pip` |
| Node.js | 18+ | with `npm` |
| .NET SDK | 9.0 | `dotnet --version` |
| SQL Server LocalDB | any | ships with Visual Studio / VS Build Tools |

---

## 1 · Python Backend (port 8000)

```powershell
cd backend

# Create virtual environment (first time only)
python -m venv .venv
.venv\Scripts\activate

# Install dependencies (downloads YOLOv8 weights ~6 MB on first run)
pip install -r requirements.txt

# Start
.venv\Scripts\uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

> **API:** http://localhost:8000  
> **Swagger docs:** http://localhost:8000/docs

---

## 2 · Angular Live Dashboard (port 4200)

```powershell
cd frontend

# Install dependencies (first time only)
npm install

# Start
npm start
```

> **Dashboard:** http://localhost:4200

---

## 3 · .NET Traffic API (port 5050)

Polls the Python backend every **1 minute**, stores snapshots to **SQL Server LocalDB**, and exposes REST endpoints for the map client.

```powershell
cd traffic-api

# Restore packages (first time only)
dotnet restore

# Start (creates TrafficWatch DB automatically on first run)
dotnet run
```

> **API:** http://localhost:5050  
> **Database:** `(localdb)\MSSQLLocalDB` → `TrafficWatch` → `dbo.Snapshots`

### .NET API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/snapshots/latest` | Latest snapshot per camera |
| GET | `/api/snapshots/history/{cameraId}` | History for one camera (default: last 3 h) |
| GET | `/api/snapshots/summary` | Aggregated totals across all cameras |

---

## 4 · Angular Map Client (port 4201)

Displays live traffic density on a Leaflet map. Data comes from the .NET API.  
Refreshes every **1 minute**. Shows camera sensor icons, route polylines, vehicle breakdown, and alerts.

```powershell
cd traffic-client

# Install dependencies (first time only)
npm install

# Start
npm start
```

> **Map view:** http://localhost:4201

---

## Starting everything at once (PowerShell)

Open **four separate PowerShell terminals** and run one command in each:

```powershell
# Terminal 1 — Python backend
cd C:\Users\PC\Desktop\ioth\backend
.venv\Scripts\uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2 — Angular dashboard
cd C:\Users\PC\Desktop\ioth\frontend
npm start

# Terminal 3 — .NET Traffic API
cd C:\Users\PC\Desktop\ioth\traffic-api
dotnet run

# Terminal 4 — Angular map client
cd C:\Users\PC\Desktop\ioth\traffic-client
npm start
```

Or use this single one-liner to background all four (development only):

```powershell
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd 'C:\Users\PC\Desktop\ioth\backend'; .venv\Scripts\uvicorn main:app --reload --host 0.0.0.0 --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd 'C:\Users\PC\Desktop\ioth\frontend'; npm start"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd 'C:\Users\PC\Desktop\ioth\traffic-api'; dotnet run"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd 'C:\Users\PC\Desktop\ioth\traffic-client'; npm start"
```

---

## Stopping everything

```powershell
# Kill Python, .NET, and Node processes
Get-Process python*, dotnet, node -ErrorAction SilentlyContinue | Stop-Process -Force
```

---

## Cameras configured

| ID | Name | Street | Gjirafa page |
|----|------|--------|--------------|
| `pejton` | Pejton | Rr. Agim Ramadani, Pejton | https://video.gjirafa.com/slow-tv-pejton |
| `pejton2` | Pejton 2 | Rr. Agim Ramadani, Pejton | https://video.gjirafa.com/slow-tv-pejton-2 |
| `tokbashqe` | Tokbashqe | Rr. Tokbashqe | https://video.gjirafa.com/slow-tv-tokbashqe |

To add more cameras, append a `CameraConfig` entry in `backend/config.py` and add GPS coordinates in `traffic-api/Services/SnapshotPollerService.cs` (`CameraCoords` dictionary).

---

## Refreshing stream URLs

Gjirafa HLS stream URLs expire. To get fresh `.m3u8` URLs:

**Chrome DevTools:**
1. Open the Gjirafa camera page
2. DevTools → Network → filter `m3u8`
3. Press Play — copy the URL
4. Paste into `stream_url` in `backend/config.py`

**yt-dlp:**
```bash
pip install yt-dlp
yt-dlp -g https://video.gjirafa.com/slow-tv-pejton
```

---

## Python Backend API reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/traffic/cameras` | List all configured cameras |
| GET | `/api/traffic/stats/{cameraId}` | Latest YOLO stats snapshot |
| GET | `/api/traffic/stream/{cameraId}` | MJPEG annotated stream (`<img src="…">`) |
| GET | `/api/traffic/history/{cameraId}` | Rolling stats history |
| POST | `/api/traffic/start/{cameraId}` | Start a camera worker |
| POST | `/api/traffic/stop/{cameraId}` | Stop a camera worker |
| POST | `/api/traffic/upload` | Upload local `.mp4` for offline testing |

---

## Notes

- YOLOv8n weights download automatically on first backend start (~6 MB).
- The .NET API polls all **active** cameras (not just running ones) — so data is stored even if the YOLO stream is idle.
- SQL Server LocalDB creates `TrafficWatch` database automatically via `EnsureCreated()` on first startup — no migrations needed.
- Snapshots older than **24 hours** are pruned automatically on each poll cycle.
- The map client polls the .NET API every **60 seconds**; the countdown timer is shown in the sidebar.

# IOT
