"""
SEO + GEO Audit Skill
=====================
Comprehensive SEO and Generative Engine Optimization analysis.

GEO insight: AI search engines don't rank pages — they CITE sources.
Being cited is the new ranking #1.

Usage:
    from skills.seo_geo import run
    result = await run("https://example.com", context={"deep": True})

Context options:
    deep (bool): Run full 5-step analysis. Default: False (quick audit only)
    keyword_focus (str): Primary keyword to analyze. Optional.
    competitors (list[str]): Competitor domains to benchmark against. Optional.
"""

import re
import httpx
from anthropic import AsyncAnthropic
from config import settings
from services.token_tracker import log_token_usage

def _get_client(api_key: str = "") -> AsyncAnthropic:
    return AsyncAnthropic(api_key=api_key or settings.anthropic_api_key)

# GEO optimization methods with their visibility boost estimates
# Source: Princeton GEO research
GEO_METHODS = [
    ("source_citations", "+40%", "Cite authoritative sources inline"),
    ("statistics", "+37%", "Include specific data points and metrics"),
    ("expert_quotations", "+30%", "Quote named experts or research"),
    ("authoritative_tone", "+25%", "Write with confidence and authority"),
    ("simplified_explanations", "+20%", "Define technical terms clearly"),
    ("technical_terminology", "+18%", "Use domain-specific vocabulary correctly"),
    ("vocabulary_diversity", "+15%", "Avoid repetitive phrasing"),
    ("fluency_optimization", "+15-30%", "Natural, readable prose"),
]

# AI bots that should be allowed in robots.txt
AI_BOTS = [
    "GPTBot",
    "ChatGPT-User",
    "PerplexityBot",
    "ClaudeBot",
    "anthropic-ai",
    "Googlebot",
    "Bingbot",
    "facebookexternalhit",
]


async def run(url: str, context: dict = {}) -> dict:
    """
    Run SEO + GEO audit on a URL.

    Returns a structured audit report dict with:
    - technical: basic technical SEO findings
    - geo: GEO optimization findings
    - schema: recommended schema markup
    - meta: recommended meta tags
    - robots: robots.txt analysis
    - recommendations: prioritized action list
    - score: 0-100 overall score
    """
    if not url.startswith("http"):
        url = f"https://{url}"
    url = url.rstrip("/")

    deep = context.get("deep", False)
    keyword_focus = context.get("keyword_focus", "")
    competitors = context.get("competitors", [])
    client = _get_client(context.get("api_key", ""))

    report = {
        "url": url,
        "technical": {},
        "geo": {},
        "robots": {},
        "meta": {},
        "schema": {},
        "recommendations": [],
        "score": 0,
    }

    # Step 1: Fetch and parse the page
    page_data = await _fetch_page(url)
    if page_data.get("error"):
        report["error"] = page_data["error"]
        return report

    # Step 2: Technical SEO checks
    report["technical"] = _technical_checks(url, page_data)

    # Step 3: robots.txt analysis
    report["robots"] = await _check_robots(url)

    if deep:
        # Step 4: GEO analysis via Claude
        report["geo"] = await _geo_analysis(client, url, page_data, keyword_focus)

        # Step 5: Generate meta tag recommendations
        report["meta"] = await _generate_meta(client, url, page_data, keyword_focus)

        # Step 6: Generate schema markup
        report["schema"] = await _generate_schema(client, url, page_data)

    # Compile recommendations
    report["recommendations"] = _compile_recommendations(report)

    # Score
    report["score"] = _calculate_score(report)

    return report


async def _fetch_page(url: str) -> dict:
    """Fetch page HTML and extract key elements."""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "PressroomHQ/1.0 SEO Audit"})
            html = resp.text

        # Extract title
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        title = title_match.group(1).strip() if title_match else ""

        # Extract meta description
        desc_match = re.search(
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']',
            html, re.IGNORECASE
        ) or re.search(
            r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+name=["\']description["\']',
            html, re.IGNORECASE
        )
        description = desc_match.group(1).strip() if desc_match else ""

        # Extract H1s
        h1_matches = re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
        h1s = [re.sub(r"<[^>]+>", "", h).strip() for h in h1_matches]

        # Extract H2s
        h2_matches = re.findall(r"<h2[^>]*>(.*?)</h2>", html, re.IGNORECASE | re.DOTALL)
        h2s = [re.sub(r"<[^>]+>", "", h).strip() for h in h2_matches[:10]]

        # Extract body text (rough)
        body = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        body = re.sub(r"<style[^>]*>.*?</style>", "", body, flags=re.DOTALL | re.IGNORECASE)
        body_text = re.sub(r"<[^>]+>", " ", body)
        body_text = re.sub(r"\s+", " ", body_text).strip()
        word_count = len(body_text.split())

        # Check for Open Graph (handle both attribute orders: property before content, or content before property)
        og_title = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']*)["\']', html, re.IGNORECASE) \
            or re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+property=["\']og:title["\']', html, re.IGNORECASE)
        og_desc = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']*)["\']', html, re.IGNORECASE) \
            or re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+property=["\']og:description["\']', html, re.IGNORECASE)

        # Check for canonical (handle both attribute orders)
        canonical = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']*)["\']', html, re.IGNORECASE) \
            or re.search(r'<link[^>]+href=["\']([^"\']*)["\'][^>]+rel=["\']canonical["\']', html, re.IGNORECASE)

        # Check for schema markup
        has_schema = bool(re.search(r'application/ld\+json', html, re.IGNORECASE))

        return {
            "html": html[:50000],  # cap for Claude context
            "title": title,
            "description": description,
            "h1s": h1s,
            "h2s": h2s,
            "word_count": word_count,
            "body_text": body_text[:5000],  # excerpt for analysis
            "has_og_title": bool(og_title),
            "has_og_desc": bool(og_desc),
            "has_canonical": bool(canonical),
            "has_schema": has_schema,
        }
    except Exception as e:
        return {"error": f"Failed to fetch {url}: {str(e)}"}


