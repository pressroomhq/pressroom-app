"""Blog publisher — write content as Markdown to an Astro blog directory.

Gated behind the org-level `blog_publish_path` setting.  When a blog-channel
content item is published and the setting exists, this writes the .md file,
then git-adds and commits it so the site can redeploy.
"""

import logging
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("pressroom")


def slugify(text: str) -> str:
    """Turn a headline into a URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:80]


def publish_to_blog(content: dict, blog_path: str) -> str | None:
    """Write a published content item as a Markdown blog post.

    Returns the file path written, or None on failure.
    """
    headline = (content.get("headline") or "Untitled").strip()
    body = (content.get("body") or "").strip()
    author = (content.get("author") or "Pressroom HQ").strip()
    created = content.get("created_at") or datetime.now(timezone.utc).isoformat()

    # Strip channel prefixes like "BLOG DRAFT", "BLOG:", etc.
    headline = re.sub(r'^(BLOG\s*DRAFT|BLOG)\s*[:\-–—]?\s*', '', headline, flags=re.IGNORECASE).strip()

    # Parse date for frontmatter (just YYYY-MM-DD)
    try:
        dt = datetime.fromisoformat(created)
        date_str = dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    slug = slugify(headline)
    if not slug:
        slug = f"post-{date_str}"

    filename = f"{slug}.md"
    dest = Path(blog_path)

    if not dest.is_dir():
        log.warning("blog_publish_path does not exist: %s", blog_path)
        return None

    filepath = dest / filename

    # Build frontmatter
    # Escape quotes in title/description for YAML safety
    safe_title = headline.replace('"', '\\"')
    # Use first plain-text line of body as description (skip markdown headers)
    desc_raw = ""
    for line in body.split("\n"):
        line = line.strip()
        if line and not line.startswith("#"):
            desc_raw = line[:160]
            break
    safe_desc = desc_raw.replace('"', '\\"') if desc_raw else safe_title

    md = f'''---
title: "{safe_title}"
description: "{safe_desc}"
date: "{date_str}"
author: "{author}"
tags: ["pressroom"]
---

{body}
'''

    try:
        filepath.write_text(md, encoding="utf-8")
        log.info("Blog post written: %s", filepath)
    except OSError as e:
        log.error("Failed to write blog post %s: %s", filepath, e)
        return None

    # Git add + commit (non-fatal if git isn't available or repo isn't set up)
    _git_commit(dest, filename, headline)

    return str(filepath)


def _git_commit(repo_dir: Path, filename: str, headline: str):
    """Stage and commit the new blog post. Failures are logged, not raised."""
    try:
        subprocess.run(
            ["git", "add", filename],
            cwd=str(repo_dir),
            capture_output=True, timeout=10,
        )
        subprocess.run(
            ["git", "commit", "-m", f"publish: {headline[:72]}"],
            cwd=str(repo_dir),
            capture_output=True, timeout=10,
        )
        log.info("Blog post committed: %s", filename)
    except Exception as e:
        log.warning("Git commit skipped for blog post: %s", e)
