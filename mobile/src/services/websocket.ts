import { WS_BASE_URL } from "./config";
import { WsInboundEvent } from "../types";

type Listener = (event: WsInboundEvent) => void;

export class SessionWsClient {
  private socket: WebSocket | null = null;
  private sequence = 1;

  constructor(private readonly sessionId: string) {}

  connect(listener: Listener, onClosed?: () => void): Promise<void> {
    if (this.socket?.readyState === WebSocket.OPEN) {
      return Promise.resolve();
    }
    const url = `${WS_BASE_URL}/ws/sessions/${encodeURIComponent(this.sessionId)}`;

    return new Promise((resolve, reject) => {
      const ws = new WebSocket(url);
      this.socket = ws;

      ws.onopen = () => resolve();
      ws.onmessage = (message) => {
        try {
          const parsed = JSON.parse(String(message.data)) as WsInboundEvent;
          listener(parsed);
        } catch {
          listener({ type: "server.error", payload: { message: "invalid message format" } });
        }
      };
      ws.onerror = () => reject(new Error("websocket connection failed"));
      ws.onclose = () => {
        this.socket = null;
        if (onClosed) {
          onClosed();
        }
      };
    });
  }

  sendVadState(speaking: boolean) {
    this.send({
      type: "client.vad.state",
      sequence: this.nextSequence(),
      payload: { speaking }
    });
  }

  sendTextUtterance(text: string) {
    const trimmed = text.trim();
    if (!trimmed) {
      return;
    }
    const utteranceDurationMs = Math.max(350, Math.min(4500, trimmed.length * 44));
    this.sendVadState(true);
    this.send({
      type: "client.audio.chunk",
      sequence: this.nextSequence(),
      payload: {
        transcript_hint: trimmed,
        codec: "opus",
        utterance_duration_ms: utteranceDurationMs
      }
    });
    this.sendVadState(false);
  }

  endSession() {
    this.send({
      type: "client.session.end",
      sequence: this.nextSequence(),
      payload: {}
    });
  }

  close() {
    this.socket?.close();
    this.socket = null;
  }

  private nextSequence() {
    const seq = this.sequence;
    this.sequence += 1;
    return seq;
  }

  private send(event: Record<string, unknown>) {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      return;
    }
    this.socket.send(JSON.stringify(event));
  }
}
