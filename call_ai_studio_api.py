#!/usr/bin/env python3
"""Call Genesys Cloud AI Studio APIs using OAuth client credentials."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_ENDPOINT = "/api/v2/apps/agentic/copilots/agents"
DEFAULT_ENVIRONMENT = "mypurecloud.com"


def load_gc_profile(profile: str) -> dict[str, str]:
    config_path = Path.home() / ".gc" / "config.toml"
    if not config_path.exists():
        raise FileNotFoundError(f"Missing gc config: {config_path}")

    section: str | None = None
    values: dict[str, str] = {}
    for raw_line in config_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section != profile or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")

    if not values:
        raise ValueError(f"Profile '{profile}' not found in {config_path}")

    return values


def resolve_config(profile: str) -> tuple[str, str, str]:
    client_id = os.getenv("GENESYS_CLIENT_ID", "").strip()
    client_secret = os.getenv("GENESYS_CLIENT_SECRET", "").strip()
    environment = os.getenv("GENESYS_ENVIRONMENT", "").strip() or DEFAULT_ENVIRONMENT

    if client_id and client_secret:
        return client_id, client_secret, environment

    profile_values = load_gc_profile(profile)
    client_id = client_id or profile_values.get("client_credentials", "")
    client_secret = client_secret or profile_values.get("client_secret", "")
    environment = environment or profile_values.get("environment", DEFAULT_ENVIRONMENT)

    if not client_id or not client_secret:
        raise ValueError(
            "Missing OAuth credentials. Set GENESYS_CLIENT_ID/GENESYS_CLIENT_SECRET "
            f"or configure profile '{profile}' in ~/.gc/config.toml."
        )

    return client_id, client_secret, environment


def request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    payload = None
    req_headers = {"Accept": "application/json", **(headers or {})}
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        req_headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=payload, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {"message": exc.reason}
        except json.JSONDecodeError:
            parsed = {"message": raw or exc.reason}
        return exc.code, parsed


def get_access_token(client_id: str, client_secret: str, environment: str) -> str:
    token_url = f"https://login.{environment}/oauth/token"
    form = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode("utf-8")
    request = urllib.request.Request(
        token_url,
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    credentials = f"{client_id}:{client_secret}".encode("utf-8")
    import base64

    request.add_header("Authorization", f"Basic {base64.b64encode(credentials).decode('ascii')}")

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            token_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OAuth failed ({exc.code}): {detail}") from exc

    access_token = token_payload.get("access_token")
    if not access_token:
        raise RuntimeError(f"OAuth response missing access_token: {token_payload}")
    return access_token


def build_api_url(environment: str, endpoint: str, query: dict[str, str]) -> str:
    endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
    query_string = urllib.parse.urlencode(query)
    return f"https://api.{environment}{endpoint}?{query_string}" if query_string else f"https://api.{environment}{endpoint}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Call a Genesys Cloud AI Studio API endpoint.")
    parser.add_argument(
        "--profile",
        default=os.getenv("GENESYS_PROFILE", "default"),
        help="Profile name in ~/.gc/config.toml (default: default)",
    )
    parser.add_argument(
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        help=f"API path to call (default: {DEFAULT_ENDPOINT})",
    )
    parser.add_argument("--method", default="GET", choices=["GET", "POST", "PUT", "PATCH", "DELETE"])
    parser.add_argument("--page-size", type=int, default=5, help="pageSize query param for list endpoints")
    parser.add_argument("--page-number", type=int, default=1, help="pageNumber query param for list endpoints")
    parser.add_argument("--body", help="JSON request body for POST/PUT/PATCH")
    args = parser.parse_args()

    client_id, client_secret, environment = resolve_config(args.profile)
    print(f"Using environment: {environment}")
    print(f"Fetching OAuth token from login.{environment} ...")

    token = get_access_token(client_id, client_secret, environment)
    print("Token acquired.")

    query = {}
    if args.method == "GET" and "agents" in args.endpoint and args.endpoint.endswith("/agents"):
        query = {"pageSize": str(args.page_size), "pageNumber": str(args.page_number)}

    url = build_api_url(environment, args.endpoint, query)
    body = json.loads(args.body) if args.body else None

    print(f"{args.method} {url}")
    status, payload = request_json(
        args.method,
        url,
        headers={"Authorization": f"Bearer {token}"},
        body=body,
    )

    print(f"HTTP {status}")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if 200 <= status < 300 else 1


if __name__ == "__main__":
    sys.exit(main())
