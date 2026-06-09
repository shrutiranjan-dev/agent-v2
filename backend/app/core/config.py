from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class AppConfig(BaseModel):
    name: str = "Local Agent Platform"
    env: str = "development"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    enable_test_endpoints: bool = False
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])


class DatabaseConfig(BaseModel):
    url: str = "postgresql+asyncpg://agent:agent@localhost:5432/agent_platform"
    pool_size: int = 10
    max_overflow: int = 20


class RedisConfig(BaseModel):
    url: str = "redis://localhost:6379/0"
    pubsub_enabled: bool = False


class QueueConfig(BaseModel):
    enabled: bool = False
    name: str = "agent-platform:jobs"
    dead_letter_name: str = "agent-platform:jobs:dead"
    poll_timeout_seconds: int = Field(default=5, ge=1)
    max_attempts: int = Field(default=3, ge=1)
    retry_backoff_seconds: float = Field(default=1.0, ge=0)
    visibility_timeout_seconds: int = Field(default=300, ge=1)
    worker_id: str | None = None
    worker_heartbeat_interval_seconds: int = Field(default=10, ge=1)
    worker_stale_after_seconds: int = Field(default=60, ge=1)


class QdrantConfig(BaseModel):
    url: str = "http://localhost:6333"
    enabled: bool = False
    collection: str = "agent_platform_memory"


class MemoryConfig(BaseModel):
    embedding_enabled: bool = False
    embedding_model: str | None = None
    embedding_dimensions: int = Field(default=1536, ge=1)
    text_search_limit: int = Field(default=8, ge=1)
    compaction_threshold_ratio: float = Field(default=0.8, ge=0.1, le=1.0)
    compaction_min_excluded_messages: int = Field(default=4, ge=1)


class CodeIntelConfig(BaseModel):
    enabled: bool = True
    lsp_enabled: bool = False
    max_file_bytes: int = Field(default=512_000, ge=1)
    max_files: int = Field(default=5000, ge=1)
    context_symbol_limit: int = Field(default=12, ge=1)
    context_diagnostic_limit: int = Field(default=8, ge=1)


class LspConfig(BaseModel):
    enabled: bool = False
    python_command: str = "pylsp"
    startup_timeout_seconds: int = Field(default=10, ge=1)
    request_timeout_seconds: int = Field(default=10, ge=1)
    shutdown_timeout_seconds: int = Field(default=5, ge=1)
    max_response_chars: int = Field(default=200_000, ge=1000)
    workspace_root: Path = Path("/workspace")
    ts_enabled: bool = False
    ts_command: str = "typescript-language-server --stdio"
    ts_startup_timeout_seconds: int = Field(default=10, ge=1)
    ts_request_timeout_seconds: int = Field(default=10, ge=1)
    ts_shutdown_timeout_seconds: int = Field(default=5, ge=1)
    ts_max_response_chars: int = Field(default=200_000, ge=1000)
    ts_workspace_root: Path | None = None
    go_enabled: bool = False
    go_command: str = "gopls"
    go_startup_timeout_seconds: int = Field(default=10, ge=1)
    go_request_timeout_seconds: int = Field(default=10, ge=1)
    go_shutdown_timeout_seconds: int = Field(default=5, ge=1)
    go_max_response_chars: int = Field(default=200_000, ge=1000)
    go_workspace_root: Path | None = None
    rust_enabled: bool = False
    rust_command: str = "rust-analyzer"
    rust_startup_timeout_seconds: int = Field(default=10, ge=1)
    rust_request_timeout_seconds: int = Field(default=10, ge=1)
    rust_shutdown_timeout_seconds: int = Field(default=5, ge=1)
    rust_max_response_chars: int = Field(default=200_000, ge=1000)
    rust_workspace_root: Path | None = None
    java_enabled: bool = False
    java_command: str = "jdtls"
    java_startup_timeout_seconds: int = Field(default=10, ge=1)
    java_request_timeout_seconds: int = Field(default=10, ge=1)
    java_shutdown_timeout_seconds: int = Field(default=5, ge=1)
    java_max_response_chars: int = Field(default=200_000, ge=1000)
    java_workspace_root: Path | None = None
    ruby_enabled: bool = False
    ruby_command: str = "ruby-lsp"
    ruby_startup_timeout_seconds: int = Field(default=10, ge=1)
    ruby_request_timeout_seconds: int = Field(default=10, ge=1)
    ruby_shutdown_timeout_seconds: int = Field(default=5, ge=1)
    ruby_max_response_chars: int = Field(default=200_000, ge=1000)
    ruby_workspace_root: Path | None = None
    php_enabled: bool = False
    php_command: str = "intelephense --stdio"
    php_startup_timeout_seconds: int = Field(default=10, ge=1)
    php_request_timeout_seconds: int = Field(default=10, ge=1)
    php_shutdown_timeout_seconds: int = Field(default=5, ge=1)
    php_max_response_chars: int = Field(default=200_000, ge=1000)
    php_workspace_root: Path | None = None
    csharp_enabled: bool = False
    csharp_command: str = "csharp-ls"
    csharp_startup_timeout_seconds: int = Field(default=10, ge=1)
    csharp_request_timeout_seconds: int = Field(default=10, ge=1)
    csharp_shutdown_timeout_seconds: int = Field(default=5, ge=1)
    csharp_max_response_chars: int = Field(default=200_000, ge=1000)
    csharp_workspace_root: Path | None = None
    kotlin_enabled: bool = False
    kotlin_command: str = "kotlin-language-server"
    kotlin_startup_timeout_seconds: int = Field(default=10, ge=1)
    kotlin_request_timeout_seconds: int = Field(default=10, ge=1)
    kotlin_shutdown_timeout_seconds: int = Field(default=5, ge=1)
    kotlin_max_response_chars: int = Field(default=200_000, ge=1000)
    kotlin_workspace_root: Path | None = None
    lua_enabled: bool = False
    lua_command: str = "lua-language-server"
    lua_startup_timeout_seconds: int = Field(default=10, ge=1)
    lua_request_timeout_seconds: int = Field(default=10, ge=1)
    lua_shutdown_timeout_seconds: int = Field(default=5, ge=1)
    lua_max_response_chars: int = Field(default=200_000, ge=1000)
    lua_workspace_root: Path | None = None
    clangd_enabled: bool = False
    clangd_command: str = "clangd"
    clangd_startup_timeout_seconds: int = Field(default=10, ge=1)
    clangd_request_timeout_seconds: int = Field(default=10, ge=1)
    clangd_shutdown_timeout_seconds: int = Field(default=5, ge=1)
    clangd_max_response_chars: int = Field(default=200_000, ge=1000)
    clangd_workspace_root: Path | None = None

    def get_for_language(self, language: str, attr: str) -> Any:
        if language in ("python",):
            mapped = "python_command" if attr == "command" else attr
            return getattr(self, mapped)
        if language in ("typescript", "typescriptreact", "javascript", "javascriptreact"):
            ts_attr = f"ts_{attr}"
            if hasattr(self, ts_attr):
                return getattr(self, ts_attr)
        lang_attr = f"{language}_{attr}"
        if hasattr(self, lang_attr):
            return getattr(self, lang_attr)
        return getattr(self, attr, None)

    def get_for_server(self, server_id: str, attr: str) -> Any:
        if server_id == "python":
            mapped = "python_command" if attr == "command" else attr
            return getattr(self, mapped)
        if server_id in ("typescript", "typescriptreact", "javascript", "javascriptreact"):
            ts_attr = f"ts_{attr}"
            if hasattr(self, ts_attr):
                return getattr(self, ts_attr)
        lang_attr = f"{server_id}_{attr}"
        if hasattr(self, lang_attr):
            return getattr(self, lang_attr)
        return getattr(self, attr, None)


