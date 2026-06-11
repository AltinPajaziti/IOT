"""
Entry point for the IoTH Traffic Monitoring API.
Run with: uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from camera_manager import CameraManager
from routes.traffic import router as traffic_router
from routes.chat import router as chat_router
from routes.pipeline import router as pipeline_router
from sensor_simulator import start as start_simulator, stop as stop_simulator
from stream_processor import start as start_processor, stop as stop_processor
from iot_config import SIMULATOR_ENABLED
import os

STREAM_PROCESSOR_FALLBACK = os.getenv("STREAM_PROCESSOR_FALLBACK", "false").lower() in ("1", "true", "yes")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialise shared camera manager (which loads the YOLO model)
    app.state.camera_manager = CameraManager()
    if SIMULATOR_ENABLED:
        start_simulator()
    if STREAM_PROCESSOR_FALLBACK:
        start_processor()
    yield
    # Shutdown: stop all running streams cleanly
    stop_simulator()
    stop_processor()
    app.state.camera_manager.stop_all()


app = FastAPI(
    title="IoTH Traffic Monitor",
    description="Real-time vehicle detection from Prishtina traffic cameras using YOLOv8.",
    version="1.0.0",
    lifespan=lifespan,
)

# Allow Angular dev server origins (frontend :4200 and traffic-client :4201)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "http://127.0.0.1:4200",
        "http://localhost:4201",
        "http://127.0.0.1:4201",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(traffic_router)
app.include_router(chat_router)
app.include_router(pipeline_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
