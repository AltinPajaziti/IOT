import { Routes } from '@angular/router';
import { TrafficMonitorComponent } from './pages/traffic-monitor/traffic-monitor';

export const routes: Routes = [
  { path: '', component: TrafficMonitorComponent },
  { path: '**', redirectTo: '' },
];
