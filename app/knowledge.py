"""Genesys Knowledge Fabric (File Connector) management helpers."""

from __future__ import annotations

import json
from typing import Any

from call_ai_studio_api import get_access_token, request_json, resolve_config

from app.config import knowledge_sync_state_path


def _api_url(environment: str, endpoint: str) -> str:
    endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
    return f"https://api.{environment}{endpoint}"


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _genesys_client() -> tuple[str, str]:
    client_id, client_secret, environment = resolve_config("default")
    token = get_access_token(client_id, client_secret, environment)
    return token, environment


def get_source(source_id: str) -> dict[str, Any]:
    token, environment = _genesys_client()
    status, payload = request_json(
        "GET",
        _api_url(environment, f"/api/v2/knowledge/sources/{source_id}"),
        headers=_auth_headers(token),
    )
    if status == 404:
        raise LookupError(f"Knowledge source not found: {source_id}")
    if status != 200:
        raise RuntimeError(f"Get source failed (HTTP {status}): {json.dumps(payload)}")
    return payload if isinstance(payload, dict) else {"raw": payload}


def delete_source(source_id: str, *, clear_local_state: bool = True) -> dict[str, Any]:
    token, environment = _genesys_client()
    status, payload = request_json(
        "DELETE",
        _api_url(environment, f"/api/v2/knowledge/sources/{source_id}"),
        headers=_auth_headers(token),
    )
    if status not in {200, 202, 204}:
        raise RuntimeError(f"Delete source failed (HTTP {status}): {json.dumps(payload)}")

    if clear_local_state:
        state_path = knowledge_sync_state_path()
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                state = {}
            if state.get("sourceId") == source_id:
                state_path.unlink(missing_ok=True)

    return {"deleted": True, "sourceId": source_id}


def knowledge_overview() -> dict[str, Any]:
    """Combine local sync state with live Genesys source metadata when possible."""
    state_path = knowledge_sync_state_path()
    state: dict[str, Any] = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state = {}

    source_id = state.get("sourceId")
    remote: dict[str, Any] | None = None
    remote_error: str | None = None
    if source_id:
        try:
            remote = get_source(source_id)
        except (LookupError, RuntimeError, ValueError, FileNotFoundError) as exc:
            remote_error = str(exc)

    return {
        "localState": state,
        "sourceId": source_id,
        "remoteSource": remote,
        "remoteError": remote_error,
    }
