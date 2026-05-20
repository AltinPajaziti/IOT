"""
IoU-based multi-object tracker with velocity prediction.
No extra dependencies — pure Python + NumPy (already required by YOLO).

How it works
────────────
Each YOLO inference cycle produces a raw list of detected boxes.
The tracker:
  1. Predicts each track's new position using its smoothed velocity vector.
  2. Matches new detections to predicted track positions by IoU.
  3. Updates matched tracks with the fresh box and resets their miss counter.
  4. Creates new tracks for detections that did not match anything.
  5. Removes tracks missing for more than MAX_MISSED consecutive cycles.
  6. Returns ALL live tracks — including coasting ones — so boxes remain
     visible between detections AND follow the vehicle's motion.

Velocity model
──────────────
Each track maintains (vx, vy) smoothed with an exponential moving average.
During coasting, `predict()` shifts the box by (vx, vy) each cycle so the
box moves with the car even when YOLO temporarily misses the detection.
Velocity decays by COAST_DECAY per missed frame to avoid runaway drift.
"""

from __future__ import annotations

import numpy as np


# ── IoU helper ────────────────────────────────────────────────────────────────

def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter == 0:
        return 0.0
    area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
    area_b = max(1, (bx2 - bx1) * (by2 - by1))
    return inter / (area_a + area_b - inter)


# ── Track ─────────────────────────────────────────────────────────────────────

class _Track:
    """Single tracked vehicle with a stable integer ID and velocity model."""

    __slots__ = ("track_id", "box", "missed", "age", "coasting",
                 "_vx", "_vy", "_prev_cx", "_prev_cy")

    # Velocity smoothing factor (0 = no update, 1 = instant update)
    _VEL_ALPHA: float = 0.45
    # Velocity decay per coasting frame (prevents runaway drift)
    _COAST_DECAY: float = 0.80

    def __init__(self, track_id: int, box: dict) -> None:
        self.track_id: int = track_id
        self.box: dict = box
        self.missed: int = 0
        self.age: int = 1
        self.coasting: bool = False
        self._vx: float = 0.0
        self._vy: float = 0.0
        self._prev_cx: float = (box["x1"] + box["x2"]) / 2.0
        self._prev_cy: float = (box["y1"] + box["y2"]) / 2.0

    def update(self, box: dict) -> None:
        cx = (box["x1"] + box["x2"]) / 2.0
        cy = (box["y1"] + box["y2"]) / 2.0
        # Update velocity via EMA
        new_vx = cx - self._prev_cx
        new_vy = cy - self._prev_cy
        a = self._VEL_ALPHA
        self._vx = a * new_vx + (1.0 - a) * self._vx
        self._vy = a * new_vy + (1.0 - a) * self._vy
        self._prev_cx = cx
        self._prev_cy = cy
        self.box = box
        self.missed = 0
        self.age += 1
        self.coasting = False

    def predict(self) -> None:
        """Shift the box by the smoothed velocity and decay speed."""
        dx = round(self._vx)
        dy = round(self._vy)
        b = self.box
        self.box = {
            "x1": b["x1"] + dx,
            "y1": b["y1"] + dy,
            "x2": b["x2"] + dx,
            "y2": b["y2"] + dy,
            "cls_id": b["cls_id"],
            "label":  b["label"],
            "conf":   b["conf"],
        }
        # Decay velocity so the box doesn't drift indefinitely
        self._vx *= self._COAST_DECAY
        self._vy *= self._COAST_DECAY
        self._prev_cx += dx
        self._prev_cy += dy
        self.missed += 1
        self.coasting = True


# ── Tracker ───────────────────────────────────────────────────────────────────

class VehicleTracker:
    """
    Per-camera IoU-based tracker with velocity-predicted coasting.
    Each CameraWorker creates its own instance so state is never shared.

    Usage::

        tracker = VehicleTracker()
        tracked_boxes = tracker.update(raw_yolo_boxes)  # call once per YOLO cycle

    Each dict in `tracked_boxes` is the original YOLO box dict extended with:
      • "track_id"  — stable integer, 1-based
      • "coasting"  — True when the box position is velocity-predicted
    """

    # Frames a track survives without a matching detection.
    # Low value = boxes vanish quickly when YOLO misses; keep at 3-5.
    MAX_MISSED: int = 4

    # Minimum IoU (against predicted position) to accept a match.
    MIN_IOU: float = 0.15

    def __init__(self) -> None:
        self._tracks: list[_Track] = []
        self._next_id: int = 1

    # ── public API ────────────────────────────────────────────────────────────

    def update(self, detections: list[dict]) -> list[dict]:
        """
        Feed raw YOLO detections; get back all live tracked boxes.
        Coasting boxes have already been shifted by the velocity model,
        so they follow the vehicle's last known trajectory.
        """
        # Predict new positions for all existing tracks
        for t in self._tracks:
            t.predict()

        matched_track_ids: set[int] = set()
        matched_det_indices: set[int] = set()

        if self._tracks and detections:
            n_t = len(self._tracks)
            n_d = len(detections)

            # IoU matrix between predicted track positions and new detections
            iou_mat = np.zeros((n_t, n_d), dtype=np.float32)
            for ti, track in enumerate(self._tracks):
                tb = (track.box["x1"], track.box["y1"],
                      track.box["x2"], track.box["y2"])
                for di, det in enumerate(detections):
                    db = (det["x1"], det["y1"], det["x2"], det["y2"])
                    iou_mat[ti, di] = _iou(tb, db)

            # Greedy matching — highest IoU pair first
            flat_order = np.argsort(-iou_mat.ravel())
            for flat_idx in flat_order:
                ti = int(flat_idx // n_d)
                di = int(flat_idx % n_d)
                if float(iou_mat[ti, di]) < self.MIN_IOU:
                    break
                t_id = self._tracks[ti].track_id
                if t_id in matched_track_ids or di in matched_det_indices:
                    continue
                self._tracks[ti].update(detections[di])
                matched_track_ids.add(t_id)
                matched_det_indices.add(di)

        # Spawn new tracks for unmatched detections
        for di, det in enumerate(detections):
            if di not in matched_det_indices:
                self._tracks.append(_Track(self._next_id, det))
                self._next_id += 1

        # Expire dead tracks
        self._tracks = [t for t in self._tracks if t.missed <= self.MAX_MISSED]

        # Return all live tracks with tracking metadata
        result: list[dict] = []
        for t in self._tracks:
            box = dict(t.box)
            box["track_id"] = t.track_id
            box["coasting"] = t.coasting
            result.append(box)
        return result

    def reset(self) -> None:
        self._tracks = []
        self._next_id = 1
