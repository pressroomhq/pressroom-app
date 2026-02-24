"""Onboarding — domain crawl, profile synthesis, DF service classification.

The onboarding flow:
1. User enters their domain → we crawl key pages
2. Claude synthesizes a company profile from the crawl
3. If DF is connected → discover services, introspect schemas, classify with Claude
4. User reviews → apply as voice settings + service map
"""

import re
import json
import logging
import httpx
import anthropic

from config import settings
from services.token_tracker import log_token_usage

log = logging.getLogger("pressroom")


def _repair_json(text: str) -> dict | None:
    """Try to parse JSON, repairing common LLM output issues."""
    text = text.strip()
    # Strip any markdown fences anywhere in the string
    text = re.sub(r'```(?:json)?\s*', '', text)
    text = re.sub(r'```', '', text).strip()

    # Direct parse first
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # Find outermost { ... }
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1:
        return None
    candidate = text[start:end + 1]

    try:
        return json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        pass

    # Repair: escape control chars inside string values
    repaired = re.sub(r'(?<=: ")([^"]*?)(?=")', lambda m: m.group(1).replace('\n', '\\n').replace('\t', '\\t'), candidate)
    try:
        return json.loads(repaired)
    except (json.JSONDecodeError, ValueError):
        pass

    # Repair: if truncated, try closing open structures
    balanced = candidate
    open_braces = balanced.count('{') - balanced.count('}')
    open_brackets = balanced.count('[') - balanced.count(']')
    if open_braces > 0 or open_brackets > 0:
        # Trim to last complete key-value pair
        last_comma = balanced.rfind(',')
        last_brace = balanced.rfind('}')
        last_bracket = balanced.rfind(']')
        # Find the last "good" stopping point
        cut = max(last_comma, last_brace, last_bracket)
        if cut > len(balanced) // 2:
            balanced = balanced[:cut]
        balanced += ']' * open_brackets + '}' * open_braces
        try:
            return json.loads(balanced)
        except (json.JSONDecodeError, ValueError):
            pass

    return None


def _get_client(api_key: str | None = None):
    """Lazy client — uses explicit key if provided, else runtime config."""
    return anthropic.Anthropic(api_key=api_key or settings.anthropic_api_key)


# ──────────────────────────────────────
# Domain Crawl
# ──────────────────────────────────────

MAX_PAGES = 15  # Don't hammer any site

# Keywords for labeling discovered URLs
_LABEL_HINTS = {
    "about": ["about", "company", "team", "who-we-are", "our-story"],
    "pricing": ["pricing", "plans", "price", "cost"],
    "blog": ["blog", "news", "articles", "insights", "resources"],
    "docs": ["docs", "documentation", "developers", "api", "reference", "guides"],
    "product": ["product", "features", "platform", "solutions", "services"],
    "contact": ["contact", "support", "help"],
    "careers": ["careers", "jobs", "hiring", "work-with-us"],
    "customers": ["customers", "case-studies", "testimonials", "stories"],
    "integrations": ["integrations", "partners", "marketplace", "ecosystem"],
}


def _root_domain(host: str) -> str:
    """Extract root domain — 'wiki.dreamfactory.com' → 'dreamfactory.com'."""
    host = host.lower().removeprefix("www.")
    parts = host.split(".")
    # Handle two-part TLDs like co.uk, com.au
    if len(parts) >= 3 and len(parts[-2]) <= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _is_same_org(host: str, base_host: str) -> bool:
    """Check if a host belongs to the same org (root domain match)."""
    return _root_domain(host) == _root_domain(base_host)


def _subdomain_prefix(host: str, base_host: str) -> str:
    """Get the subdomain prefix — 'wiki.dreamfactory.com' → 'wiki'."""
    host = host.lower().removeprefix("www.")
    base = _root_domain(base_host)
    if host == base:
        return ""
    prefix = host.removesuffix(f".{base}").removesuffix("www.")
    return prefix if prefix != host else ""


