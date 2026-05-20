"""
YOLOv8 vehicle detector — singleton model wrapper.
Inference is intentionally single-threaded via a threading.Lock so that
multiple camera workers sharing one model never collide.
"""

import threading
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np
from ultralytics import YOLO

from config import VEHICLE_CLASSES, DETECTION_CONFIDENCE, DENSITY_THRESHOLDS, YOLO_MODEL


@dataclass
class DetectionResult:
    timestamp: str
    camera_id: str
    camera_name: str
    fps: float
    total_vehicles: int
    counts: dict[str, int] = field(default_factory=dict)
    density: str = "Low"
    frame_width: int = 0
    frame_height: int = 0


class VehicleDetector:
    """Thread-safe singleton. One YOLO model, serialised via _infer_lock."""

    _instance: Optional["VehicleDetector"] = None
    _creation_lock = threading.Lock()

    def __new__(cls) -> "VehicleDetector":
        with cls._creation_lock:
            if cls._instance is None:
                obj = super().__new__(cls)
                obj._initialized = False
                cls._instance = obj
        return cls._instance

    def initialize(self) -> None:
        if self._initialized:
            return
        print(f"[Detector] Loading {YOLO_MODEL} …")
        self.model = YOLO(YOLO_MODEL)
        self.conf = DETECTION_CONFIDENCE
        self._infer_lock = threading.Lock()
        self._initialized = True
        print("[Detector] Model ready.")

    def infer(self, frame: np.ndarray) -> list[dict]:
        """
        Run inference on `frame` (serialised — only one call at a time).
        Returns a list of dicts: {x1, y1, x2, y2, cls_id, label, conf}
        """
        with self._infer_lock:
            results = self.model(frame, conf=self.conf, verbose=False)

        boxes = []
        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                cls_id = int(box.cls[0])
                if cls_id not in VEHICLE_CLASSES:
                    continue
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                boxes.append({
                    "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                    "cls_id": cls_id,
                    "label": VEHICLE_CLASSES[cls_id],
                    "conf": float(box.conf[0]),
                })
        return boxes


# ── drawing helpers (used by camera_manager) ──────────────────────────────────

# BGR colours per COCO class
_COLORS: dict[int, tuple[int, int, int]] = {
    2: (0, 230, 80),    # car        — green
    3: (0, 180, 255),   # motorcycle — amber-blue
    5: (60, 120, 255),  # bus        — blue
    7: (190, 60, 255),  # truck      — violet
}


def class_color(cls_id: int) -> tuple[int, int, int]:
    return _COLORS.get(cls_id, (180, 180, 180))


def compute_density(total: int) -> str:
    if total <= DENSITY_THRESHOLDS["low"]:
        return "Low"
    if total <= DENSITY_THRESHOLDS["medium"]:
        return "Medium"
    return "High"