def _technical_checks(url: str, page_data: dict) -> dict:
    """Run basic technical SEO checks."""
    issues = []
    passes = []

    title = page_data.get("title", "")
    description = page_data.get("description", "")
    h1s = page_data.get("h1s", [])
    word_count = page_data.get("word_count", 0)

    # Title checks
    if not title:
        issues.append({"severity": "P0", "check": "title", "issue": "Missing title tag"})
    elif len(title) > 60:
        issues.append({"severity": "P1", "check": "title", "issue": f"Title too long: {len(title)} chars (target: 50-60)", "value": title})
    elif len(title) < 30:
        issues.append({"severity": "P2", "check": "title", "issue": f"Title too short: {len(title)} chars", "value": title})
    else:
        passes.append(f"Title length OK: {len(title)} chars")

    # Description checks
    if not description:
        issues.append({"severity": "P0", "check": "description", "issue": "Missing meta description"})
    elif len(description) > 160:
        issues.append({"severity": "P1", "check": "description", "issue": f"Description too long: {len(description)} chars (target: 120-160)", "value": description})
    elif len(description) < 120:
        issues.append({"severity": "P2", "check": "description", "issue": f"Description too short: {len(description)} chars", "value": description})
    else:
        passes.append(f"Description length OK: {len(description)} chars")

    # H1 checks
    if not h1s:
        issues.append({"severity": "P0", "check": "h1", "issue": "Missing H1 tag"})
    elif len(h1s) > 1:
        issues.append({"severity": "P0", "check": "h1", "issue": f"Multiple H1 tags: {len(h1s)} found", "value": h1s})
    else:
        passes.append(f"Single H1: '{h1s[0][:60]}'")

    # Open Graph
    if not page_data.get("has_og_title"):
        issues.append({"severity": "P1", "check": "og", "issue": "Missing og:title"})
    if not page_data.get("has_og_desc"):
        issues.append({"severity": "P1", "check": "og", "issue": "Missing og:description"})

    # Canonical
    if not page_data.get("has_canonical"):
        issues.append({"severity": "P2", "check": "canonical", "issue": "Missing canonical tag"})

    # Schema
    if not page_data.get("has_schema"):
        issues.append({"severity": "P1", "check": "schema", "issue": "No JSON-LD schema markup detected"})
    else:
        passes.append("JSON-LD schema markup present")

    # Word count
    if word_count < 300:
        issues.append({"severity": "P1", "check": "content", "issue": f"Thin content: {word_count} words (target: 300+)"})
    else:
        passes.append(f"Content length OK: {word_count} words")

    return {
        "issues": issues,
        "passes": passes,
        "issue_count": len(issues),
        "title": title,
        "description": description,
        "h1s": h1s,
        "word_count": word_count,
    }


async def _check_robots(url: str) -> dict:
    """Fetch and analyze robots.txt."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(robots_url)
            if resp.status_code != 200:
                return {"found": False, "url": robots_url, "issues": ["robots.txt not found (404)"]}

            content = resp.text
            blocked_bots = []
            for bot in AI_BOTS:
                # Check if bot is explicitly disallowed
                if re.search(rf"User-agent:\s*{bot}.*?Disallow:\s*/", content, re.IGNORECASE | re.DOTALL):
                    blocked_bots.append(bot)

            has_sitemap = bool(re.search(r"Sitemap:", content, re.IGNORECASE))

            return {
                "found": True,
                "url": robots_url,
                "content": content[:2000],
                "blocked_bots": blocked_bots,
                "has_sitemap_reference": has_sitemap,
                "issues": [f"{bot} is blocked — will not be indexed by AI search" for bot in blocked_bots],
            }
    except Exception as e:
        return {"found": False, "url": robots_url, "issues": [f"Could not fetch robots.txt: {str(e)}"]}


async def _geo_analysis(client, url: str, page_data: dict, keyword_focus: str) -> dict:
    """Use Claude to analyze GEO optimization opportunities."""
    body_excerpt = page_data.get("body_text", "")[:3000]
    title = page_data.get("title", "")
    h1s = page_data.get("h1s", [])
    h2s = page_data.get("h2s", [])

    geo_methods_text = "\n".join([f"- {name}: {boost} — {desc}" for name, boost, desc in GEO_METHODS])

    prompt = f"""You are an expert in GEO (Generative Engine Optimization) — optimizing content to be cited by AI search engines like ChatGPT, Perplexity, and Claude.

