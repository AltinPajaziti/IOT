"""
Camera configuration for Prishtina traffic monitoring.

HOW TO FIND REAL STREAM URLs:
  1. Open the camera page in Chrome (e.g. https://video.gjirafa.com/slow-tv-pejton)
  2. Open DevTools → Network tab → filter by "m3u8"
  3. Reload the page and start playback
  4. Copy the .m3u8 URL that appears in Network requests
  5. Paste it in the stream_url field below

  Alternatively, use yt-dlp to extract the URL:
    yt-dlp -g https://video.gjirafa.com/slow-tv-pejton

  The URL pattern is typically:
    https://cdn.vpplayer.tech/{projectId}/encode/{videoId}/hls/master_file.m3u8
  or for live streams:
    https://cdn.vpplayer.tech/{projectId}/live/{liveId}/index.m3u8
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CameraConfig:
    id: str
    name: str
    location: str
    city: str
    # ─── PASTE THE REAL .m3u8 OR STREAM URL HERE ───────────────────────────
    stream_url: Optional[str]
    # ───────────────────────────────────────────────────────────────────────
    gjirafa_page: str
    embed_url: Optional[str] = None  # Gjirafa embed iframe URL if available
    active: bool = True


CAMERAS: list[CameraConfig] = [
    CameraConfig(
        id="pejton",
        name="Pejton",
        location="Rr. Agim Ramadani, Pejton",
        city="Prishtinë",
        # Live HLS stream — auto-extracted via Playwright from Gjirafa
        # If this stops working, re-run: python extract_streams.py
        stream_url="https://gjirafa-video-live.gjirafa.net/gjvideo-slow/dsh-ipv-i07-bhk/index.m3u8",
        gjirafa_page="https://video.gjirafa.com/slow-tv-pejton",
    ),
    CameraConfig(
        id="pejton2",
        name="Pejton 2",
        location="Rr. Agim Ramadani, Pejton",
        city="Prishtinë",
        stream_url="https://gjirafa-video-live.gjirafa.net/gjvideo-slow/wpx-rhn-qjg-sz0/index.m3u8",
        gjirafa_page="https://video.gjirafa.com/slow-tv-pejton-2",
    ),
    CameraConfig(
        id="tokbashqe",
        name="Tokbashqe",
        location="Rr. Tokbashqe",
        city="Prishtinë",
        stream_url="https://gjirafa-video-live.gjirafa.net/gjvideo-slow/klg-iqz-39a-4dd/index.m3u8",
        gjirafa_page="https://video.gjirafa.com/slow-tv-tokbashqe",
    ),
]

# Map camera id → config for O(1) lookup
CAMERA_MAP: dict[str, CameraConfig] = {cam.id: cam for cam in CAMERAS}

# YOLO classes we care about (COCO dataset indices)
VEHICLE_CLASSES: dict[int, str] = {
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}

DENSITY_THRESHOLDS = {
    "low": 5,
    "medium": 15,
}

# Seconds between stats snapshots stored in memory per camera
STATS_INTERVAL_SECONDS = 2

# Max in-memory history entries per camera (last N snapshots)
MAX_HISTORY_ENTRIES = 150

# YOLO model to use — change to "yolo11n.pt" for YOLOv11 nano
YOLO_MODEL = "yolov8n.pt"

# Detection confidence threshold
DETECTION_CONFIDENCE = 0.4
