import { Check, ShieldQuestion, X } from "lucide-react";
import { Permission } from "../api/client";

type PermissionPromptProps = {
  permission: Permission;
  busy?: "approve" | "deny";
  compact?: boolean;
  onApprove: (id: string) => void;
  onDeny: (id: string) => void;
};

export function PermissionPrompt(props: PermissionPromptProps) {
  const metadata = props.permission.metadata ?? {};
  const toolName = String(metadata.tool ?? props.permission.permission_key);
  const reason = metadata.reason ? String(metadata.reason) : "Runtime approval required before tool execution.";
  const riskLevel = metadata.risk_level ? String(metadata.risk_level) : "review";

  return (
    <article className={props.compact ? "chat-permission permission-card" : "permission-card"}>
      <header>
        <ShieldQuestion size={18} />
        <div>
          <strong>{toolName}</strong>
          <span>{props.permission.permission_key} · {riskLevel}</span>
        </div>
      </header>
      <p>{reason}</p>
      <dl>
        <div>
          <dt>Resource</dt>
          <dd>{props.permission.resource}</dd>
        </div>
        {props.permission.agent_run_id && (
          <div>
            <dt>Run</dt>
            <dd>{props.permission.agent_run_id}</dd>
          </div>
        )}
        <div>
          <dt>Input</dt>
          <dd><code>{JSON.stringify(props.permission.input ?? {})}</code></dd>
        </div>
      </dl>
      <footer>
        <button disabled={Boolean(props.busy)} onClick={() => props.onApprove(props.permission.id)}>
          <Check size={15} />
          {props.busy === "approve" ? "Approving" : "Approve"}
        </button>
        <button className="danger" disabled={Boolean(props.busy)} onClick={() => props.onDeny(props.permission.id)}>
          <X size={15} />
          {props.busy === "deny" ? "Denying" : "Deny"}
        </button>
      </footer>
    </article>
  );
}
