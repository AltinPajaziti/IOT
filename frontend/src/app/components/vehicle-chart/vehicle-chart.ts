import {
  Component,
  Input,
  OnChanges,
  SimpleChanges,
  ElementRef,
  ViewChild,
  AfterViewInit,
  OnDestroy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { Chart, ChartConfiguration, registerables } from 'chart.js';

Chart.register(...registerables);

@Component({
  selector: 'app-vehicle-chart',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './vehicle-chart.html',
  styleUrl: './vehicle-chart.scss',
})
export class VehicleChartComponent implements AfterViewInit, OnChanges, OnDestroy {
  @Input() counts: { car: number; truck: number; bus: number; motorcycle: number } | null = null;
  @ViewChild('chartCanvas') chartCanvas!: ElementRef<HTMLCanvasElement>;

  private chart: Chart | null = null;

  ngAfterViewInit(): void {
    this.buildChart();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['counts'] && this.chart && this.counts) {
      this.chart.data.datasets[0].data = [
        this.counts.car,
        this.counts.truck,
        this.counts.bus,
        this.counts.motorcycle,
      ];
      this.chart.update('none');
    }
  }

  ngOnDestroy(): void {
    this.chart?.destroy();
  }

  private buildChart(): void {
    const ctx = this.chartCanvas.nativeElement.getContext('2d');
    if (!ctx) return;

    const cfg: ChartConfiguration = {
      type: 'bar',
      data: {
        labels: ['Cars', 'Trucks', 'Buses', 'Motorcycles'],
        datasets: [
          {
            data: [
              this.counts?.car ?? 0,
              this.counts?.truck ?? 0,
              this.counts?.bus ?? 0,
              this.counts?.motorcycle ?? 0,
            ],
            backgroundColor: [
              'rgba(52,211,153,0.8)',
              'rgba(167,139,250,0.8)',
              'rgba(96,165,250,0.8)',
              'rgba(251,191,36,0.8)',
            ],
            borderColor: [
              '#34d399',
              '#a78bfa',
              '#60a5fa',
              '#fbbf24',
            ],
            borderWidth: 1,
            borderRadius: 4,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
        },
        scales: {
          x: {
            grid: { color: 'rgba(255,255,255,0.04)' },
            ticks: { color: '#6b7280', font: { size: 11 } },
          },
          y: {
            grid: { color: 'rgba(255,255,255,0.04)' },
            ticks: { color: '#6b7280', font: { size: 11 }, precision: 0 },
            beginAtZero: true,
          },
        },
        animation: { duration: 300 },
      },
    };

    this.chart = new Chart(ctx, cfg);
  }
}
