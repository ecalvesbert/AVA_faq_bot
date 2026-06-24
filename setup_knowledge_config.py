#!/usr/bin/env python3
"""Create or update a Genesys Knowledge Fabric configuration (knowledge setting)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from call_ai_studio_api import get_access_token, request_json, resolve_config


DEFAULT_STATE_FILE = Path("artifacts/knowledge-sync-state.json")
DEFAULT_CONFIG_STATE = Path("artifacts/knowledge-config-state.json")


def api_url(environment: str, endpoint: str) -> str:
    endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
    return f"https://api.{environment}{endpoint}"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


DEFAULT_FOUND_RESULT_MESSAGE = (
    "Answer using only the retrieved knowledge. "
    "Always end with a short 'Source:' line that includes the source page URL from the result "
    "(use the url field when present, otherwise the value after 'Customer reference URL:' or 'Source:'). "
    "Do not ask 'Did this answer your question?' or similar after every response."
)


def ensure_draft_version(
    token: str,
    environment: str,
    agent_id: str,
    base_version: str,
    new_version: str | None,
) -> str:
    status, current = request_json(
        "GET",
        api_url(
            environment,
            f"/api/v2/apps/agentic/virtualagents/{agent_id}/versions/{base_version}",
        ),
        headers={"Authorization": f"Bearer {token}"},
    )
    if status != 200:
        raise RuntimeError(f"Could not load AVA version {base_version} (HTTP {status})")

    if current.get("status") != "ProductionReady":
        return base_version

    if not new_version:
        raise RuntimeError(
            f"AVA version {base_version} is ProductionReady. "
            "Pass --new-version to create an editable draft before updating knowledge output."
        )

    status, payload = request_json(
        "POST",
        api_url(environment, f"/api/v2/apps/agentic/virtualagents/{agent_id}/versions"),
        headers={"Authorization": f"Bearer {token}"},
        body={"version": new_version, "definition": current["definition"]},
    )
    if status not in {200, 201}:
        raise RuntimeError(f"Create AVA version failed (HTTP {status}): {json.dumps(payload)}")

    print(f"Created draft AVA version {new_version} from {base_version}")
    return new_version


def ensure_knowledge_setting(
    token: str,
    environment: str,
    *,
    setting_id: str | None,
    name: str,
    description: str,
    source_id: str,
    search_with_context: bool,
    answer_generation: bool,
    answer_language: str,
) -> dict[str, Any]:
    body = {
        "name": name,
        "description": description,
        "sources": [{"id": source_id}],
        "searchWithContext": search_with_context,
        "answerGeneration": {
            "enabled": answer_generation,
            "language": answer_language,
        },
    }

    if setting_id:
        status, payload = request_json(
            "PATCH",
            api_url(environment, f"/api/v2/knowledge/settings/{setting_id}"),
            headers={"Authorization": f"Bearer {token}"},
            body=body,
        )
        action = "updated"
    else:
        status, payload = request_json(
            "POST",
            api_url(environment, "/api/v2/knowledge/settings"),
            headers={"Authorization": f"Bearer {token}"},
            body=body,
        )
        action = "created"

    if status not in {200, 201}:
        raise RuntimeError(f"Knowledge setting {action} failed (HTTP {status}): {json.dumps(payload)}")

    print(f"Knowledge configuration {action}: {payload['id']} ({payload['name']})")
    return payload


def connect_ava_knowledge_tool(
    token: str,
    environment: str,
    *,
    agent_id: str,
    version: str,
    setting_id: str,
    setting_name: str,
    tool_name: str,
    tool_description: str,
    pre_instructions: list[str],
    output_instructions: list[dict[str, str]],
    publish: bool,
) -> dict[str, Any]:
    status, current = request_json(
        "GET",
        api_url(
            environment,
            f"/api/v2/apps/agentic/virtualagents/{agent_id}/versions/{version}",
        ),
        headers={"Authorization": f"Bearer {token}"},
    )
    if status != 200:
        raise RuntimeError(f"Could not load AVA version {version} (HTTP {status}): {json.dumps(current)}")

    if current.get("status") == "ProductionReady":
        raise RuntimeError(
            f"AVA version {version} is ProductionReady and immutable. "
            "Create a new draft version in AI Studio or pass --version with a Draft version."
        )

    definition = current["definition"]
    tools = definition.setdefault("tools", [])
    tools = [tool for tool in tools if tool.get("targetId") != setting_id]
    tools.append(
        {
            "name": tool_name,
            "description": tool_description,
            "inputInstructions": pre_instructions,
            "outputInstructions": output_instructions,
            "targetId": setting_id,
            "targetName": setting_name,
            "type": "KnowledgeSetting",
        }
    )
    definition["tools"] = tools

    status, payload = request_json(
        "PATCH",
        api_url(
            environment,
            f"/api/v2/apps/agentic/virtualagents/{agent_id}/versions/{version}",
        ),
        headers={"Authorization": f"Bearer {token}"},
        body={"definition": definition},
    )
    if status != 200:
        raise RuntimeError(f"AVA knowledge connect failed (HTTP {status}): {json.dumps(payload)}")

    print(f"Connected knowledge configuration to AVA {agent_id} v{version}")

    if publish:
        publish_body = {
            "job": {"type": "Publish"},
            "virtualAgentVersion": {
                "version": version,
                "status": "ProductionReady",
                "virtualAgent": {"id": agent_id},
            },
        }
        status, job = request_json(
            "POST",
            api_url(
                environment,
                f"/api/v2/apps/agentic/virtualagents/{agent_id}/versions/{version}/jobs",
            ),
            headers={"Authorization": f"Bearer {token}"},
            body=publish_body,
        )
        if status not in {200, 201, 202}:
            raise RuntimeError(f"AVA publish failed (HTTP {status}): {json.dumps(job)}")

        job_id = job["id"]
        print(f"Publish job started: {job_id}")
        for _ in range(20):
            time.sleep(2)
            status, job_status = request_json(
                "GET",
                api_url(
                    environment,
                    f"/api/v2/apps/agentic/virtualagents/{agent_id}/versions/{version}/jobs/{job_id}",
                ),
                headers={"Authorization": f"Bearer {token}"},
            )
            state = (job_status or {}).get("status")
            print(f"  publish status={state}")
            if state in {"Succeeded", "Failed", "Cancelled"}:
                if state != "Succeeded":
                    raise RuntimeError(f"Publish job ended with {state}: {json.dumps(job_status)}")
                break

    return payload


def cmd_setup(args: argparse.Namespace) -> int:
    sync_state = load_json(Path(args.sync_state_file))
    source_id = args.source_id or sync_state.get("sourceId")
    if not source_id:
        raise ValueError("Missing sourceId. Run sync_faq_to_genesys.py first or pass --source-id.")

    config_state = load_json(Path(args.config_state_file))
    setting_id = args.setting_id or config_state.get("settingId")

    client_id, client_secret, environment = resolve_config(args.profile)
    print(f"Environment: {environment}")
    token = get_access_token(client_id, client_secret, environment)
    print("Token acquired.")

    setting = ensure_knowledge_setting(
        token,
        environment,
        setting_id=setting_id,
        name=args.name,
        description=args.description,
        source_id=source_id,
        search_with_context=args.search_with_context,
        answer_generation=args.answer_generation,
        answer_language=args.answer_language,
    )

    config_state.update(
        {
            "settingId": setting["id"],
            "settingName": setting["name"],
            "sourceId": source_id,
            "environment": environment,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }
    )
    save_json(Path(args.config_state_file), config_state)

    if args.agent_id and args.version:
        version = ensure_draft_version(
            token,
            environment,
            args.agent_id,
            args.version,
            args.new_version,
        )
        connect_ava_knowledge_tool(
            token,
            environment,
            agent_id=args.agent_id,
            version=version,
            setting_id=setting["id"],
            setting_name=setting["name"],
            tool_name=args.tool_name,
            tool_description=args.tool_description,
            pre_instructions=args.pre_instruction,
            output_instructions=[
                {
                    "when": "lambda result: len(result) == 0",
                    "then": args.no_result_message,
                },
                {
                    "when": "lambda result: len(result) > 0",
                    "then": args.found_result_message,
                },
            ],
            publish=args.publish,
        )
        config_state["ava"] = {
            "agentId": args.agent_id,
            "version": version,
            "toolName": args.tool_name,
            "published": args.publish,
        }
        save_json(Path(args.config_state_file), config_state)

    print()
    print(f"Knowledge configuration ID: {setting['id']}")
    print(f"State file: {args.config_state_file}")
    if not args.agent_id:
        print("Optional next step: connect to an AVA draft version with --agent-id and --version")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create/update Genesys Knowledge Fabric configuration and optionally connect to AVA.",
    )
    parser.add_argument("--profile", default="default")
    parser.add_argument("--sync-state-file", default=str(DEFAULT_STATE_FILE))
    parser.add_argument("--config-state-file", default=str(DEFAULT_CONFIG_STATE))
    parser.add_argument("--source-id", help="Knowledge fabric source ID")
    parser.add_argument("--setting-id", help="Existing knowledge setting ID to update")
    parser.add_argument("--name", default="genesys-com-ava-faq-config")
    parser.add_argument(
        "--description",
        default="AVA self-service FAQ from processed genesys.com website crawl",
    )
    parser.add_argument("--search-with-context", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--answer-generation", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--answer-language", default="en-us")
    parser.add_argument("--agent-id", help="Agentic virtual agent ID")
    parser.add_argument("--version", help="AVA version to connect (e.g. 4.0)")
    parser.add_argument(
        "--new-version",
        help="When --version is ProductionReady, clone to this draft version first (e.g. 5.0)",
    )
    parser.add_argument("--tool-name", default="search_genesys_com_faq_knowledge")
    parser.add_argument(
        "--tool-description",
        default="Public Genesys.com product and capability FAQ from crawled website content.",
    )
    parser.add_argument(
        "--pre-instruction",
        action="append",
        default=[
            "Use when the customer asks about Genesys Cloud products, Agentic Virtual Agents, Copilot, integrations, journey management, WhatsApp CX, or experience orchestration.",
            "Do not use for pricing quotes, account-specific issues, legal terms, or downloading gated resources.",
            "If knowledge returns no useful results, apologize and offer to transfer to a human agent.",
        ],
    )
    parser.add_argument(
        "--no-result-message",
        default="I couldn't find that in our public FAQ. Would you like me to connect you with someone who can help?",
    )
    parser.add_argument(
        "--found-result-message",
        default=DEFAULT_FOUND_RESULT_MESSAGE,
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Publish the AVA version to ProductionReady after connecting knowledge",
    )
    parser.set_defaults(func=cmd_setup)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
