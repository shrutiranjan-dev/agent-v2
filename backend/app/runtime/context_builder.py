import json
import re
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agents.base import AgentDefinition
from backend.app.agents.prompts import STRICT_JSON_RUNTIME
from backend.app.codeintel.repository import codeintel_repository
from backend.app.core.config import get_settings
from backend.app.db.models import MemoryItem, Message, Session, SessionSummary
from backend.app.memory.memory_service import memory_service, serialize_memory_item
from backend.app.memory.summary_service import serialize_summary
from backend.app.tools.registry import tool_registry


class ContextMessage(BaseModel):
    role: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextBundle(BaseModel):
    system_prompt: str
    prompt: str
    included_messages: list[ContextMessage]
    included_summaries: list[dict[str, Any]] = Field(default_factory=list)
    included_memory_items: list[dict[str, Any]] = Field(default_factory=list)
    included_code_context: dict[str, Any] = Field(default_factory=dict)
    excluded_message_count: int = 0
    needs_compaction: bool = False
    char_budget: int
    budget_used: int = 0
    compaction_reason: str | None = None


def tool_definitions_for_agent(agent: AgentDefinition) -> list[dict[str, Any]]:
    allowed = set(agent.allowed_tools)
    return [
        {"name": item["name"], "description": item["description"], "input_schema": item["input_schema"]}
        for item in tool_registry.list()
        if item["name"] in allowed
    ]


