"""
Per-camera dual-thread architecture with multi-object tracking
──────────────────────────────────────────────────────────────
READER THREAD (per camera)
  • Reads every frame from the HLS stream at full speed
  • Draws the CACHED tracked boxes on every frame
  • Never blocks on inference → smooth, continuous video

YOLO THREAD (per camera)
  • Picks up the latest raw frame
  • Acquires the GLOBAL inference lock (so 3 cameras never call YOLO at once)
  • Passes detections through VehicleTracker to assign stable IDs
  • Updates the tracked box cache for the reader to use
  • Skips re-processing if no new frame has arrived since last run

Tracking benefits:
  • Each vehicle keeps a stable integer ID across frames
  • Coasting: if YOLO misses a vehicle for up to MAX_MISSED cycles the tracker
    keeps the last known box visible, eliminating flicker
  • Only truly disappeared vehicles are eventually removed
"""

import threading
import time
from collections import deque
from dataclasses import asdict
from typing import Optional

import cv2
import numpy as np

from config import (
    CameraConfig,
    STATS_INTERVAL_SECONDS,
    MAX_HISTORY_ENTRIES,
    VEHICLE_CLASSES,
    YOLO_INFERENCE_INTERVAL_SECONDS,
    STREAM_BUFFER_SIZE,
    STREAM_OPEN_TIMEOUT_MS,
    STREAM_READ_TIMEOUT_MS,
    STREAM_RECONNECT_DELAY_SECONDS,
    JPEG_QUALITY,
    DEFAULT_METERS_PER_PIXEL,
    CAMERA_METERS_PER_PIXEL,
    CAMERA_PERSPECTIVE_METERS_PER_PIXEL,
    CAMERA_DIRECTION_AXES,
    CAMERA_LANE_SPLITS,
    STOPPED_VEHICLE_ALERT_THRESHOLD,
    STOPPED_VEHICLE_HIGH_TRAFFIC_THRESHOLD,
    STOPPED_VEHICLE_CONFIRM_FRAMES,
    STOPPED_VEHICLE_SPEED_PX_THRESHOLD,
)
from detector import (
    VehicleDetector, DetectionResult,
    draw_boxes, draw_stats_overlay, compute_density,
)
from tracker import VehicleTracker

# Global lock — ensures only ONE camera runs YOLO at any moment
_GLOBAL_INFER_LOCK = threading.Lock()


