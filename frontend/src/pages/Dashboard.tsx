import {
  Activity,
  AlertTriangle,
  BookOpenText,
  Bot,
  Box,
  Cpu,
  Database,
  FileCode2,
  FileClock,
  Loader2,
  MessageCircle,
  MessageSquare,
  Plug,
  Play,
  RefreshCw,
  Send,
  Server,
  ShieldQuestion,
  Search,
  TerminalSquare,
  Wrench
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  CodeDiagnostic,
  CodeSymbol,
  HumanInputRequest,
  McpServer,
  McpTool,
  OllamaModel,
  api,
  Permission,
  Plugin,
  PluginTool,
  SessionDetail,
  SystemEvent
} from "../api/client";
import { SessionEventSocket, SocketStatus } from "../api/sessionSocket";
import { EventStream } from "../components/EventStream";
import { HumanInputPrompt } from "../components/HumanInputPrompt";
import { MessageList } from "../components/MessageList";
import { PermissionPrompt } from "../components/PermissionPrompt";
import { StatusPill } from "../components/StatusPill";
import { ToolCallTimeline } from "../components/ToolCallTimeline";
import { usePolling } from "../stores/usePolling";

type Tab = "chat" | "sessions" | "agents" | "tools" | "permissions" | "models" | "code" | "extensions" | "artifacts" | "events";

const tabs: Array<{ id: Tab; label: string; icon: typeof Activity }> = [
  { id: "chat", label: "Chat", icon: MessageCircle },
  { id: "sessions", label: "Sessions", icon: MessageSquare },
  { id: "agents", label: "Agents", icon: Bot },
  { id: "tools", label: "Tools", icon: Wrench },
  { id: "permissions", label: "Permissions", icon: ShieldQuestion },
  { id: "models", label: "Ollama", icon: Server },
  { id: "code", label: "Code", icon: FileCode2 },
  { id: "extensions", label: "Extensions", icon: Plug },
  { id: "artifacts", label: "Artifacts", icon: Box },
  { id: "events", label: "Events", icon: FileClock }
];

