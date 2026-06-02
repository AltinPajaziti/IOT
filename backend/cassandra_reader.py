"""Read processed sensor data from Apache Cassandra."""
from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime
from typing import Any, Optional

from config import CAMERAS
from iot_config import CASSANDRA_HOSTS, CASSANDRA_PORT, CASSANDRA_KEYSPACE

logger = logging.getLogger("cassandra_reader")

_session = None
_last_error: Optional[str] = None
_use_cqlsh = False


def _get_session():
    global _session, _last_error, _use_cqlsh
    if _use_cqlsh:
        return None
    if _session is not None:
        return _session
    try:
        from cassandra.cluster import Cluster
        from cassandra.policies import DCAwareRoundRobinPolicy
        cluster = Cluster(
            CASSANDRA_HOSTS,
            port=CASSANDRA_PORT,
            load_balancing_policy=DCAwareRoundRobinPolicy(local_dc="datacenter1"),
            connect_timeout=5,
        )
        _session = cluster.connect()
        _session.set_keyspace(CASSANDRA_KEYSPACE)
        _last_error = None
        return _session
    except ImportError:
        logger.info("cassandra-driver not installed — using docker cqlsh fallback")
        _use_cqlsh = True
        return None
    except Exception as exc:
        _last_error = str(exc)
        logger.warning("Cassandra driver unavailable: %s — trying cqlsh fallback", exc)
        _use_cqlsh = True
        return None


def _cqlsh_query(cql: str) -> list[list[str]]:
    """Run CQL via docker exec when native driver is unavailable."""
    try:
        proc = subprocess.run(
            ["docker", "exec", "ioth-cassandra", "cqlsh", "-e", cql],
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
        rows = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("---") or line.startswith("("):
                continue
            if "|" in line:
                rows.append([c.strip() for c in line.split("|")])
            elif line.isdigit():
                rows.append([line])
        return rows
    except Exception as exc:
        global _last_error
        _last_error = str(exc)
        return []


def _row_to_snapshot(row) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    ts = row.captured_at
    if isinstance(ts, datetime):
        ts = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "id":             0,
        "cameraId":       row.camera_id,
        "cameraName":     row.camera_name or row.camera_id,
        "location":       row.location or "",
        "city":           row.city or "",
        "capturedAt":     ts,
        "totalVehicles":  row.total_vehicles,
        "cars":           row.cars,
        "trucks":         row.trucks,
        "buses":          row.buses,
        "motorcycles":    row.motorcycles,
        "density":        row.density,
        "fps":            row.fps or 0.0,
        "latitude":       row.latitude or 0.0,
        "longitude":      row.longitude or 0.0,
        "source":         row.source or "spark",
    }


def _snapshot_from_cqlsh_row(cols: list[str]) -> dict[str, Any]:
    # camera_id | captured_at | camera_name | ... (variable columns)
    return {
        "id": 0,
        "cameraId": cols[0],
        "cameraName": cols[2] if len(cols) > 2 else cols[0],
        "location": cols[3] if len(cols) > 3 else "",
        "city": cols[4] if len(cols) > 4 else "",
        "capturedAt": cols[1] if len(cols) > 1 else "",
        "totalVehicles": int(cols[5]) if len(cols) > 5 else 0,
        "cars": int(cols[6]) if len(cols) > 6 else 0,
        "trucks": int(cols[7]) if len(cols) > 7 else 0,
        "buses": int(cols[8]) if len(cols) > 8 else 0,
        "motorcycles": int(cols[9]) if len(cols) > 9 else 0,
        "density": cols[10] if len(cols) > 10 else "Low",
        "fps": float(cols[11]) if len(cols) > 11 else 0.0,
        "latitude": float(cols[12]) if len(cols) > 12 else 0.0,
        "longitude": float(cols[13]) if len(cols) > 13 else 0.0,
        "source": cols[14] if len(cols) > 14 else "kafka",
    }