def _label_url(url: str, base: str) -> str | None:
    """Classify a URL by its path. Returns a label or None if uninteresting."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    base_parsed = urlparse(base)
    path = parsed.path.lower().strip("/")

    # Subdomain handling — label by subdomain name if it's a different host
    sub = _subdomain_prefix(parsed.netloc, base_parsed.netloc)

    if not path:
        # Subdomain root (e.g. blog.example.com) → "sub:blog"
        return f"sub:{sub}" if sub else "homepage"

    # For subdomains, grab root + one level deep (e.g. guide.example.com/docs)
    if sub:
        if path.count("/") == 0 and len(path) < 40:
            return f"sub:{sub}"  # Collapse to subdomain root label
        return None

    # Skip assets, anchors, auth, and deep paths (likely blog posts, not key pages)
    if any(path.endswith(ext) for ext in (".png", ".jpg", ".svg", ".css", ".js", ".xml", ".pdf")):
        return None
    if path.count("/") > 2:
        return None
    skip_patterns = ["login", "signup", "sign-up", "register", "cart", "checkout", "account",
                     "privacy", "terms", "cookie", "legal", "sitemap"]
    if any(s in path for s in skip_patterns):
        return None

    for label, hints in _LABEL_HINTS.items():
        if any(h in path for h in hints):
            return label

    # If it's a top-level page we don't recognize, still grab it
    if path.count("/") == 0 and len(path) < 40:
        return path

    return None


def _prefer_url(new_url: str, existing_url: str) -> bool:
    """Should new_url replace existing_url for the same label?

    Prefers root/shorter paths over deep links. e.g. blog.example.com
    beats blog.example.com/some-article-title.
    """
    from urllib.parse import urlparse
    new_path = urlparse(new_url).path.strip("/")
    old_path = urlparse(existing_url).path.strip("/")
    # Root URL always wins
    if not new_path and old_path:
        return True
    # Shorter path wins (fewer segments = closer to root)
    if new_path.count("/") < old_path.count("/"):
        return True
    return False


async def _discover_from_sitemap(client: httpx.AsyncClient, base: str) -> dict[str, str]:
    """Try sitemap.xml → return {label: url} for interesting pages."""
    from urllib.parse import urlparse
    base_host = urlparse(base).netloc
    discovered = {}

    for sitemap_path in ["/sitemap.xml", "/sitemap_index.xml"]:
        try:
            resp = await client.get(f"{base}{sitemap_path}",
                                    headers={"User-Agent": "Pressroom/0.1 (content-engine)"})
            if resp.status_code != 200:
                continue
            # Extract URLs from <loc> tags
            urls = re.findall(r'<loc>\s*(.*?)\s*</loc>', resp.text)
            for url in urls:
                url = url.strip()
                # If it's a sub-sitemap, fetch that too (one level deep)
                if url.endswith(".xml"):
                    try:
                        sub_resp = await client.get(url, headers={"User-Agent": "Pressroom/0.1 (content-engine)"})
                        if sub_resp.status_code == 200:
                            sub_urls = re.findall(r'<loc>\s*(.*?)\s*</loc>', sub_resp.text)
                            for su in sub_urls:
                                su = su.strip()
                                su_host = urlparse(su).netloc
                                if not _is_same_org(su_host, base_host):
                                    continue
                                label = _label_url(su, base)
                                if label and (label not in discovered or _prefer_url(su, discovered[label])):
                                    discovered[label] = su
                    except Exception:
                        pass
                    continue
                # Check org match for non-sitemap URLs too
                url_host = urlparse(url).netloc
                if url_host and not _is_same_org(url_host, base_host):
                    continue
                label = _label_url(url, base)
                if label and (label not in discovered or _prefer_url(url, discovered[label])):
                    discovered[label] = url
            if discovered:
                break
        except Exception:
            continue
    return discovered


async def _discover_from_nav(client: httpx.AsyncClient, base: str, homepage_html: str) -> dict[str, str]:
    """Parse homepage HTML for internal nav links → {label: url}."""
    from urllib.parse import urljoin, urlparse
    discovered = {}
    base_host = urlparse(base).netloc

    # Extract hrefs from the page
    hrefs = re.findall(r'<a[^>]+href=["\']([^"\'#]+)["\']', homepage_html, re.IGNORECASE)

    for href in hrefs:
        url = urljoin(base, href)
        parsed = urlparse(url)

        # Same org (root domain match) — allows subdomains
        if parsed.netloc and not _is_same_org(parsed.netloc, base_host):
            continue

        label = _label_url(url, base)
        if label and (label not in discovered or _prefer_url(url, discovered[label])):
            discovered[label] = url

    return discovered


_SOCIAL_PATTERNS = {
    "linkedin": r'https?://(?:www\.)?linkedin\.com/(?:company|in)/[^\s"\'<>]+',
    "x": r'https?://(?:www\.)?(?:twitter\.com|x\.com)/[^\s"\'<>]+',
    "facebook": r'https?://(?:www\.)?facebook\.com/[^\s"\'<>]+',
    "instagram": r'https?://(?:www\.)?instagram\.com/[^\s"\'<>]+',
    "youtube": r'https?://(?:www\.)?youtube\.com/(?:@|channel/|c/|user/)[^\s"\'<>]+',
    "github": r'https?://(?:www\.)?github\.com/[^\s"\'<>]+',
    "tiktok": r'https?://(?:www\.)?tiktok\.com/@[^\s"\'<>]+',
}


_SOCIAL_SKIP = ('/sharer', '/intent/', '/share?', '/dialog/', '/embed/', '/watch?', '/playlist?')


def _extract_social_links(html: str) -> dict[str, str]:
    """Pull social media profile URLs from page HTML.

    Finds ALL matches per platform, skips share/intent/embed links,
    and keeps the shortest (most canonical) URL.
    """
    found = {}
    for platform, pattern in _SOCIAL_PATTERNS.items():
        matches = re.findall(pattern, html, re.IGNORECASE)
        candidates = []
        for url in matches:
            url = url.rstrip('/')
            if any(skip in url.lower() for skip in _SOCIAL_SKIP):
                continue
            candidates.append(url)
        if candidates:
            # Shortest URL is usually the canonical profile link
            found[platform] = min(candidates, key=len)
    return found


async def crawl_domain(domain: str) -> dict:
    """Crawl a domain's key pages via sitemap discovery + nav link extraction."""
    if not domain.startswith("http"):
        domain = f"https://{domain}"
    domain = domain.rstrip("/")

    pages = {}
    headers = {"User-Agent": "Pressroom/0.1 (content-engine)"}

    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
        # Always grab homepage first
        homepage_html = ""
        try:
            resp = await c.get(domain, headers=headers)
            if resp.status_code == 200:
                homepage_html = resp.text
                text = _extract_text(homepage_html)
                if text and len(text) > 50:
                    pages["homepage"] = {"url": domain, "text": text[:5000]}
        except Exception:
            pass

        # Extract social media profiles from homepage
        socials = _extract_social_links(homepage_html) if homepage_html else {}

        # Discover pages: sitemap + nav links (always run both)
        targets = await _discover_from_sitemap(c, domain)
        if homepage_html:
            nav_targets = await _discover_from_nav(c, domain, homepage_html)
            # Merge — sitemap wins on conflicts for same labels
            for label, url in nav_targets.items():
                if label not in targets:
                    targets[label] = url

        # Remove homepage from targets (already crawled)
        targets.pop("homepage", None)

        # Prioritize: subdomains first (high-value distinct properties), then main pages
        sorted_targets = sorted(targets.items(), key=lambda x: (0 if x[0].startswith("sub:") else 1, x[0]))

        # Crawl discovered pages up to limit
        for label, url in sorted_targets[:MAX_PAGES]:
            try:
                resp = await c.get(url, headers=headers)
                if resp.status_code == 200:
                    page_html = resp.text
                    text = _extract_text(page_html)
                    if text and len(text) > 50:
                        pages[label] = {"url": url, "text": text[:5000]}
                    # Extract social links from every crawled page (fill gaps)
                    for platform, surl in _extract_social_links(page_html).items():
                        if platform not in socials:
                            socials[platform] = surl
            except Exception:
                continue

    return {
        "domain": domain,
        "pages_found": list(pages.keys()),
        "pages": pages,
        "social_profiles": socials,
    }


