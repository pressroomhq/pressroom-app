"""SEO PR Pipeline — audit a site, analyze issues, implement fixes, create a PR.

This is the server-side pipeline that:
1. Runs an SEO audit (reuses seo_audit.py)
2. Sends audit results to Claude for tiered analysis
3. Clones the target repo
4. Uses Claude API to generate file edits for each tier
5. Commits tier-by-tier, pushes, and creates a PR

CRITICAL: Never merges to main/master — only creates PRs for human review.
"""

import datetime
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import anthropic

from config import settings
from services.seo_audit import audit_domain
from services.token_tracker import log_token_usage

log = logging.getLogger("pressroom.seo_pipeline")


# ──────────────────────────────────────
# Analysis
# ──────────────────────────────────────

ANALYSIS_SYSTEM_PROMPT = """You are an expert SEO analyst. You will receive an SEO audit of a website.

Your task: produce a prioritized SEO improvement plan as JSON. Analyze the audit data and identify concrete, implementable changes organized into priority tiers.

## Output Format

You MUST output valid JSON matching this schema exactly:

```json
{
  "summary": "2-3 sentence executive summary of the biggest opportunities",
  "tiers": [
    {
      "tier": "P0",
      "description": "Critical fixes - highest impact",
      "changes": [
        {
          "page_url": "the URL of the page",
          "file_path": "best guess at repo file path (e.g. docs/getting-started.md)",
          "change_type": "title | description | heading | body | internal_link | front_matter",
          "current_value": "what exists currently",
          "suggested_value": "the exact new text or a specific directive for body changes",
          "justification": "why this change matters, citing specific audit data",
          "priority_score": 95
        }
      ]
    },
    {
      "tier": "P1",
      "description": "Important improvements",
      "changes": []
    },
    {
      "tier": "P2",
      "description": "Incremental optimizations",
      "changes": []
    }
  ]
}
```

## Constraints

- P0: Maximum 5 changes. Highest-impact fixes only.
- P1: Maximum 7 changes. Important but not urgent.
- P2: Maximum 8 changes. Incremental improvements.
- Every suggestion MUST reference specific audit data (issues found, missing elements, etc.).
- Titles should be under 60 characters. Descriptions under 155 characters.
- Be specific and actionable — every change should be implementable without ambiguity.
- For body changes, describe exactly what content to add and where.
- Do NOT suggest changes for pages that are already performing well.

## CRITICAL: Output Instructions

Your ENTIRE response must be a single valid JSON object. No markdown fences, no commentary.
Start with `{` and end with `}`. Nothing else."""


async def analyze_seo_issues(audit_result: dict, repo_info: dict, api_key: str) -> dict:
    """Take audit data, send to Claude with analysis prompt. Returns tiered plan."""
    # Build the audit summary for Claude
    summary_parts = [
        f"SEO AUDIT RESULTS FOR {audit_result.get('domain', 'unknown')}",
        f"{audit_result.get('pages_audited', 0)} pages crawled.\n",
    ]

    pages = audit_result.get("pages", [])
    total_issues = 0

    for p in pages:
        issues = p.get("issues", [])
        total_issues += len(issues)
        summary_parts.append(f"\n--- {p['url']} ---")
        summary_parts.append(f"Title ({p.get('title_length', 0)} chars): {p.get('title', 'MISSING')}")
        summary_parts.append(f"Meta desc ({p.get('meta_description_length', 0)} chars): {p.get('meta_description', 'MISSING')[:100]}")
        summary_parts.append(f"H1s: {p.get('h1_count', 0)} | H2s: {p.get('h2_count', 0)} | Words: {p.get('word_count', 0)}")
        summary_parts.append(f"Images: {p.get('total_images', 0)} total, {p.get('images_missing_alt', 0)} missing alt")
        summary_parts.append(f"Links: {p.get('internal_links', 0)} internal, {p.get('external_links', 0)} external")
        summary_parts.append(f"Schema: {'Yes' if p.get('has_schema') else 'No'} | Canonical: {'Yes' if p.get('canonical') else 'No'} | OG: {'Yes' if p.get('og_image') else 'No'}")
        if issues:
            summary_parts.append(f"Issues: {', '.join(issues)}")

    summary_parts.append(f"\nTOTAL ISSUES: {total_issues} across {len(pages)} pages")

    # Add existing analysis if available
    recs = audit_result.get("recommendations", {})
    if recs.get("analysis"):
        summary_parts.append(f"\n\nEXISTING ANALYSIS:\n{recs['analysis']}")

    # Add repo context if available
    if repo_info.get("repo_url"):
        summary_parts.append(f"\n\nTARGET REPO: {repo_info['repo_url']}")
    if repo_info.get("base_branch"):
        summary_parts.append(f"BASE BRANCH: {repo_info['base_branch']}")

    # Add company context if available
    if repo_info.get("company_description"):
        summary_parts.append(f"\nCOMPANY CONTEXT: {repo_info['company_description']}")

    user_message = "\n".join(summary_parts)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=8000,
            system=ANALYSIS_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        await log_token_usage(None, "seo_pipeline_analyze", response)

        raw_text = response.content[0].text
        plan = _extract_json(raw_text)
        return plan

    except Exception as e:
        log.error("SEO analysis failed: %s", e)
        return {
            "summary": f"Analysis failed: {str(e)}",
            "tiers": [],
            "error": str(e),
        }


