import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agents.registry import agent_registry
from backend.app.core.config import get_settings
from backend.app.core.events import EventType
from backend.app.core.redaction import redact_data, redact_text
from backend.app.db.models import AgentRun, Message, ModelCall, Session
from backend.app.memory.memory_service import memory_service
from backend.app.memory.summary_service import summary_service
from backend.app.providers.router import capability_for_model, get_provider
from backend.app.runtime.context_builder import context_builder
from backend.app.runtime.event_bus import event_bus
from backend.app.runtime.human_input_service import HumanInputResumeContext
from backend.app.runtime.message_service import message_service
from backend.app.runtime.tool_executor import tool_executor


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()
    return json.loads(cleaned)


def _fallback_final_content(raw: str, fallback: str = "The model returned an empty response.") -> str:
    return raw.strip() or fallback


class AgentRunner:
    async def create_run(
        self,
        db: AsyncSession,
        *,
        session: Session,
        status: str = "queued",
        user_message_id: Any | None = None,
    ) -> AgentRun:
        agent = agent_registry.get(session.agent_id)
        run = AgentRun(
            organization_id=session.organization_id,
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            session_id=session.id,
            agent_id=agent.id,
            model_provider=session.model_provider,
            model_name=session.model_name,
            status=status,
        )
        db.add(run)
        await db.flush()
        if status == "queued":
            session.status = "queued"
            await event_bus.publish(
                db,
                organization_id=session.organization_id,
                project_id=session.project_id,
                workspace_id=session.workspace_id,
                session_id=session.id,
                agent_run_id=run.id,
                event_type=EventType.AGENT_RUN_QUEUED,
                payload={
                    "id": str(run.id),
                    "agent_id": agent.id,
                    "model": session.model_name,
                    "user_message_id": str(user_message_id) if user_message_id else None,
                },
            )
        elif status == "running":
            session.status = "running"
            await self._publish_started(db, session=session, run=run)
        return run

    async def run(self, db: AsyncSession, *, session: Session, user_id) -> AgentRun:
        run = await self.create_run(db, session=session, status="running")
        return await self._continue_loop(db, session=session, run=run, user_id=user_id)

    async def start_queued_run(
        self,
        db: AsyncSession,
        *,
        session: Session,
        run: AgentRun,
        user_id,
        job_id: str | None = None,
    ) -> AgentRun:
        if run.status not in {"queued", "running"}:
            return run
        run.status = "running"
        run.started_at = datetime.now(UTC)
        session.status = "running"
        await self._publish_started(db, session=session, run=run, job_id=job_id)
        return await self._continue_loop(db, session=session, run=run, user_id=user_id)

    async def _publish_started(
        self,
        db: AsyncSession,
        *,
        session: Session,
        run: AgentRun,
        job_id: str | None = None,
    ) -> None:
        await event_bus.publish(
            db,
            organization_id=session.organization_id,
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            session_id=session.id,
            agent_run_id=run.id,
            event_type=EventType.AGENT_RUN_STARTED,
            payload={"id": str(run.id), "agent_id": run.agent_id, "model": session.model_name, "job_id": job_id},
        )

    async def resume_after_permission(
        self,
        db: AsyncSession,
        *,
        session: Session,
        run: AgentRun,
        tool_call,
        user_id,
        job_id: str | None = None,
    ) -> AgentRun:
        agent = agent_registry.get(run.agent_id)
        session.status = "running"
        run.status = "running"
        await event_bus.publish(
            db,
            organization_id=session.organization_id,
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            session_id=session.id,
            agent_run_id=run.id,
            tool_call_id=tool_call.id,
            event_type=EventType.AGENT_RUN_RESUMED,
            payload={"id": str(run.id), "permission_request_id": str(tool_call.permission_request_id), "job_id": job_id},
        )
        outcome = await tool_executor.execute_approved_call(
            db,
            tool_call=tool_call,
            user_id=user_id,
            agent=agent,
        )
        if outcome.status != "completed":
            return await self._fail_run(
                db,
                run=run,
                session=session,
                error=f"Approved tool call failed: {outcome.error}",
                metadata={"tool_call_id": str(tool_call.id)},
            )
        tool_output = json.dumps(outcome.output, indent=2)
        await message_service.create_tool_result(
            db,
            session=session,
            tool_name=tool_call.tool_name,
            content=tool_output,
            metadata={
                "agent_run_id": str(run.id),
                "tool_call_id": str(tool_call.id),
                "permission_request_id": str(tool_call.permission_request_id),
            },
        )
        return await self._continue_loop(db, session=session, run=run, user_id=user_id)

    async def resume_after_human_input(
        self,
        db: AsyncSession,
        *,
        context: HumanInputResumeContext,
        user_id,
        job_id: str | None = None,
    ) -> AgentRun:
        session = context.session
        run = context.run
        request = context.request
        tool_call = context.tool_call
        session.status = "running"
        run.status = "running"
        await event_bus.publish(
            db,
            organization_id=session.organization_id,
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            session_id=session.id,
            agent_run_id=run.id,
            tool_call_id=tool_call.id,
            event_type=EventType.AGENT_RUN_RESUMED_FROM_HUMAN_INPUT,
            payload={"id": str(run.id), "human_input_request_id": str(request.id), "job_id": job_id},
        )
        output = await self._complete_human_input_tool(db, context=context, user_id=user_id)
        await message_service.create_tool_result(
            db,
            session=session,
            tool_name=tool_call.tool_name,
            content=json.dumps(output, indent=2),
            metadata={
                "agent_run_id": str(run.id),
                "tool_call_id": str(tool_call.id),
                "human_input_request_id": str(request.id),
            },
        )
        if (request.metadata_json or {}).get("test_complete_on_answer") and get_settings().app.env.lower() != "production":
            await message_service.create_assistant(
                db,
                session=session,
                content="Human input received.",
                metadata={"agent_run_id": str(run.id), "human_input_request_id": str(request.id), "test": True},
            )
            run.status = "completed"
            run.completed_at = datetime.now(UTC)
            session.status = "idle"
            await event_bus.publish(
                db,
                organization_id=session.organization_id,
                project_id=session.project_id,
                workspace_id=session.workspace_id,
                session_id=session.id,
                agent_run_id=run.id,
                event_type=EventType.AGENT_RUN_COMPLETED,
                payload={"id": str(run.id), "human_input_request_id": str(request.id), "test": True},
            )
            return run
        return await self._continue_loop(db, session=session, run=run, user_id=user_id)

    async def _continue_loop(self, db: AsyncSession, *, session: Session, run: AgentRun, user_id) -> AgentRun:
        agent = agent_registry.get(run.agent_id)
        if run.step_count is None:
            run.step_count = 0
        selected_capability = capability_for_model(session.model_name, recommended_for=[agent.id])
        if not selected_capability.enabled:
            return await self._fail_run(
                db,
                run=run,
                session=session,
                error=f"Model {session.model_name} is disabled by runtime configuration.",
            )
        if agent.requires_json_protocol and not selected_capability.supports_json_protocol:
            return await self._fail_run(
                db,
                run=run,
                session=session,
                error=f"Model {session.model_name} does not support the strict JSON agent protocol.",
            )
        provider = get_provider(session.model_provider)
        invalid_repaired = False
        repair_instruction: str | None = None

        while run.step_count < agent.max_steps:
            run.step_count += 1
            await event_bus.publish(
                db,
                organization_id=session.organization_id,
                project_id=session.project_id,
                workspace_id=session.workspace_id,
                session_id=session.id,
                agent_run_id=run.id,
                event_type=EventType.AGENT_RUN_STEP,
                payload={"id": str(run.id), "step": run.step_count, "max_steps": agent.max_steps},
            )
            bundle = await context_builder.build(db, session=session, agent=agent)
            await self._maybe_enqueue_compaction(db, session=session, run=run, bundle=bundle, user_id=user_id)
            prompt = bundle.prompt
            if repair_instruction:
                prompt = prompt + "\n\nJSON repair instruction:\n" + repair_instruction
            model_call = ModelCall(
                organization_id=session.organization_id,
                project_id=session.project_id,
                workspace_id=session.workspace_id,
                session_id=session.id,
                agent_run_id=run.id,
                provider=session.model_provider,
                model=session.model_name,
                status="running",
                request_json=redact_data({
                    "system": bundle.system_prompt,
                    "prompt": prompt,
                    "included_messages": len(bundle.included_messages),
                    "excluded_message_count": bundle.excluded_message_count,
                }),
            )
            db.add(model_call)
            await db.flush()
            await event_bus.publish(
                db,
                organization_id=session.organization_id,
                project_id=session.project_id,
                workspace_id=session.workspace_id,
                session_id=session.id,
                agent_run_id=run.id,
                event_type=EventType.MODEL_CALL_STARTED,
                payload={"id": str(model_call.id), "model": session.model_name},
            )
            try:
                response = await provider.generate(
                    model=session.model_name,
                    system=bundle.system_prompt,
                    prompt=prompt,
                    temperature=agent.temperature,
                    top_p=agent.top_p,
                )
            except httpx.HTTPError as exc:
                error = redact_text(str(exc) or exc.__class__.__name__)
                model_call.status = "failed"
                model_call.error = error
                await event_bus.publish(
                    db,
                    organization_id=session.organization_id,
                    project_id=session.project_id,
                    workspace_id=session.workspace_id,
                    session_id=session.id,
                    agent_run_id=run.id,
                    event_type=EventType.MODEL_CALL_FAILED,
                    severity="error",
                    payload={"id": str(model_call.id), "error": error},
                )
                return await self._fail_run(
                    db,
                    run=run,
                    session=session,
                    error=f"Ollama model call failed: {error}",
                )

            model_call.status = "completed"
            model_call.latency_ms = response.get("latency_ms")
            model_call.prompt_tokens = int(response.get("prompt_eval_count") or 0)
            model_call.completion_tokens = int(response.get("eval_count") or 0)
            model_call.response_json = redact_data(response)
            await event_bus.publish(
                db,
                organization_id=session.organization_id,
                project_id=session.project_id,
                workspace_id=session.workspace_id,
                session_id=session.id,
                agent_run_id=run.id,
                event_type=EventType.MODEL_CALL_COMPLETED,
                payload={"id": str(model_call.id), "latency_ms": model_call.latency_ms},
            )

            raw = str(response.get("response", ""))
            try:
                payload = _extract_json(raw)
            except Exception:
                if invalid_repaired:
                    return await self._fail_run(
                        db,
                        run=run,
                        session=session,
                        error="Model returned invalid JSON after one repair attempt.",
                        metadata={"raw_response": redact_text(raw)},
                    )
                invalid_repaired = True
                repair_instruction = (
                    "Your previous response was invalid JSON. Repair it into exactly one JSON object "
                    'with type "final" or "tool_call". Previous response:\n'
                    + raw
                )
                continue

            invalid_repaired = False
            repair_instruction = None
            if payload.get("type") == "final":
                content = str(payload.get("content", ""))
                await message_service.create_assistant(
                    db,
                    session=session,
                    content=content,
                    metadata={"agent_run_id": str(run.id), "model": session.model_name},
                )
                run.status = "completed"
                run.completed_at = datetime.now(UTC)
                session.status = "idle"
                await event_bus.publish(
                    db,
                    organization_id=session.organization_id,
                    project_id=session.project_id,
                    workspace_id=session.workspace_id,
                    session_id=session.id,
                    agent_run_id=run.id,
                    event_type=EventType.AGENT_RUN_COMPLETED,
                    payload={"id": str(run.id), "steps": run.step_count},
                )
                return run

            if payload.get("type") != "tool_call":
                return await self._fail_run(
                    db,
                    run=run,
                    session=session,
                    error='Model JSON response must have type "final" or "tool_call".',
                    metadata={"model": session.model_name, "reason": "unknown_json_type", "payload": payload},
                )

            tool_name = str(payload.get("tool", ""))
            tool_input = payload.get("input")
            if not isinstance(tool_input, dict):
                return await self._fail_run(
                    db,
                    run=run,
                    session=session,
                    error="Tool call input must be a JSON object.",
                    metadata={"payload": payload},
                )

            try:
                outcome = await tool_executor.execute(
                    db,
                    organization_id=session.organization_id,
                    project_id=session.project_id,
                    workspace_id=session.workspace_id,
                    session_id=session.id,
                    user_id=user_id,
                    agent_run_id=run.id,
                    agent=agent,
                    tool_name=tool_name,
                    input_json=tool_input,
                )
            except Exception as exc:
                return await self._fail_run(
                    db,
                    run=run,
                    session=session,
                    error=redact_text(f"Tool call failed before execution: {exc}"),
                    metadata=redact_data({"tool": tool_name, "input": tool_input}),
                )
            if outcome.status == "waiting_permission":
                run.status = "waiting_permission"
                session.status = "waiting_permission"
                return run
            if outcome.status == "waiting_human_input":
                run.status = "waiting_human_input"
                session.status = "waiting_human_input"
                await event_bus.publish(
                    db,
                    organization_id=session.organization_id,
                    project_id=session.project_id,
                    workspace_id=session.workspace_id,
                    session_id=session.id,
                    agent_run_id=run.id,
                    tool_call_id=outcome.tool_call.id,
                    event_type=EventType.AGENT_RUN_WAITING_HUMAN_INPUT,
                    payload={
                        "id": str(run.id),
                        "tool_call_id": str(outcome.tool_call.id),
                        "human_input_request_id": str(outcome.human_input_request_id) if outcome.human_input_request_id else None,
                    },
                )
                return run
            if outcome.status != "completed":
                run.status = "failed"
                run.error = outcome.error
                run.completed_at = datetime.now(UTC)
                session.status = "failed"
                await message_service.create_assistant(
                    db,
                    session=session,
                    content=f"Tool call failed: {outcome.error}",
                    metadata={"agent_run_id": str(run.id), "tool_call_id": str(outcome.tool_call.id)},
                )
                await event_bus.publish(
                    db,
                    organization_id=session.organization_id,
                    project_id=session.project_id,
                    workspace_id=session.workspace_id,
                    session_id=session.id,
                    agent_run_id=run.id,
                    tool_call_id=outcome.tool_call.id,
                    event_type=EventType.AGENT_RUN_FAILED,
                    severity="error",
                    payload={"id": str(run.id), "error": run.error},
                )
                return run

            tool_output = json.dumps(outcome.output, indent=2)
            await message_service.create_tool_result(
                db,
                session=session,
                tool_name=tool_name,
                content=tool_output,
                metadata={"agent_run_id": str(run.id), "tool_call_id": str(outcome.tool_call.id)},
            )

        run.status = "failed"
        run.error = f"Agent exceeded max steps: {agent.max_steps}"
        run.completed_at = datetime.now(UTC)
        session.status = "failed"
        await message_service.create_assistant(db, session=session, content=run.error, metadata={"error": True})
        await event_bus.publish(
            db,
            organization_id=session.organization_id,
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            session_id=session.id,
            agent_run_id=run.id,
            event_type=EventType.AGENT_RUN_FAILED,
            severity="error",
            payload={"id": str(run.id), "error": run.error},
        )
        return run

    async def run_compaction_job(
        self,
        db: AsyncSession,
        *,
        session: Session,
        source_message_end_id,
        job_id: str | None = None,
    ):
        agent = agent_registry.get("compaction")
        await event_bus.publish(
            db,
            organization_id=session.organization_id,
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            session_id=session.id,
            event_type=EventType.COMPACTION_STARTED,
            payload={"session_id": str(session.id), "source_message_end_id": str(source_message_end_id) if source_message_end_id else None, "job_id": job_id},
        )
        messages = await self._load_session_messages(db, session=session, source_message_end_id=source_message_end_id)
        if not messages:
            await summary_service.record_failed(
                db,
                session=session,
                summary_type="compaction",
                error="No messages available for compaction.",
                model=agent.llm.model,
                metadata={"job_id": job_id},
            )
            await event_bus.publish(
                db,
                organization_id=session.organization_id,
                project_id=session.project_id,
                workspace_id=session.workspace_id,
                session_id=session.id,
                event_type=EventType.COMPACTION_FAILED,
                severity="warning",
                payload={"session_id": str(session.id), "error": "No messages available for compaction.", "job_id": job_id},
            )
            return None

        test_content = (session.metadata_json or {}).get("test_compaction_content")
        if test_content and get_settings().app.env.lower() != "production" and get_settings().app.enable_test_endpoints:
            summary = await summary_service.create_from_messages(
                db,
                session=session,
                messages=messages,
                content=str(test_content),
                summary_type="compaction",
                model=None,
                metadata={"job_id": job_id, "source": "test_endpoint"},
                supersede_active=True,
            )
            await memory_service.create_from_session_summary(
                db,
                session=session,
                summary_id=summary.id,
                content=summary.content,
                metadata={"summary_type": summary.summary_type, "job_id": job_id, "source": "test_endpoint"},
            )
            await event_bus.publish(
                db,
                organization_id=session.organization_id,
                project_id=session.project_id,
                workspace_id=session.workspace_id,
                session_id=session.id,
                event_type=EventType.COMPACTION_COMPLETED,
                payload={"summary": {"id": str(summary.id), "char_count": summary.char_count}, "job_id": job_id, "test": True},
            )
            return summary

        try:
            summary = await self._generate_summary(
                db,
                session=session,
                messages=messages,
                agent_id="compaction",
                summary_type="compaction",
                supersede_active=True,
                metadata={"job_id": job_id, "source": "queue"},
            )
        except Exception as exc:
            await event_bus.publish(
                db,
                organization_id=session.organization_id,
                project_id=session.project_id,
                workspace_id=session.workspace_id,
                session_id=session.id,
                event_type=EventType.COMPACTION_FAILED,
                severity="error",
                payload={"session_id": str(session.id), "error": redact_text(str(exc)), "job_id": job_id},
            )
            return None

        if summary.status != "active":
            await event_bus.publish(
                db,
                organization_id=session.organization_id,
                project_id=session.project_id,
                workspace_id=session.workspace_id,
                session_id=session.id,
                event_type=EventType.COMPACTION_FAILED,
                severity="error",
                payload={"session_id": str(session.id), "summary_id": str(summary.id), "job_id": job_id},
            )
            return summary

        await memory_service.create_from_session_summary(
            db,
            session=session,
            summary_id=summary.id,
            content=summary.content,
            metadata={"summary_type": summary.summary_type, "job_id": job_id},
        )
        await event_bus.publish(
            db,
            organization_id=session.organization_id,
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            session_id=session.id,
            event_type=EventType.COMPACTION_COMPLETED,
            payload={"summary": {"id": str(summary.id), "char_count": summary.char_count}, "job_id": job_id},
        )
        return summary

    async def create_session_summary(
        self,
        db: AsyncSession,
        *,
        session: Session,
        summary_type: str = "rolling",
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        messages = await self._load_session_messages(db, session=session, source_message_end_id=None)
        if content:
            summary = await summary_service.create_from_messages(
                db,
                session=session,
                messages=messages,
                content=content,
                summary_type=summary_type,
                model=None,
                metadata=metadata,
                supersede_active=summary_type == "compaction",
            )
        else:
            summary = await self._generate_summary(
                db,
                session=session,
                messages=messages,
                agent_id="summary",
                summary_type=summary_type,
                metadata=metadata,
                supersede_active=summary_type == "compaction",
            )
        await memory_service.create_from_session_summary(
            db,
            session=session,
            summary_id=summary.id,
            content=summary.content,
            metadata={"summary_type": summary.summary_type, **(metadata or {})},
        )
        return summary

    async def _generate_summary(
        self,
        db: AsyncSession,
        *,
        session: Session,
        messages: list[Message],
        agent_id: str,
        summary_type: str,
        metadata: dict[str, Any] | None = None,
        supersede_active: bool = False,
    ):
        agent = agent_registry.get(agent_id)
        provider = get_provider(agent.llm.provider)
        prompt = self._summary_prompt(messages, summary_type=summary_type)
        model_call = ModelCall(
            organization_id=session.organization_id,
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            session_id=session.id,
            provider=agent.llm.provider,
            model=agent.llm.model,
            status="running",
            request_json=redact_data({"system": agent.system_prompt, "prompt": prompt, "summary_type": summary_type}),
        )
        db.add(model_call)
        await db.flush()
        await event_bus.publish(
            db,
            organization_id=session.organization_id,
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            session_id=session.id,
            event_type=EventType.MODEL_CALL_STARTED,
            payload={"id": str(model_call.id), "model": agent.llm.model, "agent_id": agent.id},
        )
        try:
            response = await provider.generate(
                model=agent.llm.model,
                system=agent.system_prompt,
                prompt=prompt,
                temperature=agent.temperature,
                top_p=agent.top_p,
            )
        except httpx.HTTPError as exc:
            error = redact_text(str(exc) or exc.__class__.__name__)
            model_call.status = "failed"
            model_call.error = error
            await event_bus.publish(
                db,
                organization_id=session.organization_id,
                project_id=session.project_id,
                workspace_id=session.workspace_id,
                session_id=session.id,
                event_type=EventType.MODEL_CALL_FAILED,
                severity="error",
                payload={"id": str(model_call.id), "error": error},
            )
            return await summary_service.record_failed(
                db,
                session=session,
                summary_type=summary_type,
                error=error,
                model=agent.llm.model,
                metadata=metadata,
            )
        raw = str(response.get("response", ""))
        content = self._summary_content(raw)
        model_call.status = "completed"
        model_call.latency_ms = response.get("latency_ms")
        model_call.prompt_tokens = int(response.get("prompt_eval_count") or 0)
        model_call.completion_tokens = int(response.get("eval_count") or 0)
        model_call.response_json = redact_data(response)
        await event_bus.publish(
            db,
            organization_id=session.organization_id,
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            session_id=session.id,
            event_type=EventType.MODEL_CALL_COMPLETED,
            payload={"id": str(model_call.id), "latency_ms": model_call.latency_ms},
        )
        return await summary_service.create_from_messages(
            db,
            session=session,
            messages=messages,
            content=content,
            summary_type=summary_type,
            model=agent.llm.model,
            metadata=metadata,
            supersede_active=supersede_active,
        )

    async def _maybe_enqueue_compaction(self, db: AsyncSession, *, session: Session, run: AgentRun, bundle, user_id) -> None:
        if run.agent_id in {"summary", "compaction"} or not bundle.needs_compaction:
            return
        await event_bus.publish(
            db,
            organization_id=session.organization_id,
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            session_id=session.id,
            agent_run_id=run.id,
            event_type=EventType.COMPACTION_NEEDED,
            payload={
                "excluded_message_count": bundle.excluded_message_count,
                "budget_used": bundle.budget_used,
                "char_budget": bundle.char_budget,
                "reason": bundle.compaction_reason,
            },
        )
        settings = get_settings()
        if not settings.queue.enabled:
            return
        from backend.app.queue.jobs import runtime_queue

        end_message_id = self._latest_included_message_id(bundle)
        job = await runtime_queue.enqueue_session_compaction(
            db,
            session_id=session.id,
            source_message_end_id=end_message_id,
            user_id=user_id,
            organization_id=session.organization_id,
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            reason=bundle.compaction_reason or "context_pressure",
        )
        await event_bus.publish(
            db,
            organization_id=session.organization_id,
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            session_id=session.id,
            agent_run_id=run.id,
            event_type=EventType.COMPACTION_QUEUED,
            payload={"queue_job_id": str(job.id), "source_message_end_id": str(end_message_id) if end_message_id else None},
        )

    def _latest_included_message_id(self, bundle) -> UUID | None:
        if not bundle.included_messages:
            return None
        value = bundle.included_messages[-1].metadata.get("id")
        return UUID(str(value)) if value else None

    def _summary_prompt(self, messages: list[Message], *, summary_type: str) -> str:
        transcript = "\n\n".join(f"{message.role.upper()}:\n{message.content}" for message in messages)
        return (
            f"Create a {summary_type} summary of the session transcript below. "
            "Return exactly JSON: {\"type\":\"final\",\"content\":\"...\"}. "
            "Preserve goals, constraints, decisions, progress, blockers, next steps, and important file paths.\n\n"
            f"{transcript}"
        )

    def _summary_content(self, raw: str) -> str:
        try:
            payload = _extract_json(raw)
        except Exception:
            return _fallback_final_content(raw, "Summary generation returned no content.")
        return _fallback_final_content(str(payload.get("content") or payload.get("summary") or raw))

    async def _load_session_messages(self, db: AsyncSession, *, session: Session, source_message_end_id) -> list[Message]:
        if hasattr(db, "objects"):
            rows = [
                row
                for (model, _row_id), row in db.objects.items()
                if model is Message and row.session_id == session.id
            ]
        else:
            rows = list(
                (
                    await db.scalars(
                        select(Message)
                        .where(Message.session_id == session.id)
                        .order_by(Message.created_at.asc(), Message.id.asc())
                    )
                ).all()
            )
        rows = sorted(rows, key=lambda item: (item.created_at, item.id))
        if source_message_end_id:
            filtered: list[Message] = []
            for row in rows:
                filtered.append(row)
                if row.id == source_message_end_id:
                    break
            return filtered
        return rows

    async def _complete_human_input_tool(
        self,
        db: AsyncSession,
        *,
        context: HumanInputResumeContext,
        user_id,
    ) -> dict[str, Any]:
        request = context.request
        tool_call = context.tool_call
        metadata = request.metadata_json or {}
        choices = list(metadata.get("choices") or [])
        selected_choice = request.answer if request.answer in choices else None
        payload = {
            "ok": True,
            "output": {
                "answer": request.answer,
                "selected_choice": selected_choice,
                "human_input_request_id": str(request.id),
            },
            "error": None,
            "artifacts": [],
            "metadata": {
                "answered_at": request.answered_at.isoformat() if request.answered_at else None,
                "answered_by": str(request.answered_by_user_id or user_id) if (request.answered_by_user_id or user_id) else None,
            },
            "redacted": False,
            "truncated": False,
        }
        tool_call.status = "completed"
        tool_call.output_json = redact_data(payload)
        tool_call.completed_at = datetime.now(UTC)
        tool_call.duration_ms = self._duration_ms(tool_call.started_at, tool_call.completed_at)
        await event_bus.publish(
            db,
            organization_id=request.organization_id,
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            session_id=request.session_id,
            agent_run_id=request.run_id,
            tool_call_id=request.tool_call_id,
            event_type=EventType.TOOL_CALL_COMPLETED,
            payload={"id": str(tool_call.id), "tool": tool_call.tool_name, "result": tool_call.output_json, "resumed": True},
        )
        return tool_call.output_json

    def _duration_ms(self, started_at: datetime | None, completed_at: datetime | None) -> int | None:
        if not started_at or not completed_at:
            return None
        return max(int((completed_at - started_at).total_seconds() * 1000), 0)

    async def _fail_run(
        self,
        db: AsyncSession,
        *,
        run: AgentRun,
        session: Session,
        error: str,
        metadata: dict[str, Any] | None = None,
    ) -> AgentRun:
        await message_service.create_assistant(
            db,
            session=session,
            content=redact_text(error),
            metadata=redact_data({"error": True, "agent_run_id": str(run.id), **(metadata or {})}),
        )
        run.status = "failed"
        run.error = redact_text(error)
        run.completed_at = datetime.now(UTC)
        session.status = "failed"
        await event_bus.publish(
            db,
            organization_id=session.organization_id,
            project_id=session.project_id,
            workspace_id=session.workspace_id,
            session_id=session.id,
            agent_run_id=run.id,
            event_type=EventType.AGENT_RUN_FAILED,
            severity="error",
            payload={"id": str(run.id), "error": error},
        )
        return run


agent_runner = AgentRunner()