def _extract_text(html: str) -> str:
    """Rough text extraction from HTML — strip tags, collapse whitespace."""
    # Remove script/style blocks
    html = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', html)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Remove common boilerplate patterns
    text = re.sub(r'(cookie|privacy|terms of service|all rights reserved).*?\.', '', text, flags=re.IGNORECASE)
    return text


# ──────────────────────────────────────
# Profile Synthesis
# ──────────────────────────────────────

async def synthesize_profile(crawl_data: dict, extra_context: str = "",
                              api_key: str | None = None) -> dict:
    """Claude synthesizes a company profile from crawled page data."""
    pages_text = ""
    for label, page in crawl_data.get("pages", {}).items():
        pages_text += f"\n--- {label.upper()} ({page['url']}) ---\n{page['text'][:3000]}\n"

    # Social profiles from crawl
    socials = crawl_data.get("social_profiles", {})
    socials_text = ""
    if socials:
        socials_text = "\nSOCIAL PROFILES FOUND:\n" + "\n".join(f"  {p}: {u}" for p, u in socials.items()) + "\n"

    if not pages_text.strip():
        return {"error": "No page content to analyze"}

    prompt = f"""Analyze this company's website content and create a content operations profile.

Website: {crawl_data.get('domain', 'unknown')}

{pages_text}

{socials_text}
{f'Additional context from user: {extra_context}' if extra_context else ''}

Return ONLY a valid JSON object (no markdown, no commentary) with these exact fields:
- company_name: string
- industry: string
- persona: string (2-3 sentences, the company voice)
- bio: string (one-liner for author attribution)
- audience: string
- tone: string (e.g. "Technical, direct, no-nonsense")
- never_say: array of strings
- brand_keywords: array of strings
- always: string
- topics: array of strings
- competitors: array of strings
- linkedin_style: string
- x_style: string
- blog_style: string
- golden_anchor: string (the one core message or phrase this company should weave into all content — their north star statement, derived from their messaging)
- social_profiles: object with keys linkedin, x, facebook, instagram, youtube, github (values are URL strings or null)

IMPORTANT: Escape all special characters in JSON strings. Do not use unescaped quotes or newlines inside string values.

Be specific to THIS company. Not generic marketing advice. Derive everything from what you actually see on their site."""

    response = _get_client(api_key).messages.create(
        model=settings.claude_model_fast,
        max_tokens=4000,
        system="You are a content strategist analyzing a company to set up their AI content engine. Return valid JSON only, no markdown fences.",
        messages=[{"role": "user", "content": prompt}],
    )
    await log_token_usage(None, "onboard_profile", response)

    text = response.content[0].text
    log.info("PROFILE RAW RESPONSE (%d chars): %s", len(text), text[:500])

    parsed = _repair_json(text)
    if parsed and isinstance(parsed, dict) and not parsed.get("error"):
        return parsed

    log.error("PROFILE JSON PARSE FAILED.\nRAW: %s", text[:1000])
    return {"error": "Failed to parse profile — Claude returned malformed JSON", "raw": text[:500]}


