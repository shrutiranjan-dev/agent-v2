from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from backend.app.db.models import Message


class FakeScalarResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class FakeAsyncSession:
    def __init__(
        self,
        *,
        messages: list[Message] | None = None,
        objects: list[Any] | None = None,
        scalar_value: Any = 0,
    ) -> None:
        self.messages = messages or []
        self.scalar_value = scalar_value
        self.added: list[Any] = []
        self.objects: dict[tuple[type, Any], Any] = {}
        self.committed = False
        for row in [*self.messages, *(objects or [])]:
            self._assign_defaults(row)
            self.objects[(type(row), row.id)] = row

    def add(self, row: Any) -> None:
        self._assign_defaults(row)
        self.added.append(row)
        self.objects[(type(row), row.id)] = row
        if isinstance(row, Message) and row not in self.messages:
            self.messages.append(row)

    async def flush(self) -> None:
        for row in self.added:
            self._assign_defaults(row)

    async def scalar(self, _statement: Any) -> Any:
        return self.scalar_value

    async def scalars(self, _statement: Any) -> FakeScalarResult:
        entity = None
        descriptions = getattr(_statement, "column_descriptions", None)
        if descriptions:
            entity = descriptions[0].get("entity")
        if entity is None:
            return FakeScalarResult(self.messages)
        rows = [row for (model, _row_id), row in self.objects.items() if model is entity]
        return FakeScalarResult(rows)

    async def get(self, model: type, row_id: Any) -> Any:
        return self.objects.get((model, row_id))

    async def commit(self) -> None:
        self.committed = True

    def _assign_defaults(self, row: Any) -> None:
        if hasattr(row, "id") and getattr(row, "id", None) is None:
            row.id = uuid4()
        now = datetime.now(UTC)
        if hasattr(row, "created_at") and getattr(row, "created_at", None) is None:
            row.created_at = now
        if hasattr(row, "updated_at") and getattr(row, "updated_at", None) is None:
            row.updated_at = now
