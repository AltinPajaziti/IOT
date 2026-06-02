"""
Kafka → Cassandra stream processor (dev fallback when Spark is not running).

For the professor presentation, use spark-jobs/traffic_streaming.py (Apache Spark
Structured Streaming). This module keeps the pipeline functional during development.
"""
from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone

from config import CAMERAS
from iot_config import KAFKA_BOOTSTRAP, KAFKA_TOPIC, CASSANDRA_KEYSPACE

logger = logging.getLogger("stream_processor")

_stop = threading.Event()
_thread: threading.Thread | None = None
_processed = 0
_windows: dict[str, list] = defaultdict(list)


def _write_snapshot_cqlsh(event: dict) -> bool:
    try:
        from datetime import datetime, timezone
        captured = event.get("captured_at")
        try:
            ts = datetime.fromisoformat(captured.replace("Z", "+00:00"))
        except Exception:
            ts = datetime.now(timezone.utc)
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S+0000")
        cql = (
            f"INSERT INTO {CASSANDRA_KEYSPACE}.sensor_snapshots "
            f"(camera_id, captured_at, camera_name, location, city, total_vehicles, "
            f"cars, trucks, buses, motorcycles, density, fps, latitude, longitude, source) "
            f"VALUES ('{event['camera_id']}', '{ts_str}', '{event.get('camera_name','')}', "
            f"'{event.get('location','')}', '{event.get('city','')}', {event['total_vehicles']}, "
            f"{event.get('cars',0)}, {event.get('trucks',0)}, {event.get('buses',0)}, "
            f"{event.get('motorcycles',0)}, '{event.get('density','Low')}', "
            f"{float(event.get('fps',0))}, {float(event.get('latitude',0))}, "
            f"{float(event.get('longitude',0))}, '{event.get('source','kafka')}');"
        )
        subprocess.run(
            ["docker", "exec", "ioth-cassandra", "cqlsh", "-e", cql],
            capture_output=True, text=True, timeout=15, check=True,
        )
        return True
    except Exception as exc:
        logger.warning("cqlsh write failed: %s", exc)
        return False


def _write_snapshot(session, event: dict) -> None:
    if session is None:
        if _write_snapshot_cqlsh(event):
            return
        raise RuntimeError("No Cassandra session")
    captured = event.get("captured_at")
    try:
        ts = datetime.fromisoformat(captured.replace("Z", "+00:00"))
    except Exception:
        ts = datetime.now(timezone.utc)

    session.execute(
        """
        INSERT INTO sensor_snapshots (
            camera_id, captured_at, camera_name, location, city,
            total_vehicles, cars, trucks, buses, motorcycles,
            density, fps, latitude, longitude, source
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            event["camera_id"], ts, event.get("camera_name"), event.get("location"),
            event.get("city"), event["total_vehicles"], event.get("cars", 0),
            event.get("trucks", 0), event.get("buses", 0), event.get("motorcycles", 0),
            event.get("density", "Low"), float(event.get("fps", 0)),
            float(event.get("latitude", 0)), float(event.get("longitude", 0)),
            event.get("source", "kafka"),
        ),
    )


def _maybe_flush_window(session, camera_id: str) -> None:
    bucket = _windows[camera_id]
    if len(bucket) < 3:
        return
    now = time.time()
    # Flush 1-minute window
    window_start = datetime.fromtimestamp(now - 60, tz=timezone.utc).replace(microsecond=0)
    window_end   = datetime.fromtimestamp(now, tz=timezone.utc).replace(microsecond=0)
    totals = [e["total_vehicles"] for e in bucket]
    avg_v  = sum(totals) / len(totals)
    max_v  = max(totals)
    density = "Low" if avg_v <= 5 else ("Medium" if avg_v <= 15 else "High")
    if session is None:
        cql = (
            f"INSERT INTO {CASSANDRA_KEYSPACE}.sensor_aggregates "
            f"(camera_id, window_start, window_end, avg_vehicles, max_vehicles, "
            f"sample_count, dominant_density) VALUES ('{camera_id}', "
            f"'{window_start.strftime('%Y-%m-%d %H:%M:%S+0000')}', "
            f"'{window_end.strftime('%Y-%m-%d %H:%M:%S+0000')}', "
            f"{avg_v}, {max_v}, {len(bucket)}, '{density}');"
        )
        subprocess.run(
            ["docker", "exec", "ioth-cassandra", "cqlsh", "-e", cql],
            capture_output=True, text=True, timeout=15, check=True,
        )
    else:
        session.execute(
            """
            INSERT INTO sensor_aggregates (
                camera_id, window_start, window_end,
                avg_vehicles, max_vehicles, sample_count, dominant_density
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (camera_id, window_start, window_end, avg_v, max_v, len(bucket), density),
        )
    _windows[camera_id].clear()


def _loop() -> None:
    global _processed
    try:
        from kafka import KafkaConsumer
        from cassandra_reader import _get_session
    except ImportError as exc:
        logger.error("Stream processor dependencies missing: %s", exc)
        return

    consumer = None
    for attempt in range(30):
        try:
            consumer = KafkaConsumer(
                KAFKA_TOPIC,
                bootstrap_servers=KAFKA_BOOTSTRAP,
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
                auto_offset_reset="latest",
                group_id="traffic-iot-fallback-processor",
                consumer_timeout_ms=1000,
            )
            break
        except Exception as exc:
            logger.warning("Waiting for Kafka (attempt %d): %s", attempt + 1, exc)
            time.sleep(2)

    if consumer is None:
        logger.error("Could not connect to Kafka — stream processor stopped")
        return

    logger.info("Stream processor (fallback) consuming topic %s", KAFKA_TOPIC)
    while not _stop.is_set():
        try:
            session = _get_session()
            for msg in consumer:
                if _stop.is_set():
                    break
                event = msg.value
                if not event or not event.get("camera_id"):
                    continue
                if event.get("total_vehicles", -1) < 0:
                    continue
                _write_snapshot(session, event)
                _windows[event["camera_id"]].append(event)
                _maybe_flush_window(session, event["camera_id"])
                _processed += 1
        except Exception as exc:
            logger.warning("Stream processor error: %s", exc)
            time.sleep(2)


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="stream-processor")
    _thread.start()


def stop() -> None:
    _stop.set()


def status() -> dict:
    return {
        "running":   _thread.is_alive() if _thread else False,
        "processed": _processed,
        "mode":      "fallback (use Spark for production demo)",
    }
