from dataclasses import dataclass
from uuid import UUID

from fastapi import Header


@dataclass(frozen=True)
class TenantContext:
    organization_id: UUID | None
    user_id: UUID | None


async def tenant_context(
    x_organization_id: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> TenantContext:
    org = UUID(x_organization_id) if x_organization_id else None
    user = UUID(x_user_id) if x_user_id else None
    return TenantContext(organization_id=org, user_id=user)