class McpConfig(BaseModel):
    enabled: bool = True
    connect_timeout_seconds: int = Field(default=10, ge=1)
    call_timeout_seconds: int = Field(default=30, ge=1)
    shutdown_timeout_seconds: int = Field(default=5, ge=1)
    allow_untrusted_stdio: bool = False
    allowed_stdio_commands: list[str] = Field(default_factory=lambda: ["python", "python3"])
    env_allowlist: list[str] = Field(default_factory=list)
    max_response_chars: int = Field(default=20000, ge=1000)


class PluginConfig(BaseModel):
    enabled: bool = True
    directory: Path = Path("plugins")
    auto_register_trusted_tools: bool = False


class Neo4jConfig(BaseModel):
    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: SecretStr = SecretStr("agent-platform")


class MinioConfig(BaseModel):
    endpoint: str = "localhost:9000"
    access_key: str = "minioadmin"
    secret_key: SecretStr = SecretStr("minioadmin")
    secure: bool = False


class ClickHouseConfig(BaseModel):
    host: str = "localhost"
    port: int = 8123
    user: str = "default"
    password: SecretStr = SecretStr("")


class OllamaConfig(BaseModel):
    base_url: str = "http://localhost:11434"
    default_model: str = "qwen2.5-coder:7b"
    build_model: str | None = None
    plan_model: str | None = None
    general_model: str | None = None
    explore_model: str | None = None
    summary_model: str | None = None
    compaction_model: str | None = None
    disabled_models: list[str] = Field(default_factory=list)
    non_json_models: list[str] = Field(default_factory=list)
    context_window: int = Field(default=8192, ge=1)
    max_output_tokens: int = Field(default=2048, ge=1)
    timeout_seconds: int = Field(default=120, ge=1)
    num_predict: int = Field(default=64, ge=1)


class SecurityConfig(BaseModel):
    secret_key: SecretStr = SecretStr("dev-only-change-me")
    allow_bootstrap_user: bool = True


class RuntimeLimitsConfig(BaseModel):
    workspace_root: Path = Path("/workspace")
    permission_wait_timeout_seconds: int = Field(default=600, ge=1)
    context_char_budget: int = Field(default=24000, ge=2000)
    max_tool_repeats: int = Field(default=3, ge=2)
    external_write_policy: Literal["deny", "ask"] = "deny"


class BootstrapConfig(BaseModel):
    organization_slug: str = "local"
    project_slug: str = "default"
    workspace_name: str = "default"
    user_email: str = "local-user@example.local"


