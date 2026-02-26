"""GitHub README Audit — fetch repo README, analyze quality with Claude."""

import re
import logging
import base64

import httpx
import anthropic
from config import settings
from services.token_tracker import log_token_usage

log = logging.getLogger("pressroom")

HEADERS = {"Accept": "application/vnd.github.v3+json"}


def _get_client(api_key: str | None = None):
    return anthropic.AsyncAnthropic(api_key=api_key or settings.anthropic_api_key)


def _parse_repo(repo_input: str) -> str:
    """Normalize repo input to 'owner/repo' format.

    Accepts: 'owner/repo', 'https://github.com/owner/repo', etc.
    """
    repo = repo_input.strip().rstrip("/")
    if "github.com/" in repo:
        parts = repo.split("github.com/")[1].split("/")
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1]}"
    return repo


async def audit_readme(repo: str, gh_token: str | None = None, api_key: str | None = None) -> dict:
    """Fetch a GitHub repo's README and run quality analysis."""
    owner_repo = _parse_repo(repo)

    if not gh_token:
        gh_token = settings.github_token

    headers = {**HEADERS}
    if gh_token:
        headers["Authorization"] = f"token {gh_token}"

    async with httpx.AsyncClient(timeout=15) as client:
        # Fetch README via GitHub API
        resp = await client.get(
            f"https://api.github.com/repos/{owner_repo}/readme",
            headers=headers,
        )

        if resp.status_code == 404:
            return {"error": f"No README found for {owner_repo}", "repo": owner_repo}
        if resp.status_code == 403:
            return {"error": "GitHub API rate limited. Add a GitHub token in Settings.", "repo": owner_repo}
        if resp.status_code != 200:
            return {"error": f"GitHub API error: {resp.status_code}", "repo": owner_repo}

        data = resp.json()
        content_b64 = data.get("content", "")
        readme_text = base64.b64decode(content_b64).decode("utf-8", errors="replace")
        filename = data.get("name", "README.md")

        # Fetch repo metadata for context
        repo_resp = await client.get(
            f"https://api.github.com/repos/{owner_repo}",
            headers=headers,
        )
        repo_meta = repo_resp.json() if repo_resp.status_code == 200 else {}

    # Extract structural elements
    structure = _analyze_structure(readme_text)

    # Claude analysis
    analysis = await _analyze_readme(
        readme_text, owner_repo, repo_meta, structure, api_key=api_key
    )

    return {
        "repo": owner_repo,
        "filename": filename,
        "char_count": len(readme_text),
        "word_count": len(readme_text.split()),
        "structure": structure,
        "recommendations": analysis,
    }


def _analyze_structure(text: str) -> dict:
    """Extract structural elements from the README."""
    lines = text.split("\n")

    # Headings
    headings = []
    for line in lines:
        m = re.match(r'^(#{1,6})\s+(.+)', line)
        if m:
            headings.append({"level": len(m.group(1)), "text": m.group(2).strip()})

    # Sections we look for
    section_keywords = {
        "installation": ["install", "getting started", "setup", "quick start", "quickstart"],
        "usage": ["usage", "how to use", "example", "examples", "tutorial"],
        "api_reference": ["api", "reference", "documentation", "docs"],
        "contributing": ["contributing", "contribute", "development"],
        "license": ["license", "licence"],
        "badges": [],  # handled separately
        "images": [],  # handled separately
        "code_blocks": [],  # handled separately
    }

    heading_texts_lower = [h["text"].lower() for h in headings]
    sections_found = {}
    for section, keywords in section_keywords.items():
        sections_found[section] = any(
            any(kw in ht for kw in keywords) for ht in heading_texts_lower
        )

    # Badges (shield.io, img.shields.io, badge patterns)
    badge_count = len(re.findall(
        r'!\[.*?\]\(.*?(?:shields\.io|badge|img\.shields).*?\)', text, re.IGNORECASE
    ))
    sections_found["badges"] = badge_count > 0

    # Images (non-badge)
    image_count = len(re.findall(r'!\[.*?\]\(.*?\)', text)) - badge_count
    sections_found["images"] = image_count > 0

    # Code blocks
    code_blocks = len(re.findall(r'```', text)) // 2
    sections_found["code_blocks"] = code_blocks > 0

    # Links
    link_count = len(re.findall(r'\[.*?\]\(.*?\)', text)) - len(re.findall(r'!\[', text))

    return {
        "headings": headings,
        "heading_count": len(headings),
        "sections_found": sections_found,
        "badge_count": badge_count,
        "image_count": image_count,
        "code_block_count": code_blocks,
        "link_count": link_count,
    }


async def _analyze_readme(
    readme_text: str,
    repo: str,
    repo_meta: dict,
    structure: dict,
    api_key: str | None = None,
) -> dict:
    """Claude analyzes README quality and gives recommendations."""
    desc = repo_meta.get("description", "No description")
    lang = repo_meta.get("language", "Unknown")
    stars = repo_meta.get("stargazers_count", 0)
    topics = repo_meta.get("topics", [])

    summary = f"""README AUDIT FOR {repo}
Repo: {desc}
Language: {lang} | Stars: {stars} | Topics: {', '.join(topics) if topics else 'none'}

STRUCTURAL ANALYSIS:
- Headings: {structure['heading_count']}
- Badges: {structure['badge_count']}
- Images: {structure['image_count']}
- Code blocks: {structure['code_block_count']}
- Links: {structure['link_count']}
- Sections found: {', '.join(k for k, v in structure['sections_found'].items() if v) or 'none'}
- Sections missing: {', '.join(k for k, v in structure['sections_found'].items() if not v) or 'none'}

FULL README CONTENT:
{readme_text[:8000]}"""

    try:
        response = await _get_client(api_key).messages.create(
            model=settings.claude_model_fast,
            max_tokens=2000,
            system="""You are a developer relations expert auditing a GitHub README. Score and critique it based on:

1. SCORE: Overall README quality (0-100) with one-line justification.
2. FIRST IMPRESSION: What a developer sees in the first 10 seconds — is the value proposition clear?
3. STRUCTURE: Is the README well-organized? Does it have the essential sections (install, usage, examples, contributing)?
4. CODE EXAMPLES: Are there runnable code samples? Do they show common use cases?
5. MISSING SECTIONS: What sections should be added? Be specific about what content each should contain.
6. QUICK WINS: 3-5 specific improvements that would immediately make this README better.

Be specific. Reference actual content from the README. Every recommendation should be actionable.""",
            messages=[{"role": "user", "content": summary}],
        )

        await log_token_usage(None, "readme_audit", response)
        analysis_text = response.content[0].text

        score = 0
        score_match = re.search(r'(?:SCORE|score)[:\s]*(\d+)', analysis_text)
        if score_match:
            score = min(100, max(0, int(score_match.group(1))))

        # Count issues from missing sections
        missing = [k for k, v in structure["sections_found"].items()
                   if not v and k not in ("badges", "images")]
        total_issues = len(missing)

        return {
            "score": score,
            "total_issues": total_issues,
            "analysis": analysis_text,
        }

    except Exception as e:
        log.error("README analysis failed: %s", e)
        return {
            "score": 0,
            "total_issues": 0,
            "analysis": f"Analysis failed: {str(e)}",
        }
