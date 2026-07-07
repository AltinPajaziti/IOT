import {
  Component,
  OnInit,
  OnDestroy,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { Subscription, catchError, of } from 'rxjs';

import { TrafficService, Camera, TrafficStats } from '../../services/traffic';
import { StatCardComponent } from '../../components/stat-card/stat-card';
import { VehicleChartComponent } from '../../components/vehicle-chart/vehicle-chart';

@Component({
  selector: 'app-traffic-monitor',
  standalone: true,
  imports: [CommonModule, StatCardComponent, VehicleChartComponent],
  templateUrl: './traffic-monitor.html',
  styleUrl: './traffic-monitor.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TrafficMonitorComponent implements OnInit, OnDestroy {
  cameras: Camera[] = [];
  selectedCameraId = '';

  stats = signal<TrafficStats | null>(null);
  loading = signal(true);
  streamError = signal(false);
  uploadStatus = signal('');
  statusMessage = signal('');

  private pollSub?: Subscription;

  get selectedCamera(): Camera | undefined {
    return this.cameras.find((c) => c.id === this.selectedCameraId);
  }

  get mjpegUrl(): string {
    return this.selectedCameraId
      ? this.trafficSvc.getMjpegStreamUrl(this.selectedCameraId)
      : '';
  }

  get safeEmbedUrl(): SafeResourceUrl | null {
    const cam = this.selectedCamera;
    if (!cam?.embedUrl) return null;
    return this.sanitizer.bypassSecurityTrustResourceUrl(cam.embedUrl);
  }

  get densityClass(): string {
    const d = this.stats()?.density;
    return d === 'High' ? 'density-high' : d === 'Medium' ? 'density-medium' : 'density-low';
  }

  get densityPct(): number {
    const d = this.stats()?.density;
    if (d === 'High') return 100;
    if (d === 'Medium') return 55;
    return 20;
  }

  constructor(
    private trafficSvc: TrafficService,
    private cdr: ChangeDetectorRef,
    private sanitizer: DomSanitizer,
  ) {}

  ngOnInit(): void {
    this.trafficSvc.getCameras().subscribe({
      next: (cams) => {
        this.cameras = cams;
        if (cams.length > 0) this.selectCamera(cams[0].id);
        this.loading.set(false);
        this.cdr.markForCheck();
      },
      error: () => {
        this.statusMessage.set(
          'Backend unreachable — start the Python server: uvicorn main:app --reload --port 8000',
        );
        this.loading.set(false);
        this.cdr.markForCheck();
      },
    });
  }

  ngOnDestroy(): void {
    this.pollSub?.unsubscribe();
  }

  selectCamera(id: string): void {
    this.pollSub?.unsubscribe();
    this.selectedCameraId = id;
    this.stats.set(null);
    this.streamError.set(false);
    this._startPolling(id);
    this.cdr.markForCheck();
  }

  onCameraChange(id: string): void {
    this.selectCamera(id);
  }

  onStreamError(): void {
    this.streamError.set(true);
    this.cdr.markForCheck();
  }

  onStreamLoad(): void {
    this.streamError.set(false);
    this.cdr.markForCheck();
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;

    this.uploadStatus.set('Uploading…');
    this.trafficSvc
      .uploadVideo(file)
      .pipe(catchError((err) => { this.uploadStatus.set('Failed: ' + err.message); this.cdr.markForCheck(); return of(null); }))
      .subscribe((res) => {
        if (!res) return;
        this.uploadStatus.set(`"${res.filename}" — id: ${res.cameraId}`);
        this.cameras = [...this.cameras, {
          id: res.cameraId,
          name: `Upload: ${res.filename}`,
          location: 'Local file',
          city: '—',
          hasStreamUrl: true,
          gjirafaPage: '',
          embedUrl: null,
          active: true,
          running: true,
          error: null,
        }];
        this.selectCamera(res.cameraId);
        this.cdr.markForCheck();
      });
  }

  private _startPolling(cameraId: string): void {
    this.pollSub = this.trafficSvc
      .pollStats(cameraId, 500)
      .pipe(catchError(() => of(null)))
      .subscribe((s) => {
        if (s && 'total_vehicles' in s) this.stats.set(s as TrafficStats);
        this.cdr.markForCheck();
      });
  }
}
