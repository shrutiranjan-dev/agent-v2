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
            <strong>{event.event_type ?? event.type}</strong>
            <span>{new Date(event.created_at).toLocaleString()} · {event.severity}</span>
            {!props.compact && <code>{JSON.stringify(event.payload)}</code>}
          </div>
        </article>
      ))}
    </div>
  );
}
