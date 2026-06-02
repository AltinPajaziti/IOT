"""IoT pipeline API — Kafka / Spark / Cassandra status and reads."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from cassandra_reader import cassandra_status, get_aggregates, get_latest_snapshots
from kafka_producer import producer_status
from sensor_simulator import simulate_congestion, status as sim_status
from stream_processor import status as processor_status

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


class SimulateRequest(BaseModel):
    cars: int = 200


@router.get("/status")
async def pipeline_status():
    """Health of the IoT pipeline components (Kafka, Cassandra, Simulator)."""
    kafka = producer_status()
    cassandra = cassandra_status()
    simulator = sim_status()
    return {
        "pipeline": "Traffic Monitoring IoT",
        "flow": "Sensors/Simulator → Kafka → Spark Streaming → Cassandra → Web UI",
        "kafka": kafka,
        "cassandra": cassandra,
        "simulator": simulator,
        "stream_processor": processor_status(),
        "spark": {
            "job": "spark-jobs/traffic_streaming.py",
            "note": "Run with: spark-submit traffic_streaming.py (requires Java + PySpark)",
        },
    }


@router.get("/snapshots/latest")
async def latest_from_cassandra():
    """Latest processed snapshot per camera from Cassandra (post-Spark)."""
    rows = get_latest_snapshots()
    return rows


@router.get("/aggregates")
async def window_aggregates(limit: int = 20):
    """Spark Streaming window aggregates stored in Cassandra."""
    return get_aggregates(limit)


@router.post("/simulate")
async def simulate_to_kafka(body: SimulateRequest | None = None):
    """Publish simulated high-traffic sensor events to Kafka (for live demo)."""
    cars = body.cars if body and 0 < body.cars <= 500 else 200
    return simulate_congestion(cars)