class CameraWorker:
    def __init__(self, config: CameraConfig, detector: VehicleDetector) -> None:
        self.config = config
        self._det = detector
        self._tracker = VehicleTracker()

        self._stop_event = threading.Event()

        # ── raw frame shared between reader → yolo thread ────────────────
        self._raw_frame: Optional[np.ndarray] = None
        self._raw_frame_id: int = 0          # increments each time reader stores a frame
        self._raw_frame_time: float = 0.0
        self._raw_lock = threading.Lock()

        # ── cached tracked boxes shared between yolo → reader thread ─────
        # These are the tracker's output (include coasting tracks), so boxes
        # persist on screen even when YOLO temporarily misses a vehicle.
        self._boxes: list[dict] = []
        self._counts: dict[str, int] = {v: 0 for v in VEHICLE_CLASSES.values()}
        self._total: int = 0
        self._density: str = "Low"
        self._avg_speed_kmh: float = 0.0
        self._max_speed_kmh: float = 0.0
        self._direction_counts: dict[str, int] = {}
        self._lane_counts: dict[str, int] = {}
        self._densest_lane: str = ""
        self._stopped_vehicles: int = 0
        self._alarm_message: str = ""
        self._boxes_updated_at: float = 0.0
        self._stopped_hits: dict[int, int] = {}
        self._boxes_lock = threading.Lock()

        # ── output ────────────────────────────────────────────────────────
        self._out_lock = threading.Lock()
        self._latest_jpeg: Optional[bytes] = None
        self._latest_stats: Optional[DetectionResult] = None
        self._history: deque[dict] = deque(maxlen=MAX_HISTORY_ENTRIES)

        self.running = False
        self.error: Optional[str] = None

    # ── public API ────────────────────────────────────────────────────────

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        threading.Thread(
            target=self._reader_loop, daemon=True, name=f"reader-{self.config.id}"
        ).start()
        threading.Thread(
            target=self._yolo_loop, daemon=True, name=f"yolo-{self.config.id}"
        ).start()

    def stop(self) -> None:
        self._stop_event.set()
        self.running = False
        self._tracker.reset()

    def get_latest_frame(self) -> Optional[bytes]:
        with self._out_lock:
            return self._latest_jpeg

    def get_latest_stats(self) -> Optional[dict]:
        with self._out_lock:
            return asdict(self._latest_stats) if self._latest_stats else None

    def get_history(self) -> list[dict]:
        with self._out_lock:
            return list(self._history)

    # ── READER THREAD ─────────────────────────────────────────────────────

    def _reader_loop(self) -> None:
        self.running = True
        self.error = None
        url = self.config.stream_url

        if not url:
            self.error = "No stream URL configured."
            self.running = False
            return

        print(f"[{self.config.id}] Opening: {url}")
        cap = _open_capture(url)
        if not cap.isOpened():
            self.error = f"Cannot open stream: {url}"
            self.running = False
            return

        print(f"[{self.config.id}] Stream open.")
        fps_ctr = _FPSCounter()
        last_stats_t = 0.0
        last_raw_t = 0.0
        reconnects = 0

        while not self._stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                reconnects += 1
                self.error = f"Stream reconnecting ({reconnects})"
                time.sleep(STREAM_RECONNECT_DELAY_SECONDS)
                cap.release()
                cap = _open_capture(url)
                continue
            if reconnects:
                print(f"[{self.config.id}] Stream recovered after {reconnects} reconnect(s).")
                reconnects = 0
                self.error = None

            fps_ctr.tick()
            fps = fps_ctr.get()

            now = time.monotonic()

            # Share only sampled frames with YOLO; the video stream still stays smooth.
            if now - last_raw_t >= YOLO_INFERENCE_INTERVAL_SECONDS:
                last_raw_t = now
                with self._raw_lock:
                    self._raw_frame = frame.copy()
                    self._raw_frame_id += 1
                    self._raw_frame_time = now

            # ── Draw latest cached boxes on this frame (never blank) ──────
            annotated = frame.copy()
            with self._boxes_lock:
                boxes   = list(self._boxes)
                counts  = dict(self._counts)
                total   = self._total
                density = self._density
                avg_speed_kmh = self._avg_speed_kmh
                max_speed_kmh = self._max_speed_kmh
                direction_counts = dict(self._direction_counts)
                lane_counts = dict(self._lane_counts)
                densest_lane = self._densest_lane
                stopped_vehicles = self._stopped_vehicles
                alarm_message = self._alarm_message
                boxes_updated_at = self._boxes_updated_at

            boxes = _project_boxes(
                boxes,
                elapsed=max(0.0, now - boxes_updated_at),
                frame_width=frame.shape[1],
                frame_height=frame.shape[0],
            )

            draw_boxes(annotated, boxes)
            draw_stats_overlay(
                annotated,
                counts,
                total,
                density,
                fps,
                avg_speed_kmh,
                max_speed_kmh,
                direction_counts,
                lane_counts,
                densest_lane,
                stopped_vehicles,
                alarm_message,
            )

            jpeg = _encode_jpeg(annotated)

            # ── Update output ─────────────────────────────────────────────
            with self._out_lock:
                self._latest_jpeg = jpeg
                if now - last_stats_t >= STATS_INTERVAL_SECONDS:
                    last_stats_t = now
                    stats = DetectionResult(
                        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        camera_id=self.config.id,
                        camera_name=self.config.name,
                        fps=round(fps, 1),
                        total_vehicles=total,
                        counts=counts,
                        density=density,
                        frame_width=frame.shape[1],
                        frame_height=frame.shape[0],
                        avg_speed_kmh=round(avg_speed_kmh, 1),
                        max_speed_kmh=round(max_speed_kmh, 1),
                        direction_counts=direction_counts,
                        lane_counts=lane_counts,
                        densest_lane=densest_lane,
                        stopped_vehicles=stopped_vehicles,
                        stopped_alarm=bool(alarm_message),
                        alarm_message=alarm_message,
                    )
                    self._latest_stats = stats
                    hist = asdict(stats)
                    hist["location"] = self.config.location
                    hist["city"] = self.config.city
                    self._history.append(hist)
                    try:
                        from kafka_producer import build_event_from_detection, publish_event
                        publish_event(build_event_from_detection(hist, source="yolo"))
                    except Exception:
                        pass

        cap.release()
        self.running = False
        print(f"[{self.config.id}] Reader stopped.")

    # ── YOLO THREAD ───────────────────────────────────────────────────────

    def _yolo_loop(self) -> None:
        last_processed_id = -1
        last_infer_t = 0.0
        last_source_frame_t = 0.0

        while not self._stop_event.is_set():
            # Wait for a new frame from the reader
            with self._raw_lock:
                frame_id = self._raw_frame_id
                frame    = self._raw_frame
                frame_t  = self._raw_frame_time

            if frame is None or frame_id == last_processed_id:
                time.sleep(0.015)
                continue

            now = time.monotonic()
            wait_for = YOLO_INFERENCE_INTERVAL_SECONDS - (now - last_infer_t)
            if wait_for > 0:
                time.sleep(min(wait_for, 0.03))
                continue

            last_processed_id = frame_id
            sample_interval = max(frame_t - last_source_frame_t, YOLO_INFERENCE_INTERVAL_SECONDS)
            last_source_frame_t = frame_t
            last_infer_t = time.monotonic()

            # ── Serialised inference: one camera at a time globally ───────
            with _GLOBAL_INFER_LOCK:
                try:
                    with self._raw_lock:
                        fresh_id = self._raw_frame_id
                        fresh_frame = self._raw_frame
                        fresh_t = self._raw_frame_time
                    if fresh_frame is not None and fresh_id != frame_id:
                        frame_id = fresh_id
                        frame = fresh_frame
                        frame_t = fresh_t
                        sample_interval = max(frame_t - last_source_frame_t, YOLO_INFERENCE_INTERVAL_SECONDS)
                        last_source_frame_t = frame_t
                        last_processed_id = frame_id
                    raw_boxes = self._det.infer(frame)
                except Exception as exc:
                    print(f"[{self.config.id}] YOLO error: {exc}")
                    raw_boxes = []

            # ── Multi-object tracking ─────────────────────────────────────
            # Even when raw_boxes is empty the tracker returns coasting
            # tracks so vehicles keep their bounding boxes visible.
            tracked_boxes = self._tracker.update(raw_boxes, sample_interval)
            tracked_boxes = _add_speed_estimates(
                tracked_boxes,
                camera_id=self.config.id,
                sample_interval=sample_interval,
            )
            tracked_boxes = _add_direction_estimates(
                tracked_boxes,
                camera_id=self.config.id,
            )
            tracked_boxes = self._confirm_stopped_tracks(tracked_boxes)
            tracked_boxes = _add_lane_estimates(
                tracked_boxes,
                camera_id=self.config.id,
                frame_width=frame.shape[1],
            )

            # ── Count only non-coasting (actively detected) tracks ────────
            counts: dict[str, int] = {v: 0 for v in VEHICLE_CLASSES.values()}
            for b in tracked_boxes:
                if not b.get("coasting", False):
                    counts[b["label"]] += 1
            total   = sum(counts.values())
            density = compute_density(total)
            speeds = [
                float(b.get("speed_kmh", 0.0))
                for b in tracked_boxes
                if not b.get("coasting", False) and b.get("speed_kmh", 0.0) > 1
            ]
            avg_speed_kmh = sum(speeds) / len(speeds) if speeds else 0.0
            max_speed_kmh = max(speeds) if speeds else 0.0
            direction_counts: dict[str, int] = {}
            for b in tracked_boxes:
                if b.get("coasting", False):
                    continue
                direction = b.get("direction")
                if direction:
                    direction_counts[direction] = direction_counts.get(direction, 0) + 1
            lane_counts: dict[str, int] = {}
            for b in tracked_boxes:
                if b.get("coasting", False):
                    continue
                lane = b.get("lane")
                if lane:
                    lane_counts[lane] = lane_counts.get(lane, 0) + 1
            densest_lane = ""
            if lane_counts:
                densest_lane = max(lane_counts.items(), key=lambda item: item[1])[0]
            stopped_vehicles = sum(
                1
                for b in tracked_boxes
                if not b.get("coasting", False)
                and b.get("direction") == "Ndalur"
            )
            if stopped_vehicles > STOPPED_VEHICLE_HIGH_TRAFFIC_THRESHOLD:
                density = "High"
            alarm_message = ""
            if stopped_vehicles > STOPPED_VEHICLE_ALERT_THRESHOLD:
                alarm_message = f"{stopped_vehicles} mjete te ndalura"

            # ── Publish to reader thread ──────────────────────────────────
            with self._boxes_lock:
                self._boxes   = tracked_boxes
                self._counts  = counts
                self._total   = total
                self._density = density
                self._avg_speed_kmh = avg_speed_kmh
                self._max_speed_kmh = max_speed_kmh
                self._direction_counts = direction_counts
                self._lane_counts = lane_counts
                self._densest_lane = densest_lane
                self._stopped_vehicles = stopped_vehicles
                self._alarm_message = alarm_message
                self._boxes_updated_at = frame_t

    def _confirm_stopped_tracks(self, boxes: list[dict]) -> list[dict]:
        active_ids: set[int] = set()
        enriched: list[dict] = []

        for box in boxes:
            b = dict(box)
            track_id = int(b.get("track_id", -1))
            if track_id < 0 or b.get("coasting", False):
                enriched.append(b)
                continue

            active_ids.add(track_id)
            vx = float(b.get("vx", 0.0))
            vy = float(b.get("vy", 0.0))
            speed_px_s = float(np.hypot(vx, vy))
            is_slow = (
                int(b.get("age", 0)) >= STOPPED_VEHICLE_CONFIRM_FRAMES
                and speed_px_s <= STOPPED_VEHICLE_SPEED_PX_THRESHOLD
            )

            if is_slow:
                self._stopped_hits[track_id] = self._stopped_hits.get(track_id, 0) + 1
            else:
                self._stopped_hits[track_id] = 0

            if self._stopped_hits.get(track_id, 0) >= STOPPED_VEHICLE_CONFIRM_FRAMES:
                b["direction"] = "Ndalur"
                b["direction_confidence"] = 1.0
            elif b.get("direction") == "Ndalur":
                b["direction"] = ""
                b["direction_confidence"] = 0.0

            enriched.append(b)

        for old_id in list(self._stopped_hits):
            if old_id not in active_ids:
                self._stopped_hits.pop(old_id, None)

        return enriched


