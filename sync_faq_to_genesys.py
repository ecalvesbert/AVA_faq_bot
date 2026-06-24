#!/usr/bin/env python3
"""Upload processed crawl markdown to Genesys Knowledge Fabric (File Connector API)."""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from call_ai_studio_api import get_access_token, request_json, resolve_config


DEFAULT_INPUT_DIR = Path("artifacts/crawls/genesys.com/processed")
DEFAULT_STATE_FILE = Path("artifacts/knowledge-sync-state.json")
SUPPORTED_SUFFIXES = {".md", ".txt", ".html", ".pdf", ".doc", ".docx", ".csv", ".xls", ".xlsx"}
FRONT_MATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def api_url(environment: str, endpoint: str) -> str:
    endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
    return f"https://api.{environment}{endpoint}"


def ensure_source(
    token: str,
    environment: str,
    *,
    source_id: str | None,
    source_name: str,
    source_description: str,
) -> str:
    if source_id:
        status, payload = request_json(
            "GET",
            api_url(environment, f"/api/v2/knowledge/sources/{source_id}"),
            headers={"Authorization": f"Bearer {token}"},
        )
        if status == 200:
            print(f"Using existing source: {source_id} ({payload.get('name')})")
            return source_id
        print(f"Source {source_id} not found (HTTP {status}); creating a new one.")

    status, payload = request_json(
        "POST",
        api_url(environment, "/api/v2/knowledge/sources"),
        headers={"Authorization": f"Bearer {token}"},
        body={
            "name": source_name,
            "description": source_description,
            "type": "FileUpload",
        },
    )
    if status not in {200, 201}:
        raise RuntimeError(f"Create source failed (HTTP {status}): {json.dumps(payload)}")

    created_id = payload["id"]
    print(f"Created source: {created_id} ({payload.get('name')})")
    return created_id


def start_sync(
    token: str,
    environment: str,
    source_id: str,
    sync_type: str,
) -> str:
    status, payload = request_json(
        "POST",
        api_url(environment, f"/api/v2/knowledge/sources/{source_id}/synchronizations"),
        headers={"Authorization": f"Bearer {token}"},
        body={"type": sync_type},
    )
    if status not in {200, 201, 202}:
        raise RuntimeError(f"Start sync failed (HTTP {status}): {json.dumps(payload)}")

    sync_id = payload["id"]
    print(f"Started sync: {sync_id} (type={payload.get('type', sync_type)})")
    return sync_id


def parse_front_matter(text: str) -> dict[str, str]:
    match = FRONT_MATTER_RE.match(text)
    if not match:
        return {}
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if line.startswith("source_url:"):
            meta["source_url"] = line.split(":", 1)[1].strip()
        elif line.startswith("title:"):
            meta["title"] = line.split(":", 1)[1].strip()
    return meta


def read_upload_metadata(file_path: Path) -> dict[str, str]:
    meta = parse_front_matter(file_path.read_text(encoding="utf-8"))
    payload = {"fileName": file_path.name}
    source_url = meta.get("source_url", "").strip()
    if source_url:
        payload["url"] = source_url
    return payload


