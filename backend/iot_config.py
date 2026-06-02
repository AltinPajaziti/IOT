"""IoT pipeline configuration — Kafka & Cassandra (Professor Project 2)."""
import os

# ── Kafka ─────────────────────────────────────────────────────────────────────
KAFKA_BOOTSTRAP   = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
KAFKA_TOPIC       = os.getenv("KAFKA_TOPIC", "traffic-sensor-events")
KAFKA_ENABLED     = os.getenv("KAFKA_ENABLED", "true").lower() in ("1", "true", "yes")

# ── Cassandra ─────────────────────────────────────────────────────────────────
CASSANDRA_HOSTS   = [h.strip() for h in os.getenv("CASSANDRA_HOSTS", "127.0.0.1").split(",")]
CASSANDRA_PORT    = int(os.getenv("CASSANDRA_PORT", "9042"))
CASSANDRA_KEYSPACE = os.getenv("CASSANDRA_KEYSPACE", "traffic_iot")

# ── Sensor simulator (when no physical sensors) ───────────────────────────────
SIMULATOR_ENABLED    = os.getenv("SIMULATOR_ENABLED", "true").lower() in ("1", "true", "yes")
SIMULATOR_INTERVAL_S = float(os.getenv("SIMULATOR_INTERVAL_S", "5"))

# ── Camera GPS (mirrors .NET CameraCatalog) ───────────────────────────────────
CAMERA_COORDS: dict[str, tuple[float, float]] = {
    "pejton":    (42.6594, 21.1558),
    "pejton2":   (42.6601, 21.1565),
    "tokbashqe": (42.6572, 21.1621),
}

DENSITY_THRESHOLDS = {"low": 5, "medium": 15}