def draw_boxes(frame: np.ndarray, boxes: list[dict]) -> np.ndarray:
    """
    Draw tracked bounding boxes with track IDs onto `frame`.

    Actively detected vehicles (coasting=False):
      • Solid 2-px coloured rectangle
      • Corner accent ticks
      • Filled label pill: "#ID  label  conf%"

    Coasting vehicles (coasting=True — tracker predicting, YOLO missed):
      • Same box drawn at reduced opacity via addWeighted
      • Dashed-style thin border (drawn as a semi-transparent rectangle)
      • Label pill shows "#ID  label  ~" to indicate prediction
    """
    if not boxes:
        return frame

    # Separate active and coasting to draw coasting first (below active)
    active = [b for b in boxes if not b.get("coasting", False)]
    coasting = [b for b in boxes if b.get("coasting", False)]

    # ── draw coasting tracks first (under active ones) ────────────────────
    if coasting:
        overlay = frame.copy()
        for b in coasting:
            x1, y1, x2, y2 = b["x1"], b["y1"], b["x2"], b["y2"]
            cls_id = b["cls_id"]
            track_id = b.get("track_id", "?")
            color = class_color(cls_id)
            # Dimmed thin border
            cv2.rectangle(overlay, (x1, y1), (x2, y2), color, 1, cv2.LINE_AA)
            # Small label showing prediction state
            text = f"#{track_id}"
            font, scale, thick = cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1
            (tw, th), _ = cv2.getTextSize(text, font, scale, thick)
            pad = 3
            py1 = max(y1 - th - pad * 2, 0)
            py2 = py1 + th + pad * 2
            cv2.rectangle(overlay, (x1, py1), (x1 + tw + pad * 2, py2), color, -1)
            cv2.putText(
                overlay, text, (x1 + pad, py2 - pad),
                font, scale, (0, 0, 0), thick, cv2.LINE_AA,
            )
        # Blend coasting visuals at 50% opacity so they don't clutter
        cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)

    # ── draw active (confirmed) tracks on top ─────────────────────────────
    for b in active:
        x1, y1, x2, y2 = b["x1"], b["y1"], b["x2"], b["y2"]
        label, conf, cls_id = b["label"], b["conf"], b["cls_id"]
        track_id = b.get("track_id", "")
        color = class_color(cls_id)

        # Bounding box
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)

        # Corner accent ticks
        tick = min(12, (x2 - x1) // 5, (y2 - y1) // 5)
        cv2.line(frame, (x1, y1), (x1 + tick, y1), color, 3, cv2.LINE_AA)
        cv2.line(frame, (x1, y1), (x1, y1 + tick), color, 3, cv2.LINE_AA)
        cv2.line(frame, (x2, y2), (x2 - tick, y2), color, 3, cv2.LINE_AA)
        cv2.line(frame, (x2, y2), (x2, y2 - tick), color, 3, cv2.LINE_AA)

        # Label pill with track ID
        id_prefix = f"#{track_id}  " if track_id != "" else ""
        text = f"{id_prefix}{label}  {conf:.0%}"
        font, scale, thick = cv2.FONT_HERSHEY_SIMPLEX, 0.48, 1
        (tw, th), _ = cv2.getTextSize(text, font, scale, thick)
        pad = 4
        pill_x1 = x1
        pill_y1_ = max(y1 - th - pad * 2, 0)
        pill_x2 = x1 + tw + pad * 2
        pill_y2_ = pill_y1_ + th + pad * 2
        cv2.rectangle(frame, (pill_x1, pill_y1_), (pill_x2, pill_y2_), color, -1)
        cv2.putText(
            frame, text,
            (pill_x1 + pad, pill_y2_ - pad),
            font, scale, (0, 0, 0), thick, cv2.LINE_AA,
        )

    return frame


def draw_stats_overlay(
    frame: np.ndarray,
    counts: dict[str, int],
    total: int,
    density: str,
    fps: float,
) -> None:
    """Semi-transparent stats box top-left."""
    lines = [
        f"Vehicles: {total}",
        f"Cars:  {counts.get('car', 0)}",
        f"Trucks: {counts.get('truck', 0)}",
        f"Buses: {counts.get('bus', 0)}",
        f"Motos: {counts.get('motorcycle', 0)}",
        f"Density: {density}",
        f"FPS: {fps:.1f}",
    ]
    density_color = {"Low": (0, 230, 80), "Medium": (30, 165, 255), "High": (60, 60, 255)}
    lh, pad = 20, 7
    bw, bh = 150, lh * len(lines) + pad * 2

    overlay = frame.copy()
    cv2.rectangle(overlay, (5, 5), (5 + bw, 5 + bh), (8, 8, 8), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)
    cv2.rectangle(frame, (5, 5), (5 + bw, 5 + bh), (55, 55, 55), 1)

    for i, line in enumerate(lines):
        y = 5 + pad + (i + 1) * lh - 3
        c = density_color.get(density, (220, 220, 220)) if "Density" in line else (215, 215, 215)
        cv2.putText(frame, line, (11, y), cv2.FONT_HERSHEY_SIMPLEX, 0.46, c, 1, cv2.LINE_AA)
