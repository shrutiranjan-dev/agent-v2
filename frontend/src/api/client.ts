export type Session = {
  id: string;
  title: string;
  agent_id: string;
  model_name: string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type AgentRun = {
  id: string;
  status: string;
  error?: string | null;
  step_count?: number;
};

export type Message = {
  id: string;
  role: string;
  content: string;
  parts: unknown[];
  metadata: Record<string, unknown>;
  created_at: string;
};

export type ToolCall = {
  id: string;
  tool_name: string;
  input: Record<string, unknown>;
  status: string;
  output?: unknown;
  error?: string;
  permission_request_id?: string;
  created_at: string;
};

export type SessionSummary = {
  id: string;
  session_id: string;
  run_id?: string | null;
  summary_type: string;
  content: string;
  source_message_count: number;
  token_estimate?: number | null;
  char_count: number;
  model?: string | null;
  status: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type MemoryItem = {
  id: string;
  source_type: string;
  source_id?: string | null;
  content: string;
  content_hash: string;
  embedding_model?: string | null;
  visibility: string;
  status: string;
  score?: number | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type Permission = {
  id: string;
  session_id: string;
  agent_run_id?: string | null;
  tool_call_id?: string;
  permission_key: string;
  resource: string;
  status: string;
  input?: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string;
  resolved_at?: string | null;
};

export type HumanInputRequest = {
  id: string;
  human_input_request_id: string;
  session_id: string;
  run_id: string;
  agent_run_id: string;
  tool_call_id: string;
  question: string;
  details: Record<string, unknown>;
  status: string;
  answer?: string | null;
  answered_by?: string | null;
  choices: string[];
  allow_free_text: boolean;
  created_at: string;
  updated_at: string;
  answered_at?: string | null;
  expires_at?: string | null;
  cancelled_at?: string | null;
  metadata: Record<string, unknown>;
};

export type SystemEvent = {
  id: string;
  session_id?: string;
  type: string;
  event_type?: string;
  severity: string;
  agent_run_id?: string | null;
  tool_call_id?: string | null;
  payload: Record<string, unknown>;
  created_at: string;
};

export type CodeFile = {
  id: string;
  path: string;
  resolved_path: string;
  language?: string | null;
  size_bytes: number;
  sha256: string;
  line_count?: number | null;
  indexed_at?: string | null;
  status: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type CodeSymbol = {
  id: string;
  code_file_id: string;
  file_path?: string;
  name: string;
  kind: string;
  language?: string | null;
  start_line: number;
  end_line?: number | null;
  signature?: string | null;
  docstring?: string | null;
  parent_symbol_id?: string | null;
  metadata: Record<string, unknown>;
};

export type CodeDiagnostic = {
  id: string;
  code_file_id: string;
  file_path?: string;
  source: string;
  severity: string;
  code?: string | null;
  message: string;
  line: number;
  column?: number | null;
  end_line?: number | null;
  end_column?: number | null;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type CodeMap = {
  file_count: number;
  symbol_count: number;
  reference_count: number;
  diagnostic_count: number;
  languages: Record<string, number>;
  files: Array<Record<string, unknown>>;
};

export type CodeIntelHealth = {
  status: string;
  indexing_enabled: boolean;
  workspace_root: string;
  lsp: Record<string, unknown>;
};

export type McpServer = {
  id: string;
  name: string;
  server_type: string;
  command?: string | null;
  args: string[];
  url?: string | null;
  env: Record<string, unknown>;
  status: string;
  enabled: boolean;
  trusted: boolean;
  last_connected_at?: string | null;
  last_error?: string | null;
  metadata: Record<string, unknown>;
};

export type McpTool = {
  id: string;
  mcp_server_id: string;
  name: string;
  full_name: string;
  description?: string | null;
  input_schema: Record<string, unknown>;
  risk_level: string;
  enabled: boolean;
  discovered_at?: string | null;
  metadata: Record<string, unknown>;
};

export type Plugin = {
  id: string;
  name: string;
  version?: string | null;
  manifest_path?: string | null;
  source_type: string;
  status: string;
  enabled: boolean;
  trusted: boolean;
  capabilities: string[];
  hooks: string[];
  last_loaded_at?: string | null;
  last_error?: string | null;
  metadata: Record<string, unknown>;
};

export type PluginTool = {
  id: string;
  plugin_id: string;
  name: string;
  full_name: string;
  description?: string | null;
  input_schema: Record<string, unknown>;
  risk_level: string;
  enabled: boolean;
  metadata: Record<string, unknown>;
};

export type ExtensionHealth = {
  status: string;
  enabled: boolean;
  [key: string]: unknown;
};

export type OllamaModel = Record<string, unknown> & {
  name?: string;
  model?: string;
  remote_model?: string;
  remote_host?: string;
  size?: number;
  modified_at?: string;
  capabilities?: ModelCapability;
};

export type ModelCapability = {
  name: string;
  provider: string;
  supports_json_protocol: boolean;
  supports_tools_native: boolean;
  context_window: number;
  recommended_for: string[];
  max_output_tokens: number;
  enabled: boolean;
};

export type Agent = Record<string, unknown> & {
  id: string;
  name: string;
  description: string;
  mode: string;
  max_steps: number;
  hidden?: boolean;
};

export type DependencyHealth = {
  status: string;
  dependencies: Record<string, { status: string; error?: string; [key: string]: unknown }>;
};

export type QueueStats = {
  queued: number;
  claimed: number;
  running: number;
  completed: number;
  failed: number;
  dead_letter: number;
  cancelled: number;
  retry_scheduled: number;
  oldest_queued_age_seconds?: number | null;
  total: number;
};

export type QueueJob = {
  id: string;
  queue_job_id: string;
  job_type: string;
  status: string;
  priority: number;
  run_id?: string | null;
  session_id?: string | null;
  permission_request_id?: string | null;
  human_input_request_id?: string | null;
  user_message_id?: string | null;
  idempotency_key: string;
  attempt_count: number;
  max_attempts: number;
  claimed_by?: string | null;
  claimed_at?: string | null;
  available_at: string;
  completed_at?: string | null;
  failed_at?: string | null;
  last_error?: string | null;
  created_at: string;
  updated_at: string;
};

export type QueueWorker = {
  id: string;
  worker_id: string;
  hostname?: string | null;
  process_id?: number | null;
  status: string;
  current_queue_job_id?: string | null;
  current_run_id?: string | null;
  claimed_jobs_count: number;
  completed_jobs_count: number;
  failed_jobs_count: number;
  last_heartbeat_at: string;
  last_heartbeat_age_seconds: number;
  started_at?: string | null;
  stopped_at?: string | null;
  stale: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type Artifact = {
  id: string;
  name: string;
  kind: string;
  session_id?: string | null;
  tool_call_id?: string | null;
  content_type?: string | null;
  size_bytes?: number | null;
  checksum?: string | null;
  metadata: Record<string, unknown>;
  download_url?: string | null;
  download_status: string;
  created_at: string;
};

export type FileChange = {
  id: string;
  session_id: string;
  agent_run_id?: string | null;
  tool_call_id?: string | null;
  tool_name: string;
  operation: string;
  relative_path: string;
  before_sha256?: string | null;
  after_sha256?: string | null;
  before_size_bytes?: number | null;
  after_size_bytes?: number | null;
  additions: number;
  deletions: number;
  replacement_count: number;
  backup_path?: string | null;
  redacted: boolean;
  redaction_reason?: string | null;
  revertible: boolean;
  revert_status: string;
  reverted_at?: string | null;
  reverted_by_user_id?: string | null;
  revert_tool_call_id?: string | null;
  revert_error?: string | null;
  metadata: Record<string, unknown>;
  diff?: string | null;
  diff_truncated?: boolean;
  before_content?: string | null;
  after_content?: string | null;
  before_content_truncated?: boolean;
  after_content_truncated?: boolean;
  created_at: string;
  updated_at: string;
};

export type SessionDetail = {
  session: Session;
  messages: Message[];
  tool_calls: ToolCall[];
  summaries?: SessionSummary[];
  agent_runs?: AgentRun[];
  model_calls?: Array<Record<string, unknown>>;
};

export type PermissionReplyResponse = {
  permission: Permission;
  agent_run: AgentRun;
  queue_job?: Record<string, unknown>;
};

export type HumanInputReplyResponse = {
  request: HumanInputRequest;
  agent_run: AgentRun;
  queue_job?: Record<string, unknown>;
};

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
export const WS_BASE = import.meta.env.VITE_WS_BASE_URL ?? "ws://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(init?.headers ?? {})
    }
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || response.statusText);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string }>("/health"),
  dependencies: () => request<DependencyHealth>("/health/dependencies"),
  models: () => request<{ provider: string; models: OllamaModel[] }>("/models"),
  agents: () => request<{ agents: Agent[] }>("/agents?include_hidden=true"),
  tools: () => request<{ tools: Array<Record<string, unknown>> }>("/tools"),
  sessions: () => request<{ sessions: Session[] }>("/sessions"),
  createSession: (body: { title: string; agent_id: string; model_name?: string }) =>
    request<{ session: Session }>("/sessions", { method: "POST", body: JSON.stringify(body) }),
  session: (id: string) => request<SessionDetail>(`/sessions/${id}`),
  sendMessage: (id: string, content: string, agent_id?: string, model_name?: string) =>
    request<SessionDetail & { agent_run: AgentRun; queue_job?: Record<string, unknown> }>(
      `/sessions/${id}/messages`,
      { method: "POST", body: JSON.stringify({ content, agent_id, model_name }) }
    ),
  sessionEvents: (id: string) => request<{ events: SystemEvent[] }>(`/sessions/${id}/events`),
  sessionSummaries: (id: string) => request<{ summaries: SessionSummary[] }>(`/sessions/${id}/summaries`),
  createSessionSummary: (id: string, body: { content?: string; summary_type?: string; metadata?: Record<string, unknown> }) =>
    request<{ summary: SessionSummary }>(`/sessions/${id}/summaries`, {
      method: "POST",
      body: JSON.stringify(body)
    }),
  sessionMemory: (id: string) => request<{ memory_items: MemoryItem[] }>(`/sessions/${id}/memory`),
  memoryItems: (query?: string) => request<{ memory_items: MemoryItem[] }>(`/memory/items${query ? `?query=${encodeURIComponent(query)}` : ""}`),
  permissions: (sessionId?: string) =>
    request<{ permissions: Permission[] }>(`/permissions${sessionId ? `?session_id=${sessionId}` : ""}`),
  humanInputRequests: (sessionId?: string, status?: string) => {
    const params = new URLSearchParams();
    if (sessionId) params.set("session_id", sessionId);
    if (status) params.set("status", status);
    const query = params.toString();
    return request<{ requests: HumanInputRequest[] }>(`/human-input/requests${query ? `?${query}` : ""}`);
  },
  answerHumanInput: (id: string, answer: string) =>
    request<HumanInputReplyResponse>(`/human-input/${id}/answer`, {
      method: "POST",
      body: JSON.stringify({ answer })
    }),
  cancelHumanInput: (id: string, message?: string) =>
    request<HumanInputReplyResponse>(`/human-input/${id}/cancel`, {
      method: "POST",
      body: JSON.stringify({ message: message ?? null })
    }),
  approvePermission: (id: string, message?: string) =>
    request<PermissionReplyResponse>(`/permissions/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ message: message ?? null })
    }),
  denyPermission: (id: string, message?: string) =>
    request<PermissionReplyResponse>(`/permissions/${id}/deny`, {
      method: "POST",
      body: JSON.stringify({ message: message ?? null })
    }),
  approve: (id: string) =>
    request<PermissionReplyResponse>(`/permissions/${id}/approve`, { method: "POST", body: JSON.stringify({}) }),
  deny: (id: string) =>
    request<PermissionReplyResponse>(`/permissions/${id}/deny`, { method: "POST", body: JSON.stringify({}) }),
  artifacts: () => request<{ artifacts: Artifact[] }>("/artifacts"),
  artifact: (id: string) => request<{ artifact: Artifact }>(`/artifacts/${id}`),
  sessionArtifacts: (id: string) => request<{ artifacts: Artifact[] }>(`/sessions/${id}/artifacts`),
  events: () => request<{ events: SystemEvent[] }>("/system/events"),
  queueStats: () => request<{ stats: QueueStats; queue_enabled: boolean }>("/queue/stats"),
  queueJobs: () => request<{ jobs: QueueJob[] }>("/queue/jobs?limit=50"),
  queueWorkers: () => request<{ workers: QueueWorker[] }>("/queue/workers"),
  retryQueueJob: (id: string, reason = "manual_retry") =>
    request<{ job: QueueJob }>(`/queue/jobs/${id}/retry`, {
      method: "POST",
      body: JSON.stringify({ reason })
    }),
  cancelQueueJob: (id: string, reason = "manual_cancel") =>
    request<{ job: QueueJob }>(`/queue/jobs/${id}/cancel`, {
      method: "POST",
      body: JSON.stringify({ reason })
    }),
  codeIntelHealth: () => request<CodeIntelHealth>("/health/codeintel"),
  mcpHealth: () => request<ExtensionHealth>("/health/mcp"),
  pluginHealth: () => request<ExtensionHealth>("/health/plugins"),
  mcpServers: () => request<{ servers: McpServer[] }>("/mcp/servers"),
  mcpTools: () => request<{ tools: McpTool[] }>("/mcp/tools"),
  plugins: () => request<{ plugins: Plugin[] }>("/plugins"),
  pluginTools: () => request<{ tools: PluginTool[] }>("/plugins/tools"),
  codeIndex: (body: { workspace_path?: string | null; include?: string[]; exclude?: string[]; force?: boolean }) =>
    request<{ files_indexed: number; files_skipped: number; symbols_found: number; diagnostics_found: number; errors: string[] }>(
      "/code/index",
      { method: "POST", body: JSON.stringify(body) }
    ),
  codeFiles: () => request<{ files: CodeFile[] }>("/code/files?limit=100"),
  codeSymbols: (query?: string) =>
    request<{ symbols: CodeSymbol[] }>(`/code/symbols?limit=50${query ? `&query=${encodeURIComponent(query)}` : ""}`),
  codeDiagnostics: () => request<{ diagnostics: CodeDiagnostic[] }>("/code/diagnostics?limit=50"),
  codeMap: () => request<{ code_map: CodeMap }>("/code/map?depth=2&include_symbols=true"),
  fileChanges: (params: { sessionId?: string; runId?: string; path?: string; limit?: number } = {}) => {
    const search = new URLSearchParams();
    if (params.sessionId) search.set("session_id", params.sessionId);
    if (params.runId) search.set("run_id", params.runId);
    if (params.path) search.set("path", params.path);
    search.set("limit", String(params.limit ?? 100));
    const query = search.toString();
    return request<{ file_changes: FileChange[]; count: number }>(`/file-changes?${query}`);
  },
  fileChange: (id: string, includeContent = true) => {
    const search = new URLSearchParams({ include_content: String(includeContent) });
    return request<{ file_change: FileChange }>(`/file-changes/${id}?${search.toString()}`);
  },
  revertFileChange: (id: string, force = false, permissionRequestId?: string) =>
    request<{ file_change: FileChange }>(`/file-changes/${id}/revert`, {
      method: "POST",
      body: JSON.stringify({ force, ...(permissionRequestId ? { permission_request_id: permissionRequestId } : {}) })
    }),
  revertFileChangesBatch: (
    changeIds: string[],
    force = false,
    permissionRequestId?: string
  ) =>
    request<{ reverted: string[]; skipped: unknown[]; failed: unknown[]; restored_from_snapshots: boolean }>(
      "/file-changes/revert-batch",
      {
        method: "POST",
        body: JSON.stringify({
          change_ids: changeIds,
          force,
          ...(permissionRequestId ? { permission_request_id: permissionRequestId } : {})
        })
      }
    )
};