# ── Camera manager ────────────────────────────────────────────────────────────

class CameraManager:
    def __init__(self) -> None:
        self._detector = VehicleDetector()
        self._detector.initialize()
        self._workers: dict[str, CameraWorker] = {}

    def start_camera(self, config: CameraConfig) -> CameraWorker:
        cam_id = config.id
        if cam_id in self._workers and self._workers[cam_id].running:
            return self._workers[cam_id]
        worker = CameraWorker(config, self._detector)
        self._workers[cam_id] = worker
        worker.start()
        return worker

    def stop_camera(self, cam_id: str) -> None:
        if cam_id in self._workers:
            self._workers[cam_id].stop()

    def get_worker(self, cam_id: str) -> Optional[CameraWorker]:
        return self._workers.get(cam_id)

    def get_all_workers(self) -> list[CameraWorker]:
        return list(self._workers.values())

    def stop_all(self) -> None:
        for w in self._workers.values():
            w.stop()


# ── helpers ───────────────────────────────────────────────────────────────────

class _FPSCounter:
    def __init__(self, window: int = 30) -> None:
        self._t: deque[float] = deque(maxlen=window)

    def tick(self) -> None:
        self._t.append(time.monotonic())

    def get(self) -> float:
        if len(self._t) < 2:
            return 0.0
        elapsed = self._t[-1] - self._t[0]
        return 0.0 if elapsed <= 0 else (len(self._t) - 1) / elapsed


