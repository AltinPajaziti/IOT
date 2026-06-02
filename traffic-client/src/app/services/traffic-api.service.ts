import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, of } from 'rxjs';
import { catchError, switchMap } from 'rxjs/operators';
import { PipelineService } from './pipeline.service';

export interface AppSettings {
  refreshSeconds: number;
}

export interface SimulateResponse {
  message: string;
  snapshots: CameraSnapshot[];
}

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
  private readonly pipelineBase = 'http://localhost:8000/api/pipeline';
  private http = inject(HttpClient);
  private pipeline = inject(PipelineService);

  /** Prefer Cassandra (IoT pipeline); fall back to SQL Server via .NET API. */
  getLatest(): Observable<CameraSnapshot[]> {
    return this.pipeline.getLatestFromCassandra().pipe(
      switchMap(cassandraRows => {
        if (cassandraRows.length > 0) return of(cassandraRows);
        return this.http.get<CameraSnapshot[]>(`${this.base}/snapshots/latest`).pipe(
          catchError(() => of([] as CameraSnapshot[])),
        );
      }),
    );
  }

  getSummary(): Observable<SummaryResponse> {
    return this.http.get<SummaryResponse>(`${this.base}/snapshots/summary`);
  }

  getHistory(cameraId: string, hours = 3): Observable<CameraSnapshot[]> {
    return this.http.get<CameraSnapshot[]>(
      `${this.base}/snapshots/history/${cameraId}?hours=${hours}`
    );
  }

  getSettings(): Observable<AppSettings> {
    return this.http.get<AppSettings>(`${this.base}/settings`);
  }

  simulate(cars = 200, cameraId?: string): Observable<SimulateResponse> {
    return this.http.post<SimulateResponse>(`${this.base}/snapshots/simulate`, {
      cars,
      cameraId: cameraId ?? null,
    });
  }

  simulatePipeline(cars = 200): Observable<{ message: string } | null> {
    return this.pipeline.simulateToKafka(cars);
  }
}
