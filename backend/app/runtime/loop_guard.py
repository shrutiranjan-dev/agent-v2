import hashlib
import json
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.events import EventType
from backend.app.db.models import ToolCall
from backend.app.runtime.event_bus import event_bus


def input_hash(input_json: dict) -> str:
    normalized = json.dumps(input_json, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class LoopGuard:
    async def assert_not_repeated(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        project_id: UUID,
        workspace_id: UUID,
        session_id: UUID,
        agent_id: str,
        tool_name: str,
        input_json: dict,
        ) -> str:
        digest = input_hash(input_json)
        max_repeats = get_settings().runtime.max_tool_repeats
        count = await db.scalar(
            select(func.count())
            .select_from(ToolCall)
            .where(
                ToolCall.session_id == session_id,
                ToolCall.agent_id == agent_id,
                ToolCall.tool_name == tool_name,
                ToolCall.input_hash == digest,
            )
        )
        if (count or 0) >= max_repeats - 1:
            await event_bus.publish(
                db,
                organization_id=organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                session_id=session_id,
                event_type=EventType.LOOP_GUARD_BLOCKED,
                severity="warning",
                payload={
                    "agent_id": agent_id,
                    "tool_name": tool_name,
                    "input_hash": digest,
                    "max_repeats": max_repeats,
                    "reason": f"same agent + same tool + same input repeated {max_repeats} times",
                },
            )
            raise RuntimeError("Doom-loop guard blocked repeated identical tool call.")
        return digest


loop_guard = LoopGuard()
