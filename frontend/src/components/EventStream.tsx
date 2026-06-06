import { Activity } from "lucide-react";

import { SystemEvent } from "../api/client";

export function EventStream(props: { events: SystemEvent[]; compact?: boolean; connectionStatus?: string }) {
  return (
    <div className={props.compact ? "mini-stack" : "event-stack"}>
      {props.connectionStatus && (
        <div className="connection-row">
          <Activity size={14} />
          <span>WebSocket {props.connectionStatus}</span>
        </div>
      )}
      {!props.events.length ? (
        <p className="muted-copy">No live events</p>
      ) : props.events.map((event) => (
        <article className={props.compact ? "chat-mini-row" : "event-row wide"} key={event.id}>
          <Activity size={16} />
          <div>
            <strong>{formatEventType(event)}</strong>
            <span>{new Date(event.created_at).toLocaleString()} / {event.severity}</span>
            <p className="event-summary">{summarizeEvent(event)}</p>
            {!props.compact && <code>{JSON.stringify(event.payload)}</code>}
          </div>
        </article>
      ))}
    </div>
  );
}

function formatEventType(event: SystemEvent) {
  return event.event_type ?? event.type;
}

function summarizeEvent(event: SystemEvent) {
  const type = formatEventType(event);
  const payload = event.payload ?? {};
  if (type.startsWith("queue_job.")) {
    const jobId = valueOrFallback(payload.queue_job_id, "queue job");
    const workerId = valueOrFallback(payload.worker_id, "");
    const reason = valueOrFallback(payload.reason, "");
    return [jobId, workerId, reason].filter(Boolean).join(" / ");
  }
  if (type.startsWith("worker.")) {
    const workerId = valueOrFallback(payload.worker_id, "worker");
    const status = valueOrFallback(payload.status, "");
    const currentJob = valueOrFallback(payload.current_queue_job_id, "");
    return [workerId, status, currentJob].filter(Boolean).join(" / ");
  }
  return Object.entries(payload)
    .slice(0, 3)
    .map(([key, value]) => `${key}: ${String(value)}`)
    .join(" / ");
}

function valueOrFallback(value: unknown, fallback: string) {
  if (typeof value === "string" && value.trim()) return value;
  return fallback;
}
