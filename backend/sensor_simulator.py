"""Sensor simulator — generates traffic sensor data when no physical sensors are available."""
from __future__ import annotations

import logging
import random
import threading
import time

from config import CAMERAS
from iot_config import SIMULATOR_INTERVAL_S
from detector import compute_density
from kafka_producer import build_event, publish_event

logger = logging.getLogger("sensor_simulator")

_stop = threading.Event()
_thread: threading.Thread | None = None
_ticks = 0


def _simulate_once() -> int:
    sent = 0
    for cam in CAMERAS:
        if not cam.active:
            continue
        # Realistic random traffic: mostly low, occasionally medium
        total = random.randint(1, 18)
        cars  = max(0, total - random.randint(0, 2))
        trucks = random.randint(0, max(1, total // 8))
        buses  = random.randint(0, max(1, total // 10))
        motos  = max(0, total - cars - trucks - buses)
        density = compute_density(total)
        event = build_event(
            camera_id=cam.id,
            camera_name=cam.name,
            location=cam.location,
            city=cam.city,
            total_vehicles=total,
            cars=cars,
            trucks=trucks,
            buses=buses,
            motorcycles=motos,
            density=density,
            fps=round(random.uniform(18, 26), 1),
            source="simulator",
        )
        if publish_event(event):
            sent += 1
    return sent


def _loop() -> None:
    global _ticks
    logger.info("Sensor simulator started (interval=%ss)", SIMULATOR_INTERVAL_S)
    while not _stop.is_set():
        _ticks += 1
        sent = _simulate_once()
        logger.debug("Simulator tick #%d — published %d events", _ticks, sent)
        _stop.wait(SIMULATOR_INTERVAL_S)


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="sensor-simulator")
    _thread.start()


def stop() -> None:
    _stop.set()


def simulate_congestion(cars: int = 200) -> dict:
    """Publish high-traffic events for all cameras (demo / alarm test)."""
    from kafka_producer import build_event, publish_event
    trucks = max(1, cars // 40)
    buses  = max(1, cars // 50)
    motos  = max(1, cars // 25)
    total  = cars + trucks + buses + motos
    published = []
    for cam in CAMERAS:
        event = build_event(
            camera_id=cam.id,
            camera_name=cam.name,
            location=cam.location,
            city=cam.city,
            total_vehicles=total,
            cars=cars,
            trucks=trucks,
            buses=buses,
            motorcycles=motos,
            density="High",
            fps=24.0,
            source="simulator-congestion",
        )
        if publish_event(event):
            published.append(cam.id)
    return {
        "message": f"Published congestion ({cars} cars) for {len(published)} camera(s) to Kafka",
        "cameras": published,
        "total_vehicles": total,
    }


def status() -> dict:
    return {
        "running": _thread.is_alive() if _thread else False,
        "ticks":   _ticks,
        "interval_seconds": SIMULATOR_INTERVAL_S,
    }
