import { WsInboundEvent } from "../types";
import { AudioChunk } from "./audio";
import { WS_BASE_URL } from "./config";

type Listener = (event: WsInboundEvent) => void;

export class SessionWsClient {
  private socket: WebSocket | null = null;
  private sequence = 1;
  private connectPromise: Promise<void> | null = null;

  constructor(private readonly sessionId: string) {}

  connect(listener: Listener, onClosed?: () => void): Promise<void> {
    if (this.socket?.readyState === WebSocket.OPEN) {
      return Promise.resolve();
    }
    if (this.connectPromise) {
      return this.connectPromise;
    }

    const url = `${WS_BASE_URL}/ws/sessions/${encodeURIComponent(this.sessionId)}`;

    this.connectPromise = new Promise((resolve, reject) => {
      const ws = new WebSocket(url);
      this.socket = ws;

      ws.onopen = () => {
        this.connectPromise = null;
        resolve();
      };
      ws.onmessage = (message) => {
        try {
          const parsed = JSON.parse(String(message.data)) as WsInboundEvent;
          listener(parsed);
        } catch {
          listener({ type: "server.error", payload: { message: "invalid message format" } });
        }
      };
      ws.onerror = () => {
        this.connectPromise = null;
        reject(new Error("websocket connection failed"));
      };
      ws.onclose = () => {
        this.connectPromise = null;
        this.socket = null;
        if (onClosed) {
          onClosed();
        }
      };
    });

    return this.connectPromise;
  }

  isConnected(): boolean {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  sendVadState(speaking: boolean): void {
    this.send({
      type: "client.vad.state",
      sequence: this.nextSequence(),
      event_id: this.newEventId(),
      payload: { speaking }
    });
  }

  sendAudioChunk(chunk: AudioChunk, transcriptHint?: string): void {
    const payload: Record<string, unknown> = {
      codec: chunk.codec,
      audio_base64: chunk.payload,
      content_type: chunk.contentType,
      sample_rate: chunk.sampleRate,
      channels: chunk.channels,
      utterance_duration_ms: chunk.durationMs,
      captured_at: chunk.createdAt
    };
    const hint = transcriptHint?.trim();
    if (hint) {
      payload.transcript_hint = hint;
    }

    this.send({
      type: "client.audio.chunk",
      sequence: this.nextSequence(),
      event_id: this.newEventId(),
      payload
    });
  }

  sendTextUtterance(text: string): void {
    const trimmed = text.trim();
    if (!trimmed) {
      return;
    }
    const utteranceDurationMs = Math.max(350, Math.min(4500, trimmed.length * 44));
    this.sendVadState(true);
    this.send({
      type: "client.audio.chunk",
      sequence: this.nextSequence(),
      event_id: this.newEventId(),
      payload: {
        transcript_hint: trimmed,
        codec: "opus",
        utterance_duration_ms: utteranceDurationMs
      }
    });
    this.sendVadState(false);
  }

  endSession(): void {
    this.send({
      type: "client.session.end",
      sequence: this.nextSequence(),
      event_id: this.newEventId(),
      payload: {}
    });
  }

  close(): void {
    this.socket?.close();
    this.socket = null;
    this.connectPromise = null;
  }

  private newEventId(): string {
    return `${this.sessionId}-client-${this.sequence}`;
  }

  private nextSequence(): number {
    const seq = this.sequence;
    this.sequence += 1;
    return seq;
  }

  private send(event: Record<string, unknown>): void {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      return;
    }
    this.socket.send(JSON.stringify(event));
  }
}
