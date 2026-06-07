import { useMemo, useState } from "react";
import { AlertTriangle, FileClock, Loader2, RotateCcw, ShieldOff, Sparkles, Hourglass, ShieldCheck } from "lucide-react";
import { FileChange, api } from "../api/client";

type FileChangesPanelProps = {
  fileChanges: FileChange[];
  loading?: boolean;
  error?: string | undefined;
  onRefresh: () => void;
};

type RevertErrorState = {
  kind: "conflict" | "forbidden" | "error";
  message: string;
  changeId: string;
};

type WaitingPermissionState = {
  changeId: string;
  permissionRequestId: string;
  approvalNonce?: string;
};

export function FileChangesPanel({ fileChanges, loading, error, onRefresh }: FileChangesPanelProps) {
  const [selectedId, setSelectedId] = useState<string | undefined>();
  const [detail, setDetail] = useState<FileChange | undefined>();
  const [detailError, setDetailError] = useState<string | undefined>();
  const [busy, setBusy] = useState<Record<string, "revert">>({});
  const [revertError, setRevertError] = useState<RevertErrorState | undefined>();
  const [waitingPermission, setWaitingPermission] = useState<WaitingPermissionState | undefined>();

  const ordered = useMemo(
    () => [...fileChanges].sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? "")),
    [fileChanges]
  );

  const loadDetail = async (id: string) => {
    setSelectedId(id);
    setDetailError(undefined);
    try {
      const { file_change } = await api.fileChange(id, true);
      setDetail(file_change);
    } catch (err) {
      setDetail(undefined);
      setDetailError(err instanceof Error ? err.message : String(err));
    }
  };

  const classifyRevertError = (raw: string, changeId: string): RevertErrorState => {
    const lower = raw.toLowerCase();
    if (lower.includes("hash_mismatch") || lower.includes("already_reverted") || lower.includes("not_revertible")) {
      return { kind: "conflict", message: raw, changeId };
    }
    if (lower.includes("forbidden") || lower.includes("secret")) {
      return { kind: "forbidden", message: raw, changeId };
    }
    return { kind: "error", message: raw, changeId };
  };

  const revertChange = async (id: string, force: boolean, permissionRequestId?: string) => {
    setBusy((current) => ({ ...current, [id]: "revert" }));
    setRevertError(undefined);
    setWaitingPermission(undefined);
    try {
      const { file_change } = await api.revertFileChange(id, force, permissionRequestId);
      if (selectedId === id) {
        setDetail(file_change);
      }
      onRefresh();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (message.includes("permission_request_id")) {
        const match = message.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/);
        if (match) {
          setWaitingPermission({ changeId: id, permissionRequestId: match[0] });
          return;
        }
      }
      setRevertError(classifyRevertError(message, id));
    } finally {
      setBusy((current) => {
        const next = { ...current };
        delete next[id];
        return next;
      });
    }
  };

  const approveAndRetry = async (state: WaitingPermissionState) => {
    try {
      await api.approvePermission(state.permissionRequestId, "ui_approval");
      await revertChange(state.changeId, false, state.permissionRequestId);
    } catch (err) {
      setRevertError({
        kind: "error",
        message: err instanceof Error ? err.message : String(err),
        changeId: state.changeId,
      });
    }
  };

  if (loading) {
    return (
      <div className="card empty">
        <Loader2 className="spin" size={20} />
        <span>Loading file changes...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card empty error">
        <AlertTriangle size={20} />
        <span>{error}</span>
      </div>
    );
  }

  if (ordered.length === 0) {
    return (
      <div className="card empty">
        <Sparkles size={20} />
        <span>No file changes yet. Trigger a write.file, edit.file, or patch.apply to record one.</span>
      </div>
    );
  }

  return (
    <div className="card file-changes-panel">
      <div className="panel-header">
        <h3>
          <FileClock size={18} /> File Changes
        </h3>
        <span className="muted">{ordered.length} change(s)</span>
      </div>
      {revertError ? (
        <div className={`banner ${revertError.kind === "conflict" ? "warn" : "error"}`}>
          {revertError.kind === "conflict" ? <AlertTriangle size={14} /> : <ShieldOff size={14} />}
          <span>{revertError.message}</span>
        </div>
      ) : null}
      {waitingPermission ? (
        <div className="banner info">
          <Hourglass size={14} />
          <span>
            Revert is waiting for approval (permission_request_id=
            <code>{waitingPermission.permissionRequestId}</code>).
          </span>
          <button
            type="button"
            className="primary"
            onClick={() => approveAndRetry(waitingPermission)}
            disabled={Boolean(busy[waitingPermission.changeId])}
          >
            <ShieldCheck size={14} /> Approve and retry
          </button>
        </div>
      ) : null}
      <div className="file-changes-grid">
        <ul className="file-changes-list">
          {ordered.map((change) => {
            const status = change.revert_status;
            const revertible = change.revertible;
            const revertLabel =
              status === "reverted"
                ? "reverted"
                : status === "revert_failed"
                ? "failed"
                : revertible
                ? "available"
                : "not_revertible";
            return (
              <li
                key={change.id}
                className={selectedId === change.id ? "active" : ""}
                onClick={() => loadDetail(change.id)}
              >
                <div className="row">
                  <span className="tool">{change.tool_name}</span>
                  <span className="op">{change.operation}</span>
                  <span className={`revert revert-${revertLabel}`}>{revertLabel}</span>
                </div>
                <div className="path">{change.relative_path}</div>
                <div className="meta">
                  <span>+{change.additions}</span>
                  <span>-{change.deletions}</span>
                  {change.redacted ? <span className="redacted">redacted</span> : null}
                  <span className="muted">{change.created_at}</span>
                </div>
              </li>
            );
          })}
        </ul>
        <div className="file-changes-detail">
          {detail ? (
            <>
              <div className="panel-header">
                <h4>{detail.relative_path}</h4>
                <span className="muted">{detail.tool_name} / {detail.operation}</span>
              </div>
              <div className="detail-meta">
                <span>Revert: {detail.revert_status}</span>
                <span>Redacted: {detail.redacted ? "yes" : "no"}</span>
                <span>Before: {detail.before_sha256?.slice(0, 12) ?? "-"}</span>
                <span>After: {detail.after_sha256?.slice(0, 12) ?? "-"}</span>
              </div>
              {detail.diff ? (
                <pre className="diff">{detail.diff}</pre>
              ) : (
                <div className="empty muted">No diff recorded (redacted or no changes).</div>
              )}
              {detail.revertible && detail.revert_status === "not_reverted" ? (
                <div className="detail-actions">
                  <button
                    type="button"
                    className="primary"
                    disabled={Boolean(busy[detail.id])}
                    onClick={() => revertChange(detail.id, false)}
                  >
                    <RotateCcw size={14} /> Revert
                  </button>
                </div>
              ) : null}
              {!detail.revertible ? (
                <div className="banner warn">
                  <ShieldOff size={14} /> Revert unavailable: {detail.redaction_reason || "not revertible"}.
                </div>
              ) : null}
              {detail.revert_status === "reverted" ? (
                <div className="banner ok">Reverted at {detail.reverted_at}.</div>
              ) : null}
              {detail.revert_status === "revert_failed" ? (
                <div className="banner error">Revert failed: {detail.revert_error || "unknown error"}</div>
              ) : null}
            </>
          ) : (
            <div className="empty muted">
              {detailError ?? "Select a file change to view its diff and revert options."}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
