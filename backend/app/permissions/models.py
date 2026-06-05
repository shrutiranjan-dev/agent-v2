from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class PermissionAction(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class PermissionStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class PermissionDecision(BaseModel):
    action: PermissionAction
    reason: str
    permission_key: str
    resource: str


class PermissionRequestCreate(BaseModel):
    organization_id: UUID
    project_id: UUID
    workspace_id: UUID
    session_id: UUID
    agent_run_id: UUID | None = None
    tool_call_id: UUID | None = None
    permission_key: str
    resource: str
    input_json: dict[str, Any]
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    requested_by_user_id: UUID | None = None
