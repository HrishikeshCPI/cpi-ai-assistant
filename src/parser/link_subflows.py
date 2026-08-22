from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from src.models.schema import IFlowArtifact


def _effective_address(flow: dict[str, Any], parameters: list[dict[str, Any]]) -> str:
    address = flow.get("address", "")
    placeholder = re.fullmatch(r"\{\{(.*)\}\}", address)
    if placeholder is None:
        return address
    parameter_name = placeholder.group(1)
    return next((parameter.get("configured_value", "") for parameter in parameters if parameter.get("name") == parameter_name), address)


def build_subflow_links(artifacts: Iterable[IFlowArtifact]) -> list[dict[str, str]]:
    senders: list[tuple[str, str]] = []
    receivers: list[tuple[str, str]] = []
    for artifact in artifacts:
        for flow in artifact.message_flows:
            if flow.get("component_type") != "ProcessDirect":
                continue
            address = _effective_address(flow, artifact.externalized_parameters)
            if not address:
                continue
            if flow.get("direction") == "Sender":
                senders.append((artifact.artifact_id, address))
            elif flow.get("direction") == "Receiver":
                receivers.append((artifact.artifact_id, address))
    return [
        {"caller": caller, "callee": callee, "address": receiver_address}
        for caller, receiver_address in receivers
        for callee, sender_address in senders
        if receiver_address == sender_address
    ]


def write_subflow_links(artifacts: Iterable[IFlowArtifact], output_path: str | Path = "output/subflow_links.json") -> list[dict[str, str]]:
    links = build_subflow_links(artifacts)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(links, indent=2), encoding="utf-8")
    return links
