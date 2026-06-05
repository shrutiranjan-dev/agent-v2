import { SystemEvent, WS_BASE } from "./client";

export type SocketStatus = "connecting" | "open" | "closed" | "reconnecting" | "error";

type SessionSocketOptions = {
  sessionId: string;
  onEvent: (event: SystemEvent) => void;
  onStatus?: (status: SocketStatus) => void;
  onError?: (error: Error) => void;
};

export class SessionEventSocket {
  private socket?: WebSocket;
  private reconnectTimer?: number;
  private closedByClient = false;
  private attempt = 0;

  constructor(private readonly options: SessionSocketOptions) {}

  connect() {
    this.closedByClient = false;
    this.open();
  }

  close() {
    this.closedByClient = true;
    if (this.reconnectTimer) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = undefined;
    }
    this.socket?.close();
    this.options.onStatus?.("closed");
  }

  private open() {
    this.options.onStatus?.(this.attempt ? "reconnecting" : "connecting");
    const url = `${WS_BASE}/ws/sessions/${this.options.sessionId}`;
    const socket = new WebSocket(url);
    this.socket = socket;

    socket.onopen = () => {
      this.attempt = 0;
      this.options.onStatus?.("open");
    };

    socket.onmessage = (message) => {
      try {
        this.options.onEvent(JSON.parse(message.data) as SystemEvent);
      } catch (error) {
        this.options.onError?.(error instanceof Error ? error : new Error(String(error)));
      }
    };

    socket.onerror = () => {
      this.options.onStatus?.("error");
    };

    socket.onclose = () => {
      if (this.closedByClient) return;
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect() {
    this.attempt += 1;
    this.options.onStatus?.("reconnecting");
    const delayMs = Math.min(8000, 500 * 2 ** Math.min(this.attempt, 4));
    this.reconnectTimer = window.setTimeout(() => this.open(), delayMs);
  }
}