def get_latest_snapshots() -> list[dict[str, Any]]:
    session = _get_session()
    if session is None and _use_cqlsh:
        results = []
        for cam in CAMERAS:
            rows = _cqlsh_query(
                f"SELECT camera_id, captured_at, camera_name, location, city, "
                f"total_vehicles, cars, trucks, buses, motorcycles, density, fps, "
                f"latitude, longitude, source FROM {CASSANDRA_KEYSPACE}.sensor_snapshots "
                f"WHERE camera_id = '{cam.id}' LIMIT 1;"
            )
            data_rows = [row for row in rows if row and row[0] != "camera_id"]
            if data_rows:
                results.append(_snapshot_from_cqlsh_row(data_rows[0]))
        return results

    if session is None:
        return []

    try:
        results = []
        for cam in CAMERAS:
            row = session.execute(
                """
                SELECT camera_id, captured_at, camera_name, location, city,
                       total_vehicles, cars, trucks, buses, motorcycles,
                       density, fps, latitude, longitude, source
                FROM sensor_snapshots
                WHERE camera_id = %s
                LIMIT 1
                """,
                (cam.id,),
            ).one_or_none()
            if row:
                results.append(_row_to_snapshot(row))
        return results
    except Exception as exc:
        global _last_error
        _last_error = str(exc)
        logger.warning("Cassandra read failed: %s", exc)
        return []


def get_aggregates(limit: int = 20) -> list[dict[str, Any]]:
    session = _get_session()
    if session is None and _use_cqlsh:
        rows = _cqlsh_query(
            f"SELECT camera_id, window_start, window_end, avg_vehicles, "
            f"max_vehicles, sample_count, dominant_density "
            f"FROM {CASSANDRA_KEYSPACE}.sensor_aggregates LIMIT {limit};"
        )
        return [
            {
                "cameraId": row[0],
                "windowStart": row[1],
                "windowEnd": row[2],
                "avgVehicles": float(row[3]),
                "maxVehicles": int(row[4]),
                "sampleCount": int(row[5]),
                "dominantDensity": row[6],
            }
            for row in rows
            if row and row[0] != "camera_id"
        ]

    if session is None:
        return []
    try:
        rows = session.execute(
            """
            SELECT camera_id, window_start, window_end, avg_vehicles,
                   max_vehicles, sample_count, dominant_density
            FROM sensor_aggregates
            LIMIT %s
            ALLOW FILTERING
            """,
            (limit,),
        )
        out = []
        for r in rows:
            ws = r.window_start.strftime("%Y-%m-%dT%H:%M:%SZ") if r.window_start else ""
            we = r.window_end.strftime("%Y-%m-%dT%H:%M:%SZ") if r.window_end else ""
            out.append({
                "cameraId":        r.camera_id,
                "windowStart":     ws,
                "windowEnd":       we,
                "avgVehicles":     r.avg_vehicles,
                "maxVehicles":     r.max_vehicles,
                "sampleCount":     r.sample_count,
                "dominantDensity": r.dominant_density,
            })
        return out
    except Exception as exc:
        global _last_error
        _last_error = str(exc)
        return []


def cassandra_status() -> dict[str, Any]:
    if _use_cqlsh or _session is None:
        _get_session()
    connected = _session is not None
    count = 0
    if _session is not None:
        try:
            count = _session.execute("SELECT COUNT(*) FROM sensor_snapshots").one().count
        except Exception:
            count = -1
    elif _use_cqlsh:
        rows = _cqlsh_query(f"SELECT COUNT(*) FROM {CASSANDRA_KEYSPACE}.sensor_snapshots;")
        try:
            data_rows = [row for row in rows if row and row[0] != "count"]
            count = int(data_rows[0][0]) if data_rows else 0
            connected = True
        except Exception:
            count = -1
    return {
        "hosts":     CASSANDRA_HOSTS,
        "keyspace":  CASSANDRA_KEYSPACE,
        "connected": connected,
        "row_count": count,
        "last_error": _last_error,
        "mode":      "cqlsh-fallback" if _use_cqlsh else "native-driver",
    }
