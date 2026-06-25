"""Orchestrate crawl → process → Genesys Knowledge Fabric sync."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

PipelineStep = Literal["crawl", "process", "sync"]

from app.config import (
    crawl_dir_for_url,
    data_dir,
    jobs_dir,
    knowledge_sync_state_path,
    processed_dir_for_url,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_lock = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_path(job_id: str) -> Path:
    return jobs_dir() / f"{job_id}.json"


def load_job(job_id: str) -> dict[str, Any] | None:
    path = _job_path(job_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_job(job: dict[str, Any]) -> None:
    path = _job_path(job["id"])
    path.write_text(json.dumps(job, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    paths = sorted(jobs_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    jobs: list[dict[str, Any]] = []
    for path in paths[:limit]:
        try:
            jobs.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return jobs


def _append_step_output(step: dict[str, Any], key: str, chunk: str) -> None:
    current = step.get(key) or ""
    step[key] = (current + chunk)[-4000:]


def _run_step(job: dict[str, Any], name: str, command: list[str]) -> None:
    step: dict[str, Any] = {
        "name": name,
        "status": "running",
        "startedAt": _utc_now(),
        "stdout": "",
        "stderr": "",
    }
    job["steps"].append(step)
    save_job(job)

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        command,
        cwd=_REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    def read_stream(stream: Any, key: str) -> None:
        for line in iter(stream.readline, ""):
            with _lock:
                _append_step_output(step, key, line)
                save_job(job)
        stream.close()

    threads = [
        threading.Thread(target=read_stream, args=(proc.stdout, "stdout"), daemon=True),
        threading.Thread(target=read_stream, args=(proc.stderr, "stderr"), daemon=True),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    returncode = proc.wait()
    step["finishedAt"] = _utc_now()
    step["exitCode"] = returncode

    if returncode != 0:
        step["status"] = "failed"
        save_job(job)
        raise RuntimeError(f"{name} failed (exit {returncode}): {step.get('stderr') or step.get('stdout')}")

    step["status"] = "completed"
    save_job(job)


def _site_key(url: str) -> str:
    return urlparse(url).netloc.replace(":", "-") or "site"


def _site_dir(site: str) -> Path:
    if not site or "/" in site or "\\" in site or ".." in site:
        raise ValueError("Invalid site name")
    return data_dir() / "crawls" / site


def _safe_filename(filename: str) -> str:
    name = filename.strip()
    if not name or "/" in name or "\\" in name or ".." in name:
        raise ValueError("Invalid filename")
    return name


def _resolve_pipeline_paths(
    *,
    url: str | None,
    site: str | None,
) -> tuple[str, Path, Path]:
    if site:
        site_key = site.strip()
        crawl_dir = _site_dir(site_key)
    elif url:
        site_key = _site_key(url)
        crawl_dir = crawl_dir_for_url(url)
    else:
        raise ValueError("Provide url or site")

    processed_dir = crawl_dir / "processed"
    return site_key, crawl_dir, processed_dir


def run_pipeline(
    *,
    url: str | None = None,
    site: str | None = None,
    sync_type: str = "Full",
    source_id: str | None = None,
    source_name: str = "genesys-com-ava-faq",
    crawl_limit: int = 100,
    steps: list[PipelineStep] | None = None,
) -> str:
    selected_steps = steps or ["crawl", "process", "sync"]
    if not selected_steps:
        raise ValueError("At least one pipeline step is required")
    if "crawl" in selected_steps and not url:
        raise ValueError("url is required for the crawl step")

    site_key, crawl_dir, processed_dir = _resolve_pipeline_paths(url=url, site=site)
    job_id = str(uuid.uuid4())

    job: dict[str, Any] = {
        "id": job_id,
        "status": "pending",
        "url": url or f"https://{site_key}/",
        "site": site_key,
        "syncType": sync_type,
        "stepsRequested": selected_steps,
        "crawlDir": str(crawl_dir),
        "processedDir": str(processed_dir),
        "createdAt": _utc_now(),
        "steps": [],
        "error": None,
    }
    save_job(job)

    def worker() -> None:
        with _lock:
            job["status"] = "running"
            job["startedAt"] = _utc_now()
            save_job(job)

        try:
            data_dir().mkdir(parents=True, exist_ok=True)
            crawl_dir.mkdir(parents=True, exist_ok=True)

            if "crawl" in selected_steps:
                if not os.getenv("FIRECRAWL_API_KEY", "").strip():
                    on_railway = bool(
                        os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_PROJECT_ID")
                    )
                    if on_railway:
                        raise RuntimeError(
                            "FIRECRAWL_API_KEY is required for crawls on Railway. "
                            "Add it in Railway → ava-faq-chat → Variables, then retry ingest."
                        )

                _run_step(
                    job,
                    "crawl",
                    [
                        sys.executable,
                        "firecrawl_demo.py",
                        "crawl-shallow",
                        url or f"https://{site_key}/",
                        "--output-dir",
                        str(crawl_dir),
                        "--limit",
                        str(crawl_limit),
                    ],
                )

            if "process" in selected_steps:
                _run_step(
                    job,
                    "process",
                    [
                        sys.executable,
                        "process_crawl.py",
                        "--input-dir",
                        str(crawl_dir),
                        "--output-dir",
                        str(processed_dir),
                    ],
                )

            if "sync" in selected_steps:
                if not processed_dir.exists() or not any(processed_dir.glob("*.md")):
                    raise RuntimeError(
                        f"No processed content for {site_key}. Run process or full ingest first."
                    )

                sync_cmd = [
                    sys.executable,
                    "sync_faq_to_genesys.py",
                    "--input-dir",
                    str(processed_dir),
                    "--state-file",
                    str(knowledge_sync_state_path()),
                    "--source-name",
                    source_name,
                    "--sync-type",
                    sync_type,
                ]
                if source_id:
                    sync_cmd.extend(["--source-id", source_id])

                _run_step(job, "sync", sync_cmd)

            job["status"] = "completed"
            job["finishedAt"] = _utc_now()
            save_job(job)
        except Exception as exc:  # noqa: BLE001 — surface pipeline failure in job record
            job["status"] = "failed"
            job["error"] = str(exc)
            job["finishedAt"] = _utc_now()
            save_job(job)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return job_id


def list_sites() -> list[dict[str, Any]]:
    crawls_root = data_dir() / "crawls"
    if not crawls_root.exists():
        return []

    sites: list[dict[str, Any]] = []
    for site_dir in sorted(crawls_root.iterdir()):
        if not site_dir.is_dir():
            continue
        processed = site_dir / "processed"
        manifest = processed / "manifest.json" if processed.exists() else site_dir / "manifest.json"
        entry: dict[str, Any] = {
            "site": site_dir.name,
            "crawlDir": str(site_dir),
            "processedDir": str(processed) if processed.exists() else None,
        }
        if manifest.exists():
            try:
                meta = json.loads(manifest.read_text(encoding="utf-8"))
                entry["pageCount"] = meta.get("pageCount") or len(meta.get("pages", []))
                entry["processedAt"] = meta.get("processedAt")
            except json.JSONDecodeError:
                pass
        if processed.exists():
            entry["fileCount"] = len(list(processed.glob("*.md")))
        raw_md = [p for p in site_dir.glob("*.md") if p.is_file()]
        entry["rawFileCount"] = len(raw_md)
        sites.append(entry)
    return sites


def _content_file_path(site: str, filename: str, *, processed: bool) -> Path:
    base = _site_dir(site).resolve()
    name = _safe_filename(filename)
    relative = f"processed/{name}" if processed else name
    target = (base / relative).resolve()
    if not str(target).startswith(str(base)):
        raise ValueError("Invalid path")
    return target


def read_content_file(site: str, relative_path: str) -> str:
    base = _site_dir(site).resolve()
    target = (base / relative_path).resolve()
    if not str(target).startswith(str(base)):
        raise ValueError("Invalid path")
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(relative_path)
    return target.read_text(encoding="utf-8")


def write_content_file(site: str, filename: str, content: str, *, processed: bool) -> None:
    target = _content_file_path(site, filename, processed=processed)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def delete_content_file(site: str, filename: str, *, processed: bool) -> None:
    target = _content_file_path(site, filename, processed=processed)
    if not target.exists():
        raise FileNotFoundError(filename)
    target.unlink()


def delete_site(site: str) -> dict[str, Any]:
    site_dir = _site_dir(site)
    if not site_dir.exists():
        raise FileNotFoundError(site)
    shutil.rmtree(site_dir)
    return {"deleted": True, "site": site}


def load_sync_state() -> dict[str, Any]:
    path = knowledge_sync_state_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def list_content_files(site: str, *, processed: bool = True) -> list[str]:
    base = data_dir() / "crawls" / site
    folder = base / "processed" if processed else base
    if not folder.exists():
        return []
    return sorted(path.name for path in folder.glob("*.md"))


def import_bundle(files: list[dict[str, str]]) -> dict[str, Any]:
    """Write text files under DATA_DIR. Paths must be relative (e.g. crawls/site/foo.md)."""
    base = data_dir().resolve()
    imported: list[str] = []

    for item in files:
        rel = item.get("path", "").strip().lstrip("/")
        content = item.get("content")
        if not rel or content is None:
            raise ValueError("Each file requires path and content")
        if ".." in Path(rel).parts:
            raise ValueError(f"Invalid path: {rel}")

        target = (base / rel).resolve()
        if not str(target).startswith(str(base)):
            raise ValueError(f"Invalid path: {rel}")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        imported.append(rel)

    return {"imported": len(imported), "files": imported}
