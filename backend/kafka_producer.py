"""Kafka producer — sends traffic sensor events to Apache Kafka."""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from iot_config import KAFKA_BOOTSTRAP, KAFKA_ENABLED, KAFKA_TOPIC, CAMERA_COORDS, DENSITY_THRESHOLDS

logger = logging.getLogger("kafka_producer")

_producer = None
_last_error: Optional[str] = None
_events_sent = 0


def _density(total: int) -> str:
    if total <= DENSITY_THRESHOLDS["low"]:
        return "Low"
    if total <= DENSITY_THRESHOLDS["medium"]:
        return "Medium"
    return "High"


def _get_producer():
    global _producer, _last_error
    if not KAFKA_ENABLED:
        return None
    if _producer is not None:
        return _producer
    try:
        from kafka import KafkaProducer
        _producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
            acks="all",
            retries=3,
            request_timeout_ms=5000,
        )
        _last_error = None
        logger.info("Kafka producer connected to %s", KAFKA_BOOTSTRAP)
        return _producer
    except Exception as exc:
        _last_error = str(exc)
        logger.warning("Kafka unavailable: %s", exc)
        return None


def build_event(
    *,
    camera_id: str,
    camera_name: str,
    location: str,
    city: str,
    total_vehicles: int,
    cars: int,
    trucks: int,
    buses: int,
    motorcycles: int,
    density: str,
    fps: float = 0.0,
    source: str = "yolo",
    captured_at: Optional[str] = None,
) -> dict[str, Any]:
    lat, lng = CAMERA_COORDS.get(camera_id, (42.6629, 21.1655))
    return {
        "camera_id":       camera_id,
        "camera_name":     camera_name,
        "location":        location,
        "city":            city,
        "captured_at":     captured_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_vehicles":  total_vehicles,
        "cars":            cars,
        "trucks":          trucks,
        "buses":           buses,
        "motorcycles":     motorcycles,
        "density":         density,
        "fps":             fps,
        "latitude":        lat,
        "longitude":       lng,
        "source":          source,
    }


def build_event_from_detection(stats: dict, source: str = "yolo") -> dict[str, Any]:
    counts = stats.get("counts") or {}
    total  = stats.get("total_vehicles", 0)
    return build_event(
        camera_id=stats.get("camera_id", ""),
        camera_name=stats.get("camera_name", ""),
        location=stats.get("location", ""),
        city=stats.get("city", "Prishtinë"),
        total_vehicles=total,
        cars=counts.get("car", 0),
        trucks=counts.get("truck", 0),
        buses=counts.get("bus", 0),
        motorcycles=counts.get("motorcycle", 0),
        density=stats.get("density", _density(total)),
        fps=float(stats.get("fps", 0)),
        source=source,
        captured_at=stats.get("timestamp"),
    )


def publish_event(event: dict[str, Any]) -> bool:
    global _events_sent, _last_error
    producer = _get_producer()
    if producer is None:
        return False
    try:
        future = producer.send(KAFKA_TOPIC, event)
        future.add_errback(lambda exc: logger.warning("Kafka publish failed: %s", exc))
        _events_sent += 1
        _last_error = None
        return True
    except Exception as exc:
        _last_error = str(exc)
        logger.warning("Kafka publish failed: %s", exc)
        return False


def producer_status() -> dict[str, Any]:
    return {
        "enabled":     KAFKA_ENABLED,
        "bootstrap":   KAFKA_BOOTSTRAP,
        "topic":       KAFKA_TOPIC,
        "connected":   _get_producer() is not None,
        "events_sent": _events_sent,
        "last_error":  _last_error,
    }
