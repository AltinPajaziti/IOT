import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, interval, switchMap, shareReplay, startWith } from 'rxjs';

export interface Camera {
  id: string;
  name: string;
  location: string;
  city: string;
  hasStreamUrl: boolean;
  gjirafaPage: string;
  embedUrl: string | null;
  active: boolean;
  running: boolean;
  error: string | null;
}

export interface TrafficStats {
  timestamp: string;
  camera_id: string;
  camera_name: string;
  fps: number;
  total_vehicles: number;
  counts: {
    car: number;
    truck: number;
    bus: number;
    motorcycle: number;
  };
  density: 'Low' | 'Medium' | 'High';
  frame_width: number;
  frame_height: number;
}

@Injectable({ providedIn: 'root' })
export class TrafficService {
  // ── If the backend runs on a different host, change this base URL ─────────
  private readonly API_BASE = 'http://localhost:8000';
  // ──────────────────────────────────────────────────────────────────────────

  constructor(private http: HttpClient) {}

  getCameras(): Observable<Camera[]> {
    return this.http.get<Camera[]>(`${this.API_BASE}/api/traffic/cameras`);
  }

  getStats(cameraId: string): Observable<TrafficStats | null> {
    return this.http.get<TrafficStats>(`${this.API_BASE}/api/traffic/stats/${cameraId}`);
  }

  pollStats(cameraId: string, intervalMs = 500): Observable<TrafficStats | null> {
    return interval(intervalMs).pipe(
      startWith(0),
      switchMap(() => this.getStats(cameraId)),
      shareReplay(1),
    );
  }

  getHistory(cameraId: string): Observable<TrafficStats[]> {
    return this.http.get<TrafficStats[]>(`${this.API_BASE}/api/traffic/history/${cameraId}`);
  }

  startCamera(cameraId: string): Observable<unknown> {
    return this.http.post(`${this.API_BASE}/api/traffic/start/${cameraId}`, {});
  }

  stopCamera(cameraId: string): Observable<unknown> {
    return this.http.post(`${this.API_BASE}/api/traffic/stop/${cameraId}`, {});
  }

  /**
   * Returns the MJPEG stream URL for an <img> tag.
   * Angular simply sets [src] to this URL; the browser handles the multipart stream.
   */
  getMjpegStreamUrl(cameraId: string): string {
    return `${this.API_BASE}/api/traffic/stream/${cameraId}`;
  }

  uploadVideo(file: File): Observable<{ cameraId: string; filename: string; message: string }> {
    const form = new FormData();
    form.append('file', file);
    return this.http.post<{ cameraId: string; filename: string; message: string }>(
      `${this.API_BASE}/api/traffic/upload`,
      form,
    );
  }
}
