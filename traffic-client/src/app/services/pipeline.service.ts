import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, of } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import { CameraSnapshot } from './traffic-api.service';

export interface PipelineStatus {
  pipeline: string;
  flow: string;
  kafka: {
    enabled: boolean;
    bootstrap: string;
    topic: string;
    connected: boolean;
    events_sent: number;
    last_error: string | null;
  };
  cassandra: {
    hosts: string[];
    keyspace: string;
    connected: boolean;
    row_count: number;
    last_error: string | null;
  };
  simulator: { running: boolean; ticks: number; interval_seconds: number };
  stream_processor: { running: boolean; processed: number; mode: string };
  spark: { job: string; note: string };
}

@Injectable({ providedIn: 'root' })
export class PipelineService {
  private readonly base = 'http://localhost:8000/api/pipeline';
  private http = inject(HttpClient);

  getStatus(): Observable<PipelineStatus | null> {
    return this.http.get<PipelineStatus>(`${this.base}/status`).pipe(
      catchError(() => of(null)),
    );
  }

  getLatestFromCassandra(): Observable<CameraSnapshot[]> {
    return this.http.get<CameraSnapshot[]>(`${this.base}/snapshots/latest`).pipe(
      catchError(() => of([])),
    );
  }

  simulateToKafka(cars = 200): Observable<{ message: string } | null> {
    return this.http.post<{ message: string }>(`${this.base}/simulate`, { cars }).pipe(
      catchError(() => of(null)),
    );
  }
}
