import {
  Component, OnInit, OnDestroy, AfterViewInit,
  signal, computed, inject
} from '@angular/core';
import { CommonModule, DatePipe, DecimalPipe } from '@angular/common';
import * as L from 'leaflet';
import { interval, Subscription, catchError, of, forkJoin, switchMap } from 'rxjs';
import { TrafficApiService, CameraSnapshot } from '../../services/traffic-api.service';
import { PipelineService, PipelineStatus } from '../../services/pipeline.service';
import { ChatbotComponent } from '../../components/chatbot/chatbot.component';

const DEFAULT_REFRESH_MS = 15 * 1000;

const DENSITY_COLOR: Record<string, string> = {
  Low:    '#22c55e',
  Medium: '#f59e0b',
  High:   '#ef4444',
};
const DENSITY_BG: Record<string, string> = {
  Low:    'rgba(34,197,94,.13)',
  Medium: 'rgba(245,158,11,.13)',
  High:   'rgba(239,68,68,.13)',
};
const DENSITY_PCT: Record<string, number> = { Low: 22, Medium: 62, High: 96 };

// Route polylines approximate road geometry (Prishtina)
const ROUTE_SEGMENTS: Record<string, [number, number][]> = {
  pejton: [
    [42.6574, 21.1520], [42.6580, 21.1533], [42.6588, 21.1548],
    [42.6594, 21.1558], [42.6601, 21.1565], [42.6610, 21.1577],
    [42.6620, 21.1591],
  ],
  pejton2: [
    [42.6574, 21.1520], [42.6580, 21.1533], [42.6588, 21.1548],
    [42.6594, 21.1558], [42.6601, 21.1565], [42.6610, 21.1577],
    [42.6620, 21.1591],
  ],
  tokbashqe: [
    [42.6551, 21.1592], [42.6558, 21.1604], [42.6565, 21.1612],
    [42.6572, 21.1621], [42.6580, 21.1633], [42.6589, 21.1647],
  ],
};

interface Alert {
  id: string; camera: string; density: string;
  level: 'high' | 'medium' | 'low'; message: string; time: string;
}

// Professional camera/sensor pin
function sensorIcon(color: string, name: string, count: number, active: boolean): L.DivIcon {
  const pulse = active
    ? `<span style="position:absolute;inset:-8px;border-radius:50%;border:2px solid ${color};opacity:.4;animation:sensor-pulse 2s ease-out infinite"></span>
       <span style="position:absolute;inset:-16px;border-radius:50%;border:1.5px solid ${color};opacity:.18;animation:sensor-pulse 2s ease-out .5s infinite"></span>`
    : '';

  return L.divIcon({
    className: '',
    html: `
    <div style="display:flex;flex-direction:column;align-items:center;gap:3px;cursor:pointer;font-family:Inter,sans-serif">
      <!-- ring + dot -->
      <div style="position:relative;width:44px;height:44px">
        ${pulse}
        <div style="width:44px;height:44px;border-radius:50%;
          background:#fff;
          border:3px solid ${color};
          box-shadow:0 2px 12px ${color}55,0 1px 4px rgba(0,0,0,.25);
          display:flex;align-items:center;justify-content:center;flex-direction:column;gap:1px">
          <!-- camera SVG icon -->
          <svg width="18" height="14" viewBox="0 0 20 16" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect x="0" y="3" width="13" height="10" rx="2" fill="${color}"/>
            <polygon points="13,5 20,1 20,15 13,11" fill="${color}"/>
            <circle cx="6" cy="8" r="2.5" fill="#fff" opacity="0.9"/>
          </svg>
          <!-- count -->
          <span style="font-size:10px;font-weight:800;color:${color};line-height:1">${count}</span>
        </div>
      </div>
      <!-- label tag -->
      <div style="background:#fff;color:#111827;font-size:10px;font-weight:700;
        padding:2px 7px;border-radius:4px;white-space:nowrap;
        border:1.5px solid ${color};
        box-shadow:0 1px 4px rgba(0,0,0,.2);letter-spacing:.02em">
        ${name}
      </div>
    </div>`,
    iconSize: [80, 70],
    iconAnchor: [40, 44],
    tooltipAnchor: [0, -48],
  });
}

@Component({
  selector: 'app-map',
  standalone: true,
  imports: [CommonModule, DatePipe, DecimalPipe, ChatbotComponent],
  templateUrl: './map.component.html',
  styleUrls: ['./map.component.scss'],
})
export class MapComponent implements OnInit, AfterViewInit, OnDestroy {
  private api = inject(TrafficApiService);
  private pipelineSvc = inject(PipelineService);

  snapshots  = signal<CameraSnapshot[]>([]);
  pipeline   = signal<PipelineStatus | null>(null);
  dataSource = signal<'cassandra' | 'sqlserver' | 'none'>('none');
  selected   = signal<CameraSnapshot | null>(null);
  loading    = signal(true);
  error      = signal<string | null>(null);
  lastUpdate = signal<Date | null>(null);
  countdown  = signal(DEFAULT_REFRESH_MS / 1000);
  alerts     = signal<Alert[]>([]);
  refreshMs  = signal(DEFAULT_REFRESH_MS);
  simulating = signal(false);
  simulateMsg = signal<string | null>(null);