def _extract_json(text: str) -> dict:
    """Extract JSON from Claude's response, handling various formats."""
    text = text.lstrip("\ufeff").strip()

    # Strip code fences
    if text.startswith("```"):
        first_newline = text.index("\n")
        text = text[first_newline + 1:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()
            text = text[: text.rfind("```")].rstrip()

    text = text.strip()

    # Direct parse
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    # First { to last }
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        candidate = text[first_brace:last_brace + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract JSON from response (length={len(text)})")


# ──────────────────────────────────────
# Implementation
# ──────────────────────────────────────

IMPLEMENT_SYSTEM_PROMPT = """You are an SEO implementation specialist. You will receive a list of SEO changes to make to specific files in a repository.

For each change, output the exact file edits needed as a JSON array. Each edit should specify:
- file_path: the file to edit
- search: the exact text to find in the file (must be unique within the file)
- replace: the text to replace it with

If you need to add new content (like a meta description that doesn't exist), use a nearby unique string as the search anchor and include it plus the new content in the replace.

Your ENTIRE response must be a JSON array of edits:
```json
[
  {
    "file_path": "docs/getting-started.md",
    "search": "exact text to find",
    "replace": "replacement text"
  }
]
```

Rules:
- The `search` string MUST be unique within the file — include enough surrounding context.
- Preserve existing formatting (indentation, line endings).
- Do NOT remove or break existing content unless the change specifically requires it.
- For front matter changes (title, description), include the full front matter key-value line.
- For heading changes, include the full heading line with markdown markers.
- Output ONLY the JSON array. No commentary."""


async def implement_seo_changes(plan: dict, repo_path: str, api_key: str) -> list[dict]:
    """For each tier, send implementation directives to Claude. Returns list of tier results."""
    tiers = plan.get("tiers", [])
    results = []

    for tier in tiers:
        tier_name = tier.get("tier", "P0")
        changes = tier.get("changes", [])
        if not changes:
            results.append({"tier": tier_name, "edits_applied": 0, "errors": []})
            continue

        # Build the implementation prompt
        lines = [
            f"# SEO Changes: {tier_name}",
            f"Apply these {len(changes)} changes to the repository at {repo_path}.",
            "",
        ]

        for i, change in enumerate(changes, 1):
            lines.append(f"## Change {i}: {change.get('change_type', 'update').upper()}")
            if change.get("file_path"):
                lines.append(f"**File**: `{change['file_path']}`")
            if change.get("page_url"):
                lines.append(f"**Page**: {change['page_url']}")
            lines.append(f"**Type**: {change.get('change_type', 'N/A')}")
            if change.get("current_value"):
                lines.append(f"**Current value**: {change['current_value']}")
            if change.get("suggested_value"):
                lines.append(f"**Change to**: {change['suggested_value']}")
            if change.get("justification"):
                lines.append(f"**Why**: {change['justification']}")
            lines.append("")

        # Read the current content of referenced files to give Claude context
        file_contexts = []
        seen_files = set()
        for change in changes:
            fp = change.get("file_path", "")
            if fp and fp not in seen_files:
                seen_files.add(fp)
                full_path = Path(repo_path) / fp
                if full_path.exists():
                    try:
                        content = full_path.read_text(encoding="utf-8")
                        # Truncate very large files
                        if len(content) > 10000:
                            content = content[:10000] + "\n... (truncated)"
                        file_contexts.append(f"\n--- Current content of {fp} ---\n{content}\n--- End of {fp} ---")
                    except Exception:
                        pass

        if file_contexts:
            lines.append("\n# Current File Contents")
            lines.extend(file_contexts)

        user_message = "\n".join(lines)

        try:
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model=settings.claude_model,
                max_tokens=8000,
                system=IMPLEMENT_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            await log_token_usage(None, "seo_pipeline_implement", response)

            raw_text = response.content[0].text
            edits = _extract_edits(raw_text)

            # Apply edits
            applied = 0
            errors = []
            for edit in edits:
                try:
                    _apply_edit(repo_path, edit)
                    applied += 1
                except Exception as e:
                    errors.append(f"{edit.get('file_path', '?')}: {str(e)}")

            results.append({
                "tier": tier_name,
                "edits_applied": applied,
                "edits_total": len(edits),
                "errors": errors,
            })

        except Exception as e:
            log.error("Implementation failed for %s: %s", tier_name, e)
            results.append({
                "tier": tier_name,
                "edits_applied": 0,
                "errors": [str(e)],
            })

    return results


def _extract_edits(text: str) -> list[dict]:
    """Extract a JSON array of edits from Claude's response."""
    text = text.lstrip("\ufeff").strip()

    # Strip code fences
    if text.startswith("```"):
        first_newline = text.index("\n")
        text = text[first_newline + 1:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()
            text = text[: text.rfind("```")].rstrip()

    text = text.strip()

    # Try direct parse
    if text.startswith("["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    # Find array boundaries
    first_bracket = text.find("[")
    last_bracket = text.rfind("]")
    if first_bracket != -1 and last_bracket > first_bracket:
        try:
            return json.loads(text[first_bracket:last_bracket + 1])
        except json.JSONDecodeError:
            pass

    log.warning("Could not parse edits from Claude response")
    return []


def _apply_edit(repo_path: str, edit: dict):
    """Apply a single search-and-replace edit to a file."""
    file_path = edit.get("file_path", "")
    search = edit.get("search", "")
    replace = edit.get("replace", "")

    if not file_path or not search:
        raise ValueError("Missing file_path or search text")

    full_path = Path(repo_path) / file_path
    if not full_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    content = full_path.read_text(encoding="utf-8")

    if search not in content:
        # Try a more lenient match (strip whitespace differences)
        search_stripped = " ".join(search.split())
        lines = content.split("\n")
        found = False
        for i, line in enumerate(lines):
            if search_stripped in " ".join(line.split()):
                # Found approximate match — use the original line
                content = content.replace(line, replace, 1)
                found = True
                break
        if not found:
            raise ValueError(f"Search text not found in {file_path}")
    else:
        content = content.replace(search, replace, 1)

    full_path.write_text(content, encoding="utf-8")


# ──────────────────────────────────────
# Git / PR Operations
# ──────────────────────────────────────

def clone_repo(repo_url: str, branch: str = "main") -> str:
    """Clone repo to temp dir, return path."""
    tmp_dir = tempfile.mkdtemp(prefix="seo-pr-")
    log.info("Cloning %s (branch: %s) to %s", repo_url, branch, tmp_dir)

    result = subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", branch, repo_url, tmp_dir],
        capture_output=True, text=True, timeout=120,
    )

    if result.returncode != 0:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RuntimeError(f"git clone failed: {result.stderr}")

    return tmp_dir


def create_seo_pr(repo_path: str, repo_url: str, branch_name: str, base_branch: str, plan: dict, domain: str) -> dict:
    """Git operations: branch, commit per tier, push, create PR via gh CLI.

    CRITICAL: Never merges to main/master — only creates PRs.
    """
    def _git(cmd, **kwargs):
        r = subprocess.run(
            ["git"] + cmd,
            capture_output=True, text=True, cwd=repo_path, timeout=60,
            **kwargs,
        )
        return r

    # Create branch
    result = _git(["checkout", "-b", branch_name])
    if result.returncode != 0:
        raise RuntimeError(f"Failed to create branch: {result.stderr}")

    tiers = plan.get("tiers", [])
    total_changes = 0

    for tier in tiers:
        tier_name = tier.get("tier", "P0")
        changes = tier.get("changes", [])
        if not changes:
            continue

        # Check for uncommitted changes
        status = _git(["status", "--porcelain"])
        if not status.stdout.strip():
            continue

        # Stage all changes
        _git(["add", "-A"])

        # Commit this tier
        desc = tier.get("description", "SEO improvements")
        commit_msg = f"[SEO {tier_name}] {domain}: {desc}"
        commit_result = _git(["commit", "-m", commit_msg])
        if commit_result.returncode == 0:
            total_changes += len(changes)

    if total_changes == 0:
        return {"pr_url": "", "changes_made": 0, "error": "No changes to commit"}

    # Push
    push_result = _git(["push", "origin", branch_name])
    if push_result.returncode != 0:
        return {
            "pr_url": "",
            "changes_made": total_changes,
            "error": f"Push failed: {push_result.stderr}",
        }

    # Build PR body
    pr_body = _build_pr_body(plan, domain)
    pr_title = f"[SEO] {domain}: Automated improvements ({datetime.date.today().strftime('%Y-%m-%d')})"

    # Extract repo slug from URL
    repo_slug = repo_url.replace("https://github.com/", "").replace(".git", "")

    # Create PR via gh CLI
    pr_result = subprocess.run(
        [
            "gh", "pr", "create",
            "--repo", repo_slug,
            "--title", pr_title,
            "--body", pr_body,
            "--base", base_branch,
            "--head", branch_name,
            "--label", "seo-auto",
        ],
        capture_output=True, text=True, cwd=repo_path, timeout=60,
    )

    if pr_result.returncode != 0:
        # Try creating the label first if that's the issue
        if "label" in pr_result.stderr.lower():
            subprocess.run(
                ["gh", "label", "create", "seo-auto", "--repo", repo_slug,
                 "--description", "Automated SEO improvements", "--color", "0E8A16"],
                capture_output=True, text=True, timeout=30,
            )
            pr_result = subprocess.run(
                [
                    "gh", "pr", "create",
                    "--repo", repo_slug,
                    "--title", pr_title,
                    "--body", pr_body,
                    "--base", base_branch,
                    "--head", branch_name,
                    "--label", "seo-auto",
                ],
                capture_output=True, text=True, cwd=repo_path, timeout=60,
            )

    pr_url = pr_result.stdout.strip() if pr_result.returncode == 0 else ""
    error = pr_result.stderr.strip() if pr_result.returncode != 0 else ""

    return {
        "pr_url": pr_url,
        "changes_made": total_changes,
        "branch_name": branch_name,
        "error": error,
    }


def _build_pr_body(plan: dict, domain: str) -> str:
    """Build the PR description."""
    tiers = plan.get("tiers", [])
    all_changes = []
    tier_sections = []

    for tier in tiers:
        tier_name = tier.get("tier", "P0")
        changes = tier.get("changes", [])
        if not changes:
            continue

        all_changes.extend(changes)
        change_lines = []
        for c in changes:
            change_type = c.get("change_type", "update")
            page = c.get("page_url", c.get("file_path", "N/A"))
            justification = c.get("justification", "")
            change_lines.append(f"- **{change_type}** on `{page}`: {justification}")

        tier_sections.append(
            f"### {tier_name} — {tier.get('description', '')} ({len(changes)} changes)\n"
            + "\n".join(change_lines)
        )

    body = f"""## SEO Improvements for {domain}

Automated analysis identified {len(all_changes)} improvements across {len([t for t in tiers if t.get('changes')])} priority tiers.

{chr(10).join(tier_sections)}

---
*Generated by [Pressroom](https://github.com/nicdavidson/pressroomhq) — AI-powered marketing content engine. Human review required before merge.*"""

    return body


# ──────────────────────────────────────
# Deploy Verification & Self-Healing
# ──────────────────────────────────────

HEAL_SYSTEM_PROMPT = """You are a build-fix specialist. A Netlify deploy failed after automated SEO changes were pushed to a repo.

You will receive:
1. The build log showing the error
2. The list of SEO changes that were made

Your task: produce the exact file edits needed to fix the build, as a JSON array.

Rules:
- Fix the BUILD error, not the SEO intent. If a change broke the build, revert or adjust it.
- Common issues: broken front-matter YAML, invalid markdown syntax, missing closing tags, broken links.
- Keep the SEO improvements intact where possible — only modify what's breaking the build.
- Output ONLY a JSON array of edits: [{"file_path": "...", "search": "...", "replace": "..."}]
- If you can't determine the fix, return an empty array: []"""


async def verify_deploy(repo_slug: str, branch_name: str, max_wait: int = 300, poll_interval: int = 15) -> dict:
    """Poll GitHub Checks API for deploy status on a branch.

    Returns: {"status": "success"|"failed"|"timeout"|"no_checks", "log_url": "...", "details": "..."}
    """
    import asyncio
    import time

    token = settings.github_token
    if not token:
        return {"status": "no_checks", "details": "No GitHub token configured"}

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }

    start = time.time()
    last_status = None

    while (time.time() - start) < max_wait:
        try:
            # Get the latest commit SHA on the branch
            result = subprocess.run(
                ["gh", "api", f"repos/{repo_slug}/commits/{branch_name}", "--jq", ".sha"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                log.warning("Could not get branch SHA: %s", result.stderr)
                return {"status": "no_checks", "details": f"Cannot read branch: {result.stderr[:200]}"}

            sha = result.stdout.strip()
            if not sha:
                return {"status": "no_checks", "details": "Empty SHA returned"}

            # Get check runs for this commit
            check_result = subprocess.run(
                ["gh", "api", f"repos/{repo_slug}/commits/{sha}/check-runs"],
                capture_output=True, text=True, timeout=15,
            )
            if check_result.returncode != 0:
                await asyncio.sleep(poll_interval)
                continue

            data = json.loads(check_result.stdout)
            check_runs = data.get("check_runs", [])

            # Look for Netlify or any deploy-related check
            deploy_check = None
            for cr in check_runs:
                name = (cr.get("name") or "").lower()
                app = (cr.get("app", {}).get("slug") or "").lower()
                if any(kw in name or kw in app for kw in ["netlify", "deploy", "build", "vercel", "cloudflare"]):
                    deploy_check = cr
                    break

            if not deploy_check:
                # Also check commit statuses (some services use status API instead of checks)
                status_result = subprocess.run(
                    ["gh", "api", f"repos/{repo_slug}/commits/{sha}/statuses"],
                    capture_output=True, text=True, timeout=15,
                )
                if status_result.returncode == 0:
                    statuses = json.loads(status_result.stdout)
                    for st in statuses:
                        ctx = (st.get("context") or "").lower()
                        if any(kw in ctx for kw in ["netlify", "deploy", "build"]):
                            state = st.get("state", "")
                            if state == "success":
                                return {"status": "success", "details": f"Deploy passed via status: {st.get('context')}", "log_url": st.get("target_url", "")}
                            elif state in ("failure", "error"):
                                return {"status": "failed", "details": st.get("description", "Deploy failed"), "log_url": st.get("target_url", "")}
                            # pending — keep polling
                            last_status = state
                            break

                if not last_status:
                    # No deploy checks found yet — might still be queueing
                    elapsed = time.time() - start
                    if elapsed > 60:
                        # After 60s with no checks, likely no CI configured
                        return {"status": "no_checks", "details": "No deploy checks found after 60s"}

                await asyncio.sleep(poll_interval)
                continue

            # We have a deploy check
            check_status = deploy_check.get("status")  # queued, in_progress, completed
            conclusion = deploy_check.get("conclusion")  # success, failure, etc.

            if check_status == "completed":
                log_url = deploy_check.get("details_url") or deploy_check.get("html_url", "")
                if conclusion == "success":
                    return {"status": "success", "details": "Deploy succeeded", "log_url": log_url}
                else:
                    output = deploy_check.get("output", {})
                    summary = output.get("summary", "") or output.get("text", "") or ""
                    return {
                        "status": "failed",
                        "details": summary[:2000] or f"Deploy failed: {conclusion}",
                        "log_url": log_url,
                        "conclusion": conclusion,
                    }

            # Still running — keep polling
            last_status = check_status

        except Exception as e:
            log.warning("Deploy check poll error: %s", e)

        await asyncio.sleep(poll_interval)

    return {"status": "timeout", "details": f"Deploy verification timed out after {max_wait}s"}


async def fetch_deploy_log(log_url: str) -> str:
    """Fetch build log from Netlify deploy URL. Returns log text."""
    if not log_url:
        return ""

    try:
        import httpx
        # Netlify deploy URLs look like: https://app.netlify.com/sites/SITE/deploys/DEPLOY_ID
        # The API equivalent: https://api.netlify.com/api/v1/deploys/DEPLOY_ID
        # But we can also just fetch the page and look for error info

        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(log_url)
            if resp.status_code == 200:
                text = resp.text
                # Extract useful error info — look for common patterns
                # For now, return a truncated version
                return text[:5000]
    except Exception as e:
        log.warning("Failed to fetch deploy log from %s: %s", log_url, e)

    return ""


async def diagnose_and_fix_build(
    build_log: str,
    deploy_details: str,
    plan: dict,
    repo_path: str,
    api_key: str,
) -> list[dict]:
    """Send build failure + our changes to Claude, get fix edits."""
    # Collect what we changed
    change_summary = []
    for tier in plan.get("tiers", []):
        for change in tier.get("changes", []):
            change_summary.append(
                f"- {change.get('change_type', 'update')} on {change.get('file_path', '?')}: "
                f"'{change.get('current_value', '')[:80]}' → '{change.get('suggested_value', '')[:80]}'"
            )

    # Read the current state of changed files
    file_contents = []
    seen_files = set()
    for tier in plan.get("tiers", []):
        for change in tier.get("changes", []):
            fp = change.get("file_path", "")
            if fp and fp not in seen_files:
                seen_files.add(fp)
                full_path = Path(repo_path) / fp
                if full_path.exists():
                    try:
                        content = full_path.read_text(encoding="utf-8")
                        if len(content) > 8000:
                            content = content[:8000] + "\n... (truncated)"
                        file_contents.append(f"\n--- {fp} ---\n{content}\n--- end {fp} ---")
                    except Exception:
                        pass

    user_message = f"""BUILD FAILED after SEO changes were pushed.

## Deploy Error
{deploy_details[:3000]}

## Build Log (excerpt)
{build_log[:3000]}

## Changes We Made
{chr(10).join(change_summary) if change_summary else '(no change details available)'}

## Current File Contents (after our changes)
{''.join(file_contents) if file_contents else '(no file contents available)'}

Fix the build error. Return JSON edits to repair the files."""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=6000,
            system=HEAL_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        await log_token_usage(None, "seo_pipeline_heal", response)

        raw_text = response.content[0].text
        edits = _extract_edits(raw_text)
        return edits

    except Exception as e:
        log.error("Build diagnosis failed: %s", e)
        return []


async def heal_build(
    repo_path: str,
    repo_url: str,
    branch_name: str,
    plan: dict,
    deploy_result: dict,
    api_key: str,
) -> dict:
    """Full self-healing cycle: fetch log → diagnose → fix → push.

    Returns: {"healed": bool, "edits_applied": int, "error": str}
    """
    # 1. Fetch build log
    log_url = deploy_result.get("log_url", "")
    build_log = await fetch_deploy_log(log_url) if log_url else ""
    deploy_details = deploy_result.get("details", "Build failed")

    # 2. Diagnose and get fix edits
    edits = await diagnose_and_fix_build(build_log, deploy_details, plan, repo_path, api_key)

    if not edits:
        return {"healed": False, "edits_applied": 0, "error": "Could not determine fix from build log"}

    # 3. Apply edits
    applied = 0
    errors = []
    for edit in edits:
        try:
            _apply_edit(repo_path, edit)
            applied += 1
        except Exception as e:
            errors.append(f"{edit.get('file_path', '?')}: {str(e)}")

    if applied == 0:
        return {"healed": False, "edits_applied": 0, "error": f"No edits could be applied: {'; '.join(errors)}"}

    # 4. Commit and push the fix
    def _git(cmd):
        return subprocess.run(
            ["git"] + cmd,
            capture_output=True, text=True, cwd=repo_path, timeout=60,
        )

    _git(["add", "-A"])
    commit_msg = f"[SEO fix] Build repair: {applied} edit{'s' if applied != 1 else ''}"
    commit_result = _git(["commit", "-m", commit_msg])

    if commit_result.returncode != 0:
        return {"healed": False, "edits_applied": applied, "error": f"Commit failed: {commit_result.stderr[:200]}"}

    push_result = _git(["push", "origin", branch_name])
    if push_result.returncode != 0:
        return {"healed": False, "edits_applied": applied, "error": f"Push failed: {push_result.stderr[:200]}"}

    log.info("[SEO HEAL] Pushed %d fix edits to %s", applied, branch_name)
    return {"healed": True, "edits_applied": applied, "error": ""}


# ──────────────────────────────────────
# Main Pipeline
# ──────────────────────────────────────

async def run_seo_pipeline(org_id: int, config: dict, api_key: str, update_fn=None) -> dict:
    """Full SEO pipeline:
    1. Run SEO audit on the domain
    2. Analyze audit results with Claude to create tiered improvement plan
    3. Clone the target repo
    4. Implement changes via Claude API
    5. Create branch, commit tier-by-tier, push, create PR
    6. Verify deploy (poll GitHub Checks API) — if deploy fails, self-heal

    config keys: domain, repo_url, base_branch, run_id, company_description
    update_fn: async callable(updates_dict) to update the run record in real-time
    """
    domain = config["domain"]
    repo_url = config["repo_url"]
    base_branch = config.get("base_branch", "main")
    run_id = config.get("run_id")

    async def _update(updates):
        if update_fn:
            try:
                await update_fn(updates)
            except Exception as e:
                log.warning("Failed to update run status: %s", e)

    result = {
        "status": "complete",
        "pr_url": "",
        "branch_name": "",
        "changes_made": 0,
        "plan": {},
        "error": "",
    }

    repo_path = None

    try:
        # ── Phase 1: SEO Audit ──
        await _update({"status": "auditing"})
        log.info("[SEO PR] Auditing %s...", domain)

        audit_result = await audit_domain(domain, max_pages=15, api_key=api_key)
        if "error" in audit_result:
            result["status"] = "failed"
            result["error"] = f"Audit failed: {audit_result['error']}"
            await _update({"status": "failed", "error": result["error"]})
            return result

        audit_id = audit_result.get("audit_id")
        await _update({"audit_id": audit_id} if audit_id else {})

        # ── Phase 2: Claude Analysis ──
        await _update({"status": "analyzing"})
        log.info("[SEO PR] Analyzing audit results...")

        repo_info = {
            "repo_url": repo_url,
            "base_branch": base_branch,
            "company_description": config.get("company_description", ""),
        }
        plan = await analyze_seo_issues(audit_result, repo_info, api_key)

        if plan.get("error"):
            result["status"] = "failed"
            result["error"] = f"Analysis failed: {plan['error']}"
            await _update({"status": "failed", "error": result["error"], "plan_json": json.dumps(plan)})
            return result

        result["plan"] = plan
        await _update({"plan_json": json.dumps(plan)})

        # Count total planned changes
        total_planned = sum(len(t.get("changes", [])) for t in plan.get("tiers", []))
        if total_planned == 0:
            result["status"] = "complete"
            result["error"] = "No SEO improvements identified"
            await _update({"status": "complete", "error": result["error"], "plan_json": json.dumps(plan)})
            return result

        # ── Phase 3: Clone Repo ──
        await _update({"status": "implementing"})
        log.info("[SEO PR] Cloning %s...", repo_url)

        repo_path = clone_repo(repo_url, base_branch)

        # ── Phase 4: Implement Changes ──
        log.info("[SEO PR] Implementing %d planned changes...", total_planned)

        tier_results = await implement_seo_changes(plan, repo_path, api_key)

        total_applied = sum(r.get("edits_applied", 0) for r in tier_results)
        result["changes_made"] = total_applied

        if total_applied == 0:
            result["status"] = "complete"
            result["error"] = "No changes could be applied to repo files"
            await _update({
                "status": "complete",
                "error": result["error"],
                "changes_made": 0,
                "plan_json": json.dumps(plan),
            })
            return result

        # ── Phase 5: Create PR ──
        await _update({"status": "pushing", "changes_made": total_applied})
        log.info("[SEO PR] Pushing changes and creating PR...")

        today = datetime.date.today().strftime("%Y-%m-%d")
        clean_domain = domain.replace("https://", "").replace("http://", "").replace("/", "_")
        branch_name = f"seo-auto/{clean_domain}/{today}"

        pr_result = create_seo_pr(repo_path, repo_url, branch_name, base_branch, plan, domain)

        result["pr_url"] = pr_result.get("pr_url", "")
        result["branch_name"] = pr_result.get("branch_name", branch_name)
        result["changes_made"] = pr_result.get("changes_made", total_applied)

        if pr_result.get("error") and not pr_result.get("pr_url"):
            result["status"] = "failed"
            result["error"] = pr_result["error"]
            await _update({
                "status": "failed",
                "pr_url": result["pr_url"],
                "branch_name": result["branch_name"],
                "changes_made": result["changes_made"],
                "error": result["error"],
                "completed_at": datetime.datetime.utcnow(),
                "plan_json": json.dumps(plan),
            })
            return result

        await _update({
            "status": "verifying",
            "pr_url": result["pr_url"],
            "branch_name": result["branch_name"],
            "changes_made": result["changes_made"],
            "deploy_status": "pending",
            "plan_json": json.dumps(plan),
        })

        # ── Phase 6: Verify Deploy & Self-Heal ──
        log.info("[SEO PR] Verifying deploy for %s...", branch_name)

        repo_slug = repo_url.replace("https://github.com/", "").replace(".git", "")
        deploy_result = await verify_deploy(repo_slug, branch_name, max_wait=300)
        deploy_status = deploy_result.get("status", "no_checks")

        if deploy_status == "success":
            log.info("[SEO PR] Deploy verified — build passed")
            result["status"] = "complete"
            await _update({
                "status": "complete",
                "deploy_status": "success",
                "completed_at": datetime.datetime.utcnow(),
            })
            return result

        if deploy_status in ("no_checks", "timeout"):
            # No CI to verify — mark complete, note the situation
            log.info("[SEO PR] No deploy checks found or timed out — completing without verification")
            result["status"] = "complete"
            result["error"] = pr_result.get("error", "")
            await _update({
                "status": "complete",
                "deploy_status": deploy_status,
                "deploy_log": deploy_result.get("details", ""),
                "completed_at": datetime.datetime.utcnow(),
            })
            return result

        # Deploy FAILED — attempt self-healing
        log.warning("[SEO PR] Deploy failed: %s", deploy_result.get("details", "")[:200])
        await _update({
            "status": "healing",
            "deploy_status": "failed",
            "deploy_log": deploy_result.get("details", "")[:2000],
        })

        max_heal_attempts = 2
        for attempt in range(1, max_heal_attempts + 1):
            log.info("[SEO PR] Heal attempt %d/%d...", attempt, max_heal_attempts)
            await _update({"heal_attempts": attempt})

            heal_result = await heal_build(
                repo_path, repo_url, branch_name, plan, deploy_result, api_key,
            )

            if not heal_result.get("healed"):
                log.warning("[SEO PR] Heal attempt %d failed: %s", attempt, heal_result.get("error"))
                if attempt == max_heal_attempts:
                    result["status"] = "complete"
                    result["error"] = f"Deploy failed, heal failed: {heal_result.get('error', '')}"
                    await _update({
                        "status": "complete",
                        "deploy_status": "failed",
                        "error": result["error"],
                        "completed_at": datetime.datetime.utcnow(),
                    })
                    return result
                continue

            # Fix pushed — verify again
            log.info("[SEO PR] Fix pushed, re-verifying deploy...")
            await _update({"status": "verifying", "deploy_status": "pending"})

            deploy_result = await verify_deploy(repo_slug, branch_name, max_wait=300)
            deploy_status = deploy_result.get("status", "no_checks")

            if deploy_status == "success":
                log.info("[SEO PR] Deploy healed on attempt %d!", attempt)
                result["status"] = "complete"
                await _update({
                    "status": "complete",
                    "deploy_status": "healed",
                    "completed_at": datetime.datetime.utcnow(),
                })
                return result

            if deploy_status in ("no_checks", "timeout"):
                result["status"] = "complete"
                await _update({
                    "status": "complete",
                    "deploy_status": "healed",
                    "deploy_log": deploy_result.get("details", ""),
                    "completed_at": datetime.datetime.utcnow(),
                })
                return result

            # Still failing — loop for next attempt
            log.warning("[SEO PR] Deploy still failing after heal attempt %d", attempt)

        # Exhausted heal attempts
        result["status"] = "complete"
        result["error"] = "Deploy failed after all heal attempts"
        await _update({
            "status": "complete",
            "deploy_status": "failed",
            "error": result["error"],
            "completed_at": datetime.datetime.utcnow(),
        })
        return result

    except Exception as e:
        log.error("[SEO PR] Pipeline failed: %s", e, exc_info=True)
        result["status"] = "failed"
        result["error"] = str(e)
        await _update({
            "status": "failed",
            "error": str(e),
            "completed_at": datetime.datetime.utcnow(),
        })
        return result

    finally:
        # Cleanup temp repo
        if repo_path and os.path.exists(repo_path):
            try:
                shutil.rmtree(repo_path)
            except Exception:
                pass


# ──────────────────────────────────────
# README Fix Pipeline
# ──────────────────────────────────────

README_FIX_PROMPT = """You are a developer relations expert improving a GitHub README.

You will receive:
1. The current README content
2. An audit analysis with specific recommendations

Your job: produce an IMPROVED version of the full README that addresses the audit recommendations.

Rules:
- Keep all existing content that is good — don't remove things that work
- Add missing sections identified in the audit (installation, usage, examples, contributing, etc.)
- Improve existing sections that were called out as weak
- Add code examples where the audit recommends them
- Keep the voice and tone consistent with the existing README
- Use proper markdown formatting
- If the README is very short, expand it significantly
- If the README is already decent, make targeted improvements

Return ONLY the full improved README content. No explanation, no wrapping — just the raw markdown."""


async def fix_readme_with_pr(
    repo_url: str,
    base_branch: str,
    audit_recommendations: str,
    current_readme: str | None = None,
    api_key: str | None = None,
) -> dict:
    """Clone a repo, improve the README based on audit recommendations, create a PR.

    Returns dict with: pr_url, branch_name, error (if any).
    """
    api_key = api_key or settings.anthropic_api_key
    repo_path = None

    try:
        # Phase 1: Clone
        log.info("[README PR] Cloning %s", repo_url)
        repo_path = clone_repo(repo_url, base_branch)

        # Phase 2: Read current README
        readme_path = None
        for name in ["README.md", "readme.md", "README.rst", "README", "README.txt"]:
            candidate = Path(repo_path) / name
            if candidate.exists():
                readme_path = candidate
                break

        if not readme_path:
            return {"error": "No README found in repo", "pr_url": ""}

        current_content = readme_path.read_text(encoding="utf-8")
        if current_readme is None:
            current_readme = current_content

        # Phase 3: Claude generates improved README
        log.info("[README PR] Generating improved README via Claude")
        client = anthropic.Anthropic(api_key=api_key)

        user_msg = f"""CURRENT README ({readme_path.name}):
```
{current_readme[:12000]}
```

AUDIT RECOMMENDATIONS:
{audit_recommendations[:4000]}"""

        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=8000,
            system=README_FIX_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        await log_token_usage(None, "seo_pipeline_readme", response)

        improved = response.content[0].text.strip()

        # Strip markdown code fences if Claude wrapped the output
        if improved.startswith("```") and improved.endswith("```"):
            lines = improved.split("\n")
            improved = "\n".join(lines[1:-1])

        if not improved or len(improved) < 50:
            return {"error": "Claude returned empty or too-short README", "pr_url": ""}

        # Phase 4: Write improved README
        readme_path.write_text(improved, encoding="utf-8")

        # Phase 5: Branch, commit, push, PR
        def _git(cmd):
            return subprocess.run(
                ["git"] + cmd,
                capture_output=True, text=True, cwd=repo_path, timeout=60,
            )

        date_str = datetime.date.today().strftime("%Y-%m-%d")
        repo_slug = repo_url.replace("https://github.com/", "").replace(".git", "")
        branch_name = f"readme-improve/{date_str}"

        _git(["checkout", "-b", branch_name])
        _git(["add", readme_path.name])

        commit_msg = f"[README] Improve documentation based on audit recommendations"
        commit_result = _git(["commit", "-m", commit_msg])
        if commit_result.returncode != 0:
            return {"error": "Nothing to commit — README unchanged", "pr_url": ""}

        push_result = _git(["push", "origin", branch_name])
        if push_result.returncode != 0:
            return {"error": f"Push failed: {push_result.stderr}", "pr_url": ""}

        # Create PR
        pr_title = f"[README] Improve documentation ({date_str})"
        pr_body = f"""## README Improvements

Automated improvements based on README audit recommendations.

### Changes
- Addressed missing sections and structural issues
- Improved code examples and documentation clarity
- Enhanced overall README quality

### Audit Summary
{audit_recommendations[:1500]}

---
*Generated by [Pressroom](https://github.com/nicdavidson/pressroomhq) — AI-powered marketing content engine. Human review required before merge.*"""

        pr_result = subprocess.run(
            [
                "gh", "pr", "create",
                "--repo", repo_slug,
                "--title", pr_title,
                "--body", pr_body,
                "--base", base_branch,
                "--head", branch_name,
            ],
            capture_output=True, text=True, cwd=repo_path, timeout=60,
        )

        if pr_result.returncode != 0 and "label" in pr_result.stderr.lower():
            pr_result = subprocess.run(
                [
                    "gh", "pr", "create",
                    "--repo", repo_slug,
                    "--title", pr_title,
                    "--body", pr_body,
                    "--base", base_branch,
                    "--head", branch_name,
                ],
                capture_output=True, text=True, cwd=repo_path, timeout=60,
            )

        pr_url = pr_result.stdout.strip() if pr_result.returncode == 0 else ""
        error = pr_result.stderr.strip() if pr_result.returncode != 0 else ""

        log.info("[README PR] Done — pr_url=%s error=%s", pr_url, error)
        return {
            "pr_url": pr_url,
            "branch_name": branch_name,
            "error": error,
        }

    except Exception as e:
        log.error("[README PR] Failed: %s", e, exc_info=True)
        return {"error": str(e), "pr_url": ""}

    finally:
        if repo_path and os.path.exists(repo_path):
            try:
                shutil.rmtree(repo_path)
            except Exception:
                pass
