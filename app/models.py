from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExecuteRequest(BaseModel):
    module: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    input: dict[str, Any] = Field(default_factory=dict)
    user_id: str = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")


class ModuleResources(BaseModel):
    timeout_ms: int = Field(gt=0)
    memory_mb: int = Field(gt=0)

    model_config = ConfigDict(extra="forbid")


class ModuleManifest(BaseModel):
    name: str = Field(min_length=1)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    runtime_api: str = Field(min_length=1)
    entrypoint: str = Field(min_length=1)
    permissions: list[str] = Field(default_factory=list)
    resources: ModuleResources

    model_config = ConfigDict(extra="forbid")


class ModuleExecutionResult(BaseModel):
    output: dict[str, Any]
    memory_write: dict[str, Any]

    model_config = ConfigDict(extra="forbid")


class ExecuteResponse(BaseModel):
    request_id: str
    module: str
    output: dict[str, Any]
    memory_write: dict[str, Any]
    execution_time_ms: int = Field(ge=0)

    model_config = ConfigDict(extra="forbid")
