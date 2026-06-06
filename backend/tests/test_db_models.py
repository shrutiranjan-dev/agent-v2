from backend.app.db.models import (
    AgentRun,
    CodeDiagnostic,
    CodeFile,
    CodeReference,
    CodeSymbol,
    HumanInputRequest,
    McpServer,
    McpTool,
    MemoryItem,
    Message,
    ModelCall,
    Plugin,
    PluginTool,
    QueueJobRecord,
    Session,
    SessionSummary,
    SystemEvent,
    ToolCall,
    WorkerHeartbeat,
)


def test_runtime_spine_tables_and_columns_are_mapped() -> None:
    assert Session.__table__.c.organization_id is not None
    assert Message.__table__.c.parts is not None
    assert AgentRun.__table__.c.step_count is not None
    assert ToolCall.__table__.c.duration_ms is not None
    assert ToolCall.__table__.c.permission_request_id.foreign_keys
    assert ModelCall.__table__.c.project_id is not None
    assert ModelCall.__table__.c.workspace_id is not None
    assert SystemEvent.__table__.c.agent_run_id is not None
    assert SystemEvent.__table__.c.tool_call_id is not None
    assert QueueJobRecord.__table__.c.payload is not None
    assert HumanInputRequest.__table__.c.request_hash is not None
    assert QueueJobRecord.__table__.c.human_input_request_id.foreign_keys
    assert SessionSummary.__tablename__ == "session_summaries"
    assert MemoryItem.__table__.c.source_type is not None
    assert MemoryItem.__table__.c.content_hash is not None
    assert CodeFile.__tablename__ == "code_files"
    assert CodeFile.__table__.c.sha256 is not None
    assert CodeSymbol.__table__.c.code_file_id.foreign_keys
    assert CodeReference.__table__.c.reference_type is not None
    assert CodeDiagnostic.__table__.c.severity is not None
    assert McpServer.__table__.c.env_json is not None
    assert McpServer.__table__.c.trusted is not None
    assert McpTool.__table__.c.full_name is not None
    assert Plugin.__table__.c.manifest_path is not None
    assert Plugin.__table__.c.trusted is not None
    assert PluginTool.__table__.c.full_name is not None
    assert QueueJobRecord.__table__.c.idempotency_key.unique or any(
        constraint.name == "uq_queue_jobs_idempotency_key" for constraint in QueueJobRecord.__table__.constraints
    )
    assert WorkerHeartbeat.__table__.c.last_heartbeat_at is not None
    assert WorkerHeartbeat.__table__.c.current_queue_job_id.foreign_keys
