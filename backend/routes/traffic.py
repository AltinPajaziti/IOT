"""
Traffic monitoring API routes.

Endpoints:
  GET  /api/traffic/cameras              – List all configured cameras
  GET  /api/traffic/stats/{cameraId}     – Latest detection stats for a camera
  GET  /api/traffic/stream/{cameraId}    – MJPEG stream of annotated frames
  GET  /api/traffic/history/{cameraId}   – Recent stats history (rolling window)
  POST /api/traffic/start/{cameraId}     – Start/resume a camera worker
  POST /api/traffic/stop/{cameraId}      – Stop a camera worker
  POST /api/traffic/upload               – Upload a local video for offline detection
"""

import asyncio
import io
import time
from pathlib import Path
from typing import AsyncGenerator

import cv2
import aiofiles
import numpy as np
from fastapi import APIRouter, HTTPException, UploadFile, File, Request
from fastapi.responses import StreamingResponse, JSONResponse

from config import CAMERAS, CAMERA_MAP, CameraConfig
from camera_manager import CameraManager

router = APIRouter(prefix="/api/traffic", tags=["traffic"])

# Shared manager instance (injected by main.py via app.state)
def _mgr(request: Request) -> CameraManager:
    return request.app.state.camera_manager


# ── camera list ───────────────────────────────────────────────────────────────

@router.get("/cameras")
async def list_cameras(request: Request):
    mgr = _mgr(request)
    result = []
    for cam in CAMERAS:
        worker = mgr.get_worker(cam.id)
        result.append({
            "id": cam.id,
            "name": cam.name,
            "location": cam.location,
            "city": cam.city,
            "hasStreamUrl": cam.stream_url is not None,
            "gjirafaPage": cam.gjirafa_page,
            "embedUrl": cam.embed_url,
            "active": cam.active,
            "running": worker.running if worker else False,
            "error": worker.error if worker else None,
        })
    return result


# ── stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats/{camera_id}")
async def get_stats(camera_id: str, request: Request):
    cam = _get_camera_or_404(camera_id)
    mgr = _mgr(request)
    worker = mgr.get_worker(camera_id)

    if worker is None or not worker.running:
        # Auto-start if URL is configured
        if cam.stream_url:
            worker = mgr.start_camera(cam)
            # Give it a moment to open the stream
            await asyncio.sleep(1)
        else:
            return JSONResponse({
                "cameraId": camera_id,
                "status": "no_stream_url",
                "message": "No stream URL configured. Set stream_url in backend/config.py.",
            })

    stats = worker.get_latest_stats()
    if stats is None:
        return JSONResponse({"cameraId": camera_id, "status": "starting"})

    return stats


# ── MJPEG stream ──────────────────────────────────────────────────────────────

@router.get("/stream/{camera_id}")
async def stream_camera(camera_id: str, request: Request):
    """
    Returns a multipart/x-mixed-replace MJPEG stream.
    Angular uses this URL in an <img> tag:
      <img src="http://localhost:8000/api/traffic/stream/pejton">
    """
    cam = _get_camera_or_404(camera_id)
    mgr = _mgr(request)
    worker = mgr.get_worker(camera_id)

    if worker is None or not worker.running:
        if not cam.stream_url:
            raise HTTPException(status_code=503, detail="No stream URL configured.")
        worker = mgr.start_camera(cam)

    return StreamingResponse(
        _mjpeg_generator(worker),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache"},
    )


async def _mjpeg_generator(worker) -> AsyncGenerator[bytes, None]:
    while True:
        frame_bytes = worker.get_latest_frame()
        if frame_bytes:
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n"
                + frame_bytes
                + b"\r\n"
            )
        await asyncio.sleep(0.05)  # ~20 fps cap for the HTTP stream


# ── history ───────────────────────────────────────────────────────────────────

@router.get("/history/{camera_id}")
async def get_history(camera_id: str, request: Request):
    _get_camera_or_404(camera_id)
    mgr = _mgr(request)
    worker = mgr.get_worker(camera_id)
    if worker is None:
        return []
    return worker.get_history()


# ── start / stop ──────────────────────────────────────────────────────────────

@router.post("/start/{camera_id}")
async def start_camera(camera_id: str, request: Request):
    cam = _get_camera_or_404(camera_id)
    if not cam.stream_url:
        raise HTTPException(status_code=400, detail="No stream URL configured for this camera.")
    mgr = _mgr(request)
    mgr.start_camera(cam)
    return {"status": "started", "cameraId": camera_id}


@router.post("/stop/{camera_id}")
async def stop_camera(camera_id: str, request: Request):
    _get_camera_or_404(camera_id)
    _mgr(request).stop_camera(camera_id)
    return {"status": "stopped", "cameraId": camera_id}


# ── local video upload (for testing without a live stream) ────────────────────

UPLOAD_DIR = Path(__file__).parent.parent / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

@router.post("/upload")
async def upload_video(request: Request, file: UploadFile = File(...)):
    """
    Upload a local .mp4 / .avi / .mkv file to test YOLO detection.
    The backend saves it and returns a virtual camera id you can poll.
    """
    allowed = {".mp4", ".avi", ".mkv", ".mov", ".webm"}
    suffix = Path(file.filename).suffix.lower()
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")

    dest = UPLOAD_DIR / f"upload_{int(time.time())}{suffix}"
    async with aiofiles.open(dest, "wb") as out:
        content = await file.read()
        await out.write(content)

    # Register as a temporary virtual camera
    virtual_id = f"upload_{dest.stem}"
    virtual_cam = CameraConfig(
        id=virtual_id,
        name=f"Upload: {file.filename}",
        location="Local file",
        city="—",
        stream_url=str(dest),
        gjirafa_page="",
    )

    mgr = _mgr(request)
    mgr.start_camera(virtual_cam)

    return {
        "cameraId": virtual_id,
        "filename": file.filename,
        "message": "Upload successful. Use cameraId to poll stats and stream.",
    }


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_camera_or_404(camera_id: str) -> "CameraConfig":
    cam = CAMERA_MAP.get(camera_id)
    # Also allow dynamically registered upload cameras
    if cam is None and not camera_id.startswith("upload_"):
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found.")
    if cam is None:
        # Return a minimal placeholder so the worker look-up proceeds
        from config import CameraConfig as CC
        return CC(
            id=camera_id, name=camera_id, location="", city="",
            stream_url=None, gjirafa_page=""
        )
    return cam
