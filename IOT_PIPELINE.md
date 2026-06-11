# IoT Pipeline — Professor Project 2 Requirements

This document maps the **Traffic Monitoring** project to the IoT course requirements (Projekti 2).

## Domain
**Smart Traffic Monitoring** — Prishtina camera sensors count vehicles in real time.

## Architecture

```
Sensors (YOLO cameras) ──┐
Sensor Simulator ────────┼──► Apache Kafka ──► Spark Streaming ──► Apache Cassandra ──► Web UI
Simulate button ─────────┘         (9092)      (spark-jobs/)         (9042)            (4201)
```

Also supported (legacy path): Python → .NET API → SQL Server LocalDB

## Professor checklist

| Requirement | Implementation |
|-------------|----------------|
| Sensor / Simulator | YOLO cameras + `sensor_simulator.py` (publishes every 5s) |
| Apache Kafka | `docker-compose.yml`, topic `traffic-sensor-events`, Kafka UI :8080 |
| Kafka Producer | `backend/kafka_producer.py` — YOLO stats + simulator |
| Kafka Consumer | Spark Structured Streaming service `ioth-spark-streaming` |
| Spark Streaming | `spark-jobs/traffic_streaming.py` — 1-min tumbling windows, validation, aggregations |
| Apache Cassandra | `cassandra/schema.cql` — `sensor_snapshots`, `sensor_metadata`, `sensor_aggregates` |
| Web visualization | Map client :4201 with pipeline status panel |
| AI (bonus) | TrafficBot chatbot + YOLO |
| Alarms (bonus) | Red congestion banner + alerts panel |
| Stopped-vehicle alarm (bonus) | Generates an alarm when more than 15 stopped vehicles are detected |
| Smart route advisor (bonus) | Recommends the clearest route and the route to avoid from live density/vehicle scores |
| Vehicle speed estimation (bonus) | Uses tracked motion internally for traffic analysis; speed is hidden from the YOLO overlay |
| Vehicle direction detection (bonus) | Detects two-way vehicle direction from track motion and shows per-direction counts |
| Lane density detection (bonus) | Splits vehicles into left/right lanes and reports which lane is denser |
| Performance (bonus) | Window aggregates, 15s refresh from DB settings |

## Quick start (live demo)

```powershell
# 1. IoT stack: Kafka + Spark Master/Worker + Spark Streaming + Cassandra
.\scripts\start-iot-stack.ps1

# 2. Python backend (publishes YOLO/simulator events to Kafka)
cd backend
pip install -r requirements.txt
.venv\Scripts\uvicorn main:app --reload --port 8000

# 3. .NET API (SQL fallback + simulate button)
cd traffic-api
dotnet run

# 4. Map client
cd traffic-client
ng serve

# 5. Check Spark Streaming
docker ps --filter "name=ioth-spark-streaming"
```

Spark Streaming now runs in Docker through the `ioth-spark-streaming` service.
The backend fallback processor is disabled by default so Spark is the component
that consumes Kafka and writes processed data to Cassandra.

## API endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/pipeline/status` | Kafka, Cassandra, simulator health |
| `GET /api/pipeline/snapshots/latest` | Latest data from Cassandra |
| `POST /api/pipeline/simulate` | Publish 200 cars to Kafka |

## Report sections (for final document)

1. **Hyrje** — Smart traffic monitoring for Prishtina
2. **Infrastruktura** — Diagram above
3. **Kafka** — Producer in Python, topic `traffic-sensor-events`, Kafka UI screenshots
4. **Spark Streaming** — Window aggregations, validation filters
5. **Cassandra** — Schema in `cassandra/schema.cql`, including sensor data and sensor metadata
6. **Ndërfaqja** — Map client screenshots (pipeline panel, alarms, chatbot)
7. **Përfundime** — AI + alarms as advanced components
