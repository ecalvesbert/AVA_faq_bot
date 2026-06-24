#!/usr/bin/env python3
"""Upload local crawl artifacts to the Railway content store via /api/content/import."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_ARTIFACTS = Path("artifacts")
DEFAULT_REMOTE = "https://ava-faq-chat-production.up.railway.app"
TEXT_SUFFIXES = {".md", ".json", ".txt"}


def collect_files(artifacts_dir: Path) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []

    crawl_root = artifacts_dir / "crawls"
    if crawl_root.exists():
        for path in sorted(crawl_root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            rel = path.relative_to(artifacts_dir)
            files.append(
                {
                    "path": f"crawls/{rel.as_posix().removeprefix('crawls/')}",
                    "content": path.read_text(encoding="utf-8"),
                }
            )

    for name in ("knowledge-sync-state.json", "knowledge-config-state.json"):
        state_path = artifacts_dir / name
        if state_path.exists():
            files.append({"path": name, "content": state_path.read_text(encoding="utf-8")})

    return files


def post_batch(remote: str, pipeline_key: str, batch: list[dict[str, str]]) -> dict:
    payload = json.dumps({"files": batch}).encode("utf-8")
    request = urllib.request.Request(
        f"{remote.rstrip('/')}/api/content/import",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Pipeline-Key": pipeline_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Import failed (HTTP {exc.code}): {detail}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync local artifacts to Railway content store.")
    parser.add_argument("--artifacts-dir", default=str(DEFAULT_ARTIFACTS))
    parser.add_argument("--remote", default=os.getenv("RAILWAY_APP_URL", DEFAULT_REMOTE))
    parser.add_argument("--pipeline-key", default=os.getenv("PIPELINE_API_KEY", ""))
    parser.add_argument("--batch-size", type=int, default=15)
    args = parser.parse_args()

    if not args.pipeline_key:
        print("Set PIPELINE_API_KEY or pass --pipeline-key", file=sys.stderr)
        return 1

    artifacts_dir = Path(args.artifacts_dir)
    files = collect_files(artifacts_dir)
    if not files:
        print(f"No importable files under {artifacts_dir}", file=sys.stderr)
        return 1

    print(f"Remote:  {args.remote}")
    print(f"Files:   {len(files)}")
    total = 0
    for start in range(0, len(files), args.batch_size):
        batch = files[start : start + args.batch_size]
        result = post_batch(args.remote, args.pipeline_key, batch)
        total += result.get("imported", 0)
        print(f"  Batch {start // args.batch_size + 1}: imported {result.get('imported', 0)}")

    print(f"Done — {total} files on Railway under /data")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
