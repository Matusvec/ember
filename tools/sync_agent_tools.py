"""Sync the local TOOL_SCHEMAS to the ElevenLabs ConvAI agent.

What it does:
  1. GET /v1/convai/tools           — list existing workspace tools by name
  2. GET /v1/convai/agents/{id}     — read current tool_ids on the agent
  3. For each schema in tools.actions.TOOL_SCHEMAS:
     - if a workspace tool with that name already exists, reuse its id
     - otherwise POST /v1/convai/tools to create it, capture the new id
  4. PATCH /v1/convai/agents/{id}   — set conversation_config.agent.prompt.tool_ids
     to the union of existing ids + the synced ids

Requires ELEVENLABS_API_KEY and ELEVENLABS_AGENT_ID in .env.

Run:  python -m tools.sync_agent_tools
      python -m tools.sync_agent_tools --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from tools.actions import TOOL_SCHEMAS

API = "https://api.elevenlabs.io"


def _headers(api_key: str, json_body: bool = False) -> dict[str, str]:
    h = {"xi-api-key": api_key}
    if json_body:
        h["Content-Type"] = "application/json"
    return h


def _request(method: str, path: str, api_key: str, body: dict | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        headers=_headers(api_key, json_body=body is not None),
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise SystemExit(f"{method} {path} failed: {exc.code} {exc.reason}\n{detail}")


def list_workspace_tools(api_key: str) -> dict[str, str]:
    """Returns {tool_name: tool_id} for every tool in the workspace."""
    out: dict[str, str] = {}
    data = _request("GET", "/v1/convai/tools", api_key)
    for t in data.get("tools", []):
        name = t.get("tool_config", {}).get("name") or t.get("name")
        tool_id = t.get("id") or t.get("tool_id")
        if name and tool_id:
            out[name] = tool_id
    return out


def get_agent(agent_id: str, api_key: str) -> dict:
    return _request("GET", f"/v1/convai/agents/{agent_id}", api_key)


def get_agent_tool_ids(agent: dict) -> list[str]:
    return (
        agent.get("conversation_config", {})
             .get("agent", {})
             .get("prompt", {})
             .get("tool_ids", []) or []
    )


def _normalize_params(params: dict) -> dict:
    """ElevenLabs requires each property to declare one of: description,
    dynamic_variable, is_system_provided, constant_value. Our local schemas
    often omit description to stay compact — inject a sensible default
    derived from the property name so the POST validates."""
    if not params:
        return {"type": "object", "properties": {}}
    out = json.loads(json.dumps(params))  # deep copy
    props = out.get("properties", {})
    for key, prop in props.items():
        if not isinstance(prop, dict):
            continue
        has_binding = any(
            prop.get(k) for k in ("description", "dynamic_variable", "is_system_provided", "constant_value")
        )
        if not has_binding:
            prop["description"] = key.replace("_", " ").capitalize()
    return out


def create_client_tool(schema: dict, api_key: str) -> str:
    """POST /v1/convai/tools. Returns the new tool_id."""
    body = {
        "tool_config": {
            "type": "client",
            "name": schema["name"],
            "description": schema["description"],
            "parameters": _normalize_params(schema.get("parameters", {})),
            "expects_response": True,
            "response_timeout_secs": 5,
        }
    }
    resp = _request("POST", "/v1/convai/tools", api_key, body)
    tool_id = resp.get("id") or resp.get("tool_id")
    if not tool_id:
        raise SystemExit(f"create_client_tool: no id in response: {resp}")
    return tool_id


def patch_agent_tool_ids(agent_id: str, tool_ids: list[str], api_key: str) -> None:
    body = {
        "conversation_config": {
            "agent": {
                "prompt": {
                    "tool_ids": tool_ids,
                }
            }
        }
    }
    _request("PATCH", f"/v1/convai/agents/{agent_id}", api_key, body)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would change without touching the API.")
    args = ap.parse_args()

    api_key = os.getenv("ELEVENLABS_API_KEY", "")
    agent_id = os.getenv("ELEVENLABS_AGENT_ID", "")
    if not api_key or not agent_id:
        raise SystemExit("ELEVENLABS_API_KEY and ELEVENLABS_AGENT_ID must be set.")

    print(f"Agent: {agent_id}")
    print(f"Local schemas: {[s['name'] for s in TOOL_SCHEMAS]}")

    workspace = list_workspace_tools(api_key)
    print(f"Workspace tools: {sorted(workspace.keys())}")

    agent = get_agent(agent_id, api_key)
    current_ids = get_agent_tool_ids(agent)
    id_to_name = {v: k for k, v in workspace.items()}
    current_names = [id_to_name.get(tid, f"<unknown:{tid}>") for tid in current_ids]
    print(f"Agent currently has {len(current_ids)} tools: {current_names}")

    synced_ids: list[str] = list(current_ids)
    for schema in TOOL_SCHEMAS:
        name = schema["name"]
        if name in workspace:
            tid = workspace[name]
            if tid in synced_ids:
                print(f"  [skip] {name}: already on agent")
            else:
                print(f"  [attach] {name}: exists in workspace, adding to agent")
                synced_ids.append(tid)
            continue

        print(f"  [create] {name}: new workspace tool")
        if args.dry_run:
            synced_ids.append(f"<new:{name}>")
            continue
        new_id = create_client_tool(schema, api_key)
        workspace[name] = new_id
        synced_ids.append(new_id)

    # Dedupe while preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for tid in synced_ids:
        if tid not in seen:
            seen.add(tid)
            deduped.append(tid)

    if deduped == current_ids:
        print("\nNo changes needed.")
        return

    print(f"\nAgent tool_ids: {len(current_ids)} → {len(deduped)}")
    if args.dry_run:
        print("(dry run — not patching agent)")
        return

    patch_agent_tool_ids(agent_id, deduped, api_key)
    print("Agent updated.")


if __name__ == "__main__":
    main()