class FileChangeConfig(BaseModel):
    enabled: bool = True
    capture_content: bool = True
    capture_diff: bool = True
    max_content_bytes: int = Field(default=512_000, ge=1024)
    max_diff_bytes: int = Field(default=256_000, ge=1024)
    revert_requires_approval: bool = True
    git_fallback_enabled: bool = True
    secret_filename_globs: list[str] = Field(
        default_factory=lambda: [
            ".env",
            ".env.*",
            "*.pem",
            "*.key",
            "*.p12",
            "*.pfx",
            "id_rsa",
            "id_rsa.*",
            "id_ed25519",
            "id_ed25519.*",
            "credentials",
            "credentials.*",
            "*credentials*",
            "service-account*.json",
        ]
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="AP_",
        env_nested_delimiter="__",
        extra="ignore",
        populate_by_name=True,
    )

    app: AppConfig = Field(default_factory=AppConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    queue: QueueConfig = Field(default_factory=QueueConfig)
    qdrant: QdrantConfig = Field(default_factory=QdrantConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    codeintel: CodeIntelConfig = Field(default_factory=CodeIntelConfig)
    lsp: LspConfig = Field(default_factory=LspConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)
    plugins: PluginConfig = Field(default_factory=PluginConfig)
    neo4j: Neo4jConfig = Field(default_factory=Neo4jConfig)
    minio: MinioConfig = Field(default_factory=MinioConfig)
    clickhouse: ClickHouseConfig = Field(default_factory=ClickHouseConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    runtime: RuntimeLimitsConfig = Field(default_factory=RuntimeLimitsConfig)
    bootstrap: BootstrapConfig = Field(default_factory=BootstrapConfig)
    file_changes: FileChangeConfig = Field(default_factory=FileChangeConfig)

    app_env_override: str | None = Field(default=None, validation_alias=AliasChoices("APP_ENV", "AP_ENV"))
    api_host_override: str | None = Field(default=None, validation_alias=AliasChoices("AP_API_HOST", "API_HOST"))
    api_port_override: int | None = Field(default=None, validation_alias=AliasChoices("AP_API_PORT", "API_PORT"))
    log_level_override: str | None = Field(default=None, validation_alias=AliasChoices("AP_LOG_LEVEL", "LOG_LEVEL"))
    enable_test_endpoints_override: bool | None = Field(
        default=None, validation_alias=AliasChoices("AP_ENABLE_TEST_ENDPOINTS", "ENABLE_TEST_ENDPOINTS")
    )
    cors_origins_override: Annotated[list[str] | None, NoDecode] = Field(
        default=None, validation_alias=AliasChoices("AP_CORS_ORIGINS", "CORS_ORIGINS")
    )
    database_url_override: str | None = Field(
        default=None, validation_alias=AliasChoices("AP_DATABASE_URL", "DATABASE_URL")
    )
    redis_url_override: str | None = Field(default=None, validation_alias=AliasChoices("AP_REDIS_URL", "REDIS_URL"))
    redis_pubsub_enabled_override: bool | None = Field(
        default=None, validation_alias=AliasChoices("AP_REDIS_PUBSUB_ENABLED", "REDIS_PUBSUB_ENABLED")
    )
    queue_enabled_override: bool | None = Field(
        default=None, validation_alias=AliasChoices("AP_QUEUE_ENABLED", "QUEUE_ENABLED")
    )
    queue_name_override: str | None = Field(default=None, validation_alias=AliasChoices("AP_QUEUE_NAME", "QUEUE_NAME"))
    queue_dead_letter_name_override: str | None = Field(
        default=None, validation_alias=AliasChoices("AP_QUEUE_DEAD_LETTER_NAME", "QUEUE_DEAD_LETTER_NAME")
    )
    queue_max_attempts_override: int | None = Field(
        default=None, validation_alias=AliasChoices("AP_QUEUE_MAX_ATTEMPTS", "QUEUE_MAX_ATTEMPTS")
    )
    queue_poll_timeout_seconds_override: int | None = Field(
        default=None, validation_alias=AliasChoices("AP_QUEUE_POLL_TIMEOUT_SECONDS", "QUEUE_POLL_TIMEOUT_SECONDS")
    )
    queue_retry_backoff_seconds_override: float | None = Field(
        default=None, validation_alias=AliasChoices("AP_QUEUE_RETRY_BACKOFF_SECONDS", "QUEUE_RETRY_BACKOFF_SECONDS")
    )
    queue_visibility_timeout_seconds_override: int | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_QUEUE_VISIBILITY_TIMEOUT_SECONDS", "QUEUE_VISIBILITY_TIMEOUT_SECONDS"),
    )
    queue_worker_id_override: str | None = Field(
        default=None, validation_alias=AliasChoices("AP_QUEUE_WORKER_ID", "QUEUE_WORKER_ID")
    )
    queue_worker_heartbeat_interval_seconds_override: int | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AP_WORKER_HEARTBEAT_INTERVAL_SECONDS",
            "WORKER_HEARTBEAT_INTERVAL_SECONDS",
        ),
    )
    queue_worker_stale_after_seconds_override: int | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AP_WORKER_STALE_AFTER_SECONDS",
            "WORKER_STALE_AFTER_SECONDS",
        ),
    )
    qdrant_url_override: str | None = Field(default=None, validation_alias=AliasChoices("AP_QDRANT_URL", "QDRANT_URL"))
    qdrant_enabled_override: bool | None = Field(
        default=None, validation_alias=AliasChoices("AP_QDRANT_ENABLED", "QDRANT_ENABLED")
    )
    qdrant_collection_override: str | None = Field(
        default=None, validation_alias=AliasChoices("AP_QDRANT_COLLECTION", "QDRANT_COLLECTION")
    )
    memory_embedding_enabled_override: bool | None = Field(
        default=None, validation_alias=AliasChoices("AP_MEMORY_EMBEDDING_ENABLED", "MEMORY_EMBEDDING_ENABLED")
    )
    memory_embedding_model_override: str | None = Field(
        default=None, validation_alias=AliasChoices("AP_MEMORY_EMBEDDING_MODEL", "MEMORY_EMBEDDING_MODEL")
    )
    memory_text_search_limit_override: int | None = Field(
        default=None, validation_alias=AliasChoices("AP_MEMORY_TEXT_SEARCH_LIMIT", "MEMORY_TEXT_SEARCH_LIMIT")
    )
    memory_compaction_threshold_ratio_override: float | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_MEMORY_COMPACTION_THRESHOLD_RATIO", "MEMORY_COMPACTION_THRESHOLD_RATIO"),
    )
    memory_compaction_min_excluded_messages_override: int | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AP_MEMORY_COMPACTION_MIN_EXCLUDED_MESSAGES",
            "MEMORY_COMPACTION_MIN_EXCLUDED_MESSAGES",
        ),
    )
    codeintel_enabled_override: bool | None = Field(
        default=None, validation_alias=AliasChoices("AP_CODEINTEL_ENABLED", "CODEINTEL_ENABLED")
    )
    lsp_enabled_override: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_LSP_ENABLED", "LSP_ENABLED", "AP_CODEINTEL_LSP_ENABLED", "CODEINTEL_LSP_ENABLED"),
    )
    lsp_python_command_override: str | None = Field(
        default=None, validation_alias=AliasChoices("AP_LSP_PYTHON_COMMAND", "LSP_PYTHON_COMMAND")
    )
    lsp_startup_timeout_seconds_override: int | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_LSP_STARTUP_TIMEOUT_SECONDS", "LSP_STARTUP_TIMEOUT_SECONDS"),
    )
    lsp_request_timeout_seconds_override: int | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_LSP_REQUEST_TIMEOUT_SECONDS", "LSP_REQUEST_TIMEOUT_SECONDS"),
    )
    lsp_shutdown_timeout_seconds_override: int | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_LSP_SHUTDOWN_TIMEOUT_SECONDS", "LSP_SHUTDOWN_TIMEOUT_SECONDS"),
    )
    lsp_max_response_chars_override: int | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_LSP_MAX_RESPONSE_CHARS", "LSP_MAX_RESPONSE_CHARS"),
    )
    lsp_workspace_root_override: Path | None = Field(
        default=None, validation_alias=AliasChoices("AP_LSP_WORKSPACE_ROOT", "LSP_WORKSPACE_ROOT")
    )
    lsp_ts_enabled_override: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_TS_LSP_ENABLED", "TS_LSP_ENABLED"),
    )
    lsp_ts_command_override: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_TS_LSP_COMMAND", "TS_LSP_COMMAND"),
    )
    lsp_ts_startup_timeout_seconds_override: int | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_TS_LSP_STARTUP_TIMEOUT_SECONDS", "TS_LSP_STARTUP_TIMEOUT_SECONDS"),
    )
    lsp_ts_request_timeout_seconds_override: int | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_TS_LSP_REQUEST_TIMEOUT_SECONDS", "TS_LSP_REQUEST_TIMEOUT_SECONDS"),
    )
    lsp_ts_shutdown_timeout_seconds_override: int | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_TS_LSP_SHUTDOWN_TIMEOUT_SECONDS", "TS_LSP_SHUTDOWN_TIMEOUT_SECONDS"),
    )
    lsp_ts_max_response_chars_override: int | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_TS_LSP_MAX_RESPONSE_CHARS", "TS_LSP_MAX_RESPONSE_CHARS"),
    )
    lsp_ts_workspace_root_override: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_TS_LSP_WORKSPACE_ROOT", "TS_LSP_WORKSPACE_ROOT"),
    )
    lsp_go_enabled_override: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_GO_LSP_ENABLED"),
    )
    lsp_go_command_override: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_GO_LSP_COMMAND"),
    )
    lsp_go_workspace_root_override: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_GO_LSP_WORKSPACE_ROOT"),
    )
    lsp_rust_enabled_override: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_RUST_LSP_ENABLED"),
    )
    lsp_rust_command_override: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_RUST_LSP_COMMAND"),
    )
    lsp_rust_workspace_root_override: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_RUST_LSP_WORKSPACE_ROOT"),
    )
    lsp_java_enabled_override: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_JAVA_LSP_ENABLED"),
    )
    lsp_java_command_override: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_JAVA_LSP_COMMAND"),
    )
    lsp_java_workspace_root_override: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_JAVA_LSP_WORKSPACE_ROOT"),
    )
    lsp_ruby_enabled_override: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_RUBY_LSP_ENABLED"),
    )
    lsp_ruby_command_override: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_RUBY_LSP_COMMAND"),
    )
    lsp_ruby_workspace_root_override: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_RUBY_LSP_WORKSPACE_ROOT"),
    )
    lsp_php_enabled_override: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_PHP_LSP_ENABLED"),
    )
    lsp_php_command_override: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_PHP_LSP_COMMAND"),
    )
    lsp_php_workspace_root_override: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_PHP_LSP_WORKSPACE_ROOT"),
    )
    lsp_csharp_enabled_override: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_CSHARP_LSP_ENABLED"),
    )
    lsp_csharp_command_override: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_CSHARP_LSP_COMMAND"),
    )
    lsp_csharp_workspace_root_override: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_CSHARP_LSP_WORKSPACE_ROOT"),
    )
    lsp_kotlin_enabled_override: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_KOTLIN_LSP_ENABLED"),
    )
    lsp_kotlin_command_override: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_KOTLIN_LSP_COMMAND"),
    )
    lsp_kotlin_workspace_root_override: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_KOTLIN_LSP_WORKSPACE_ROOT"),
    )
    lsp_lua_enabled_override: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_LUA_LSP_ENABLED"),
    )
    lsp_lua_command_override: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_LUA_LSP_COMMAND"),
    )
    lsp_lua_workspace_root_override: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_LUA_LSP_WORKSPACE_ROOT"),
    )
    lsp_clangd_enabled_override: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_CLANGD_LSP_ENABLED"),
    )
    lsp_clangd_command_override: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_CLANGD_LSP_COMMAND"),
    )
    lsp_clangd_workspace_root_override: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_CLANGD_LSP_WORKSPACE_ROOT"),
    )
    codeintel_max_file_bytes_override: int | None = Field(
        default=None, validation_alias=AliasChoices("AP_CODEINTEL_MAX_FILE_BYTES", "CODEINTEL_MAX_FILE_BYTES")
    )
    codeintel_max_files_override: int | None = Field(
        default=None, validation_alias=AliasChoices("AP_CODEINTEL_MAX_FILES", "CODEINTEL_MAX_FILES")
    )
    mcp_enabled_override: bool | None = Field(
        default=None, validation_alias=AliasChoices("AP_MCP_ENABLED", "MCP_ENABLED")
    )
    mcp_connect_timeout_seconds_override: int | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_MCP_CONNECT_TIMEOUT_SECONDS", "MCP_CONNECT_TIMEOUT_SECONDS"),
    )
    mcp_call_timeout_seconds_override: int | None = Field(
        default=None, validation_alias=AliasChoices("AP_MCP_CALL_TIMEOUT_SECONDS", "MCP_CALL_TIMEOUT_SECONDS")
    )
    mcp_shutdown_timeout_seconds_override: int | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_MCP_SHUTDOWN_TIMEOUT_SECONDS", "MCP_SHUTDOWN_TIMEOUT_SECONDS"),
    )
    mcp_allow_untrusted_stdio_override: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_MCP_ALLOW_UNTRUSTED_STDIO", "MCP_ALLOW_UNTRUSTED_STDIO"),
    )
    mcp_allowed_stdio_commands_override: Annotated[list[str] | None, NoDecode] = Field(
        default=None,
        validation_alias=AliasChoices("AP_MCP_ALLOWED_STDIO_COMMANDS", "MCP_ALLOWED_STDIO_COMMANDS"),
    )
    mcp_env_allowlist_override: Annotated[list[str] | None, NoDecode] = Field(
        default=None,
        validation_alias=AliasChoices("AP_MCP_ENV_ALLOWLIST", "MCP_ENV_ALLOWLIST"),
    )
    mcp_max_response_chars_override: int | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_MCP_MAX_RESPONSE_CHARS", "MCP_MAX_RESPONSE_CHARS"),
    )
    plugins_enabled_override: bool | None = Field(
        default=None, validation_alias=AliasChoices("AP_PLUGINS_ENABLED", "PLUGINS_ENABLED")
    )
    plugins_directory_override: Path | None = Field(
        default=None, validation_alias=AliasChoices("AP_PLUGINS_DIRECTORY", "PLUGINS_DIRECTORY")
    )
    plugins_auto_register_trusted_tools_override: bool | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AP_PLUGINS_AUTO_REGISTER_TRUSTED_TOOLS",
            "PLUGINS_AUTO_REGISTER_TRUSTED_TOOLS",
        ),
    )
    neo4j_uri_override: str | None = Field(default=None, validation_alias=AliasChoices("AP_NEO4J_URI", "NEO4J_URI"))
    neo4j_user_override: str | None = Field(default=None, validation_alias=AliasChoices("AP_NEO4J_USER", "NEO4J_USER"))
    neo4j_password_override: str | None = Field(
        default=None, validation_alias=AliasChoices("AP_NEO4J_PASSWORD", "NEO4J_PASSWORD")
    )
    minio_endpoint_override: str | None = Field(
        default=None, validation_alias=AliasChoices("AP_MINIO_ENDPOINT", "MINIO_ENDPOINT")
    )
    minio_access_key_override: str | None = Field(
        default=None, validation_alias=AliasChoices("AP_MINIO_ACCESS_KEY", "MINIO_ACCESS_KEY")
    )
    minio_secret_key_override: str | None = Field(
        default=None, validation_alias=AliasChoices("AP_MINIO_SECRET_KEY", "MINIO_SECRET_KEY")
    )
    minio_secure_override: bool | None = Field(
        default=None, validation_alias=AliasChoices("AP_MINIO_SECURE", "MINIO_SECURE")
    )
    clickhouse_host_override: str | None = Field(
        default=None, validation_alias=AliasChoices("AP_CLICKHOUSE_HOST", "CLICKHOUSE_HOST")
    )
    clickhouse_port_override: int | None = Field(
        default=None, validation_alias=AliasChoices("AP_CLICKHOUSE_PORT", "CLICKHOUSE_PORT")
    )
    clickhouse_user_override: str | None = Field(
        default=None, validation_alias=AliasChoices("AP_CLICKHOUSE_USER", "CLICKHOUSE_USER")
    )
    clickhouse_password_override: str | None = Field(
        default=None, validation_alias=AliasChoices("AP_CLICKHOUSE_PASSWORD", "CLICKHOUSE_PASSWORD")
    )
    ollama_base_url_override: str | None = Field(
        default=None, validation_alias=AliasChoices("AP_OLLAMA_BASE_URL", "OLLAMA_BASE_URL")
    )
    ollama_timeout_seconds_override: int | None = Field(
        default=None, validation_alias=AliasChoices("AP_OLLAMA_TIMEOUT_SECONDS", "OLLAMA_TIMEOUT_SECONDS")
    )
    default_ollama_model_override: str | None = Field(
        default=None, validation_alias=AliasChoices("AP_DEFAULT_OLLAMA_MODEL", "DEFAULT_OLLAMA_MODEL")
    )
    ollama_build_model_override: str | None = Field(
        default=None, validation_alias=AliasChoices("AP_OLLAMA_BUILD_MODEL", "OLLAMA_BUILD_MODEL")
    )
    ollama_plan_model_override: str | None = Field(
        default=None, validation_alias=AliasChoices("AP_OLLAMA_PLAN_MODEL", "OLLAMA_PLAN_MODEL")
    )
    ollama_general_model_override: str | None = Field(
        default=None, validation_alias=AliasChoices("AP_OLLAMA_GENERAL_MODEL", "OLLAMA_GENERAL_MODEL")
    )
    ollama_explore_model_override: str | None = Field(
        default=None, validation_alias=AliasChoices("AP_OLLAMA_EXPLORE_MODEL", "OLLAMA_EXPLORE_MODEL")
    )
    ollama_disabled_models_override: Annotated[list[str] | None, NoDecode] = Field(
        default=None, validation_alias=AliasChoices("AP_OLLAMA_DISABLED_MODELS", "OLLAMA_DISABLED_MODELS")
    )
    ollama_non_json_models_override: Annotated[list[str] | None, NoDecode] = Field(
        default=None, validation_alias=AliasChoices("AP_OLLAMA_NON_JSON_MODELS", "OLLAMA_NON_JSON_MODELS")
    )
    ollama_num_predict_override: int | None = Field(
        default=None, validation_alias=AliasChoices("AP_OLLAMA_NUM_PREDICT", "OLLAMA_NUM_PREDICT")
    )
    workspace_root_override: Path | None = Field(
        default=None, validation_alias=AliasChoices("AP_WORKSPACE_ROOT", "WORKSPACE_ROOT")
    )
    permission_wait_timeout_seconds_override: int | None = Field(
        default=None,
        validation_alias=AliasChoices("AP_PERMISSION_WAIT_TIMEOUT_SECONDS", "PERMISSION_WAIT_TIMEOUT_SECONDS"),
    )
    context_char_budget_override: int | None = Field(
        default=None, validation_alias=AliasChoices("AP_CONTEXT_CHAR_BUDGET", "CONTEXT_CHAR_BUDGET")
    )
    max_tool_repeats_override: int | None = Field(
        default=None, validation_alias=AliasChoices("AP_MAX_TOOL_REPEATS", "MAX_TOOL_REPEATS")
    )
    external_write_policy_override: Literal["deny", "ask"] | None = Field(
        default=None, validation_alias=AliasChoices("AP_EXTERNAL_WRITE_POLICY", "EXTERNAL_WRITE_POLICY")
    )
    security_secret_key_override: str | None = Field(
        default=None, validation_alias=AliasChoices("AP_SECURITY_SECRET_KEY", "SECURITY_SECRET_KEY")
    )
    bootstrap_organization_slug_override: str | None = Field(
        default=None, validation_alias=AliasChoices("AP_BOOTSTRAP_ORGANIZATION_SLUG", "BOOTSTRAP_ORGANIZATION_SLUG")
    )
    bootstrap_project_slug_override: str | None = Field(
        default=None, validation_alias=AliasChoices("AP_BOOTSTRAP_PROJECT_SLUG", "BOOTSTRAP_PROJECT_SLUG")
    )
    bootstrap_workspace_name_override: str | None = Field(
        default=None, validation_alias=AliasChoices("AP_BOOTSTRAP_WORKSPACE_NAME", "BOOTSTRAP_WORKSPACE_NAME")
    )
    bootstrap_user_email_override: str | None = Field(
        default=None, validation_alias=AliasChoices("AP_BOOTSTRAP_USER_EMAIL", "BOOTSTRAP_USER_EMAIL")
    )
    file_changes_revert_requires_approval_override: bool | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AP_FILE_CHANGE_REVERT_REQUIRES_APPROVAL",
            "FILE_CHANGE_REVERT_REQUIRES_APPROVAL",
        ),
    )
    file_changes_git_fallback_enabled_override: bool | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AP_FILE_CHANGE_GIT_FALLBACK_ENABLED",
            "FILE_CHANGE_GIT_FALLBACK_ENABLED",
        ),
    )

    @field_validator("cors_origins_override", mode="before")
    @classmethod
    def split_cors(cls, value: str | list[str] | None) -> list[str] | None:
        if value is None or isinstance(value, list):
            return value
        return [item.strip() for item in value.split(",") if item.strip()]

    @field_validator(
        "ollama_disabled_models_override",
        "ollama_non_json_models_override",
        "mcp_allowed_stdio_commands_override",
        "mcp_env_allowlist_override",
        mode="before",
    )
    @classmethod
    def split_csv(cls, value: str | list[str] | None) -> list[str] | None:
        if value is None or isinstance(value, list):
            return value
        return [item.strip() for item in value.split(",") if item.strip()]

    @model_validator(mode="after")
    def apply_legacy_env_overrides(self) -> "Settings":
        if self.app_env_override:
            self.app.env = self.app_env_override
        if self.api_host_override:
            self.app.api_host = self.api_host_override
        if self.api_port_override is not None:
            self.app.api_port = self.api_port_override
        if self.log_level_override:
            self.app.log_level = self.log_level_override
        if self.enable_test_endpoints_override is not None:
            self.app.enable_test_endpoints = self.enable_test_endpoints_override
        if self.cors_origins_override is not None:
            self.app.cors_origins = self.cors_origins_override
        if self.database_url_override:
            self.database.url = self.database_url_override
        if self.redis_url_override:
            self.redis.url = self.redis_url_override
        if self.redis_pubsub_enabled_override is not None:
            self.redis.pubsub_enabled = self.redis_pubsub_enabled_override
        if self.queue_enabled_override is not None:
            self.queue.enabled = self.queue_enabled_override
        if self.queue_name_override:
            self.queue.name = self.queue_name_override
        if self.queue_dead_letter_name_override:
            self.queue.dead_letter_name = self.queue_dead_letter_name_override
        if self.queue_max_attempts_override is not None:
            self.queue.max_attempts = self.queue_max_attempts_override
        if self.queue_poll_timeout_seconds_override is not None:
            self.queue.poll_timeout_seconds = self.queue_poll_timeout_seconds_override
        if self.queue_retry_backoff_seconds_override is not None:
            self.queue.retry_backoff_seconds = self.queue_retry_backoff_seconds_override
        if self.queue_visibility_timeout_seconds_override is not None:
            self.queue.visibility_timeout_seconds = self.queue_visibility_timeout_seconds_override
        if self.queue_worker_id_override:
            self.queue.worker_id = self.queue_worker_id_override
        if self.queue_worker_heartbeat_interval_seconds_override is not None:
            self.queue.worker_heartbeat_interval_seconds = self.queue_worker_heartbeat_interval_seconds_override
        if self.queue_worker_stale_after_seconds_override is not None:
            self.queue.worker_stale_after_seconds = self.queue_worker_stale_after_seconds_override
        if self.qdrant_url_override:
            self.qdrant.url = self.qdrant_url_override
        if self.qdrant_enabled_override is not None:
            self.qdrant.enabled = self.qdrant_enabled_override
        if self.qdrant_collection_override:
            self.qdrant.collection = self.qdrant_collection_override
        if self.memory_embedding_enabled_override is not None:
            self.memory.embedding_enabled = self.memory_embedding_enabled_override
        if self.memory_embedding_model_override:
            self.memory.embedding_model = self.memory_embedding_model_override
        if self.memory_text_search_limit_override is not None:
            self.memory.text_search_limit = self.memory_text_search_limit_override
        if self.memory_compaction_threshold_ratio_override is not None:
            self.memory.compaction_threshold_ratio = self.memory_compaction_threshold_ratio_override
        if self.memory_compaction_min_excluded_messages_override is not None:
            self.memory.compaction_min_excluded_messages = self.memory_compaction_min_excluded_messages_override
        if self.codeintel_enabled_override is not None:
            self.codeintel.enabled = self.codeintel_enabled_override
        if self.lsp_enabled_override is not None:
            self.lsp.enabled = self.lsp_enabled_override
            self.codeintel.lsp_enabled = self.lsp_enabled_override
        if self.lsp_python_command_override:
            self.lsp.python_command = self.lsp_python_command_override
        if self.lsp_startup_timeout_seconds_override is not None:
            self.lsp.startup_timeout_seconds = self.lsp_startup_timeout_seconds_override
        if self.lsp_request_timeout_seconds_override is not None:
            self.lsp.request_timeout_seconds = self.lsp_request_timeout_seconds_override
        if self.lsp_shutdown_timeout_seconds_override is not None:
            self.lsp.shutdown_timeout_seconds = self.lsp_shutdown_timeout_seconds_override
        if self.lsp_max_response_chars_override is not None:
            self.lsp.max_response_chars = self.lsp_max_response_chars_override
        if self.lsp_workspace_root_override is not None:
            self.lsp.workspace_root = self.lsp_workspace_root_override
        if self.lsp_ts_enabled_override is not None:
            self.lsp.ts_enabled = self.lsp_ts_enabled_override
        if self.lsp_ts_command_override:
            self.lsp.ts_command = self.lsp_ts_command_override
        if self.lsp_ts_startup_timeout_seconds_override is not None:
            self.lsp.ts_startup_timeout_seconds = self.lsp_ts_startup_timeout_seconds_override
        if self.lsp_ts_request_timeout_seconds_override is not None:
            self.lsp.ts_request_timeout_seconds = self.lsp_ts_request_timeout_seconds_override
        if self.lsp_ts_shutdown_timeout_seconds_override is not None:
            self.lsp.ts_shutdown_timeout_seconds = self.lsp_ts_shutdown_timeout_seconds_override
        if self.lsp_ts_max_response_chars_override is not None:
            self.lsp.ts_max_response_chars = self.lsp_ts_max_response_chars_override
        if self.lsp_ts_workspace_root_override is not None:
            self.lsp.ts_workspace_root = self.lsp_ts_workspace_root_override
        if self.lsp_go_enabled_override is not None:
            self.lsp.go_enabled = self.lsp_go_enabled_override
        if self.lsp_go_command_override:
            self.lsp.go_command = self.lsp_go_command_override
        if self.lsp_go_workspace_root_override is not None:
            self.lsp.go_workspace_root = self.lsp_go_workspace_root_override
        if self.lsp_rust_enabled_override is not None:
            self.lsp.rust_enabled = self.lsp_rust_enabled_override
        if self.lsp_rust_command_override:
            self.lsp.rust_command = self.lsp_rust_command_override
        if self.lsp_rust_workspace_root_override is not None:
            self.lsp.rust_workspace_root = self.lsp_rust_workspace_root_override
        if self.lsp_java_enabled_override is not None:
            self.lsp.java_enabled = self.lsp_java_enabled_override
        if self.lsp_java_command_override:
            self.lsp.java_command = self.lsp_java_command_override
        if self.lsp_java_workspace_root_override is not None:
            self.lsp.java_workspace_root = self.lsp_java_workspace_root_override
        if self.lsp_ruby_enabled_override is not None:
            self.lsp.ruby_enabled = self.lsp_ruby_enabled_override
        if self.lsp_ruby_command_override:
            self.lsp.ruby_command = self.lsp_ruby_command_override
        if self.lsp_ruby_workspace_root_override is not None:
            self.lsp.ruby_workspace_root = self.lsp_ruby_workspace_root_override
        if self.lsp_php_enabled_override is not None:
            self.lsp.php_enabled = self.lsp_php_enabled_override
        if self.lsp_php_command_override:
            self.lsp.php_command = self.lsp_php_command_override
        if self.lsp_php_workspace_root_override is not None:
            self.lsp.php_workspace_root = self.lsp_php_workspace_root_override
        if self.lsp_csharp_enabled_override is not None:
            self.lsp.csharp_enabled = self.lsp_csharp_enabled_override
        if self.lsp_csharp_command_override:
            self.lsp.csharp_command = self.lsp_csharp_command_override
        if self.lsp_csharp_workspace_root_override is not None:
            self.lsp.csharp_workspace_root = self.lsp_csharp_workspace_root_override
        if self.lsp_kotlin_enabled_override is not None:
            self.lsp.kotlin_enabled = self.lsp_kotlin_enabled_override
        if self.lsp_kotlin_command_override:
            self.lsp.kotlin_command = self.lsp_kotlin_command_override
        if self.lsp_kotlin_workspace_root_override is not None:
            self.lsp.kotlin_workspace_root = self.lsp_kotlin_workspace_root_override
        if self.lsp_lua_enabled_override is not None:
            self.lsp.lua_enabled = self.lsp_lua_enabled_override
        if self.lsp_lua_command_override:
            self.lsp.lua_command = self.lsp_lua_command_override
        if self.lsp_lua_workspace_root_override is not None:
            self.lsp.lua_workspace_root = self.lsp_lua_workspace_root_override
        if self.lsp_clangd_enabled_override is not None:
            self.lsp.clangd_enabled = self.lsp_clangd_enabled_override
        if self.lsp_clangd_command_override:
            self.lsp.clangd_command = self.lsp_clangd_command_override
        if self.lsp_clangd_workspace_root_override is not None:
            self.lsp.clangd_workspace_root = self.lsp_clangd_workspace_root_override
        if self.codeintel_max_file_bytes_override is not None:
            self.codeintel.max_file_bytes = self.codeintel_max_file_bytes_override
        if self.codeintel_max_files_override is not None:
            self.codeintel.max_files = self.codeintel_max_files_override
        if self.mcp_enabled_override is not None:
            self.mcp.enabled = self.mcp_enabled_override
        if self.mcp_connect_timeout_seconds_override is not None:
            self.mcp.connect_timeout_seconds = self.mcp_connect_timeout_seconds_override
        if self.mcp_call_timeout_seconds_override is not None:
            self.mcp.call_timeout_seconds = self.mcp_call_timeout_seconds_override
        if self.mcp_shutdown_timeout_seconds_override is not None:
            self.mcp.shutdown_timeout_seconds = self.mcp_shutdown_timeout_seconds_override
        if self.mcp_allow_untrusted_stdio_override is not None:
            self.mcp.allow_untrusted_stdio = self.mcp_allow_untrusted_stdio_override
        if self.mcp_allowed_stdio_commands_override is not None:
            self.mcp.allowed_stdio_commands = self.mcp_allowed_stdio_commands_override
        if self.mcp_env_allowlist_override is not None:
            self.mcp.env_allowlist = self.mcp_env_allowlist_override
        if self.mcp_max_response_chars_override is not None:
            self.mcp.max_response_chars = self.mcp_max_response_chars_override
        if self.plugins_enabled_override is not None:
            self.plugins.enabled = self.plugins_enabled_override
        if self.plugins_directory_override is not None:
            self.plugins.directory = self.plugins_directory_override
        if self.plugins_auto_register_trusted_tools_override is not None:
            self.plugins.auto_register_trusted_tools = self.plugins_auto_register_trusted_tools_override
        if self.neo4j_uri_override:
            self.neo4j.uri = self.neo4j_uri_override
        if self.neo4j_user_override:
            self.neo4j.user = self.neo4j_user_override
        if self.neo4j_password_override:
            self.neo4j.password = SecretStr(self.neo4j_password_override)
        if self.minio_endpoint_override:
            self.minio.endpoint = self.minio_endpoint_override
        if self.minio_access_key_override:
            self.minio.access_key = self.minio_access_key_override
        if self.minio_secret_key_override:
            self.minio.secret_key = SecretStr(self.minio_secret_key_override)
        if self.minio_secure_override is not None:
            self.minio.secure = self.minio_secure_override
        if self.clickhouse_host_override:
            self.clickhouse.host = self.clickhouse_host_override
        if self.clickhouse_port_override is not None:
            self.clickhouse.port = self.clickhouse_port_override
        if self.clickhouse_user_override:
            self.clickhouse.user = self.clickhouse_user_override
        if self.clickhouse_password_override is not None:
            self.clickhouse.password = SecretStr(self.clickhouse_password_override)
        if self.ollama_base_url_override:
            self.ollama.base_url = self.ollama_base_url_override
        if self.ollama_timeout_seconds_override is not None:
            self.ollama.timeout_seconds = self.ollama_timeout_seconds_override
        if self.default_ollama_model_override:
            self.ollama.default_model = self.default_ollama_model_override
        if self.ollama_build_model_override:
            self.ollama.build_model = self.ollama_build_model_override
        if self.ollama_plan_model_override:
            self.ollama.plan_model = self.ollama_plan_model_override
        if self.ollama_general_model_override:
            self.ollama.general_model = self.ollama_general_model_override
        if self.ollama_explore_model_override:
            self.ollama.explore_model = self.ollama_explore_model_override
        if self.ollama_disabled_models_override is not None:
            self.ollama.disabled_models = self.ollama_disabled_models_override
        if self.ollama_non_json_models_override is not None:
            self.ollama.non_json_models = self.ollama_non_json_models_override
        if self.ollama_num_predict_override is not None:
            self.ollama.num_predict = self.ollama_num_predict_override
        if self.workspace_root_override is not None:
            self.runtime.workspace_root = self.workspace_root_override
            if self.lsp_workspace_root_override is None:
                self.lsp.workspace_root = self.workspace_root_override
        if self.permission_wait_timeout_seconds_override is not None:
            self.runtime.permission_wait_timeout_seconds = self.permission_wait_timeout_seconds_override
        if self.context_char_budget_override is not None:
            self.runtime.context_char_budget = self.context_char_budget_override
        if self.max_tool_repeats_override is not None:
            self.runtime.max_tool_repeats = self.max_tool_repeats_override
        if self.external_write_policy_override is not None:
            self.runtime.external_write_policy = self.external_write_policy_override
        if self.security_secret_key_override:
            self.security.secret_key = SecretStr(self.security_secret_key_override)
        if self.bootstrap_organization_slug_override:
            self.bootstrap.organization_slug = self.bootstrap_organization_slug_override
        if self.bootstrap_project_slug_override:
            self.bootstrap.project_slug = self.bootstrap_project_slug_override
        if self.bootstrap_workspace_name_override:
            self.bootstrap.workspace_name = self.bootstrap_workspace_name_override
        if self.bootstrap_user_email_override:
            self.bootstrap.user_email = self.bootstrap_user_email_override
        if self.file_changes_revert_requires_approval_override is not None:
            self.file_changes.revert_requires_approval = self.file_changes_revert_requires_approval_override
        if self.file_changes_git_fallback_enabled_override is not None:
            self.file_changes.git_fallback_enabled = self.file_changes_git_fallback_enabled_override
        self._validate_production()
        return self

    def _validate_production(self) -> None:
        if self.app.env.lower() != "production":
            return
        failures: list[str] = []
        secret = self.security.secret_key.get_secret_value()
        if not secret or secret == "dev-only-change-me" or len(secret) < 32:
            failures.append("security.secret_key must be set to a non-default value of at least 32 characters")
        if "agent:agent@" in self.database.url:
            failures.append("database.url must not use the development agent:agent credential")
        if self.minio.secret_key.get_secret_value() == "minioadmin":
            failures.append("minio.secret_key must not use the development default")
        if self.neo4j.password.get_secret_value() == "agent-platform":
            failures.append("neo4j.password must not use the development default")
        if not self.queue.enabled:
            failures.append("queue.enabled must be true in production")
        if self.app.enable_test_endpoints:
            failures.append("app.enable_test_endpoints must be false in production")
        if failures:
            raise ValueError("Invalid production configuration: " + "; ".join(failures))

    @property
    def env(self) -> str:
        return self.app.env

    @property
    def log_level(self) -> str:
        return self.app.log_level

    @property
    def api_host(self) -> str:
        return self.app.api_host

    @property
    def api_port(self) -> int:
        return self.app.api_port

    @property
    def cors_origins(self) -> list[str]:
        return self.app.cors_origins

    @property
    def database_url(self) -> str:
        return self.database.url

    @property
    def redis_url(self) -> str:
        return self.redis.url

    @property
    def queue_enabled(self) -> bool:
        return self.queue.enabled

    @property
    def qdrant_url(self) -> str:
        return self.qdrant.url

    @property
    def neo4j_uri(self) -> str:
        return self.neo4j.uri

    @property
    def neo4j_user(self) -> str:
        return self.neo4j.user

    @property
    def neo4j_password(self) -> str:
        return self.neo4j.password.get_secret_value()

    @property
    def minio_endpoint(self) -> str:
        return self.minio.endpoint

    @property
    def minio_access_key(self) -> str:
        return self.minio.access_key

    @property
    def minio_secret_key(self) -> str:
        return self.minio.secret_key.get_secret_value()

    @property
    def minio_secure(self) -> bool:
        return self.minio.secure

    @property
    def clickhouse_host(self) -> str:
        return self.clickhouse.host

    @property
    def clickhouse_port(self) -> int:
        return self.clickhouse.port

    @property
    def clickhouse_user(self) -> str:
        return self.clickhouse.user

    @property
    def clickhouse_password(self) -> str:
        return self.clickhouse.password.get_secret_value()

    @property
    def ollama_base_url(self) -> str:
        return self.ollama.base_url

    @property
    def default_ollama_model(self) -> str:
        return self.ollama.default_model

    @property
    def ollama_num_predict(self) -> int:
        return self.ollama.num_predict

    @property
    def workspace_root(self) -> Path:
        return self.runtime.workspace_root

    @property
    def permission_wait_timeout_seconds(self) -> int:
        return self.runtime.permission_wait_timeout_seconds

    @property
    def context_char_budget(self) -> int:
        return self.runtime.context_char_budget

    @property
    def bootstrap_organization_slug(self) -> str:
        return self.bootstrap.organization_slug

    @property
    def bootstrap_project_slug(self) -> str:
        return self.bootstrap.project_slug

    @property
    def bootstrap_workspace_name(self) -> str:
        return self.bootstrap.workspace_name

    @property
    def bootstrap_user_email(self) -> str:
        return self.bootstrap.user_email


@lru_cache
def get_settings() -> Settings:
    return Settings()