export function Dashboard() {
  const [active, setActive] = useState<Tab>("sessions");
  const [selectedSessionId, setSelectedSessionId] = useState<string | undefined>();
  const [sessionDetail, setSessionDetail] = useState<SessionDetail>();
  const [liveEvents, setLiveEvents] = useState<SystemEvent[]>([]);
  const [wsStatus, setWsStatus] = useState<SocketStatus>("closed");
  const [chatSessionId, setChatSessionId] = useState<string | undefined>();
  const [selectedModel, setSelectedModel] = useState("");
  const [chatDraft, setChatDraft] = useState("");
  const [chatPending, setChatPending] = useState(false);
  const [chatError, setChatError] = useState<string | undefined>();
  const [busyPermissionIds, setBusyPermissionIds] = useState<Record<string, "approve" | "deny">>({});
  const [busyHumanInputIds, setBusyHumanInputIds] = useState<Record<string, "answer" | "cancel">>({});
  const [codeQuery, setCodeQuery] = useState("");
  const [codeIndexing, setCodeIndexing] = useState(false);
  const [codeError, setCodeError] = useState<string | undefined>();
  const [codeIndexResult, setCodeIndexResult] = useState<Record<string, unknown> | undefined>();
  const health = usePolling(api.dependencies, 15000);
  const sessions = usePolling(api.sessions, 5000);
  const agents = usePolling(api.agents, 30000);
  const tools = usePolling(api.tools, 30000);
  const permissions = usePolling(() => api.permissions(selectedSessionId), 4000);
  const humanInputs = usePolling(() => api.humanInputRequests(selectedSessionId, "pending"), 4000);
  const models = usePolling(api.models, 15000);
  const artifacts = usePolling(api.artifacts, 15000);
  const events = usePolling(api.events, 5000);
  const codeHealth = usePolling(api.codeIntelHealth, 15000);
  const codeMap = usePolling(api.codeMap, 15000);
  const codeSymbols = usePolling(() => api.codeSymbols(codeQuery || undefined), 8000);
  const codeDiagnostics = usePolling(api.codeDiagnostics, 12000);
  const mcpHealth = usePolling(api.mcpHealth, 15000);
  const pluginHealth = usePolling(api.pluginHealth, 15000);
  const mcpServers = usePolling(api.mcpServers, 15000);
  const mcpTools = usePolling(api.mcpTools, 15000);
  const pluginRows = usePolling(api.plugins, 15000);
  const pluginTools = usePolling(api.pluginTools, 15000);

  const installedModels = useMemo(() => {
    const names = (models.data?.models ?? []).map(modelName).filter((name): name is string => Boolean(name));
    return Array.from(new Set(names));
  }, [models.data]);

  const selectedSession = useMemo(
    () => sessions.data?.sessions.find((item) => item.id === selectedSessionId),
    [selectedSessionId, sessions.data]
  );

  const chatSession = useMemo(() => {
    if (!chatSessionId) return undefined;
    return sessions.data?.sessions.find((item) => item.id === chatSessionId) ??
      (sessionDetail?.session.id === chatSessionId ? sessionDetail.session : undefined);
  }, [chatSessionId, sessionDetail, sessions.data]);

  useEffect(() => {
    if (selectedSessionId || !sessions.data?.sessions.length) return;
    setSelectedSessionId(sessions.data.sessions[0].id);
  }, [selectedSessionId, sessions.data]);

  useEffect(() => {
    if (active !== "chat" || !chatSessionId || selectedSessionId === chatSessionId) return;
    setSelectedSessionId(chatSessionId);
  }, [active, chatSessionId, selectedSessionId]);

  useEffect(() => {
    if (!installedModels.length) {
      if (selectedModel) setSelectedModel("");
      return;
    }
    if (selectedModel && installedModels.includes(selectedModel)) return;
    const sessionModel = selectedSession?.model_name;
    setSelectedModel(sessionModel && installedModels.includes(sessionModel) ? sessionModel : installedModels[0]);
  }, [installedModels, selectedModel, selectedSession?.model_name]);

  useEffect(() => {
    if (!selectedSessionId) return;
    void api.session(selectedSessionId).then(setSessionDetail);
    void api.sessionEvents(selectedSessionId).then((result) => {
      setLiveEvents((items) => mergeEvents([...result.events, ...items]).slice(0, 80));
    });
    const socket = new SessionEventSocket({
      sessionId: selectedSessionId,
      onStatus: setWsStatus,
      onEvent: (event) => {
        setLiveEvents((items) => mergeEvents([event, ...items]).slice(0, 80));
        void api.session(selectedSessionId).then(setSessionDetail);
        void permissions.refresh();
        void humanInputs.refresh();
      },
      onError: (error) => setChatError(error.message)
    });
    socket.connect();
    return () => socket.close();
  }, [selectedSessionId]);

  const chatMessages = chatSessionId && selectedSessionId === chatSessionId ? sessionDetail?.messages ?? [] : [];
  const chatToolCalls = chatSessionId && selectedSessionId === chatSessionId ? sessionDetail?.tool_calls ?? [] : [];
  const chatEvents = chatSessionId ? liveEvents.filter((event) => event.session_id === chatSessionId).slice(0, 8) : [];
  const chatPermissions = (permissions.data?.permissions ?? [])
    .filter((permission) => permission.session_id === chatSessionId && permission.status === "pending");
  const selectedPermissions = (permissions.data?.permissions ?? [])
    .filter((permission) => permission.session_id === selectedSessionId && permission.status === "pending");
  const chatHumanInputs = (humanInputs.data?.requests ?? [])
    .filter((request) => request.session_id === chatSessionId && request.status === "pending");
  const selectedHumanInputs = (humanInputs.data?.requests ?? [])
    .filter((request) => request.session_id === selectedSessionId && request.status === "pending");
  const selectedSummaries = sessionDetail?.summaries ?? [];

  async function createSession() {
    const created = await api.createSession({ title: `Session ${new Date().toLocaleTimeString()}`, agent_id: "build" });
    setSelectedSessionId(created.session.id);
    await sessions.refresh();
  }

  async function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const content = String(form.get("content") ?? "").trim();
    const agent = String(form.get("agent") ?? "build");
    if (!content || !selectedSessionId) return;
    event.currentTarget.reset();
    const result = await api.sendMessage(selectedSessionId, content, agent);
    setSessionDetail({ session: result.session, messages: result.messages, tool_calls: result.tool_calls });
    await sessions.refresh();
    await permissions.refresh();
    await humanInputs.refresh();
  }

  async function sendChatMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = chatDraft.trim();
    if (!content || !selectedModel || chatPending) return;

    setChatPending(true);
    setChatError(undefined);
    try {
      let sessionId = chatSessionId;
      if (!sessionId) {
        const created = await api.createSession({
          title: `Chat ${new Date().toLocaleTimeString()}`,
          agent_id: "general",
          model_name: selectedModel
        });
        sessionId = created.session.id;
        setChatSessionId(sessionId);
        setSelectedSessionId(sessionId);
      }

      const result = await api.sendMessage(sessionId, content, "general", selectedModel);
      setSessionDetail({ session: result.session, messages: result.messages, tool_calls: result.tool_calls });
      setChatDraft("");
      if (result.agent_run.error) {
        setChatError(String(result.agent_run.error));
      }
      await sessions.refresh();
      await permissions.refresh();
      await humanInputs.refresh();
    } catch (err) {
      setChatError(err instanceof Error ? err.message : String(err));
    } finally {
      setChatPending(false);
    }
  }

  async function approvePermission(id: string) {
    if (busyPermissionIds[id]) return;
    setBusyPermissionIds((items) => ({ ...items, [id]: "approve" }));
    try {
      const result = await api.approvePermission(id);
      await refreshRuntime(result.agent_run?.status);
    } catch (err) {
      setChatError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyPermissionIds((items) => {
        const next = { ...items };
        delete next[id];
        return next;
      });
    }
  }

  async function denyPermission(id: string) {
    if (busyPermissionIds[id]) return;
    setBusyPermissionIds((items) => ({ ...items, [id]: "deny" }));
    try {
      const result = await api.denyPermission(id);
      await refreshRuntime(result.agent_run?.status);
    } catch (err) {
      setChatError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyPermissionIds((items) => {
        const next = { ...items };
        delete next[id];
        return next;
      });
    }
  }

  async function answerHumanInput(id: string, answer: string) {
    if (busyHumanInputIds[id]) return;
    setBusyHumanInputIds((items) => ({ ...items, [id]: "answer" }));
    try {
      const result = await api.answerHumanInput(id, answer);
      await refreshRuntime(result.agent_run?.status);
    } catch (err) {
      setChatError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyHumanInputIds((items) => {
        const next = { ...items };
        delete next[id];
        return next;
      });
    }
  }

  async function cancelHumanInput(id: string) {
    if (busyHumanInputIds[id]) return;
    setBusyHumanInputIds((items) => ({ ...items, [id]: "cancel" }));
    try {
      const result = await api.cancelHumanInput(id);
      await refreshRuntime(result.agent_run?.status);
    } catch (err) {
      setChatError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyHumanInputIds((items) => {
        const next = { ...items };
        delete next[id];
        return next;
      });
    }
  }

  async function runCodeIndex() {
    if (codeIndexing) return;
    setCodeIndexing(true);
    setCodeError(undefined);
    try {
      const result = await api.codeIndex({ force: false });
      setCodeIndexResult(result);
      await codeMap.refresh();
      await codeSymbols.refresh();
      await codeDiagnostics.refresh();
      await codeHealth.refresh();
    } catch (err) {
      setCodeError(err instanceof Error ? err.message : String(err));
    } finally {
      setCodeIndexing(false);
    }
  }

  async function refreshRuntime(status?: string) {
    if (selectedSessionId) {
      await api.session(selectedSessionId).then(setSessionDetail);
    }
    await permissions.refresh();
    await humanInputs.refresh();
    await sessions.refresh();
    if (status === "failed") setChatPending(false);
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <Database size={22} />
          <div>
            <strong>Local Agent Platform</strong>
            <span>Ollama runtime</span>
          </div>
        </div>
        <nav>
          {tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <button key={tab.id} className={active === tab.id ? "active" : ""} onClick={() => setActive(tab.id)}>
                <Icon size={18} />
                {tab.label}
              </button>
            );
          })}
        </nav>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <span className="eyebrow">Production local-first runtime</span>
            <h1>{tabs.find((tab) => tab.id === active)?.label}</h1>
          </div>
          <button className="icon-button" onClick={() => window.location.reload()} aria-label="Refresh">
            <RefreshCw size={18} />
          </button>
        </header>

        <section className="health-strip">
          {Object.entries(health.data?.dependencies ?? {}).map(([name, status]) => (
            <div className="health-item" key={name}>
              <span>{name}</span>
              <StatusPill value={status.status} />
            </div>
          ))}
        </section>

        {active === "chat" && (
          <section className="chat-shell">
            <div className="chat-panel">
              <header className="chat-toolbar">
                <div className="chat-title">
                  <MessageCircle size={20} />
                  <div>
                    <h2>Local chat</h2>
                    <span>general · {chatPending ? "running" : chatSession?.status ?? "idle"}</span>
                  </div>
                </div>
                <label className="model-picker">
                  <Cpu size={16} />
                  <select
                    aria-label="Ollama model"
                    disabled={!installedModels.length || chatPending}
                    value={selectedModel}
                    onChange={(event) => {
                      setSelectedModel(event.target.value);
                      setChatError(undefined);
                    }}
                  >
                    {!installedModels.length && <option value="">No local models</option>}
                    {installedModels.map((model) => (
                      <option key={model} value={model}>{model}</option>
                    ))}
                  </select>
                </label>
              </header>

              {chatError && (
                <div className="chat-error">
                  <AlertTriangle size={16} />
                  <span>{chatError}</span>
                </div>
              )}

              {!chatMessages.length && !chatPending ? (
                <div className="chat-transcript">
                {!chatMessages.length ? (
                  <div className="chat-empty">
                    <TerminalSquare size={24} />
                    <strong>{installedModels.length ? "Ready" : "No local Ollama models installed"}</strong>
                    <span>
                      {installedModels.length
                        ? `general · ${selectedModel}`
                        : models.error ?? "Pull a model before starting a chat."}
                    </span>
                    {!installedModels.length && (
                      <button type="button" onClick={() => setActive("models")}>Open Ollama</button>
                    )}
                  </div>
                ) : null}
                </div>
              ) : (
                <MessageList
                  messages={chatMessages}
                  pending={chatPending}
                  pendingLabel={`Thinking with ${selectedModel}`}
                  variant="dark"
                />
              )}

              <form className="chat-composer" onSubmit={sendChatMessage}>
                <textarea
                  value={chatDraft}
                  onChange={(event) => setChatDraft(event.target.value)}
                  placeholder={installedModels.length ? "Message the local agent" : "Pull an Ollama model first"}
                  disabled={!installedModels.length || chatPending}
                />
                <button type="submit" disabled={!chatDraft.trim() || !selectedModel || chatPending}>
                  {chatPending ? <Loader2 className="spin-icon" size={17} /> : <Send size={17} />}
                  Send
                </button>
              </form>
            </div>

            <aside className="chat-sidecar">
              <section>
                <h2>Human input</h2>
                {chatHumanInputs.length ? chatHumanInputs.map((request: HumanInputRequest) => (
                  <HumanInputPrompt
                    compact
                    key={request.id}
                    request={request}
                    busy={busyHumanInputIds[request.id]}
                    onAnswer={answerHumanInput}
                    onCancel={cancelHumanInput}
                  />
                )) : <p>No pending questions</p>}
              </section>

              <section>
                <h2>Permissions</h2>
                {chatPermissions.length ? chatPermissions.map((permission: Permission) => (
                  <PermissionPrompt
                    compact
                    key={permission.id}
                    permission={permission}
                    busy={busyPermissionIds[permission.id]}
                    onApprove={approvePermission}
                    onDeny={denyPermission}
                  />
                )) : <p>No pending prompts</p>}
              </section>

              <section>
                <h2>Tool calls</h2>
                <ToolCallTimeline compact toolCalls={chatToolCalls.slice(0, 8)} />
              </section>

              <section>
                <h2>Live events</h2>
                <EventStream compact connectionStatus={wsStatus} events={chatEvents} />
              </section>
            </aside>
          </section>
        )}

        {active === "sessions" && (
          <section className="split-view">
            <div className="list-panel">
              <div className="panel-head">
                <h2>Sessions</h2>
                <button onClick={createSession}>
                  <Play size={16} />
                  New
                </button>
              </div>
              {(sessions.data?.sessions ?? []).map((session) => (
                <button
                  key={session.id}
                  className={`session-row ${session.id === selectedSessionId ? "selected" : ""}`}
                  onClick={() => setSelectedSessionId(session.id)}
                >
                  <strong>{session.title}</strong>
                  <span>{session.agent_id} · {session.model_name}</span>
                  <StatusPill value={session.status} />
                </button>
              ))}
            </div>

            <div className="detail-panel">
              <div className="panel-head">
                <div>
                  <h2>{selectedSession?.title ?? "Session detail"}</h2>
                  <span className="muted-copy">WebSocket {wsStatus}</span>
                </div>
                {sessionDetail?.session && <StatusPill value={sessionDetail.session.status} />}
              </div>
              <form className="composer" onSubmit={sendMessage}>
                <select name="agent" defaultValue={selectedSession?.agent_id ?? "build"}>
                  {(agents.data?.agents ?? []).filter((agent) => !agent.hidden).map((agent) => (
                    <option key={String(agent.id)} value={String(agent.id)}>{String(agent.id)}</option>
                  ))}
                </select>
                <input name="content" placeholder="Send a task to the selected agent" />
                <button type="submit">
                  <MessageSquare size={16} />
                  Send
                </button>
              </form>
              {selectedPermissions.length > 0 && (
                <section className="permission-stack">
                  <h3>Permission prompts</h3>
                  {selectedPermissions.map((permission) => (
                    <PermissionPrompt
                      key={permission.id}
                      permission={permission}
                      busy={busyPermissionIds[permission.id]}
                      onApprove={approvePermission}
                      onDeny={denyPermission}
                    />
                  ))}
                </section>
              )}
              {selectedHumanInputs.length > 0 && (
                <section className="permission-stack">
                  <h3>Human input prompts</h3>
                  {selectedHumanInputs.map((request) => (
                    <HumanInputPrompt
                      key={request.id}
                      request={request}
                      busy={busyHumanInputIds[request.id]}
                      onAnswer={answerHumanInput}
                      onCancel={cancelHumanInput}
                    />
                  ))}
                </section>
              )}
              {selectedSummaries.length > 0 && (
                <section className="summary-stack">
                  <div className="summary-stack-head">
                    <BookOpenText size={16} />
                    <h3>Session summaries</h3>
                  </div>
                  {selectedSummaries.map((summary) => (
                    <article className="summary-card" key={summary.id}>
                      <div>
                        <strong>{summary.summary_type}</strong>
                        <span>{summary.source_message_count} messages · {summary.char_count} chars</span>
                      </div>
                      <p>{summary.content}</p>
                    </article>
                  ))}
                </section>
              )}
              <MessageList messages={sessionDetail?.messages ?? []} />
              <div className="tool-stream">
                <h3>Tool calls</h3>
                <ToolCallTimeline toolCalls={sessionDetail?.tool_calls ?? []} />
              </div>
            </div>

            <div className="event-panel">
              <h2>Live events</h2>
              <EventStream compact connectionStatus={wsStatus} events={liveEvents} />
            </div>
          </section>
        )}

        {active === "agents" && (
          <Grid items={(agents.data?.agents ?? []).map((agent) => ({
            title: String(agent.name),
            subtitle: `${agent.mode}${agent.hidden ? " · hidden" : ""}`,
            body: String(agent.description ?? ""),
            meta: [`steps ${agent.max_steps}`, String(agent.permission_profile)]
          }))} />
        )}

        {active === "tools" && (
          <Grid items={(tools.data?.tools ?? []).map((tool) => ({
            title: String(tool.name),
            subtitle: String(tool.permission_key),
            body: String(tool.description),
            meta: [`timeout ${tool.timeout_seconds}s`]
          }))} />
        )}

        {active === "permissions" && (
          <section className="table-panel">
            {(permissions.data?.permissions ?? []).map((permission: Permission) => (
              <PermissionPrompt
                key={permission.id}
                permission={permission}
                busy={busyPermissionIds[permission.id]}
                onApprove={approvePermission}
                onDeny={denyPermission}
              />
            ))}
          </section>
        )}

        {active === "models" && (
          <Grid items={(models.data?.models ?? []).map((model) => ({
            title: String(model.name ?? model.model ?? "model"),
            subtitle: "ollama",
            body: `size ${String(model.size ?? "unknown")}`,
            meta: [String(model.modified_at ?? "")]
          }))} />
        )}

        {active === "code" && (
          <section className="code-panel">
            <div className="code-hero">
              <div>
                <span className="eyebrow">Workspace index</span>
                <h2>Code intelligence</h2>
                <p>{String(codeHealth.data?.workspace_root ?? "")}</p>
              </div>
              <div className="code-actions">
                <StatusPill value={String(codeHealth.data?.lsp?.status ?? codeHealth.data?.status ?? "unknown")} />
                <button type="button" onClick={runCodeIndex} disabled={codeIndexing}>
                  {codeIndexing ? <Loader2 className="spin-icon" size={16} /> : <Search size={16} />}
                  Index
                </button>
              </div>
            </div>
            {codeError && (
              <div className="inline-error">
                <AlertTriangle size={16} />
                <span>{codeError}</span>
              </div>
            )}
            <div className="code-metrics">
              <Metric label="Files" value={String(codeMap.data?.code_map.file_count ?? 0)} />
              <Metric label="Symbols" value={String(codeMap.data?.code_map.symbol_count ?? 0)} />
              <Metric label="References" value={String(codeMap.data?.code_map.reference_count ?? 0)} />
              <Metric label="Diagnostics" value={String(codeMap.data?.code_map.diagnostic_count ?? 0)} />
            </div>
            {codeIndexResult && (
              <code className="code-result">{JSON.stringify(codeIndexResult)}</code>
            )}
            <div className="code-grid">
              <section>
                <div className="panel-head">
                  <h2>Languages</h2>
                </div>
                <div className="tag-list">
                  {Object.entries(codeMap.data?.code_map.languages ?? {}).map(([language, count]) => (
                    <code key={language}>{language}: {count}</code>
                  ))}
                  {!Object.keys(codeMap.data?.code_map.languages ?? {}).length && <p className="muted-copy">No index yet</p>}
                </div>
              </section>
              <section>
                <div className="panel-head">
                  <h2>Symbols</h2>
                  <input
                    aria-label="Search symbols"
                    value={codeQuery}
                    onChange={(event) => setCodeQuery(event.target.value)}
                    placeholder="Search"
                  />
                </div>
                <div className="code-list">
                  {(codeSymbols.data?.symbols ?? []).map((symbol: CodeSymbol) => (
                    <article key={symbol.id}>
                      <strong>{symbol.name}</strong>
                      <span>{symbol.kind} · {symbol.file_path}:{symbol.start_line}</span>
                    </article>
                  ))}
                  {!codeSymbols.data?.symbols.length && <p className="muted-copy">No symbols found</p>}
                </div>
              </section>
              <section>
                <div className="panel-head">
                  <h2>Diagnostics</h2>
                </div>
                <div className="code-list">
                  {(codeDiagnostics.data?.diagnostics ?? []).map((diagnostic: CodeDiagnostic) => (
                    <article key={diagnostic.id}>
                      <strong>{diagnostic.severity}</strong>
                      <span>{diagnostic.file_path}:{diagnostic.line} · {diagnostic.message}</span>
                    </article>
                  ))}
                  {!codeDiagnostics.data?.diagnostics.length && <p className="muted-copy">No diagnostics ingested</p>}
                </div>
              </section>
              <section>
                <div className="panel-head">
                  <h2>Top files</h2>
                </div>
                <div className="code-list">
                  {(codeMap.data?.code_map.files ?? []).slice(0, 12).map((file) => (
                    <article key={String(file.path)}>
                      <strong>{String(file.path)}</strong>
                      <span>{String(file.language ?? "unknown")} · {String(file.symbol_count ?? 0)} symbols</span>
                    </article>
                  ))}
                  {!codeMap.data?.code_map.files.length && <p className="muted-copy">Run index to populate files</p>}
                </div>
              </section>
            </div>
          </section>
        )}

        {active === "extensions" && (
          <section className="extensions-panel">
            <div className="code-metrics">
              <Metric label="MCP" value={String(mcpHealth.data?.status ?? "unknown")} />
              <Metric label="MCP servers" value={String(mcpHealth.data?.server_count ?? 0)} />
              <Metric label="Plugins" value={String(pluginHealth.data?.status ?? "unknown")} />
              <Metric label="Plugin count" value={String(pluginHealth.data?.plugin_count ?? 0)} />
            </div>
            <div className="code-grid">
              <section>
                <div className="panel-head">
                  <h2>MCP servers</h2>
                  <StatusPill value={String(mcpHealth.data?.status ?? "unknown")} />
                </div>
                <div className="code-list">
                  {(mcpServers.data?.servers ?? []).map((server: McpServer) => (
                    <article key={server.id}>
                      <strong>{server.name}</strong>
                      <span>{server.server_type} · {server.enabled ? "enabled" : "disabled"} · {server.trusted ? "trusted" : "untrusted"}</span>
                      {server.last_error && <em>{server.last_error}</em>}
                    </article>
                  ))}
                  {!mcpServers.data?.servers.length && <p className="muted-copy">No MCP servers configured</p>}
                </div>
              </section>
              <section>
                <div className="panel-head">
                  <h2>MCP tools</h2>
                </div>
                <div className="code-list">
                  {(mcpTools.data?.tools ?? []).map((tool: McpTool) => (
                    <article key={tool.id}>
                      <strong>{tool.full_name}</strong>
                      <span>{tool.risk_level} · {tool.enabled ? "enabled" : "disabled"}</span>
                    </article>
                  ))}
                  {!mcpTools.data?.tools.length && <p className="muted-copy">No MCP tools discovered</p>}
                </div>
              </section>
              <section>
                <div className="panel-head">
                  <h2>Plugins</h2>
                  <StatusPill value={String(pluginHealth.data?.status ?? "unknown")} />
                </div>
                <div className="code-list">
                  {(pluginRows.data?.plugins ?? []).map((plugin: Plugin) => (
                    <article key={plugin.id}>
                      <strong>{plugin.name}</strong>
                      <span>{plugin.status} · {plugin.enabled ? "enabled" : "disabled"} · {plugin.trusted ? "trusted" : "untrusted"}</span>
                      {plugin.last_error && <em>{plugin.last_error}</em>}
                    </article>
                  ))}
                  {!pluginRows.data?.plugins.length && <p className="muted-copy">No plugins loaded</p>}
                </div>
              </section>
              <section>
                <div className="panel-head">
                  <h2>Plugin tools</h2>
                </div>
                <div className="code-list">
                  {(pluginTools.data?.tools ?? []).map((tool: PluginTool) => (
                    <article key={tool.id}>
                      <strong>{tool.full_name}</strong>
                      <span>{tool.risk_level} · {tool.enabled ? "enabled" : "disabled"}</span>
                    </article>
                  ))}
                  {!pluginTools.data?.tools.length && <p className="muted-copy">No plugin tools registered</p>}
                </div>
              </section>
            </div>
          </section>
        )}

        {active === "artifacts" && (
          <Grid items={(artifacts.data?.artifacts ?? []).map((artifact) => ({
            title: String(artifact.name),
            subtitle: String(artifact.kind),
            body: String(artifact.object_key),
            meta: [String(artifact.content_type ?? ""), String(artifact.size_bytes ?? "")]
          }))} />
        )}

        {active === "events" && (
          <section className="event-list">
            {(events.data?.events ?? []).map((event) => (
              <article className="event-row wide" key={event.id}>
                <Activity size={16} />
                <div>
                  <strong>{event.type}</strong>
                  <span>{new Date(event.created_at).toLocaleString()} · {event.severity}</span>
                  <code>{JSON.stringify(event.payload)}</code>
                </div>
              </article>
            ))}
          </section>
        )}
      </section>
    </main>
  );
}

function modelName(model: OllamaModel) {
  const name = model.name ?? model.model;
  return typeof name === "string" && name.trim() ? name : undefined;
}

function mergeEvents(events: SystemEvent[]) {
  const seen = new Set<string>();
  return events.filter((event) => {
    if (seen.has(event.id)) return false;
    seen.add(event.id);
    return true;
  });
}

function Grid(props: { items: Array<{ title: string; subtitle: string; body: string; meta: string[] }> }) {
  return (
    <section className="grid-panel">
      {props.items.map((item) => (
        <article className="item-card" key={`${item.title}-${item.subtitle}`}>
          <div>
            <strong>{item.title}</strong>
            <span>{item.subtitle}</span>
          </div>
          <p>{item.body}</p>
          <footer>{item.meta.filter(Boolean).map((meta) => <code key={meta}>{meta}</code>)}</footer>
        </article>
      ))}
    </section>
  );
}

function Metric(props: { label: string; value: string }) {
  return (
    <article className="metric-card">
      <span>{props.label}</span>
      <strong>{props.value}</strong>
    </article>
  );
}
