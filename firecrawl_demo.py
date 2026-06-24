#!/usr/bin/env python3
"""Firecrawl API demo — scrape and search without extra dependencies."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse


API_BASE = "https://api.firecrawl.dev/v2"
ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"


def load_dotenv() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def api_key() -> str | None:
    value = os.getenv("FIRECRAWL_API_KEY", "").strip()
    return value or None


def firecrawl_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    key = api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def request_firecrawl(path: str, body: dict[str, Any]) -> dict[str, Any]:
    url = f"{API_BASE}{path}"
    payload = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url, data=payload, headers=firecrawl_headers(), method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from Firecrawl: {detail}") from exc


def get_firecrawl(path: str) -> dict[str, Any]:
    url = f"{API_BASE}{path}"
    request = urllib.request.Request(url, headers=firecrawl_headers(), method="GET")

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from Firecrawl: {detail}") from exc


def save_artifact(name: str, payload: dict[str, Any]) -> Path:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = ARTIFACTS_DIR / f"firecrawl-{name}-{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return path


def cmd_scrape(args: argparse.Namespace) -> int:
    print(f"Scraping {args.url} ...")
    result = request_firecrawl(
        "/scrape",
        {
            "url": args.url,
            "formats": ["markdown", "links"],
        },
    )

    if not result.get("success"):
        print(json.dumps(result, indent=2), file=sys.stderr)
        return 1

    data = result.get("data") or {}
    markdown = data.get("markdown") or ""
    metadata = data.get("metadata") or {}
    links = data.get("links") or []

    print(f"Title: {metadata.get('title', '(none)')}")
    print(f"Source: {metadata.get('sourceURL') or metadata.get('source_url') or args.url}")
    print(f"Markdown length: {len(markdown)} chars")
    print(f"Links found: {len(links)}")
    print()
    preview = markdown[: args.preview_chars].rstrip()
    print("--- markdown preview ---")
    print(preview)
    if len(markdown) > args.preview_chars:
        print(f"\n... ({len(markdown) - args.preview_chars} more chars)")

    artifact = save_artifact("scrape", result)
    print(f"\nSaved full response: {artifact}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    print(f"Searching: {args.query!r} (limit={args.limit})")
    result = request_firecrawl(
        "/search",
        {
            "query": args.query,
            "limit": args.limit,
        },
    )

    if not result.get("success"):
        print(json.dumps(result, indent=2), file=sys.stderr)
        return 1

    web = (result.get("data") or {}).get("web") or []
    credits = result.get("creditsUsed")
    print(f"Results: {len(web)}  Credits used: {credits}")
    print()

    for item in web:
        position = item.get("position", "?")
        title = item.get("title", "(no title)")
        url = item.get("url", "")
        description = (item.get("description") or "").strip()
        print(f"{position}. {title}")
        print(f"   {url}")
        if description:
            print(f"   {description[:160]}{'...' if len(description) > 160 else ''}")
        print()

    artifact = save_artifact("search", result)
    print(f"Saved full response: {artifact}")
    return 0


def url_to_slug(page_url: str) -> str:
    parsed = urlparse(page_url)
    path = parsed.path.strip("/") or "index"
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", path)
    return slug[:120] or "index"


def page_source_url(page: dict[str, Any]) -> str:
    metadata = page.get("metadata") or {}
    return (
        metadata.get("sourceURL")
        or metadata.get("source_url")
        or metadata.get("url")
        or ""
    )


def save_crawl_pages(output_dir: Path, pages: list[dict[str, Any]]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_pages: list[dict[str, Any]] = []
    used_names: dict[str, int] = {}

    for page in pages:
        source_url = page_source_url(page)
        if not source_url:
            continue

        base_name = url_to_slug(source_url)
        count = used_names.get(base_name, 0)
        used_names[base_name] = count + 1
        filename = f"{base_name}.md" if count == 0 else f"{base_name}-{count}.md"

        markdown = page.get("markdown") or ""
        metadata = page.get("metadata") or {}
        file_path = output_dir / filename
        header = (
            f"---\n"
            f"source_url: {source_url}\n"
            f"title: {metadata.get('title', '')}\n"
            f"---\n\n"
        )
        file_path.write_text(header + markdown, encoding="utf-8")

        manifest_pages.append(
            {
                "url": source_url,
                "title": metadata.get("title"),
                "file": filename,
                "markdownChars": len(markdown),
                "statusCode": metadata.get("statusCode"),
            }
        )

    manifest = {
        "savedAt": datetime.now(timezone.utc).isoformat(),
        "pageCount": len(manifest_pages),
        "pages": manifest_pages,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest_path


def collect_crawl_pages(job_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    status_payload: dict[str, Any] = {}
    next_url: str | None = f"/crawl/{job_id}"

    while next_url:
        if next_url.startswith("http"):
            request = urllib.request.Request(next_url, headers=firecrawl_headers(), method="GET")
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.loads(response.read().decode("utf-8"))
        else:
            payload = get_firecrawl(next_url)

        status_payload = payload
        pages.extend(payload.get("data") or [])
        next_url = payload.get("next")

    return pages, status_payload


def scrape_page(url: str) -> dict[str, Any]:
    result = request_firecrawl(
        "/scrape",
        {
            "url": url,
            "formats": ["markdown", "links"],
            "onlyMainContent": True,
        },
    )
    if not result.get("success"):
        raise RuntimeError(json.dumps(result))
    return result.get("data") or {}


def site_host(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def is_html_page_url(url: str, base_url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    if site_host(url) != site_host(base_url):
        return False

    path = parsed.path.lower()
    if not path or path == "/":
        return True
    if "/media/" in path:
        return False
    blocked_suffixes = (
        ".svg",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
        ".pdf",
        ".css",
        ".js",
        ".ico",
    )
    return not any(path.endswith(suffix) for suffix in blocked_suffixes)


def normalize_page_url(url: str) -> str:
    cleaned, _ = urldefrag(url.rstrip("/"))
    parsed = urlparse(cleaned)
    if not parsed.path:
        return f"{parsed.scheme}://{parsed.netloc}/"
    return cleaned


def discover_child_urls(homepage: dict[str, Any], base_url: str) -> list[str]:
    candidates: set[str] = set()
    for link in homepage.get("links") or []:
        if isinstance(link, str):
            candidates.add(normalize_page_url(urljoin(base_url, link)))

    markdown = homepage.get("markdown") or ""
    for match in re.finditer(r"https?://[^\s)>\]]+", markdown):
        candidates.add(normalize_page_url(match.group(0)))

    base_norm = normalize_page_url(base_url)
    child_urls = sorted(
        url
        for url in candidates
        if is_html_page_url(url, base_url) and normalize_page_url(url) != base_norm
    )
    return child_urls


def scrape_shallow_site(base_url: str, limit: int) -> list[dict[str, Any]]:
    print("Using scrape fallback (crawl API requires FIRECRAWL_API_KEY)")
    homepage = scrape_page(base_url)
    pages = [homepage]
    child_urls = discover_child_urls(homepage, base_url)[: max(limit - 1, 0)]

    print(f"Homepage scraped; {len(child_urls)} linked pages to fetch")
    for index, child_url in enumerate(child_urls, start=1):
        print(f"  [{index}/{len(child_urls)}] {child_url}")
        try:
            pages.append(scrape_page(child_url))
        except RuntimeError as exc:
            print(f"    skipped: {exc}", file=sys.stderr)

    return pages


def cmd_crawl_shallow(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    print(f"Shallow crawl: {args.url}")
    print(f"  maxDiscoveryDepth={args.depth}, sitemap=skip, limit={args.limit}")
    print(f"  output: {output_dir}")
    print()

    pages: list[dict[str, Any]]
    status_payload: dict[str, Any]

    if api_key():
        try:
            start = request_firecrawl(
                "/crawl",
                {
                    "url": args.url,
                    "maxDiscoveryDepth": args.depth,
                    "sitemap": "skip",
                    "limit": args.limit,
                    "allowExternalLinks": False,
                    "allowSubdomains": args.allow_subdomains,
                    "crawlEntireDomain": True,
                    "scrapeOptions": {
                        "formats": ["markdown"],
                        "onlyMainContent": True,
                    },
                },
            )
        except RuntimeError as exc:
            if "401" not in str(exc):
                raise
            pages = scrape_shallow_site(args.url, args.limit)
            status_payload = {"status": "completed", "mode": "scrape-fallback", "total": len(pages)}
        else:
            if not start.get("success"):
                print(json.dumps(start, indent=2), file=sys.stderr)
                return 1

            job_id = start.get("id")
            if not job_id:
                print(json.dumps(start, indent=2), file=sys.stderr)
                return 1

            print(f"Crawl job: {job_id}")
            deadline = time.time() + args.timeout
            status_payload = {}

            while time.time() < deadline:
                status_payload = get_firecrawl(f"/crawl/{job_id}")
                status = status_payload.get("status", "unknown")
                completed = status_payload.get("completed", 0)
                total = status_payload.get("total", "?")
                print(f"  status={status}  pages={completed}/{total}")

                if status in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(args.poll_interval)

            status = status_payload.get("status", "unknown")
            if status != "completed":
                print(json.dumps(status_payload, indent=2), file=sys.stderr)
                return 1

            pages, status_payload = collect_crawl_pages(job_id)
            status_payload["mode"] = "crawl"
    else:
        pages = scrape_shallow_site(args.url, args.limit)
        status_payload = {"status": "completed", "mode": "scrape-fallback", "total": len(pages)}

    manifest_path = save_crawl_pages(output_dir, pages)
    artifact = save_artifact("crawl-shallow", status_payload)

    print()
    print(f"Saved {len(pages)} pages to {output_dir}")
    print(f"Manifest: {manifest_path}")
    print(f"Raw response: {artifact}")
    print()
    for entry in json.loads(manifest_path.read_text())["pages"][:15]:
        print(f"  - {entry['file']}  ({entry['markdownChars']} chars)")
        print(f"    {entry['url']}")
    remaining = len(pages) - 15
    if remaining > 0:
        print(f"  ... and {remaining} more")
    return 0


def cmd_demo(_: argparse.Namespace) -> int:
    print("Firecrawl demo")
    print("==============")
    if api_key():
        print("Auth: FIRECRAWL_API_KEY set (higher rate limits)")
    else:
        print("Auth: keyless free tier (no API key)")
        print("Tip: add FIRECRAWL_API_KEY to .env for higher limits")
    print()

    scrape_args = argparse.Namespace(
        url="https://www.firecrawl.dev/",
        preview_chars=700,
    )
    search_args = argparse.Namespace(
        query="Genesys Agentic Virtual Agent API",
        limit=5,
    )

    if cmd_scrape(scrape_args) != 0:
        return 1
    print()
    return cmd_search(search_args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Try Firecrawl scrape and search APIs.")
    sub = parser.add_subparsers(dest="command", required=True)

    scrape = sub.add_parser("scrape", help="Scrape a URL to markdown")
    scrape.add_argument("url", help="Page URL to scrape")
    scrape.add_argument(
        "--preview-chars",
        type=int,
        default=700,
        help="Characters of markdown to print (default: 700)",
    )
    scrape.set_defaults(func=cmd_scrape)

    search = sub.add_parser("search", help="Search the web")
    search.add_argument("query", help="Search query")
    search.add_argument("--limit", type=int, default=5, help="Max results (default: 5)")
    search.set_defaults(func=cmd_search)

    crawl = sub.add_parser(
        "crawl-shallow",
        help="Crawl a site homepage and pages linked one level down",
    )
    crawl.add_argument("url", help="Starting URL (e.g. https://www.genesys.com/)")
    crawl.add_argument(
        "--output-dir",
        default=str(ARTIFACTS_DIR / "crawls" / "site"),
        help="Directory for markdown pages and manifest.json",
    )
    crawl.add_argument(
        "--depth",
        type=int,
        default=1,
        help="maxDiscoveryDepth (1 = homepage + direct links only)",
    )
    crawl.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum pages to crawl (default: 100)",
    )
    crawl.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Seconds to wait for crawl completion (default: 600)",
    )
    crawl.add_argument(
        "--poll-interval",
        type=float,
        default=3.0,
        help="Seconds between status polls (default: 3)",
    )
    crawl.add_argument(
        "--allow-subdomains",
        action="store_true",
        help="Follow links to subdomains of the start URL",
    )
    crawl.set_defaults(func=cmd_crawl_shallow)

    demo = sub.add_parser("demo", help="Run scrape + search examples")
    demo.set_defaults(func=cmd_demo)

    return parser


def main() -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
