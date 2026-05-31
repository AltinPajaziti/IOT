import {
  Component, Input, signal, computed, ElementRef,
  ViewChild, AfterViewChecked, inject, OnChanges
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ChatbotService, ChatMessage } from '../../services/chatbot.service';
import { CameraSnapshot } from '../../services/traffic-api.service';

interface DisplayMessage {
  role: 'user' | 'assistant';
  content: string;
  loading?: boolean;
}

const QUICK_PROMPTS = [
  'Which route has the most traffic?',
  'Is Tokbashqe clear right now?',
  'How many vehicles total?',
  'Any congested routes?',
  'Give me a traffic summary',
];

@Component({
  selector: 'app-chatbot',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './chatbot.component.html',
  styleUrls: ['./chatbot.component.scss'],
})
export class ChatbotComponent implements AfterViewChecked, OnChanges {
  @Input() snapshots: CameraSnapshot[] = [];
  @ViewChild('messagesEnd') private messagesEnd!: ElementRef;

  private chatbotService = inject(ChatbotService);

  open       = signal(false);
  userInput  = signal('');
  thinking   = signal(false);
  messages   = signal<DisplayMessage[]>([
    {
      role: 'assistant',
      content: "Hi! I'm **TrafficBot** 🚦 — your Prishtina traffic assistant.\n\nAsk me about current road conditions, vehicle counts on specific routes, or which way to avoid congestion.",
    },
  ]);

  private history: ChatMessage[] = [];
  private shouldScroll = false;
  quickPrompts = QUICK_PROMPTS;

  hasMessages = computed(() => this.messages().length > 1);

  ngOnChanges() {
    // data updated — no action needed; fresh snapshot passed on each send
  }

  ngAfterViewChecked() {
    if (this.shouldScroll) {
      this.scrollToBottom();
      this.shouldScroll = false;
    }
  }

  toggle() { this.open.update(v => !v); }
  close()  { this.open.set(false); }

  setInput(text: string) {
    this.userInput.set(text);
  }

  send(text?: string) {
    const content = (text ?? this.userInput()).trim();
    if (!content || this.thinking()) return;

    this.userInput.set('');
    this.messages.update(m => [...m, { role: 'user', content }]);
    this.history.push({ role: 'user', content });

    const loadingIdx = this.messages().length;
    this.messages.update(m => [...m, { role: 'assistant', content: '', loading: true }]);
    this.thinking.set(true);
    this.shouldScroll = true;

    this.chatbotService.sendMessage(this.history, this.snapshots).subscribe({
      next: reply => {
        this.history.push({ role: 'assistant', content: reply });
        this.messages.update(msgs => {
          const updated = [...msgs];
          updated[loadingIdx] = { role: 'assistant', content: reply, loading: false };
          return updated;
        });
        this.thinking.set(false);
        this.shouldScroll = true;
      },
      error: () => {
        this.messages.update(msgs => {
          const updated = [...msgs];
          updated[loadingIdx] = {
            role: 'assistant',
            content: '⚠️ Cannot reach the backend server. Make sure the Python backend is running on port 8000.',
            loading: false,
          };
          return updated;
        });
        this.thinking.set(false);
        this.shouldScroll = true;
      },
    });
  }

  onKeydown(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.send();
    }
  }

  clearChat() {
    this.history = [];
    this.messages.set([
      {
        role: 'assistant',
        content: "Chat cleared! Ask me anything about current Prishtina traffic conditions.",
      },
    ]);
  }

  formatMessage(text: string): string {
    return text
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/\n/g, '<br>');
  }

  private scrollToBottom() {
    try {
      this.messagesEnd?.nativeElement?.scrollIntoView({ behavior: 'smooth' });
    } catch {}
  }
}
