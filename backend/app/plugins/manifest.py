from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class PluginToolManifest(BaseModel):
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    risk_level: str = "medium"
    metadata: dict[str, Any] = Field(default_factory=dict)


class PluginManifest(BaseModel):
    name: str
    version: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    tools: list[PluginToolManifest] = Field(default_factory=list)
    hooks: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def load_manifest(path: str | Path) -> PluginManifest:
    manifest_path = Path(path).expanduser().resolve()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return PluginManifest.model_validate(data)
