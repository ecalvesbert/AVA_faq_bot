"""Shared security helpers."""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

JOB_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

_SECRET_PATTERNS = (
    re.compile(r"(?i)Authorization:\s*Bearer\s+\S+"),
    re.compile(r"(?i)(client[_-]?secret|api[_-]?key|token)\s*[:=]\s*\S+"),
    re.compile(r"fc-[A-Za-z0-9_-]+"),
    re.compile(r"(?i)Bearer\s+\S+"),
)


def validate_job_id(job_id: str) -> str:
    value = job_id.strip()
    if not JOB_ID_RE.match(value):
        raise ValueError("Invalid job id")
    return value


def validate_site_name(site: str) -> str:
    value = site.strip()
    if not value or "/" in value or "\\" in value or ".." in value:
        raise ValueError("Invalid site name")
    return value


def validate_crawl_url(url: str, *, resolve_host: bool = False) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Crawl URL must use http or https")
    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise ValueError("Crawl URL must include a host")
    if hostname in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} or hostname.endswith(".local"):
        raise ValueError("Crawl URL host is not allowed")

    if resolve_host:
        try:
            for info in socket.getaddrinfo(
                hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
            ):
                address = info[4][0]
                ip = ipaddress.ip_address(address)
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                    raise ValueError("Crawl URL host resolves to a private or local address")
        except socket.gaierror as exc:
            raise ValueError(f"Crawl URL host could not be resolved: {hostname}") from exc

    return url.strip()


def redact_log_text(text: str) -> str:
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[redacted]", redacted)
    return redacted
