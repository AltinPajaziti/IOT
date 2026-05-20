import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface CameraSnapshot {
  id: number;
  cameraId: string;
  cameraName: string;
  location: string;
  city: string;
  capturedAt: string;
  totalVehicles: number;
  cars: number;
  trucks: number;
  buses: number;
  motorcycles: number;
  density: 'Low' | 'Medium' | 'High';
  fps: number;
  latitude: number;
  longitude: number;
}

export interface SummaryResponse {
  updatedAt: string;
  totalVehicles: number;
  cameras: CameraItem[];
}

export interface CameraItem {
  cameraId: string;
  cameraName: string;
  location: string;
  totalVehicles: number;
  density: 'Low' | 'Medium' | 'High';
  capturedAt: string;
  latitude: number;
  longitude: number;
}

@Injectable({ providedIn: 'root' })
export class TrafficApiService {
  private readonly base = 'http://localhost:5050/api';
  private http = inject(HttpClient);

  getLatest(): Observable<CameraSnapshot[]> {
    return this.http.get<CameraSnapshot[]>(`${this.base}/snapshots/latest`);
  }

  getSummary(): Observable<SummaryResponse> {
    return this.http.get<SummaryResponse>(`${this.base}/snapshots/summary`);
  }

  getHistory(cameraId: string, hours = 3): Observable<CameraSnapshot[]> {
    return this.http.get<CameraSnapshot[]>(
      `${this.base}/snapshots/history/${cameraId}?hours=${hours}`
    );
  }
}