def _encode_jpeg(frame: np.ndarray, quality: int = JPEG_QUALITY) -> bytes:
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return bytes(buf)


def _open_capture(url: str) -> cv2.VideoCapture:
    """Open HLS/file streams with small buffers and short FFmpeg timeouts."""
    params: list[int] = [cv2.CAP_PROP_BUFFERSIZE, STREAM_BUFFER_SIZE]
    if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
        params.extend([cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, STREAM_OPEN_TIMEOUT_MS])
    if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
        params.extend([cv2.CAP_PROP_READ_TIMEOUT_MSEC, STREAM_READ_TIMEOUT_MS])

    try:
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG, params)
    except Exception:
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        cap.release()
        cap = cv2.VideoCapture(url)

    cap.set(cv2.CAP_PROP_BUFFERSIZE, STREAM_BUFFER_SIZE)
    if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, STREAM_OPEN_TIMEOUT_MS)
    if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, STREAM_READ_TIMEOUT_MS)
    return cap


def _project_boxes(
    boxes: list[dict],
    *,
    elapsed: float,
    frame_width: int,
    frame_height: int,
) -> list[dict]:
    """Move boxes forward between YOLO cycles so overlays follow moving vehicles."""
    if not boxes or elapsed <= 0:
        return boxes

    projection_time = min(elapsed, 0.55)
    projected: list[dict] = []
    for box in boxes:
        vx = float(box.get("vx", 0.0))
        vy = float(box.get("vy", 0.0))
        dx = int(round(vx * projection_time))
        dy = int(round(vy * projection_time))
        if dx == 0 and dy == 0:
            projected.append(box)
            continue

        b = dict(box)
        width = max(1, b["x2"] - b["x1"])
        height = max(1, b["y2"] - b["y1"])
        x1 = min(max(0, b["x1"] + dx), max(0, frame_width - width))
        y1 = min(max(0, b["y1"] + dy), max(0, frame_height - height))
        b["x1"] = x1
        b["y1"] = y1
        b["x2"] = min(frame_width - 1, x1 + width)
        b["y2"] = min(frame_height - 1, y1 + height)
        projected.append(b)
    return projected


