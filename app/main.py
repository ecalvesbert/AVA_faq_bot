"""FastAPI application: AVA chat UI, ingest pipeline, content store."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from app import config, genesys_ava, knowledge, pipeline

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="AVA FAQ Chat", version="1.0.0")


class SessionResponse(BaseModel):
    sessionId: str
    agentId: str
    version: str
    greeting: Optional[str] = None


class MessageRequest(BaseModel):
    sessionId: str
    message: str = Field(min_length=1, max_length=4000)


class MessageResponse(BaseModel):
    text: str
    turnId: Optional[str] = None
    nextAction: Optional[str] = None
    responseTimeMs: int = 0
    outputTokens: int = 0


class PipelineRunRequest(BaseModel):
    url: Optional[str] = None
    site: Optional[str] = None
    syncType: Literal["Full", "Incremental"] = "Full"
    sourceId: Optional[str] = None
    sourceName: str = "genesys-com-ava-faq"
    crawlLimit: int = Field(default=100, ge=1, le=500)
    steps: list[Literal["crawl", "process", "sync"]] = Field(
        default_factory=lambda: ["crawl", "process", "sync"]
    )

    @model_validator(mode="after")
    def validate_target(self) -> "PipelineRunRequest":
        if not self.url and not self.site:
            raise ValueError("Provide url or site")
        if "crawl" in self.steps and not self.url:
            raise ValueError("url is required when crawl step is selected")
        if not self.steps:
            raise ValueError("Select at least one pipeline step")
        return self


class PipelineRunResponse(BaseModel):
    jobId: str


class ImportFileItem(BaseModel):
    path: str = Field(min_length=1)
    content: str


class ImportBundleRequest(BaseModel):
    files: list[ImportFileItem] = Field(min_length=1)


class ContentFileResponse(BaseModel):
    site: str
    filename: str
    processed: bool
    content: str


class ContentFileWriteRequest(BaseModel):
    content: str


class ContentFileCreateRequest(BaseModel):
    filename: str = Field(min_length=1)
    content: str = ""
    processed: bool = True


def require_chat_key(x_chat_key: Optional[str] = Header(default=None)) -> None:
    expected = config.chat_api_key()
    if expected and x_chat_key != expected:
        raise HTTPException(status_code=401, detail="Invalid chat API key")


def require_pipeline_key(x_pipeline_key: Optional[str] = Header(default=None)) -> None:
    expected = config.pipeline_api_key()
    provided = (x_pipeline_key or "").strip()
    if config.pipeline_key_enforced() and not expected:
        raise HTTPException(
            status_code=503,
            detail="PIPELINE_API_KEY is not configured. Ingest is manual-only via /admin.",
        )
    if expected and provided != expected:
        raise HTTPException(status_code=401, detail="Invalid pipeline API key")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config/public")
def public_config() -> dict[str, str]:
    return {
        "title": config.chat_title(),
        "subtitle": config.chat_subtitle(),
        "chatKeyRequired": "true" if config.chat_api_key() else "false",
        "pipelineKeyRequired": "true" if config.pipeline_api_key() else "false",
    }


@app.post("/api/chat/session", response_model=SessionResponse)
def create_chat_session(_: None = Depends(require_chat_key)) -> SessionResponse:
    try:
        session, greeting = genesys_ava.create_session()
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return SessionResponse(
        sessionId=session.id,
        agentId=session.agent_id,
        version=session.version,
        greeting=greeting or None,
    )


@app.post("/api/chat/message", response_model=MessageResponse)
def send_chat_message(body: MessageRequest, _: None = Depends(require_chat_key)) -> MessageResponse:
    session = genesys_ava.get_session(body.sessionId)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    try:
        started = time.perf_counter()
        turn = genesys_ava.send_message(session, body.message.strip())
        response_time_ms = int((time.perf_counter() - started) * 1000)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    text = genesys_ava.extract_agent_text(turn)
    reply = text or "I don't have a response for that yet."
    return MessageResponse(
        text=reply,
        turnId=turn.get("id"),
        nextAction=(turn.get("nextAction") or {}).get("type"),
        responseTimeMs=response_time_ms,
        outputTokens=genesys_ava.estimate_output_tokens(reply),
    )


@app.delete("/api/chat/session/{session_id}")
def delete_chat_session(session_id: str, _: None = Depends(require_chat_key)) -> dict[str, bool]:
    ended = genesys_ava.end_session(session_id)
    if not ended:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ended": True}


@app.post("/api/pipeline/run", response_model=PipelineRunResponse)
def start_pipeline(body: PipelineRunRequest, _: None = Depends(require_pipeline_key)) -> PipelineRunResponse:
    try:
        job_id = pipeline.run_pipeline(
            url=body.url,
            site=body.site,
            sync_type=body.syncType,
            source_id=body.sourceId,
            source_name=body.sourceName,
            crawl_limit=body.crawlLimit,
            steps=body.steps,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PipelineRunResponse(jobId=job_id)


@app.get("/api/pipeline/jobs")
def get_pipeline_jobs(_: None = Depends(require_pipeline_key)) -> list[dict[str, Any]]:
    return pipeline.list_jobs()


@app.get("/api/pipeline/jobs/{job_id}")
def get_pipeline_job(job_id: str, _: None = Depends(require_pipeline_key)) -> dict[str, Any]:
    job = pipeline.load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/content/sites")
def get_content_sites(_: None = Depends(require_pipeline_key)) -> list[dict[str, Any]]:
    return pipeline.list_sites()


@app.get("/api/content/sites/{site}/files")
def get_site_files(site: str, processed: bool = True, _: None = Depends(require_pipeline_key)) -> dict[str, Any]:
    return {"site": site, "processed": processed, "files": pipeline.list_content_files(site, processed=processed)}


@app.get("/api/content/sites/{site}/manifest")
def get_site_manifest(site: str, _: None = Depends(require_pipeline_key)) -> dict[str, Any]:
    path = config.data_dir() / "crawls" / site / "processed" / "manifest.json"
    if not path.exists():
        path = config.data_dir() / "crawls" / site / "manifest.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Manifest not found")
    return json.loads(path.read_text(encoding="utf-8"))


@app.post("/api/content/import")
def import_content_bundle(
    body: ImportBundleRequest,
    _: None = Depends(require_pipeline_key),
) -> dict[str, Any]:
    try:
        return pipeline.import_bundle([item.model_dump() for item in body.files])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/pipeline/sync-state")
def get_sync_state(_: None = Depends(require_pipeline_key)) -> dict[str, Any]:
    return pipeline.load_sync_state()


@app.get("/api/knowledge/overview")
def get_knowledge_overview(_: None = Depends(require_pipeline_key)) -> dict[str, Any]:
    try:
        return knowledge.knowledge_overview()
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/knowledge/sources/{source_id}")
def get_knowledge_source(source_id: str, _: None = Depends(require_pipeline_key)) -> dict[str, Any]:
    try:
        return knowledge.get_source(source_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.delete("/api/knowledge/sources/{source_id}")
def delete_knowledge_source(source_id: str, _: None = Depends(require_pipeline_key)) -> dict[str, Any]:
    try:
        return knowledge.delete_source(source_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/content/sites/{site}/files/{filename}", response_model=ContentFileResponse)
def get_site_file(
    site: str,
    filename: str,
    processed: bool = True,
    _: None = Depends(require_pipeline_key),
) -> ContentFileResponse:
    relative = f"processed/{filename}" if processed else filename
    try:
        content = pipeline.read_content_file(site, relative)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ContentFileResponse(
        site=site,
        filename=filename,
        processed=processed,
        content=content,
    )


@app.put("/api/content/sites/{site}/files/{filename}", response_model=ContentFileResponse)
def update_site_file(
    site: str,
    filename: str,
    body: ContentFileWriteRequest,
    processed: bool = True,
    _: None = Depends(require_pipeline_key),
) -> ContentFileResponse:
    try:
        pipeline.write_content_file(site, filename, body.content, processed=processed)
        content = pipeline.read_content_file(site, f"processed/{filename}" if processed else filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ContentFileResponse(site=site, filename=filename, processed=processed, content=content)


@app.post("/api/content/sites/{site}/files", response_model=ContentFileResponse)
def create_site_file(
    site: str,
    body: ContentFileCreateRequest,
    _: None = Depends(require_pipeline_key),
) -> ContentFileResponse:
    try:
        pipeline.write_content_file(site, body.filename, body.content, processed=body.processed)
        relative = f"processed/{body.filename}" if body.processed else body.filename
        content = pipeline.read_content_file(site, relative)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ContentFileResponse(
        site=site,
        filename=body.filename,
        processed=body.processed,
        content=content,
    )


@app.delete("/api/content/sites/{site}/files/{filename}")
def delete_site_file(
    site: str,
    filename: str,
    processed: bool = True,
    _: None = Depends(require_pipeline_key),
) -> dict[str, bool]:
    try:
        pipeline.delete_content_file(site, filename, processed=processed)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"deleted": True}


@app.delete("/api/content/sites/{site}")
def delete_content_site(site: str, _: None = Depends(require_pipeline_key)) -> dict[str, Any]:
    try:
        return pipeline.delete_site(site)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/admin")
def admin_redirect() -> HTMLResponse:
    return HTMLResponse(
        '<!DOCTYPE html><html><head><meta http-equiv="refresh" content="0;url=/?tab=admin"></head>'
        '<body><a href="/?tab=admin">Open Admin tab</a></body></html>'
    )


@app.get("/", response_class=HTMLResponse)
def chat_page() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
