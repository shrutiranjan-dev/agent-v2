import { Loader2 } from "lucide-react";
import { Message } from "../api/client";

export function MessageList(props: { messages: Message[]; pending?: boolean; pendingLabel?: string; variant?: "light" | "dark" }) {
  const variant = props.variant ?? "light";
  return (
    <div className={variant === "dark" ? "chat-transcript" : "timeline"}>
      {!props.messages.length && !props.pending ? (
        <div className={variant === "dark" ? "chat-empty compact" : "empty-state"}>
          <strong>No messages yet</strong>
          <span>Send a prompt to start this session.</span>
        </div>
      ) : (
        props.messages.map((message) => (
          <article className={variant === "dark" ? `chat-message ${message.role}` : `message ${message.role}`} key={message.id}>
            <span>{message.role}</span>
            <pre>{message.content}</pre>
          </article>
        ))
      )}
      {props.pending && (
        <article className={variant === "dark" ? "chat-message assistant pending" : "message assistant pending"}>
          <span>assistant</span>
          <pre><Loader2 className="spin-icon" size={14} /> {props.pendingLabel ?? "Working"}</pre>
        </article>
      )}
    </div>
  );
}