  highAlerts = computed(() => this.alerts().filter(a => a.level === 'high'));
  showAlarm  = computed(() => this.highAlerts().length > 0);

  totalVehicles   = computed(() => this.snapshots().reduce((s, x) => s + x.totalVehicles, 0));
  avgDensity      = computed(() => {
    const snaps = this.snapshots();
    if (!snaps.length) return '—';
    if (snaps.some(s => s.density === 'High'))   return 'High';
    if (snaps.some(s => s.density === 'Medium')) return 'Medium';
    return 'Low';
  });
  totalColor      = computed(() => DENSITY_COLOR[this.avgDensity()] ?? '#374151');
  avgDensityColor = computed(() => DENSITY_COLOR[this.avgDensity()] ?? '#374151');

  private map!: L.Map;
  private markers  = new Map<string, L.Marker>();
  private polylines = new Map<string, L.Polyline>();
  private countdownSub?: Subscription;
  private pollTimer?: ReturnType<typeof setInterval>;
  private pipelineTimer?: ReturnType<typeof setInterval>;

  private startPipelinePolling() {
    this.pipelineTimer && clearInterval(this.pipelineTimer);
    this.pipelineTimer = setInterval(() => {
      this.pipelineSvc.getStatus().pipe(catchError(() => of(null))).subscribe(s => {
        if (s) this.pipeline.set(s);
      });
    }, 10000);
  }

  ngOnInit() {
    forkJoin({
      settings: this.api.getSettings().pipe(catchError(() => of({ refreshSeconds: 15 }))),
      data: this.api.getLatest().pipe(catchError(() => of(null as CameraSnapshot[] | null))),
      pipeline: this.pipelineSvc.getStatus().pipe(catchError(() => of(null))),
    }).subscribe(({ settings, data, pipeline }) => {
      const ms = Math.max(5, settings.refreshSeconds) * 1000;
      this.refreshMs.set(ms);
      this.countdown.set(ms / 1000);
      this.loading.set(false);
      if (pipeline) this.pipeline.set(pipeline);
      if (data) this.applySnapshots(data);
      else this.error.set('Cannot reach Traffic API — start docker compose + backend + traffic-api');
      this.startPolling();
      this.startPipelinePolling();
    });

    this.countdownSub = interval(1000).subscribe(() => {
      const max = this.refreshMs() / 1000;
      this.countdown.update(v => v > 0 ? v - 1 : max);
    });
  }

  private startPolling() {
    this.pollTimer && clearInterval(this.pollTimer);
    const ms = this.refreshMs();
    this.pollTimer = setInterval(() => this.fetchLatest(), ms);
  }

  private fetchLatest() {
    this.pipelineSvc.getLatestFromCassandra().pipe(
      catchError(() => of([] as CameraSnapshot[])),
      switchMap(cassandra => {
        if (cassandra.length > 0) {
          this.dataSource.set('cassandra');
          return of(cassandra);
        }
        return this.api.getLatest().pipe(
          catchError(() => of(null as CameraSnapshot[] | null)),
          switchMap(sql => {
            if (sql && sql.length > 0) {
              this.dataSource.set('sqlserver');
              return of(sql);
            }
            this.dataSource.set('none');
            return of(null);
          }),
        );
      }),
    ).subscribe(data => {
      if (data) {
        this.applySnapshots(data);
        this.countdown.set(this.refreshMs() / 1000);
      } else {
        this.error.set('No data — start IoT stack: docker compose up -d');
      }
    });
  }

  private applySnapshots(data: CameraSnapshot[]) {
    this.snapshots.set(data);
    this.lastUpdate.set(new Date());
    this.error.set(null);
    this.updateMarkers(data);
    this.updatePolylines(data);
    this.buildAlerts(data);
    if (!this.selected() && data.length > 0) {
      this.selected.set(data[0]);
    } else {
      const cur = this.selected();
      if (cur) {
        const fresh = data.find(d => d.cameraId === cur.cameraId);
        if (fresh) this.selected.set(fresh);
      }
    }
  }

  runSimulator() {
    if (this.simulating()) return;
    this.simulating.set(true);
    this.simulateMsg.set(null);
    forkJoin({
      sql: this.api.simulate(200).pipe(catchError(() => of(null))),
      kafka: this.api.simulatePipeline(200).pipe(catchError(() => of(null))),
    }).subscribe(({ sql, kafka }) => {
      this.simulating.set(false);
      const parts: string[] = [];
      if (sql) parts.push('SQL: ' + sql.message);
      if (kafka) parts.push('Kafka: ' + kafka.message);
      if (parts.length) {
        this.simulateMsg.set(parts.join(' · '));
        setTimeout(() => this.fetchLatest(), 2000);
      } else {
        this.simulateMsg.set('Simulator failed — start docker compose + backend + traffic-api');
      }
    });
  }

  ngAfterViewInit() { this.initMap(); }

