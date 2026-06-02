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
| Kafka Consumer | Spark Structured Streaming (`spark-jobs/traffic_streaming.py`) |
| Spark Streaming | 1-min tumbling windows, validation, aggregations |
| Apache Cassandra | `cassandra/schema.cql` — `sensor_snapshots`, `sensor_aggregates` |
| Web visualization | Map client :4201 with pipeline status panel |
| AI (bonus) | TrafficBot chatbot + YOLO |
| Alarms (bonus) | Red congestion banner + alerts panel |
| Performance (bonus) | Window aggregates, 15s refresh from DB settings |

## Quick start (live demo)

```powershell
# 1. IoT stack
.\scripts\start-iot-stack.ps1

# 2. Python backend (includes simulator + stream processor fallback)
cd backend
pip install -r requirements.txt
.venv\Scripts\uvicorn main:app --reload --port 8000

# 3. .NET API (SQL fallback + simulate button)
cd traffic-api
dotnet run

# 4. Map client
cd traffic-client
ng serve

# 5. Spark Streaming (for professor presentation — requires Java 11+)
cd spark-jobs
pip install -r requirements.txt
# Download spark-cassandra-connector JAR, then:
spark-submit --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.3,com.datastax.spark:spark-cassandra-connector_2.12:3.5.0 traffic_streaming.py
```

Set `STREAM_PROCESSOR_FALLBACK=false` when running Spark so only Spark writes to Cassandra.

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
5. **Cassandra** — Schema in `cassandra/schema.cql`
6. **Ndërfaqja** — Map client screenshots (pipeline panel, alarms, chatbot)
7. **Përfundime** — AI + alarms as advanced components
