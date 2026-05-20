import { Routes } from '@angular/router';
import { MapComponent } from './pages/map/map.component';

export const routes: Routes = [
  { path: '', component: MapComponent },
  { path: '**', redirectTo: '' },
];
