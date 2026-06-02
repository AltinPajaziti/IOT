import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, of, timeout, catchError } from 'rxjs';
import { map } from 'rxjs/operators';
import { CameraSnapshot } from './traffic-api.service';

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

const CHAT_API_URL = 'http://localhost:8000/api/chat';
const REQUEST_TIMEOUT_MS = 20_000;

@Injectable({ providedIn: 'root' })
export class ChatbotService {
  private http = inject(HttpClient);

  /**
   * Sends conversation history + current live snapshots to the Python backend.
   * The snapshots are used server-side to build traffic context.
   * Falls back to the local engine if the backend is unreachable or times out.
   */
  sendMessage(history: ChatMessage[], snapshots: CameraSnapshot[]): Observable<string> {
    const lastUserMsg = [...history].reverse().find(m => m.role === 'user')?.content ?? '';

    return this.http
      .post<{ reply: string }>(CHAT_API_URL, {
        messages:  history,
        snapshots: snapshots,   // send live data to the backend
      })
      .pipe(
        timeout(REQUEST_TIMEOUT_MS),
        map(res => res.reply ?? 'No response received.'),
        catchError(() => of(this.localFallback(lastUserMsg, snapshots))),
      );
  }

  // ── Local fallback (used when backend is unreachable) ─────────────────────

  private localFallback(question: string, snapshots: CameraSnapshot[]): string {
    const q = question.toLowerCase();

    if (!snapshots.length) {
      return "I don't have live traffic data yet. Make sure the .NET API on port 5050 is running.";
    }

    const total    = snapshots.reduce((s, x) => s + x.totalVehicles, 0);
    const busiest  = [...snapshots].sort((a, b) => b.totalVehicles - a.totalVehicles)[0];
    const clearest = [...snapshots].sort((a, b) => a.totalVehicles - b.totalVehicles)[0];
    const high     = snapshots.filter(s => s.density === 'High');
    const medium   = snapshots.filter(s => s.density === 'Medium');
    const low      = snapshots.filter(s => s.density === 'Low');

    const emoji = (d: string) => d === 'High' ? '🔴' : d === 'Medium' ? '🟡' : '🟢';
    const line  = (s: CameraSnapshot) =>
      `${emoji(s.density)} **${s.cameraName}** — ${s.density} · ${s.totalVehicles} vehicles ` +
      `(🚗${s.cars} 🚛${s.trucks} 🚌${s.buses} 🏍️${s.motorcycles})`;

    const GREETING_WORDS = ['hello','hi','hey','sup','howdy','greetings','help'];
    const cleanQ = q.trim().replace(/[!.,?]+$/, '');
    const isGreeting = GREETING_WORDS.some(w => cleanQ === w || cleanQ.startsWith(w + ' '));

    if (isGreeting) {
      const parts = snapshots.map(s => `${emoji(s.density)} ${s.cameraName} (${s.density})`).join(' · ');
      return `Hello! 👋 I'm **TrafficBot** — your live traffic assistant for Prishtina.\n\nCurrently watching **${snapshots.length} route(s)**: ${parts}\n\nAsk me about road conditions, vehicle counts, or congestion!`;
    }

    const TRAFFIC_KEYWORDS = ['traffic','route','road','vehicle','car','truck','bus','motorcycl',
      'camera','pejton','tokba','prishtina','congest','density','clear','busy','slow','block',
      'drive','travel','commut','speed','count','sensor','monitor','yolo','detect','alert',
      'summary','status'];

    if (!TRAFFIC_KEYWORDS.some(kw => q.includes(kw))) {
      return `I'm your **Traffic AI Assistant** 🚦 — I only answer questions about live road conditions in Prishtina.\n\nTry: *"Which route has the most traffic?"*, *"Is Pejton congested?"*, or *"Give me a traffic summary"*.`;
    }

    if (q.match(/summar|overview|all route|situation|overall|report/))
      return `**Prishtina traffic summary:**\n\n${snapshots.map(line).join('\n')}\n\n📊 Total: **${total} vehicles**`;

    if (q.match(/most traffic|busiest|heaviest|worst/))
      return `The busiest route is ${line(busiest)}.`;

    if (q.match(/clear|least traffic|best route|free|quiet/))
      return low.length ? `Clearest route: ${line(clearest)} — traffic is flowing freely.`
                        : `Least congested: ${line(clearest)}.`;

    if (q.match(/congest|block|slow|alert|heavy/))
      return (!high.length && !medium.length)
        ? '✅ No congestion — all routes are clear!'
        : [...high.map(s => `🔴 **${s.cameraName}** heavily congested (${s.totalVehicles} vehicles).`),
           ...medium.map(s => `🟡 **${s.cameraName}** moderate traffic (${s.totalVehicles} vehicles).`)].join('\n');

    if (q.match(/total|how many|count/))
      return `**${total} vehicles** detected:\n` + snapshots.map(s => `  • ${s.cameraName}: ${s.totalVehicles}`).join('\n');

    if (q.match(/tokba|bashqe/)) {
      const s = snapshots.find(x => x.cameraId === 'tokbashqe');
      return s ? line(s) : "No data for Tokbashqe yet.";
    }

    if (q.match(/pejton/)) {
      const m = snapshots.filter(x => x.cameraId.startsWith('pejton'));
      return m.length ? m.map(line).join('\n') : "No data for Pejton yet.";
    }

    return `**Current traffic:**\n\n${snapshots.map(line).join('\n')}\n\nTotal: **${total} vehicles**.`;
  }
}
