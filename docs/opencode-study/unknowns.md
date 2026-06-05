# Unknowns

- OpenCode commit analyzed for this audit: `f6197cefe1745eef29ea6afae26be5a56c7a79ee`.
- The current project directory is not a Git repository, so file-change safety for this audit relies on the external checksum manifest guard rather than Git.
- OpenCode has overlapping v1/v2 session, message, and event concepts. The audit maps behavior to the Python platform target rather than requiring identical TypeScript API names.
- OpenCode uses SQLite/Drizzle for local storage; the Python target intentionally uses PostgreSQL/pgvector, Qdrant, Neo4j, Redis, MinIO, and ClickHouse. Storage parity is therefore behavioral, not database-engine parity.
- Host Ollama can expose tags ending in `:cloud`. The user requested that any model returned by host Ollama remain selectable, so the audit treats cloud-looking Ollama tags as valid provider entries unless a future policy forbids them.
- Plugin and MCP execution are deliberately deferred because a Python sandbox/trust model is needed before enabling third-party executable code.
