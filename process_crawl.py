#!/usr/bin/env python3
"""Post-process crawled markdown for Genesys Knowledge Fabric / AVA self-service."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


FRONT_MATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
IMAGE_LINE_RE = re.compile(r"^!\[.*\]\(.*\)\s*$")
TOUR_STEP_LIST_RE = re.compile(
    r"^\d+\.\s+\[\d+\]\(https?://[^)]*gctour-stop-\d+[^)]*\)\s*$"
)
TOUR_PAGER_RE = re.compile(r"^\d+\s+of\s+\d+\s*$")
FORM_FIELD_RE = re.compile(
    r"^(Work Email|First Name|Last Name|Country|State/Province|"
    r"City|Telephone|Company Name|Your Website|Job Title|Job Level|"
    r"Job Function|Industry|Number of Agent Seats|Level of Interest)\*?\s*$"
)
CTA_ONLY_RE = re.compile(
    r"^\[(Get started|Get a demo|Get demo|Take the tour|Watch the demo|"
    r"Request a demo|Start [Gg]uided [Tt]our|Restart|Explore|View all capabilities|"
    r"See why|Learn more|Next|Dismiss|Previous)\]"
    r"(\[.*\])?\s*$"
)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")

EXCLUDE_PATH_PREFIXES = (
    "/resources/",
    "/webinars/",
    "/customer-stories/",
)

CTA_LINK_PATTERNS = (
    r"#getStartedBox",
    r"#demo\b",
    r"/campaign/request-a-demo",
    r"/campaign/genesys-cloud-guided-tour",
    r"gctour-stop",
    r"browsehappy\.com",
    r"youtube\.com/embed",
)

BOILERPLATE_LINES = {
    "Welcome back",
    "Not You?",
    "Please provide your work email*",
    "By providing your information, you agree to our privacy policy.",
    "Yes. Keep me informed via email or telephone regarding Genesys information.",
    "I would like someone to reach out to me",
}


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    match = FRONT_MATTER_RE.match(text)
    if not match:
        return {}, text

    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    return meta, text[match.end() :]


def classify_page(source_url: str) -> str:
    path = urlparse(source_url).path.strip("/")
    if not path:
        return "homepage"
    prefix = path.split("/", 1)[0]
    mapping = {
        "capabilities": "product-capability",
        "resources": "resource-gated",
        "webinars": "webinar",
        "customer-stories": "case-study",
        "genesys-cloud": "product-overview",
        "experience-orchestration": "product-overview",
    }
    return mapping.get(prefix, "general")


def infer_topics(source_url: str, body: str) -> list[str]:
    path = urlparse(source_url).path.strip("/")
    topics: list[str] = []
    if path:
        topics.extend(part for part in path.split("/") if part)
    for match in HEADING_RE.finditer(body):
        level = len(match.group(1))
        if level == 2:
            heading = match.group(2).strip()
            if len(heading) < 80:
                slug = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
                if slug and slug not in topics:
                    topics.append(slug)
    return topics[:12]


def extract_summary(body: str) -> str:
    lines = body.splitlines()
    collecting = False
    parts: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if parts:
                break
            continue
        if stripped.startswith("#"):
            if stripped.startswith("# "):
                collecting = True
            continue
        if IMAGE_LINE_RE.match(stripped) or CTA_ONLY_RE.match(stripped):
            continue
        if collecting and not stripped.startswith("["):
            parts.append(stripped)
            if len(" ".join(parts)) > 80:
                break

    if not parts:
        for line in lines:
            stripped = line.strip()
            if (
                stripped
                and not stripped.startswith("#")
                and not stripped.startswith("[")
                and not IMAGE_LINE_RE.match(stripped)
                and len(stripped) > 40
            ):
                parts.append(stripped)
                break

    summary = " ".join(parts).strip()
    if len(summary) > 320:
        summary = summary[:317].rsplit(" ", 1)[0] + "..."
    return summary


def is_tour_noise_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if TOUR_STEP_LIST_RE.match(stripped):
        return True
    if TOUR_PAGER_RE.match(stripped):
        return True
    if "Skip to main content" in stripped and "global-main" in stripped:
        return True
    if stripped.startswith("Virtual Agent Tour ") or stripped.startswith("Meet Genesys Cloud Copilot "):
        return True
    if "Your browser is outdated" in stripped:
        return True
    if stripped in BOILERPLATE_LINES:
        return True
    if FORM_FIELD_RE.match(stripped):
        return True
    if CTA_ONLY_RE.match(stripped):
        return True
    if any(re.search(pattern, stripped) for pattern in CTA_LINK_PATTERNS):
        if stripped.startswith("["):
            return True
    if re.fullmatch(r"\\+", stripped):
        return True
    if re.fullmatch(r"Play", stripped):
        return True
    return False


def clean_markdown(body: str) -> str:
    cleaned_lines: list[str] = []
    previous_blank = False

    for line in body.splitlines():
        stripped = line.strip()

        if not stripped:
            if cleaned_lines and not previous_blank:
                cleaned_lines.append("")
                previous_blank = True
            continue

        previous_blank = False

        if IMAGE_LINE_RE.match(stripped):
            continue
        if is_tour_noise_line(stripped):
            continue
        if stripped.startswith("[![") and "](http" in stripped:
            continue
        if "data:image/svg+xml" in stripped:
            continue

        cleaned_lines.append(line.rstrip())

    text = "\n".join(cleaned_lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def prose_char_count(body: str) -> int:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", body)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s+", " ", text).strip()
    return len(text)


def h3_to_qa_section(body: str) -> str:
    lines = body.splitlines()
    blocks: list[tuple[str, list[str]]] = []
    current_title: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_title, current_lines
        if current_title and current_lines:
            answer = " ".join(line.strip() for line in current_lines if line.strip())
            if len(answer) > 40:
                blocks.append((current_title, [answer]))
        current_title = None
        current_lines = []

    for line in lines:
        if line.startswith("### "):
            flush()
            current_title = line[4:].strip()
            continue
        if line.startswith("## ") or line.startswith("# "):
            flush()
            continue
        if current_title is not None:
            if is_tour_noise_line(line) or IMAGE_LINE_RE.match(line.strip()):
                continue
            if line.strip():
                current_lines.append(line.strip())

    flush()

    if not blocks:
        return ""

    qa_lines = ["## Common questions", ""]
    for title, answers in blocks[:12]:
        question = title if title.endswith("?") else f"What is {title}?"
        qa_lines.append(f"### {question}")
        qa_lines.append("")
        qa_lines.append(answers[0])
        qa_lines.append("")

    return "\n".join(qa_lines).strip()


def split_by_h2(body: str, max_chars: int) -> list[tuple[str, str]]:
    if len(body) <= max_chars:
        return [("main", body)]

    sections: list[tuple[str, list[str]]] = []
    current_slug = "intro"
    current_lines: list[str] = []

    for line in body.splitlines():
        match = HEADING_RE.match(line)
        if match and len(match.group(1)) == 2:
            if current_lines:
                sections.append((current_slug, current_lines))
            heading = match.group(2).strip()
            current_slug = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-") or "section"
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_slug, current_lines))

    if len(sections) <= 1:
        return [("main", body)]

    merged: list[tuple[str, str]] = []
    buffer_slug = ""
    buffer_text = ""

    def flush_buffer() -> None:
        nonlocal buffer_slug, buffer_text
        if buffer_text.strip():
            merged.append((buffer_slug or "section", buffer_text.strip()))
        buffer_slug = ""
        buffer_text = ""

    min_section_chars = 1200

    for slug, lines in sections:
        section_text = "\n".join(lines).strip()
        if not section_text:
            continue

        if len(section_text) >= min_section_chars:
            flush_buffer()
            merged.append((slug, section_text))
            continue

        if not buffer_text:
            buffer_slug = slug
            buffer_text = section_text
        else:
            buffer_text = f"{buffer_text}\n\n{section_text}"

    flush_buffer()
    return merged or [("main", body)]


def build_context_block(
    summary: str,
    topics: list[str],
    page_type: str,
    source_url: str,
    title: str,
) -> str:
    topic_line = ", ".join(topics[:8]) if topics else "general product information"
    not_covered = {
        "product-capability": "Pricing, licensing, account setup, and troubleshooting",
        "product-overview": "Pricing, licensing, and account-specific configuration",
        "homepage": "Pricing, support tickets, and account management",
    }.get(page_type, "Pricing, legal terms, and account-specific issues")

    source_lines = ["## Source link (include in customer answers)", ""]
    if source_url:
        source_lines.extend(
            [
                f"Customer reference URL: {source_url}",
                f"Learn more: {source_url}",
            ]
        )
        if title:
            source_lines.append(f"Source page: [{title}]({source_url})")
    else:
        source_lines.append("Customer reference URL: (unknown)")

    return "\n".join(
        [
            "## Summary",
            summary or "Product information from the Genesys website.",
            "",
            "## Topics covered",
            topic_line,
            "",
            *source_lines,
            "",
            "## Not covered here",
            not_covered,
            "",
        ]
    )


def build_source_footer(source_url: str, title: str) -> str:
    if not source_url:
        return ""
    lines = [
        "## Reference for agents",
        f"Customer reference URL: {source_url}",
        f"Learn more: {source_url}",
    ]
    if title:
        lines.append(f"Source page title: {title}")
    lines.append("")
    return "\n".join(lines)


def should_include(page_type: str, include_excluded_types: set[str]) -> bool:
    if page_type in include_excluded_types:
        return True
    return page_type not in {
        "resource-gated",
        "webinar",
        "case-study",
    }


def default_include_by_url(source_url: str, include_excluded_types: set[str]) -> bool:
    path = urlparse(source_url).path
    page_type = classify_page(source_url)
    if not should_include(page_type, include_excluded_types):
        return False
    if any(path.startswith(prefix) for prefix in EXCLUDE_PATH_PREFIXES):
        if page_type not in include_excluded_types:
            return False
    return True


def render_document(meta: dict[str, Any], body: str) -> str:
    front_lines = ["---"]
    for key, value in meta.items():
        if isinstance(value, bool):
            front_lines.append(f"{key}: {'true' if value else 'false'}")
        elif isinstance(value, list):
            front_lines.append(f"{key}:")
            for item in value:
                front_lines.append(f"  - {item}")
        else:
            front_lines.append(f"{key}: {value}")
    front_lines.append("---")
    return "\n".join(front_lines) + "\n\n" + body.strip() + "\n"


def process_page(
    file_path: Path,
    args: argparse.Namespace,
    include_excluded_types: set[str],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    raw_text = file_path.read_text(encoding="utf-8")
    meta, body = parse_front_matter(raw_text)
    source_url = meta.get("source_url", "")
    title = meta.get("title", file_path.stem)
    page_type = classify_page(source_url)

    record: dict[str, Any] = {
        "sourceFile": file_path.name,
        "url": source_url,
        "title": title,
        "pageType": page_type,
    }

    if not default_include_by_url(source_url, include_excluded_types):
        record["reason"] = "excluded by page type/path filter"
        return [], record

    cleaned = clean_markdown(body)
    if prose_char_count(cleaned) < args.min_chars:
        record["reason"] = f"below min prose threshold ({args.min_chars} chars)"
        return [], record

    summary = extract_summary(cleaned)
    topics = infer_topics(source_url, cleaned)
    context = build_context_block(summary, topics, page_type, source_url, title)
    has_faq = bool(re.search(r"frequently asked questions", cleaned, re.IGNORECASE))
    qa_section = "" if has_faq or not args.add_qa else h3_to_qa_section(cleaned)
    main_body = cleaned if not qa_section else f"{cleaned}\n\n{qa_section}"

    outputs: list[dict[str, Any]] = []
    sections = split_by_h2(main_body, args.split_chars) if args.split_large else [("main", main_body)]

    for index, (section_slug, section_body) in enumerate(sections):
        suffix = "" if section_slug == "main" else f"__{section_slug}"
        out_name = file_path.stem + suffix + ".md"
        section_meta = {
            **meta,
            "page_type": page_type,
            "topics": topics,
            "include_in_ava": True,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }
        if len(sections) > 1:
            section_meta["section"] = section_slug

        document_body = f"{context}\n{section_body}\n\n{build_source_footer(source_url, title)}"
        outputs.append(
            {
                "file": out_name,
                "url": source_url,
                "title": title,
                "pageType": page_type,
                "markdownChars": len(document_body),
                "content": render_document(section_meta, document_body),
            }
        )

    return outputs, None


def cmd_process(args: argparse.Namespace) -> int:
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    manifest_path = input_dir / "manifest.json"

    if not manifest_path.exists():
        print(f"Missing manifest: {manifest_path}", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    include_excluded_types = set(args.include_types)

    output_dir.mkdir(parents=True, exist_ok=True)
    processed_pages: list[dict[str, Any]] = []
    excluded_pages: list[dict[str, Any]] = []

    source_files = sorted(input_dir.glob("*.md"))
    print(f"Processing {len(source_files)} files from {input_dir}")

    for file_path in source_files:
        outputs, excluded = process_page(file_path, args, include_excluded_types)
        if excluded:
            excluded_pages.append(excluded)
            print(f"  skip  {file_path.name}  ({excluded['reason']})")
            continue

        for item in outputs:
            out_path = output_dir / item["file"]
            out_path.write_text(item.pop("content"), encoding="utf-8")
            processed_pages.append(item)
            print(f"  write {item['file']}  ({item['markdownChars']} chars)")

    processed_manifest = {
        "processedAt": datetime.now(timezone.utc).isoformat(),
        "inputDir": str(input_dir),
        "outputDir": str(output_dir),
        "pageCount": len(processed_pages),
        "excludedCount": len(excluded_pages),
        "pages": processed_pages,
        "excluded": excluded_pages,
        "sourcesIndex": {
            page["file"]: {"url": page["url"], "title": page.get("title")}
            for page in processed_pages
        },
    }
    manifest_out = output_dir / "manifest.json"
    manifest_out.write_text(
        json.dumps(processed_manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    sources_index_out = output_dir / "sources-index.json"
    sources_index_out.write_text(
        json.dumps(processed_manifest["sourcesIndex"], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"Processed: {len(processed_pages)} files -> {output_dir}")
    print(f"Excluded:  {len(excluded_pages)} files")
    print(f"Manifest:  {manifest_out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Clean and structure crawled markdown for AVA / Knowledge Fabric upload.",
    )
    parser.add_argument(
        "--input-dir",
        default="artifacts/crawls/genesys.com",
        help="Directory containing raw crawl .md files and manifest.json",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts/crawls/genesys.com/processed",
        help="Directory for processed files ready to upload",
    )
    parser.add_argument(
        "--min-chars",
        type=int,
        default=400,
        help="Minimum prose characters after cleaning (default: 400)",
    )
    parser.add_argument(
        "--split-chars",
        type=int,
        default=15000,
        help="Split pages larger than this at H2 boundaries (default: 15000)",
    )
    parser.add_argument(
        "--no-split-large",
        action="store_true",
        help="Do not split large pages into section files",
    )
    parser.add_argument(
        "--no-qa",
        action="store_true",
        help="Skip generating Common questions section from H3 headings",
    )
    parser.add_argument(
        "--include-types",
        action="append",
        default=[],
        choices=["resource-gated", "webinar", "case-study"],
        help="Include normally excluded page types",
    )
    parser.set_defaults(func=cmd_process)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.split_large = not args.no_split_large
    args.add_qa = not args.no_qa
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
