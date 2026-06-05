from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.security import TenantContext
from backend.app.db.models import Organization, Project, User, Workspace


@dataclass(frozen=True)
class RuntimeTenant:
    organization_id: UUID
    project_id: UUID
    workspace_id: UUID
    user_id: UUID


async def ensure_runtime_tenant(db: AsyncSession, ctx: TenantContext) -> RuntimeTenant:
    settings = get_settings()
    if ctx.organization_id:
        org = await db.get(Organization, ctx.organization_id)
        if not org:
            raise ValueError(f"Organization not found: {ctx.organization_id}")
    else:
        org = await get_or_create_runtime_row(
            db,
            select(Organization).where(Organization.slug == settings.bootstrap_organization_slug),
            lambda: Organization(name="Local Organization", slug=settings.bootstrap_organization_slug),
        )

    if ctx.user_id:
        user = await db.get(User, ctx.user_id)
        if not user:
            raise ValueError(f"User not found: {ctx.user_id}")
    else:
        user = await get_or_create_runtime_row(
            db,
            select(User).where(
                User.organization_id == org.id,
                User.email == settings.bootstrap_user_email,
            ),
            lambda: User(
                organization_id=org.id,
                email=settings.bootstrap_user_email,
                display_name="Local User",
                role="owner",
            ),
        )

    project = await get_or_create_runtime_row(
        db,
        select(Project).where(
            Project.organization_id == org.id,
            Project.slug == settings.bootstrap_project_slug,
        ),
        lambda: Project(
            organization_id=org.id,
            name="Default Project",
            slug=settings.bootstrap_project_slug,
        ),
    )

    workspace = await get_or_create_runtime_row(
        db,
        select(Workspace).where(
            Workspace.organization_id == org.id,
            Workspace.project_id == project.id,
            Workspace.name == settings.bootstrap_workspace_name,
        ),
        lambda: Workspace(
            organization_id=org.id,
            project_id=project.id,
            name=settings.bootstrap_workspace_name,
            root_path=str(settings.workspace_root),
        ),
    )

    return RuntimeTenant(
        organization_id=org.id,
        project_id=project.id,
        workspace_id=workspace.id,
        user_id=user.id,
    )


async def get_or_create_runtime_row[T](
    db: AsyncSession,
    statement,
    factory,
) -> T:
    row = await db.scalar(statement)
    if row:
        return row

    row = factory()
    savepoint = await db.begin_nested()
    try:
        db.add(row)
        await db.flush()
    except IntegrityError:
        await savepoint.rollback()
        row = await db.scalar(statement)
        if row is None:
            raise
        return row
    else:
        await savepoint.commit()
        return row

