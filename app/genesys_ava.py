"""Genesys Cloud Agentic Virtual Agent session client."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any

from call_ai_studio_api import get_access_token, request_json, resolve_config

from app.config import genesys_agent_id, genesys_agent_version, studio_mode


@dataclass
class ChatSession:
    id: str
    genesys_session_id: str
    agent_id: str
    version: str
    environment: str
    studio_mode: bool
    noop_done: bool = False
    last_turn_id: str = ""


_sessions: dict[str, ChatSession] = {}


def _api_url(environment: str, path: str) -> str:
    return f"https://api.{environment}{path}"


def _studio_headers(environment: str) -> dict[str, str]:
    return {
        "genesys-app": "agentic-va-ui-webui",
        "Origin": f"https://apps.{environment}",
    }


def extract_agent_text(turn: dict[str, Any]) -> str:
    segments = turn.get("prompts", {}).get("text", {}).get("segments", [])
    parts = [segment.get("text", "") for segment in segments if segment.get("text")]
    return " ".join(parts).strip()


def _token_and_env() -> tuple[str, str]:
    client_id, client_secret, environment = resolve_config(os.getenv("GENESYS_PROFILE", "default"))
    token = get_access_token(client_id, client_secret, environment)
    return token, environment


def create_session() -> tuple[ChatSession, str]:
    token, environment = _token_and_env()
    agent_id = genesys_agent_id()
    version = genesys_agent_version()
    use_studio = studio_mode()

    if use_studio:
        body = {
            "version": version,
            "channel": {
                "name": "Messaging",
                "inputModes": ["Text"],
                "outputModes": ["Text"],
                "userAgent": {"name": "GenesysWebWidget"},
            },
            "inputData": {},
            "language": "en-us",
        }
    else:
        body = {
            "version": version,
            "channel": {
                "name": "Messaging",
                "userAgent": {"name": "Unknown", "version": "1.0"},
                "inputModes": ["text"],
                "outputModes": ["text"],
            },
            "language": "en-US",
        }

    headers = {"Authorization": f"Bearer {token}"}
    if use_studio:
        headers.update(_studio_headers(environment))

    status, payload = request_json(
        "POST",
        _api_url(environment, f"/api/v2/apps/agentic/virtualagents/{agent_id}/sessions"),
        headers=headers,
        body=body,
    )
    if status not in {200, 201}:
        raise RuntimeError(f"Create session failed (HTTP {status}): {payload}")

    session = ChatSession(
        id=str(uuid.uuid4()),
        genesys_session_id=payload["id"],
        agent_id=agent_id,
        version=version,
        environment=environment,
        studio_mode=use_studio,
    )
    _sessions[session.id] = session

    greeting = ""
    if use_studio:
        noop_turn = send_noop(session)
        greeting = extract_agent_text(noop_turn)

    return session, greeting


def get_session(session_id: str) -> ChatSession | None:
    return _sessions.get(session_id)


def end_session(session_id: str) -> bool:
    return _sessions.pop(session_id, None) is not None


def _post_turn(session: ChatSession, body: dict[str, Any]) -> dict[str, Any]:
    token, environment = _token_and_env()
    headers = {"Authorization": f"Bearer {token}"}
    if session.studio_mode:
        headers.update(_studio_headers(environment))

    status, payload = request_json(
        "POST",
        _api_url(
            environment,
            f"/api/v2/apps/agentic/virtualagents/{session.agent_id}/sessions/{session.genesys_session_id}/turns",
        ),
        headers=headers,
        body=body,
    )
    if status not in {200, 201}:
        raise RuntimeError(f"Turn failed (HTTP {status}): {payload}")
    if not isinstance(payload, dict):
        raise RuntimeError("Turn response was not JSON object")
    return payload


def send_noop(session: ChatSession) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "version": session.version,
        "inputEvent": {"type": "NoOp", "mode": "Text"},
    }
    if session.last_turn_id:
        payload["previousTurn"] = {"id": session.last_turn_id}

    turn = _post_turn(session, payload)
    session.noop_done = True
    session.last_turn_id = turn.get("id", "")
    return turn


def send_message(session: ChatSession, message: str) -> dict[str, Any]:
    if session.studio_mode and not session.noop_done:
        send_noop(session)

    payload: dict[str, Any] = {
        "version": session.version,
        "inputEvent": {
            "type": "UserInput",
            "mode": "Text",
            "alternatives": [
                {"transcript": {"confidence": 1, "text": message}},
            ],
        },
    }
    if session.last_turn_id:
        payload["previousTurn"] = {"id": session.last_turn_id}

    turn = _post_turn(session, payload)
    session.last_turn_id = turn.get("id", session.last_turn_id)

    # After knowledge/tool calls the AVA often returns nextAction NoOp with no text yet.
    for _ in range(3):
        if extract_agent_text(turn):
            break
        if (turn.get("nextAction") or {}).get("type") != "NoOp":
            break
        turn = send_noop(session)

    return turn
