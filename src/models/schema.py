from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class IFlowArtifact(BaseModel):
    model_config = ConfigDict(extra="ignore")

    artifact_id: str
    version: str
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    message_flows: list[dict[str, Any]] = Field(default_factory=list)
    systems: list[dict[str, Any]] = Field(default_factory=list)
    resources: dict[str, list[str]] = Field(
        default_factory=lambda: {"scripts": [], "mappings": [], "schemas": []}
    )
    parse_warnings: list[str] = Field(default_factory=list)
