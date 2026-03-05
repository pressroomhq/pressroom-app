"""Skill invocation — load a skill and run it as a Claude system prompt.

Resolution order:
1. Org skill (from org_skills table) — customized per-org version
2. Template skill (from skills/templates/ directory) — global default
3. Legacy skill (from skills/ root or skills/channels/) — backwards compat
"""

import logging
from pathlib import Path
from anthropic import AsyncAnthropic
from config import settings
from services.token_tracker import log_token_usage

log = logging.getLogger("pressroom")

_SKILLS_DIR = Path(__file__).parent
_TEMPLATES_DIR = _SKILLS_DIR / "templates"

# Category → subdirectory mapping for templates
_CATEGORY_DIRS = {
    "channel": _TEMPLATES_DIR / "channels",
    "marketing": _TEMPLATES_DIR / "marketing",
    "seo": _TEMPLATES_DIR / "seo",
    "processing": _TEMPLATES_DIR / "processing",
}

_client = None


def _get_client(api_key: str | None = None) -> AsyncAnthropic:
    global _client
    key = api_key or settings.anthropic_api_key
    if _client and not api_key:
        return _client
    c = AsyncAnthropic(api_key=key)
    if not api_key:
        _client = c
    return c


def resolve_template(skill_name: str) -> str | None:
    """Find a template skill on disk. Checks templates/ subdirs then legacy paths.

    Returns the file content or None.
    """
    # Check all template subdirectories
    for cat_dir in _CATEGORY_DIRS.values():
        path = cat_dir / f"{skill_name}.md"
        if path.exists():
            return path.read_text()

    # Legacy: skills/{name}.md (humanizer.md, seo_geo.md, etc.)
    legacy = _SKILLS_DIR / f"{skill_name}.md"
    if legacy.exists():
        return legacy.read_text()

    # Legacy: skills/channels/{name}.md
    legacy_channel = _SKILLS_DIR / "channels" / f"{skill_name}.md"
    if legacy_channel.exists():
        return legacy_channel.read_text()

    return None


async def resolve_skill(skill_name: str, dl=None) -> str:
    """Resolve a skill — org override first, then template.

    Args:
        skill_name: Skill name (without .md)
        dl: DataLayer instance (if available, checks org_skills table)

    Returns:
        Skill content string

    Raises:
        ValueError if skill not found anywhere
    """
    # 1. Check org-specific override
    if dl and dl.org_id:
        try:
            org_content = await dl.get_org_skill(skill_name)
            if org_content:
                log.debug("[skills] Resolved '%s' from org_skills (org=%s)", skill_name, dl.org_id)
                return org_content
        except Exception:
            pass  # Fall through to template

    # 2. Check template files
    template = resolve_template(skill_name)
    if template:
        log.debug("[skills] Resolved '%s' from template", skill_name)
        return template

    raise ValueError(f"Skill not found: {skill_name}")


async def invoke(skill_name: str, content: str, context: dict | None = None,
                 api_key: str | None = None, dl=None, org_id: int | None = None) -> str:
    """Load a skill by name and run it against content.

    Args:
        skill_name: Name of the skill (without .md extension)
        content: The content to process
        context: Optional context dict (key/value pairs added to user message)
        api_key: Optional API key override
        dl: Optional DataLayer for org-aware skill resolution
        org_id: Optional org_id for token tracking

    Returns:
        Claude's response text
    """
    system_prompt = await resolve_skill(skill_name, dl=dl)

    # Build user message from content + context
    user_msg = content
    if context:
        ctx_lines = "\n".join(f"{k}: {v}" for k, v in context.items())
        user_msg = f"Context:\n{ctx_lines}\n\n---\n\n{user_msg}"

    client = _get_client(api_key)
    response = await client.messages.create(
        model=settings.claude_model,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )
    await log_token_usage(org_id, f"skill_{skill_name}", response)
    return response.content[0].text


def list_templates() -> list[dict]:
    """List all available template skills from disk, grouped by category.

    Returns list of {name, category, path, size_bytes, first_line}.
    """
    templates = []
    for category, cat_dir in _CATEGORY_DIRS.items():
        if not cat_dir.exists():
            continue
        for f in sorted(cat_dir.iterdir()):
            if f.suffix != ".md":
                continue
            first_line = ""
            try:
                first_line = f.read_text().split("\n")[0][:100]
            except Exception:
                pass
            templates.append({
                "name": f.stem,
                "category": category,
                "path": str(f),
                "size_bytes": f.stat().st_size,
                "first_line": first_line,
            })
    return templates


def infer_category(skill_name: str) -> str:
    """Infer a skill's category from its template location."""
    for category, cat_dir in _CATEGORY_DIRS.items():
        if (cat_dir / f"{skill_name}.md").exists():
            return category
    # Check legacy locations
    if (_SKILLS_DIR / "channels" / f"{skill_name}.md").exists():
        return "channel"
    return "processing"  # default