# ──────────────────────────────────────
# Scout Source Generation
# ──────────────────────────────────────

async def generate_scout_sources(profile: dict, api_key: str | None = None) -> dict:
    """Claude generates relevant scout sources from a company profile.

    Returns subreddits, HN keywords, GitHub repos, and RSS feeds
    tailored to this specific company.
    """
    company = profile.get("company_name", "Unknown")
    industry = profile.get("industry", "")
    topics = profile.get("topics", [])
    competitors = profile.get("competitors", [])
    audience = profile.get("audience", "")

    prompt = f"""Based on this company profile, generate the best signal sources for their AI content engine.

Company: {company}
Industry: {industry}
Key topics: {', '.join(topics) if isinstance(topics, list) else topics}
Competitors: {', '.join(competitors) if isinstance(competitors, list) else competitors}
Audience: {audience}

Return ONLY a valid JSON object with:

- subreddits: array of 5-8 subreddit names (without r/) where this company's audience hangs out or discusses relevant topics. Be specific — not just "webdev" but subreddits where their actual customers would be.

- hn_keywords: array of 10-15 keywords/phrases to match on Hacker News. Include the company name, product category terms, competitor names, and technology terms. Think about what HN titles would be relevant content signals.

- github_repos: array of 2-5 GitHub repos to watch (owner/repo format). Include the company's own repo if they have one, plus key competitor or ecosystem repos.

- rss_feeds: array of 3-5 RSS feed URLs for industry blogs, competitor blogs, or news sources. Only include feeds you're confident exist (major tech blogs, known company blogs).

- web_queries: array of 5-8 web search queries that would surface relevant industry content, competitor activity, or market trends. These are used for ongoing web search monitoring. Think about what a content marketer at this company would Google to find content opportunities and stay informed.

Be SPECIFIC to this company. A DreamFactory (API platform) company should NOT get r/homelab. An e-commerce company should NOT get r/webdev. Think about WHO their customers are and WHERE those people talk."""

    response = _get_client(api_key).messages.create(
        model=settings.claude_model_fast,
        max_tokens=2000,
        system="You are a content strategist. Return valid JSON only, no markdown fences.",
        messages=[{"role": "user", "content": prompt}],
    )
    await log_token_usage(None, "onboard_scout_sources", response)

    text = response.content[0].text
    log.info("SCOUT SOURCES RAW (%d chars): %s", len(text), text[:500])

    parsed = _repair_json(text)
    if parsed and isinstance(parsed, dict):
        return parsed

    log.error("SCOUT SOURCES PARSE FAILED.\nRAW: %s", text[:1000])
    return {}