Key principle: AI search engines don't rank pages — they CITE sources. Being cited is the new ranking #1.

Page being analyzed: {url}
Title: {title}
H1: {h1s[0] if h1s else "None"}
H2s: {", ".join(h2s[:5]) if h2s else "None"}
Keyword focus: {keyword_focus or "Not specified"}

Content excerpt:
{body_excerpt}

GEO optimization methods (Princeton-backed research):
{geo_methods_text}

Analyze this page for GEO optimization. For each method:
1. Assess current implementation (good/weak/missing)
2. Give a specific, actionable improvement recommendation

Also assess:
- Citability: Would an AI search engine cite this page as a source? Why/why not?
- FAQPage schema: What FAQ questions should be added for AI visibility?
- E-E-A-T signals: Experience, Expertise, Authoritativeness, Trustworthiness

Be specific. Don't be vague. Give exact copy suggestions where possible.

Return your analysis as a structured assessment."""

    response = await client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    await log_token_usage(None, "seo_geo_analyze", response)

    analysis_text = response.content[0].text

    return {
        "analysis": analysis_text,
        "methods_evaluated": [m[0] for m in GEO_METHODS],
        "keyword_focus": keyword_focus,
    }


async def _generate_meta(client, url: str, page_data: dict, keyword_focus: str) -> dict:
    """Generate optimized meta tag recommendations."""
    title = page_data.get("title", "")
    description = page_data.get("description", "")
    h1s = page_data.get("h1s", [])
    body_excerpt = page_data.get("body_text", "")[:2000]

    prompt = f"""Generate optimized meta tags for this page.

URL: {url}
Current title: {title}
Current description: {description}
H1: {h1s[0] if h1s else "None"}
Keyword focus: {keyword_focus or "Infer from content"}
Content excerpt: {body_excerpt}

Generate:
1. Optimized title (50-60 chars, primary keyword near front)
2. Optimized meta description (120-160 chars, action-oriented, includes keyword)
3. og:title (can match title or be slightly different)
4. og:description (can match description)
5. Twitter card title and description

Format as JSON with keys: title, description, og_title, og_description, twitter_title, twitter_description
Include current char counts and whether each passes length checks."""

    response = await client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    await log_token_usage(None, "seo_geo_meta", response)

    return {
        "recommendations": response.content[0].text,
        "current_title": title,
        "current_description": description,
    }


async def _generate_schema(client, url: str, page_data: dict) -> dict:
    """Generate JSON-LD schema markup recommendations."""
    title = page_data.get("title", "")
    description = page_data.get("description", "")
    body_excerpt = page_data.get("body_text", "")[:2000]
    has_schema = page_data.get("has_schema", False)

    prompt = f"""Generate JSON-LD schema markup for this page to maximize SEO and AI citation visibility.

URL: {url}
Title: {title}
Description: {description}
Content excerpt: {body_excerpt}
Currently has schema: {has_schema}

Generate appropriate JSON-LD schema. Consider:
1. WebPage or Article schema (required)
2. FAQPage schema if FAQ content exists or could be added (high GEO value)
3. Organization schema if this is a homepage/about page
4. BreadcrumbList if it's a deep page

For FAQPage: generate 3-5 FAQ questions and answers based on the content that AI search engines are likely to query.

Return valid JSON-LD wrapped in <script type="application/ld+json"> tags."""

    response = await client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )
    await log_token_usage(None, "seo_geo_schema", response)

    return {
        "markup": response.content[0].text,
        "had_existing_schema": has_schema,
    }


def _compile_recommendations(report: dict) -> list:
    """Compile prioritized recommendations from all checks."""
    recs = []

    # Technical issues
    for issue in report.get("technical", {}).get("issues", []):
        recs.append({
            "priority": issue["severity"],
            "category": "technical",
            "action": issue["issue"],
        })

    # Robots issues
    for issue in report.get("robots", {}).get("issues", []):
        recs.append({
            "priority": "P0",
            "category": "robots",
            "action": issue,
        })

    if not report.get("robots", {}).get("has_sitemap_reference"):
        recs.append({
            "priority": "P1",
            "category": "robots",
            "action": "Add Sitemap: reference to robots.txt",
        })

    # Sort by priority
    priority_order = {"P0": 0, "P1": 1, "P2": 2}
    recs.sort(key=lambda x: priority_order.get(x["priority"], 3))

    return recs


def _calculate_score(report: dict) -> int:
    """Calculate overall SEO score 0-100."""
    score = 100
    deductions = {"P0": 15, "P1": 8, "P2": 3}

    for rec in report.get("recommendations", []):
        score -= deductions.get(rec["priority"], 0)

    return max(0, min(100, score))