  ngOnDestroy() {
    this.countdownSub?.unsubscribe();
    if (this.pollTimer) clearInterval(this.pollTimer);
    if (this.pipelineTimer) clearInterval(this.pipelineTimer);
    this.map?.remove();
  }

  private initMap() {
    this.map = L.map('map', {
      center: [42.6586, 21.1582],
      zoom: 16,
      zoomControl: false,
    });
    L.control.zoom({ position: 'bottomright' }).addTo(this.map);

    // Light Voyager tiles — professional, colored, readable
    L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
      attribution: '© OpenStreetMap contributors © CARTO',
      maxZoom: 20,
    }).addTo(this.map);
  }

  private updateMarkers(data: CameraSnapshot[]) {
    if (!this.map) return;
    data.forEach(snap => {
      const color  = DENSITY_COLOR[snap.density] ?? '#22c55e';
      const active = snap.density !== 'Low';
      const icon   = sensorIcon(color, snap.cameraName, snap.totalVehicles, active);

      if (this.markers.has(snap.cameraId)) {
        this.markers.get(snap.cameraId)!.setIcon(icon);
        this.markers.get(snap.cameraId)!.setTooltipContent(this.tooltipHtml(snap));
      } else {
        const m = L.marker([snap.latitude, snap.longitude], { icon })
          .addTo(this.map)
          .bindTooltip(this.tooltipHtml(snap), {
            direction: 'top', className: 'tw-tooltip',
          });
        m.on('click', () => this.selectCamera(snap));
        this.markers.set(snap.cameraId, m);
      }
    });
  }

  private updatePolylines(data: CameraSnapshot[]) {
    if (!this.map) return;
    data.forEach(snap => {
      const coords = ROUTE_SEGMENTS[snap.cameraId];
      if (!coords) return;
      const color  = DENSITY_COLOR[snap.density] ?? '#22c55e';
      const weight = snap.density === 'High' ? 8 : snap.density === 'Medium' ? 6 : 5;
      const opts = { color, weight, opacity: 0.75, lineCap: 'round' as const, lineJoin: 'round' as const };

      if (this.polylines.has(snap.cameraId)) {
        this.polylines.get(snap.cameraId)!.setStyle(opts);
      } else {
        const line = L.polyline(coords, opts).addTo(this.map);
        this.polylines.set(snap.cameraId, line);
      }
    });
  }

  private tooltipHtml(s: CameraSnapshot): string {
    const c = DENSITY_COLOR[s.density];
    const pct = DENSITY_PCT[s.density];
    return `
      <div style="font-family:Inter,sans-serif;min-width:170px">
        <div style="font-size:13px;font-weight:700;color:#111827;margin-bottom:2px">${s.cameraName}</div>
        <div style="font-size:11px;color:#6b7280;margin-bottom:8px">${s.location}</div>
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
          <span style="font-size:11px;font-weight:700;color:${c};background:${c}22;padding:2px 8px;border-radius:4px">${s.density}</span>
          <span style="font-size:12px;font-weight:600;color:#111827">${s.totalVehicles} vehicles</span>
        </div>
        <div style="height:4px;background:#e5e7eb;border-radius:2px;overflow:hidden;margin-bottom:8px">
          <div style="height:100%;width:${pct}%;background:${c};border-radius:2px;transition:width .4s"></div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:11px;color:#374151">
          <span>Cars: <b>${s.cars}</b></span>
          <span>Trucks: <b>${s.trucks}</b></span>
          <span>Buses: <b>${s.buses}</b></span>
          <span>Motos: <b>${s.motorcycles}</b></span>
        </div>
        <div style="margin-top:6px;font-size:10px;color:#9ca3af">${s.fps.toFixed(1)} fps · ${new Date(s.capturedAt).toLocaleTimeString()}</div>
      </div>`;
  }

  private buildAlerts(data: CameraSnapshot[]) {
    const now = new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
    this.alerts.set(data
      .filter(s => s.density !== 'Low')
      .map(s => ({
        id: s.cameraId, camera: s.cameraName, density: s.density,
        level: s.density === 'High' ? 'high' as const : 'medium' as const,
        message: s.density === 'High'
          ? `Heavy congestion — ${s.totalVehicles} vehicles detected`
          : `Moderate traffic — ${s.totalVehicles} vehicles`,
        time: now,
      })));
  }

  selectCamera(snap: CameraSnapshot) {
    this.selected.set(snap);
    if (this.map) this.map.panTo([snap.latitude, snap.longitude], { animate: true, duration: 0.4 });
  }

  densityColor(d: string)  { return DENSITY_COLOR[d]  ?? '#374151'; }
  densityBg(d: string)     { return DENSITY_BG[d]     ?? 'rgba(0,0,0,.06)'; }
  densityPctOf(d: string)  { return DENSITY_PCT[d]    ?? 20; }
  pct(val: number, max: number) { return Math.min((val / max) * 100, 100); }
  formatCountdown(s: number) {
    const m = Math.floor(s / 60), sec = s % 60;
    return `${m}:${sec.toString().padStart(2, '0')}`;
  }
}
