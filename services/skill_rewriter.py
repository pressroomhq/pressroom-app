"""Skill rewriter — rewrites global template skills to be company-specific.

Called during onboarding after profile synthesis. Takes each template skill
and asks Claude (fast model) to rewrite it with company context baked in.

The rewritten skills are stored in org_skills so the org always gets their
customized version instead of the generic template.
"""

import asyncio
import logging

import anthropic

from config import settings
from services.token_tracker import log_token_usage
from skills.invoke import list_templates, _CATEGORY_DIRS

log = logging.getLogger("pressroom")

# Categories to rewrite during onboarding.
# 'processing' skills (humanizer, taste) are internal pipeline skills
# that don't benefit from company-specific rewrites.
_REWRITE_CATEGORIES = {"channel", "marketing", "seo"}

# Max concurrent Claude calls during rewrite
_MAX_CONCURRENT = 4


def _build_company_context(profile: dict) -> str:
    """Build a rich company context block from the onboarding profile."""
    parts = []

    if profile.get("company_name"):
        parts.append(f"Company: {profile['company_name']}")
    if profile.get("industry"):
        parts.append(f"Industry: {profile['industry']}")
    if profile.get("audience"):
        parts.append(f"Target audience: {profile['audience']}")
    if profile.get("persona"):
        parts.append(f"Brand voice: {profile['persona']}")
    if profile.get("tone"):
        parts.append(f"Tone: {profile['tone']}")
    if profile.get("golden_anchor"):
        parts.append(f"Core message (golden anchor): {profile['golden_anchor']}")
    if profile.get("bio"):
        parts.append(f"Author bio: {profile['bio']}")
    if profile.get("topics"):
        topics = profile["topics"]
        if isinstance(topics, list):
            topics = ", ".join(topics)
        parts.append(f"Key topics: {topics}")
    if profile.get("competitors"):
        comps = profile["competitors"]
        if isinstance(comps, list):
            comps = ", ".join(comps)
        parts.append(f"Competitors: {comps}")
    if profile.get("brand_keywords"):
        kw = profile["brand_keywords"]
        if isinstance(kw, list):
            kw = ", ".join(kw)
        parts.append(f"Brand keywords: {kw}")
    if profile.get("never_say"):
        ns = profile["never_say"]
        if isinstance(ns, list):
            ns = ", ".join(ns)
        parts.append(f"Never say: {ns}")
    if profile.get("always"):
        parts.append(f"Always: {profile['always']}")

    # Channel-specific style hints
    for key, label in [
        ("linkedin_style", "LinkedIn style"),
        ("x_style", "X/Twitter style"),
        ("blog_style", "Blog style"),
    ]:
        if profile.get(key):
            parts.append(f"{label}: {profile[key]}")

    return "\n".join(parts)


_REWRITE_SYSTEM = """You are rewriting a marketing skill template to be specific to one company.

Your job:
1. Keep the EXACT same structure, sections, and formatting (headers, bullet points, markdown)
2. Keep all instructional content (format rules, word counts, style guidelines)
3. Replace generic/placeholder references with company-specific details
4. Weave in the company's voice, tone, audience, and positioning naturally
5. Add company-specific examples where the template uses generic ones
6. The result should read as if it was written specifically for this company from scratch

Rules:
- Do NOT add new sections the template doesn't have
- Do NOT remove sections the template has
- Do NOT change format constraints (word counts, structure rules)
- Do NOT add {{placeholders}} — everything should be fully realized
- Keep it concise — the rewrite should be roughly the same length as the original
- Output ONLY the rewritten skill content, nothing else (no "Here's the rewritten..." preamble)"""


async def _rewrite_one(
    skill_name: str,
    template_content: str,
    company_context: str,
    client: anthropic.AsyncAnthropic,
    org_id: int | None = None,
) -> tuple[str, str]:
    """Rewrite a single skill template. Returns (skill_name, rewritten_content)."""
    user_msg = f"""## Company Context

{company_context}

---

## Template Skill to Rewrite

{template_content}"""

    response = await client.messages.create(
        model=settings.claude_model_fast,
        max_tokens=4096,
        system=_REWRITE_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )
    await log_token_usage(org_id, f"skill_rewrite_{skill_name}", response)
    return skill_name, response.content[0].text


async def rewrite_skills_for_org(
    profile: dict,
    crawl_data: dict | None = None,
    api_key: str | None = None,
    org_id: int | None = None,
) -> dict[str, str]:
    """Rewrite all template skills with company context baked in.

    Args:
        profile: Company profile dict from synthesize_profile()
        crawl_data: Optional crawl data (unused for now, reserved for future enrichment)
        api_key: Optional Anthropic API key override
        org_id: Optional org_id for token tracking

    Returns:
        Dict of {skill_name: rewritten_content} for all rewritable skills
    """
    company_context = _build_company_context(profile)
    if not company_context.strip():
        log.warning("[skill_rewriter] Empty company context — skipping rewrite")
        return {}

    # Collect templates to rewrite
    templates = list_templates()
    rewritable = [t for t in templates if t["category"] in _REWRITE_CATEGORIES]

    if not rewritable:
        log.warning("[skill_rewriter] No templates found to rewrite")
        return {}

    log.info(
        "[skill_rewriter] Rewriting %d skills for '%s'",
        len(rewritable),
        profile.get("company_name", "unknown"),
    )

    client = anthropic.AsyncAnthropic(api_key=api_key or settings.anthropic_api_key)
    sem = asyncio.Semaphore(_MAX_CONCURRENT)

    async def _bounded(t: dict) -> tuple[str, str]:
        async with sem:
            content = open(t["path"]).read()
            return await _rewrite_one(
                t["name"], content, company_context, client, org_id=org_id,
            )

    # Run all rewrites concurrently (bounded by semaphore)
    results = await asyncio.gather(
        *[_bounded(t) for t in rewritable],
        return_exceptions=True,
    )

    rewritten = {}
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            log.error(
                "[skill_rewriter] Failed to rewrite '%s': %s",
                rewritable[i]["name"],
                result,
            )
            continue
        name, content = result
        rewritten[name] = content

    log.info(
        "[skill_rewriter] Rewrote %d/%d skills successfully",
        len(rewritten),
        len(rewritable),
    )
    return rewritten
