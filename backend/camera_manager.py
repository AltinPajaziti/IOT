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

from config import CameraConfig, STATS_INTERVAL_SECONDS, MAX_HISTORY_ENTRIES, VEHICLE_CLASSES
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
        self._raw_lock = threading.Lock()

        # ── cached tracked boxes shared between yolo → reader thread ─────
        # These are the tracker's output (include coasting tracks), so boxes
        # persist on screen even when YOLO temporarily misses a vehicle.
        self._boxes: list[dict] = []
        self._counts: dict[str, int] = {v: 0 for v in VEHICLE_CLASSES.values()}
        self._total: int = 0
        self._density: str = "Low"
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
        cap = cv2.VideoCapture(url)
        if not cap.isOpened():
            self.error = f"Cannot open stream: {url}"
            self.running = False
            return

        print(f"[{self.config.id}] Stream open.")
        fps_ctr = _FPSCounter()
        last_stats_t = 0.0

        while not self._stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                time.sleep(1)
                cap.release()
                cap = cv2.VideoCapture(url)
                continue

            fps_ctr.tick()
            fps = fps_ctr.get()

            # Share the latest raw frame with the YOLO thread
            with self._raw_lock:
                self._raw_frame = frame.copy()
                self._raw_frame_id += 1

            # ── Draw latest cached boxes on this frame (never blank) ──────
            annotated = frame.copy()
            with self._boxes_lock:
                boxes   = list(self._boxes)
                counts  = dict(self._counts)
                total   = self._total
                density = self._density

            draw_boxes(annotated, boxes)
            draw_stats_overlay(annotated, counts, total, density, fps)

            jpeg = _encode_jpeg(annotated)

            # ── Update output ─────────────────────────────────────────────
            now = time.monotonic()
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
                    )
                    self._latest_stats = stats
                    self._history.append(asdict(stats))

        cap.release()
        self.running = False
        print(f"[{self.config.id}] Reader stopped.")

    # ── YOLO THREAD ───────────────────────────────────────────────────────

    def _yolo_loop(self) -> None:
        last_processed_id = -1

        while not self._stop_event.is_set():
            # Wait for a new frame from the reader
            with self._raw_lock:
                frame_id = self._raw_frame_id
                frame    = self._raw_frame

            if frame is None or frame_id == last_processed_id:
                time.sleep(0.015)
                continue

            last_processed_id = frame_id

            # ── Serialised inference: one camera at a time globally ───────
            with _GLOBAL_INFER_LOCK:
                try:
                    raw_boxes = self._det.infer(frame)
                except Exception as exc:
                    print(f"[{self.config.id}] YOLO error: {exc}")
                    raw_boxes = []

            # ── Multi-object tracking ─────────────────────────────────────
            # Even when raw_boxes is empty the tracker returns coasting
            # tracks so vehicles keep their bounding boxes visible.
            tracked_boxes = self._tracker.update(raw_boxes)

            # ── Count only non-coasting (actively detected) tracks ────────
            counts: dict[str, int] = {v: 0 for v in VEHICLE_CLASSES.values()}
            for b in tracked_boxes:
                if not b.get("coasting", False):
                    counts[b["label"]] += 1
            total   = sum(counts.values())
            density = compute_density(total)

            # ── Publish to reader thread ──────────────────────────────────
            with self._boxes_lock:
                self._boxes   = tracked_boxes
                self._counts  = counts
                self._total   = total
                self._density = density


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


def _encode_jpeg(frame: np.ndarray, quality: int = 82) -> bytes:
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return bytes(buf)
