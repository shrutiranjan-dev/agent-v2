import { TerminalSquare } from "lucide-react";
import { ToolCall } from "../api/client";

export function ToolCallTimeline(props: { toolCalls: ToolCall[]; compact?: boolean }) {
  if (!props.toolCalls.length) {
    return <p className="muted-copy">No tool calls</p>;
  }

  return (
    <div className={props.compact ? "mini-stack" : "tool-stream"}>
      {props.toolCalls.map((call) => (
        <article className={props.compact ? "chat-mini-row" : "tool-row"} key={call.id}>
          <TerminalSquare size={16} />
          <div>
            <strong>{call.tool_name}</strong>
            <span>{call.status}</span>
            {!props.compact && <code>{JSON.stringify(call.input)}</code>}
            {!props.compact && call.error && <em>{call.error}</em>}
          </div>
        </article>
      ))}
    </div>
  );
}