class ContextBuilder:
    async def build(
        self,
        db: AsyncSession,
        *,
        session: Session,
        agent: AgentDefinition,
        char_budget: int | None = None,
    ) -> ContextBundle:
        rows = await self._session_messages(db, session_id=session.id)
        summaries = await self._active_summaries(db, session_id=session.id)
        memory_items = await memory_service.retrieve(
            db,
            organization_id=session.organization_id,
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            session_id=session.id,
        )
        messages = [
            ContextMessage(role=row.role, content=row.content, metadata={"id": str(row.id), **(row.metadata_json or {})})
            for row in rows
        ]
        code_context = await self._code_context(db, session=session, messages=messages)
        return self.build_from_messages(
            agent=agent,
            messages=messages,
            summaries=summaries,
            memory_items=memory_items,
            code_context=code_context,
            tools=tool_definitions_for_agent(agent),
            char_budget=char_budget or get_settings().context_char_budget,
        )

    def build_from_messages(
        self,
        *,
        agent: AgentDefinition,
        messages: list[ContextMessage | dict[str, Any]],
        tools: list[dict[str, Any]],
        char_budget: int,
        summaries: list[SessionSummary | dict[str, Any]] | None = None,
        memory_items: list[MemoryItem | dict[str, Any]] | None = None,
        code_context: dict[str, Any] | None = None,
    ) -> ContextBundle:
        normalized = [
            item if isinstance(item, ContextMessage) else ContextMessage.model_validate(item)
            for item in messages
        ]
        system_prompt = "\n\n".join(
            [
                agent.system_prompt,
                "Runtime tool-call protocol:",
                STRICT_JSON_RUNTIME.strip(),
                "Allowed tool schemas:",
                json.dumps(tools, separators=(",", ":"), sort_keys=True),
            ]
        )
        legacy_summaries = [message for message in normalized if message.metadata.get("kind") == "summary"]
        transcript = [message for message in normalized if message.metadata.get("kind") != "summary"]
        durable_summaries = summaries or []
        durable_memory = memory_items or []
        durable_code = code_context or {}
        budget_remaining = max(char_budget - len(system_prompt), 0)

        selected: list[ContextMessage] = []
        selected_summaries: list[dict[str, Any]] = []
        selected_memory: list[dict[str, Any]] = []
        selected_code = self._fit_code_context(durable_code, budget_remaining)
        budget_remaining -= len(self._format_code_context(selected_code))
        excluded_count = 0
        for summary in durable_summaries:
            summary_data = self._summary_to_context(summary)
            size = len(summary_data["content"]) + 48
            if size <= budget_remaining:
                selected_summaries.append(summary_data)
                budget_remaining -= size
            else:
                excluded_count += 1

        for memory in durable_memory:
            memory_data = self._memory_to_context(memory)
            size = len(memory_data["content"]) + 64
            if size <= budget_remaining:
                selected_memory.append(memory_data)
                budget_remaining -= size
            else:
                excluded_count += 1

        for summary in legacy_summaries:
            size = self._message_size(summary)
            if size <= budget_remaining:
                selected.append(summary)
                budget_remaining -= size
            else:
                excluded_count += 1

        recent: list[ContextMessage] = []
        for message in reversed(transcript):
            size = self._message_size(message)
            if size <= budget_remaining:
                recent.append(message)
                budget_remaining -= size
            else:
                excluded_count += 1
        selected.extend(reversed(recent))

        settings = get_settings()
        used = char_budget - budget_remaining
        threshold_exceeded = used >= int(char_budget * settings.memory.compaction_threshold_ratio)
        needs_compaction = excluded_count >= settings.memory.compaction_min_excluded_messages or threshold_exceeded
        prompt_sections = [
            "Active session summaries:",
            self._format_summaries(selected_summaries),
            "Relevant memory:",
            self._format_memory(selected_memory),
            "Code intelligence:",
            self._format_code_context(selected_code),
            "Session transcript:",
            self._format_messages(selected),
        ]
        if needs_compaction:
            prompt_sections.append(
                f"Context compaction is needed: {excluded_count} older item(s) were excluded or budget pressure is high."
            )
        prompt_sections.append(
            "Respond with exactly one JSON object using either the final response or tool_call schema."
        )
        return ContextBundle(
            system_prompt=system_prompt,
            prompt="\n\n".join(prompt_sections),
            included_messages=selected,
            included_summaries=selected_summaries,
            included_memory_items=selected_memory,
            included_code_context=selected_code,
            excluded_message_count=excluded_count,
            needs_compaction=needs_compaction,
            char_budget=char_budget,
            budget_used=used,
            compaction_reason="budget_pressure" if needs_compaction else None,
        )

    def _format_messages(self, messages: list[ContextMessage]) -> str:
        if not messages:
            return "(no prior messages)"
        return "\n\n".join(f"{message.role.upper()}:\n{message.content}" for message in messages)

    def _message_size(self, message: ContextMessage) -> int:
        return len(message.role) + len(message.content) + 8

    def _summary_to_context(self, summary: SessionSummary | dict[str, Any]) -> dict[str, Any]:
        if isinstance(summary, dict):
            return {
                "id": str(summary.get("id", "")),
                "summary_type": str(summary.get("summary_type", "summary")),
                "content": str(summary.get("content", "")),
            }
        data = serialize_summary(summary)
        return {"id": data["id"], "summary_type": data["summary_type"], "content": data["content"]}

    def _memory_to_context(self, memory: MemoryItem | dict[str, Any]) -> dict[str, Any]:
        if isinstance(memory, dict):
            return {
                "id": str(memory.get("id", "")),
                "source_type": str(memory.get("source_type", "memory")),
                "content": str(memory.get("content", "")),
            }
        data = serialize_memory_item(memory)
        return {"id": data["id"], "source_type": data["source_type"], "content": data["content"]}

    def _format_summaries(self, summaries: list[dict[str, Any]]) -> str:
        if not summaries:
            return "(none)"
        return "\n\n".join(
            f"[{item['summary_type']} summary {item['id']}]\n{item['content']}" for item in summaries
        )

    def _format_memory(self, memory_items: list[dict[str, Any]]) -> str:
        if not memory_items:
            return "(none)"
        return "\n\n".join(
            f"[{item['source_type']} memory {item['id']}]\n{item['content']}" for item in memory_items
        )

    async def _code_context(
        self,
        db: AsyncSession,
        *,
        session: Session,
        messages: list[ContextMessage],
    ) -> dict[str, Any]:
        settings = get_settings()
        if not settings.codeintel.enabled:
            return {"status": "disabled"}
        latest_user = next((message.content for message in reversed(messages) if message.role == "user"), "")
        query_terms = self._query_terms(latest_user)
        symbols: list[dict[str, Any]] = []
        try:
            code_map = await codeintel_repository.code_map(
                db,
                workspace_id=session.workspace_id,
                depth=2,
                include_symbols=False,
            )
            for term in query_terms:
                if len(symbols) >= settings.codeintel.context_symbol_limit:
                    break
                rows = await codeintel_repository.find_symbols(
                    db,
                    workspace_id=session.workspace_id,
                    query=term,
                    limit=max(settings.codeintel.context_symbol_limit - len(symbols), 1),
                )
                symbols.extend(rows)
            diagnostics = await codeintel_repository.list_diagnostics(
                db,
                workspace_id=session.workspace_id,
                severity="error",
                limit=settings.codeintel.context_diagnostic_limit,
            )
        except Exception as exc:
            return {"status": "degraded", "reason": str(exc)}
        return {
            "status": "available",
            "code_map": code_map,
            "symbols": self._dedupe_symbols(symbols)[: settings.codeintel.context_symbol_limit],
            "diagnostics": diagnostics,
        }

    def _query_terms(self, text: str) -> list[str]:
        terms = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b", text)
        stop = {"the", "and", "for", "with", "from", "this", "that", "file", "code", "agent"}
        seen: set[str] = set()
        selected: list[str] = []
        for term in terms:
            lower = term.lower()
            if lower in stop or lower in seen:
                continue
            seen.add(lower)
            selected.append(term)
            if len(selected) >= 6:
                break
        return selected

    def _dedupe_symbols(self, symbols: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for symbol in symbols:
            key = str(symbol.get("id") or f"{symbol.get('file_path')}:{symbol.get('name')}:{symbol.get('start_line')}")
            if key in seen:
                continue
            seen.add(key)
            deduped.append(symbol)
        return deduped

    def _fit_code_context(self, code_context: dict[str, Any], budget_remaining: int) -> dict[str, Any]:
        if not code_context or budget_remaining <= 0:
            return {}
        selected = dict(code_context)
        for key in ["symbols", "diagnostics"]:
            items = list(selected.get(key) or [])
            while items and len(self._format_code_context(selected | {key: items})) > budget_remaining:
                items.pop()
            selected[key] = items
        if len(self._format_code_context(selected)) > budget_remaining:
            return {"status": selected.get("status", "available"), "reason": "code context omitted by budget"}
        return selected

    def _format_code_context(self, code_context: dict[str, Any]) -> str:
        if not code_context:
            return "(not available)"
        if code_context.get("status") in {"disabled", "degraded"}:
            reason = code_context.get("reason", "")
            return f"({code_context.get('status')}: {reason})".strip()
        code_map = code_context.get("code_map") or {}
        lines = [
            (
                "Map: "
                f"{code_map.get('file_count', 0)} files, "
                f"{code_map.get('symbol_count', 0)} symbols, "
                f"languages={code_map.get('languages', {})}"
            )
        ]
        files = code_map.get("files") or []
        if files:
            lines.append("Top files:")
            for item in files[:8]:
                lines.append(
                    f"- {item.get('path')} ({item.get('language') or 'unknown'}, "
                    f"{item.get('symbol_count', 0)} symbols)"
                )
        symbols = code_context.get("symbols") or []
        if symbols:
            lines.append("Relevant symbols:")
            for symbol in symbols[:12]:
                lines.append(
                    f"- {symbol.get('kind')} {symbol.get('name')} at "
                    f"{symbol.get('file_path')}:{symbol.get('start_line')}"
                )
        diagnostics = code_context.get("diagnostics") or []
        if diagnostics:
            lines.append("Recent diagnostics:")
            for diagnostic in diagnostics[:8]:
                lines.append(
                    f"- {diagnostic.get('severity')} {diagnostic.get('file_path')}:"
                    f"{diagnostic.get('line')} {diagnostic.get('message')}"
                )
        return "\n".join(lines)

    async def _session_messages(self, db: AsyncSession, *, session_id) -> list[Message]:
        if hasattr(db, "objects"):
            rows = [
                row
                for (model, _row_id), row in db.objects.items()
                if model is Message and row.session_id == session_id
            ]
            return sorted(rows, key=lambda item: (item.created_at, item.id))
        return list(
            (
                await db.scalars(
                    select(Message)
                    .where(Message.session_id == session_id)
                    .order_by(Message.created_at.asc(), Message.id.asc())
                )
            ).all()
        )

    async def _active_summaries(self, db: AsyncSession, *, session_id) -> list[SessionSummary]:
        if hasattr(db, "objects"):
            rows = [
                row
                for (model, _row_id), row in db.objects.items()
                if model is SessionSummary and row.session_id == session_id and row.status == "active"
            ]
            return sorted(rows, key=lambda item: (item.created_at, item.id))
        return list(
            (
                await db.scalars(
                    select(SessionSummary)
                    .where(SessionSummary.session_id == session_id, SessionSummary.status == "active")
                    .order_by(SessionSummary.created_at.asc(), SessionSummary.id.asc())
                )
            ).all()
        )


context_builder = ContextBuilder()
