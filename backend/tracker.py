"""Time-aware IoU tracker with velocity and speed support."""

from __future__ import annotations

import numpy as np


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


def _anchor(box: dict) -> tuple[float, float]:
    """Bottom-center point is more stable for road speed than box center."""
    return ((box["x1"] + box["x2"]) / 2.0, float(box["y2"]))


def _shifted_box(box: dict, dx: float, dy: float) -> dict:
    b = dict(box)
    b["x1"] = int(round(b["x1"] + dx))
    b["x2"] = int(round(b["x2"] + dx))
    b["y1"] = int(round(b["y1"] + dy))
    b["y2"] = int(round(b["y2"] + dy))
    return b


class _Track:
    __slots__ = (
        "track_id",
        "box",
        "missed",
        "age",
        "coasting",
        "_vx_ps",
        "_vy_ps",
        "_prev_ax",
        "_prev_ay",
    )

    _VEL_ALPHA = 0.55
    _COAST_DECAY = 0.88

    def __init__(self, track_id: int, box: dict) -> None:
        self.track_id = track_id
        self.box = box
        self.missed = 0
        self.age = 1
        self.coasting = False
        self._vx_ps = 0.0
        self._vy_ps = 0.0
        self._prev_ax, self._prev_ay = _anchor(box)

    def predicted_box(self, dt: float) -> dict:
        return _shifted_box(self.box, self._vx_ps * dt, self._vy_ps * dt)

    def update(self, box: dict, dt: float) -> None:
        ax, ay = _anchor(box)
        dt = max(dt, 0.001)
        new_vx = (ax - self._prev_ax) / dt
        new_vy = (ay - self._prev_ay) / dt
        alpha = self._VEL_ALPHA if self.age > 1 else 1.0
        self._vx_ps = alpha * new_vx + (1.0 - alpha) * self._vx_ps
        self._vy_ps = alpha * new_vy + (1.0 - alpha) * self._vy_ps
        self._prev_ax = ax
        self._prev_ay = ay
        self.box = box
        self.missed = 0
        self.age += 1
        self.coasting = False

    def coast(self, dt: float) -> None:
        self.box = self.predicted_box(dt)
        self._prev_ax += self._vx_ps * dt
        self._prev_ay += self._vy_ps * dt
        self._vx_ps *= self._COAST_DECAY
        self._vy_ps *= self._COAST_DECAY
        self.missed += 1
        self.coasting = True


class VehicleTracker:
    MAX_MISSED = 2
    MIN_IOU = 0.10

    def __init__(self) -> None:
        self._tracks: list[_Track] = []
        self._next_id = 1

    def update(self, detections: list[dict], dt: float = 0.12) -> list[dict]:
        dt = max(dt, 0.001)

        matched_track_ids: set[int] = set()
        matched_det_indices: set[int] = set()

        if self._tracks and detections:
            n_t = len(self._tracks)
            n_d = len(detections)
            iou_mat = np.zeros((n_t, n_d), dtype=np.float32)

            predicted = [track.predicted_box(dt) for track in self._tracks]
            for ti, pred in enumerate(predicted):
                tb = (pred["x1"], pred["y1"], pred["x2"], pred["y2"])
                for di, det in enumerate(detections):
                    db = (det["x1"], det["y1"], det["x2"], det["y2"])
                    iou_mat[ti, di] = _iou(tb, db)

            for flat_idx in np.argsort(-iou_mat.ravel()):
                ti = int(flat_idx // n_d)
                di = int(flat_idx % n_d)
                if float(iou_mat[ti, di]) < self.MIN_IOU:
                    break
                track_id = self._tracks[ti].track_id
                if track_id in matched_track_ids or di in matched_det_indices:
                    continue
                self._tracks[ti].update(detections[di], dt)
                matched_track_ids.add(track_id)
                matched_det_indices.add(di)

        for track in self._tracks:
            if track.track_id not in matched_track_ids:
                track.coast(dt)

        for di, det in enumerate(detections):
            if di not in matched_det_indices:
                self._tracks.append(_Track(self._next_id, det))
                self._next_id += 1

        self._tracks = [track for track in self._tracks if track.missed <= self.MAX_MISSED]

        result: list[dict] = []
        for track in self._tracks:
            box = dict(track.box)
            box["track_id"] = track.track_id
            box["coasting"] = track.coasting
            box["age"] = track.age
            box["vx"] = track._vx_ps
            box["vy"] = track._vy_ps
            result.append(box)
        return result

    def reset(self) -> None:
        self._tracks = []
        self._next_id = 1
