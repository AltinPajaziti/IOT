import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-stat-card',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './stat-card.html',
  styleUrl: './stat-card.scss',
})
export class StatCardComponent {
  @Input() label = '';
  @Input() value: string | number = 0;
  @Input() badge = '';
  @Input() accent: 'green' | 'blue' | 'amber' | 'violet' | 'cyan' | 'rose' = 'blue';
  @Input() max = 50;

  get barPct(): number {
    const v = typeof this.value === 'number' ? this.value : parseFloat(String(this.value)) || 0;
    return Math.min(100, (v / this.max) * 100);
  }
}