def _add_speed_estimates(
    boxes: list[dict],
    *,
    camera_id: str,
    sample_interval: float,
) -> list[dict]:
    if not boxes:
        return boxes

    enriched: list[dict] = []
    for box in boxes:
        b = dict(box)
        vx = float(b.get("vx", 0.0))
        vy = float(b.get("vy", 0.0))
        if int(b.get("age", 0)) < 2:
            b["speed_kmh"] = 0.0
            b["speed_estimate"] = False
            enriched.append(b)
            continue
        meters_per_pixel = _meters_per_pixel(camera_id, b)
        pixels_per_second = float(np.hypot(vx, vy))
        kmh = pixels_per_second * meters_per_pixel * 3.6
        b["speed_kmh"] = min(max(kmh, 0.0), 160.0)
        b["speed_estimate"] = True
        enriched.append(b)
    return enriched


def _add_direction_estimates(
    boxes: list[dict],
    *,
    camera_id: str,
) -> list[dict]:
    if not boxes:
        return boxes

    cfg = CAMERA_DIRECTION_AXES.get(camera_id, {
        "axis": (1.0, 0.0),
        "positive_label": "Djathtas",
        "negative_label": "Majtas",
    })
    axis_x, axis_y = cfg["axis"]
    norm = max(float(np.hypot(axis_x, axis_y)), 0.001)
    axis_x = axis_x / norm
    axis_y = axis_y / norm

    enriched: list[dict] = []
    for box in boxes:
        b = dict(box)
        vx = float(b.get("vx", 0.0))
        vy = float(b.get("vy", 0.0))
        speed_px_s = float(np.hypot(vx, vy))
        projection = vx * axis_x + vy * axis_y

        if int(b.get("age", 0)) < 2 or speed_px_s < STOPPED_VEHICLE_SPEED_PX_THRESHOLD:
            b["direction"] = ""
            b["direction_confidence"] = 0.0
        elif projection >= 0:
            b["direction"] = cfg["positive_label"]
            b["direction_confidence"] = min(abs(projection) / speed_px_s, 1.0)
        else:
            b["direction"] = cfg["negative_label"]
            b["direction_confidence"] = min(abs(projection) / speed_px_s, 1.0)
        enriched.append(b)
    return enriched


def _add_lane_estimates(
    boxes: list[dict],
    *,
    camera_id: str,
    frame_width: int,
) -> list[dict]:
    if not boxes:
        return boxes

    cfg = CAMERA_LANE_SPLITS.get(camera_id, {
        "split_x_ratio": 0.50,
        "left_label": "Korsia Majtas",
        "right_label": "Korsia Djathtas",
    })
    split_x = float(cfg["split_x_ratio"]) * max(frame_width, 1)

    enriched: list[dict] = []
    for box in boxes:
        b = dict(box)
        anchor_x = (float(b["x1"]) + float(b["x2"])) / 2.0
        if anchor_x < split_x:
            b["lane"] = cfg["left_label"]
        else:
            b["lane"] = cfg["right_label"]
        enriched.append(b)
    return enriched


def _meters_per_pixel(camera_id: str, box: dict) -> float:
    perspective = CAMERA_PERSPECTIVE_METERS_PER_PIXEL.get(camera_id)
    if not perspective:
        return CAMERA_METERS_PER_PIXEL.get(camera_id, DEFAULT_METERS_PER_PIXEL)

    y2 = float(box.get("y2", 0.0))
    # Use 432p as the common HLS display height baseline; clamp keeps it stable.
    y_norm = min(max(y2 / 432.0, 0.0), 1.0)
    near = float(perspective["near"])
    far = float(perspective["far"])
    return far + (near - far) * y_norm