def upload_file(
    token: str,
    environment: str,
    source_id: str,
    sync_id: str,
    file_path: Path,
) -> dict[str, str]:
    upload_request = read_upload_metadata(file_path)
    file_name = upload_request["fileName"]
    status, payload = request_json(
        "POST",
        api_url(
            environment,
            f"/api/v2/knowledge/sources/{source_id}/synchronizations/{sync_id}/uploads",
        ),
        headers={"Authorization": f"Bearer {token}"},
        body=upload_request,
    )
    if status not in {200, 201}:
        raise RuntimeError(
            f"Upload URL request failed for {file_name} (HTTP {status}): {json.dumps(payload)}"
        )

    upload_url = payload["url"]
    upload_headers = payload.get("headers") or {}
    content_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
    data = file_path.read_bytes()

    request = urllib.request.Request(upload_url, data=data, method="PUT")
    for key, value in upload_headers.items():
        request.add_header(key, value)
    request.add_header("Content-Type", content_type)

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            if response.status not in {200, 201, 204}:
                raise RuntimeError(f"PUT {file_name} returned HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"PUT {file_name} failed (HTTP {exc.code}): {detail}") from exc

    return {
        "file": file_name,
        "sourceUrl": upload_request.get("url", ""),
    }


def complete_sync(
    token: str,
    environment: str,
    source_id: str,
    sync_id: str,
) -> dict[str, Any]:
    status, payload = request_json(
        "PATCH",
        api_url(
            environment,
            f"/api/v2/knowledge/sources/{source_id}/synchronizations/{sync_id}",
        ),
        headers={"Authorization": f"Bearer {token}"},
        body={"status": "Completed"},
    )
    if status not in {200, 202}:
        raise RuntimeError(f"Complete sync failed (HTTP {status}): {json.dumps(payload)}")
    return payload


def collect_files(input_dir: Path) -> list[Path]:
    files = sorted(
        path
        for path in input_dir.iterdir()
        if path.is_file()
        and path.suffix.lower() in SUPPORTED_SUFFIXES
        and path.name not in {"manifest.json", "sources-index.json"}
    )
    if not files:
        raise FileNotFoundError(f"No uploadable files found in {input_dir}")
    return files


def cmd_upload(args: argparse.Namespace) -> int:
    input_dir = Path(args.input_dir)
    state_file = Path(args.state_file)
    files = collect_files(input_dir)

    client_id, client_secret, environment = resolve_config(args.profile)
    print(f"Environment: {environment}")
    print(f"Input dir:   {input_dir} ({len(files)} files)")
    token = get_access_token(client_id, client_secret, environment)
    print("Token acquired.")

    state = load_state(state_file)
    source_id = args.source_id or state.get("sourceId")
    source_id = ensure_source(
        token,
        environment,
        source_id=source_id,
        source_name=args.source_name,
        source_description=args.source_description,
    )

    sync_type = args.sync_type
    source_id_final = source_id
    sync_id = start_sync(token, environment, source_id_final, sync_type)

    uploaded: list[str] = []
    source_links: dict[str, str] = {}
    failed: list[dict[str, str]] = []

    for index, file_path in enumerate(files, start=1):
        print(f"  [{index}/{len(files)}] {file_path.name}")
        try:
            upload_meta = upload_file(token, environment, source_id_final, sync_id, file_path)
            uploaded.append(file_path.name)
            if upload_meta.get("sourceUrl"):
                source_links[file_path.name] = upload_meta["sourceUrl"]
                print(f"    source: {upload_meta['sourceUrl']}")
        except RuntimeError as exc:
            failed.append({"file": file_path.name, "error": str(exc)})
            print(f"    ERROR: {exc}", file=sys.stderr)
            if not args.continue_on_error:
                return 1

    if not uploaded:
        print("No files uploaded.", file=sys.stderr)
        return 1

    result = complete_sync(token, environment, source_id_final, sync_id)
    print(
        f"Sync completed: status={result.get('status')} "
        f"ingestionStatus={result.get('ingestionStatus')}"
    )

    run_record = {
        "completedAt": datetime.now(timezone.utc).isoformat(),
        "sourceId": source_id_final,
        "syncId": sync_id,
        "syncType": sync_type,
        "fileCount": len(uploaded),
        "files": uploaded,
        "sourceLinks": source_links,
        "failed": failed,
        "finalStatus": result.get("status"),
        "ingestionStatus": result.get("ingestionStatus"),
    }

    state.update(
        {
            "sourceId": source_id_final,
            "sourceName": args.source_name,
            "environment": environment,
            "lastSync": run_record,
        }
    )
    save_state(state_file, state)
    artifact = input_dir.parent / f"knowledge-upload-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    artifact.write_text(json.dumps(run_record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    sources_index_path = input_dir / "sources-index.json"
    manifest_path = input_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        sources_index = manifest.get("sourcesIndex") or {}
    else:
        sources_index = dict(source_links)
    if sources_index:
        sources_index_path.write_text(
            json.dumps(sources_index, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    print()
    print(f"Uploaded: {len(uploaded)} files")
    if failed:
        print(f"Failed:   {len(failed)} files")
    print(f"State:    {state_file}")
    print(f"Artifact: {artifact}")
    print()
    print("Next: In Genesys Admin, create/attach a Knowledge configuration to this source,")
    print("      then connect it to your AVA in AI Studio (Knowledge tab).")
    return 0 if not failed else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Upload processed markdown to Genesys Knowledge Fabric via File Connector API.",
    )
    parser.add_argument(
        "--input-dir",
        default=str(DEFAULT_INPUT_DIR),
        help="Directory of processed .md files",
    )
    parser.add_argument(
        "--state-file",
        default=str(DEFAULT_STATE_FILE),
        help="Persist sourceId and last sync metadata",
    )
    parser.add_argument(
        "--profile",
        default="default",
        help="Genesys profile from ~/.gc/config.toml",
    )
    parser.add_argument(
        "--source-id",
        help="Reuse an existing knowledge source ID",
    )
    parser.add_argument(
        "--source-name",
        default="genesys-com-ava-faq",
        help="Name when creating a new source",
    )
    parser.add_argument(
        "--source-description",
        default="Processed genesys.com crawl for AVA self-service FAQ",
        help="Description when creating a new source",
    )
    parser.add_argument(
        "--sync-type",
        default="Full",
        choices=["Full", "Incremental"],
        help="Synchronization type (default: Full)",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Keep uploading remaining files after a failure",
    )
    parser.set_defaults(func=cmd_upload)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
