from __future__ import annotations

import pytest

from app.security import validate_crawl_url, validate_job_id, validate_site_name, redact_log_text


def test_validate_job_id_accepts_uuid() -> None:
    assert validate_job_id("550e8400-e29b-41d4-a716-446655440000") == "550e8400-e29b-41d4-a716-446655440000"


@pytest.mark.parametrize(
    "job_id",
    ["../secrets", "not-a-uuid", "550e8400-e29b-41d4-a716", ""],
)
def test_validate_job_id_rejects_invalid(job_id: str) -> None:
    with pytest.raises(ValueError):
        validate_job_id(job_id)


@pytest.mark.parametrize("site", ["..", "foo/bar", ""])
def test_validate_site_name_rejects_invalid(site: str) -> None:
    with pytest.raises(ValueError):
        validate_site_name(site)


def test_validate_site_name_accepts_hostname() -> None:
    assert validate_site_name("www.genesys.com") == "www.genesys.com"


def test_validate_crawl_url_requires_https_or_http() -> None:
    assert validate_crawl_url("https://www.genesys.com/").startswith("https://")
    with pytest.raises(ValueError):
        validate_crawl_url("file:///etc/passwd")


def test_validate_crawl_url_blocks_localhost() -> None:
    with pytest.raises(ValueError):
        validate_crawl_url("http://127.0.0.1/")


def test_redact_log_text_masks_secrets() -> None:
    line = "Authorization: Bearer abc123 fc-secret-key client_secret=shhh"
    redacted = redact_log_text(line)
    assert "abc123" not in redacted
    assert "fc-secret-key" not in redacted
    assert "shhh" not in redacted