# ──────────────────────────────────────
# DF Service Classification
# ──────────────────────────────────────

async def classify_df_services(db_services: list[dict], social_services: list[dict],
                                api_key: str | None = None) -> dict:
    """Claude classifies discovered DF services by role for the content engine.

    Takes introspected DB services (with schemas/samples) and social services,
    returns a service map that tells the engine what each service IS and how to use it.
    """
    # Build a description of what we found
    service_desc = "CONNECTED DREAMFACTORY SERVICES:\n\n"

    for svc in db_services:
        service_desc += f"DATABASE: {svc['name']} ({svc['type']})\n"
        if svc.get("description"):
            service_desc += f"  Description: {svc['description']}\n"
        for tbl in svc.get("tables", []):
            cols = ", ".join(tbl["columns"][:20]) if tbl.get("columns") else "unknown"
            service_desc += f"  Table: {tbl['name']} — columns: [{cols}]\n"
            if tbl.get("sample_row"):
                # Truncate values for prompt
                sample = {k: str(v)[:100] for k, v in list(tbl["sample_row"].items())[:8]}
                service_desc += f"  Sample: {json.dumps(sample)}\n"
        service_desc += "\n"

    for svc in social_services:
        stype = svc.get("type", "unknown")
        connected = svc.get("auth_status", {}).get("connected", False)
        service_desc += f"SOCIAL: {svc['name']} ({stype}) — {'authenticated' if connected else 'not authenticated'}\n"

    prompt = f"""{service_desc}

Classify each service for use in an AI content operations platform (Pressroom).

The platform needs to understand:
- Which databases contain customer data (CRM, support tickets, feedback)
- Which databases contain analytics/performance data
- Which databases contain product/company data
- Which are Pressroom's own internal databases
- Which social services are publishing channels

Return a JSON object:
{{
  "service_map": {{
    "service_name": {{
      "role": "customer_intelligence|performance_data|product_data|internal|publishing_channel|unknown",
      "description": "What this service provides to the content engine",
      "data_type": "What kind of data it holds",
      "useful_tables": ["table_names", "the engine should query"],
      "query_hints": "How to query this for content intelligence (DF filter syntax)"
    }}
  }},
  "intelligence_sources": ["service names that provide content intelligence"],
  "publishing_channels": ["service names for publishing content"]
}}"""

    response = _get_client(api_key).messages.create(
        model=settings.claude_model_fast,
        max_tokens=2000,
        system="You are a data architect classifying connected services for an AI content platform. Return valid JSON only. Be specific about what each service provides.",
        messages=[{"role": "user", "content": prompt}],
    )
    await log_token_usage(None, "onboard_classify", response)

    text = response.content[0].text
    log.info("CLASSIFY RAW RESPONSE (%d chars): %s", len(text), text[:500])

    parsed = _repair_json(text)
    if parsed and isinstance(parsed, dict):
        return parsed

    log.error("CLASSIFY JSON PARSE FAILED.\nRAW: %s", text[:1000])
    return {"error": "Failed to parse classification", "raw": text[:500]}


# ──────────────────────────────────────
# Apply Profile
# ──────────────────────────────────────

def profile_to_settings(profile: dict) -> dict:
    """Convert a synthesized profile into the settings key/value pairs."""
    mapping = {}

    if profile.get("persona"):
        mapping["voice_persona"] = profile["persona"]
    if profile.get("bio"):
        mapping["voice_bio"] = profile["bio"]
    if profile.get("audience"):
        mapping["voice_audience"] = profile["audience"]
    if profile.get("tone"):
        mapping["voice_tone"] = profile["tone"]
    if profile.get("always"):
        mapping["voice_always"] = profile["always"]
    if profile.get("never_say"):
        mapping["voice_never_say"] = json.dumps(profile["never_say"])
    if profile.get("brand_keywords"):
        mapping["voice_brand_keywords"] = json.dumps(profile["brand_keywords"])
    if profile.get("linkedin_style"):
        mapping["voice_linkedin_style"] = profile["linkedin_style"]
    if profile.get("x_style"):
        mapping["voice_x_style"] = profile["x_style"]
    if profile.get("blog_style"):
        mapping["voice_blog_style"] = profile["blog_style"]
    if profile.get("golden_anchor"):
        mapping["golden_anchor"] = profile["golden_anchor"]

    return mapping
