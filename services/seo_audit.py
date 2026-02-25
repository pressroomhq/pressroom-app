"""SEO Audit — deep crawl with robots.txt, llms.txt, sitemap, PageSpeed, structured data, and GEO."""

import re
import json
import logging
from urllib.parse import urlparse, urljoin

import httpx
import anthropic
from config import settings
from services.token_tracker import log_token_usage

log = logging.getLogger("pressroom")

HEADERS = {"User-Agent": "Pressroom/0.1 (seo-audit)"}

PRIORITY_SCORE_IMPACT = {
    "critical": 15,
    "high": 8,
    "medium": 4,
    "low": 2,
}

AI_BOTS = [
    "GPTBot", "ChatGPT-User", "PerplexityBot", "ClaudeBot",
    "anthropic-ai", "Googlebot", "Bingbot", "facebookexternalhit",
]


def _get_client(api_key: str | None = None):
    return anthropic.Anthropic(api_key=api_key or settings.anthropic_api_key)


async def audit_domain(domain: str, max_pages: int = 20, api_key: str | None = None) -> dict:
    """Run a deep SEO audit on a domain. Returns page-level findings, sitewide checks,
    and structured action items with evidence."""
    if not domain.startswith("http"):
        domain = f"https://{domain}"
    domain = domain.rstrip("/")
    base_host = urlparse(domain).netloc

    pages = []
    sitewide = {}

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        # Run sitewide checks in parallel-ish: robots, llms.txt, sitemap, pagespeed
        sitewide["robots"] = await _check_robots(client, domain)
        sitewide["llms_txt"] = await _check_llms_txt(client, domain)
        sitewide["sitemap"] = await _check_sitemap(client, domain, sitewide["robots"])
        sitewide["pagespeed"] = await _check_pagespeed(domain)

        # Homepage first
        homepage_data = await _audit_page(client, domain)
        if homepage_data:
            pages.append(homepage_data)

        # Discover and crawl internal pages
        if homepage_data and homepage_data.get("_html"):
            links = _discover_internal_links(homepage_data["_html"], domain, base_host)
            for url in links[:max_pages - 1]:
                page_data = await _audit_page(client, url)
                if page_data:
                    pages.append(page_data)

    # Strip raw HTML before analysis
    for p in pages:
        p.pop("_html", None)

    # Claude analysis — builds structured action items with evidence
    recommendations = await _analyze_seo(pages, domain, sitewide, api_key=api_key)

    # Build action_items list from all sources
    action_items = _build_action_items(pages, sitewide, recommendations)

    return {
        "domain": domain,
        "pages_audited": len(pages),
        "pages": pages,
        "sitewide": sitewide,
        "recommendations": recommendations,
        "action_items": action_items,
    }


# ─────────────────────────────────────────────────────────────
# Sitewide checks
# ─────────────────────────────────────────────────────────────

async def _check_robots(client: httpx.AsyncClient, domain: str) -> dict:
    """Fetch and analyze robots.txt — check AI bot access and sitemap pointer."""
    url = f"{domain}/robots.txt"
    result = {
        "url": url,
        "found": False,
        "content": "",
        "blocked_bots": [],
        "allowed_bots": [],
        "has_sitemap_reference": False,
        "sitemap_url": "",
        "issues": [],
        "review": "",
    }
    try:
        resp = await client.get(url, headers=HEADERS)
        if resp.status_code == 200 and resp.text.strip():
            result["found"] = True
            result["content"] = resp.text[:5000]  # cap at 5k chars

            for bot in AI_BOTS:
                # Check for explicit Disallow of / after User-agent match
                pattern = rf'User-agent:\s*{re.escape(bot)}.*?(?=User-agent:|$)'
                m = re.search(pattern, resp.text, re.DOTALL | re.IGNORECASE)
                if m:
                    block = re.search(r'Disallow:\s*/', m.group(0), re.IGNORECASE)
                    if block:
                        result["blocked_bots"].append(bot)
                    else:
                        result["allowed_bots"].append(bot)

            sitemap_m = re.search(r'Sitemap:\s*(\S+)', resp.text, re.IGNORECASE)
            if sitemap_m:
                result["has_sitemap_reference"] = True
                result["sitemap_url"] = sitemap_m.group(1)

            if not result["has_sitemap_reference"]:
                result["issues"].append("No Sitemap: directive in robots.txt")

            if "GPTBot" in result["blocked_bots"] or "ClaudeBot" in result["blocked_bots"]:
                result["issues"].append("Major AI crawlers blocked — harms GEO visibility")
        else:
            result["issues"].append("robots.txt not found or empty")
    except Exception as e:
        result["issues"].append(f"robots.txt fetch failed: {e}")

    return result


async def _check_llms_txt(client: httpx.AsyncClient, domain: str) -> dict:
    """Fetch llms.txt — the emerging standard for AI-readable site summaries."""
    url = f"{domain}/llms.txt"
    result = {
        "url": url,
        "found": False,
        "content": "",
        "issues": [],
        "review": "",
    }
    try:
        resp = await client.get(url, headers=HEADERS)
        if resp.status_code == 200 and resp.text.strip():
            result["found"] = True
            result["content"] = resp.text[:8000]
        else:
            result["issues"].append(
                "llms.txt not found — this emerging standard helps AI engines understand your site. "
                "See llmstxt.org for the spec."
            )
    except Exception as e:
        result["issues"].append(f"llms.txt fetch failed: {e}")

    return result


async def _check_sitemap(client: httpx.AsyncClient, domain: str, robots: dict) -> dict:
    """Fetch and parse sitemap.xml — count pages, find stale entries."""
    result = {
        "found": False,
        "url": "",
        "page_count": 0,
        "issues": [],
    }

    # Try sitemap URL from robots.txt first, then default
    sitemap_url = robots.get("sitemap_url") or f"{domain}/sitemap.xml"
    result["url"] = sitemap_url

    try:
        resp = await client.get(sitemap_url, headers=HEADERS)
        if resp.status_code == 200:
            xml = resp.text
            result["found"] = True
            urls = re.findall(r'<loc>(.*?)</loc>', xml, re.IGNORECASE)
            result["page_count"] = len(urls)

            if result["page_count"] == 0:
                result["issues"].append("Sitemap found but contains no <loc> entries")
        else:
            result["issues"].append(f"Sitemap not found at {sitemap_url} (HTTP {resp.status_code})")
    except Exception as e:
        result["issues"].append(f"Sitemap fetch failed: {e}")

    return result


async def _check_pagespeed(domain: str) -> dict:
    """Call Google PageSpeed Insights API (no key required for basic usage)."""
    result = {
        "found": False,
        "mobile_score": None,
        "desktop_score": None,
        "lcp": None,
        "cls": None,
        "fid": None,
        "issues": [],
    }
    try:
        url = f"https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url={domain}&strategy=mobile"
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                cats = data.get("lighthouseResult", {}).get("categories", {})
                perf = cats.get("performance", {})
                result["mobile_score"] = int((perf.get("score", 0) or 0) * 100)
                result["found"] = True

                audits = data.get("lighthouseResult", {}).get("audits", {})
                lcp_data = audits.get("largest-contentful-paint", {})
                cls_data = audits.get("cumulative-layout-shift", {})
                fid_data = audits.get("max-potential-fid", {})

                result["lcp"] = lcp_data.get("displayValue", "")
                result["cls"] = cls_data.get("displayValue", "")
                result["fid"] = fid_data.get("displayValue", "")

                if result["mobile_score"] is not None and result["mobile_score"] < 50:
                    result["issues"].append(
                        f"Mobile performance score is {result['mobile_score']}/100 — "
                        "poor scores hurt rankings and user experience"
                    )
                elif result["mobile_score"] is not None and result["mobile_score"] < 75:
                    result["issues"].append(
                        f"Mobile performance score is {result['mobile_score']}/100 — room to improve"
                    )
    except Exception as e:
        result["issues"].append(f"PageSpeed check failed: {e}")

    return result


# ─────────────────────────────────────────────────────────────
# Per-page audit
# ─────────────────────────────────────────────────────────────

async def _audit_page(client: httpx.AsyncClient, url: str) -> dict | None:
    """Audit a single page — extract all SEO-relevant elements + structured data."""
    try:
        resp = await client.get(url, headers=HEADERS)
        if resp.status_code != 200:
            return None

        html = resp.text
        data = {
            "url": url,
            "status_code": resp.status_code,
            "_html": html,
        }

        # Meta title
        title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
        data["title"] = re.sub(r'\s+', ' ', title_match.group(1)).strip() if title_match else ""
        data["title_length"] = len(data["title"])

        # Meta description
        desc_match = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']', html, re.IGNORECASE)
        if not desc_match:
            desc_match = re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+name=["\']description["\']', html, re.IGNORECASE)
        data["meta_description"] = desc_match.group(1).strip() if desc_match else ""
        data["meta_description_length"] = len(data["meta_description"])

        # Canonical
        canonical_match = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']*)["\']', html, re.IGNORECASE)
        data["canonical"] = canonical_match.group(1) if canonical_match else ""

        # Open Graph
        og_title = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']*)["\']', html, re.IGNORECASE)
        og_desc = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']*)["\']', html, re.IGNORECASE)
        og_image = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']*)["\']', html, re.IGNORECASE)
        data["og_title"] = og_title.group(1) if og_title else ""
        data["og_desc"] = og_desc.group(1) if og_desc else ""
        data["og_image"] = bool(og_image)

        # Twitter Card
        twitter_card = re.search(r'<meta[^>]+name=["\']twitter:card["\'][^>]+content=["\']([^"\']*)["\']', html, re.IGNORECASE)
        data["twitter_card"] = twitter_card.group(1) if twitter_card else ""

        # Headings
        h1s = re.findall(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL | re.IGNORECASE)
        data["h1_count"] = len(h1s)
        data["h1_texts"] = [re.sub(r'<[^>]+>', '', h).strip()[:200] for h in h1s[:3]]

        h2s = re.findall(r'<h2[^>]*>(.*?)</h2>', html, re.DOTALL | re.IGNORECASE)
        data["h2_count"] = len(h2s)
        data["h2_texts"] = [re.sub(r'<[^>]+>', '', h).strip()[:200] for h in h2s[:8]]

        h3s = re.findall(r'<h3[^>]*>(.*?)</h3>', html, re.DOTALL | re.IGNORECASE)
        data["h3_count"] = len(h3s)

        # Images
        images = re.findall(r'<img[^>]*>', html, re.IGNORECASE)
        imgs_missing_alt = 0
        imgs_empty_alt = 0
        for img in images:
            if 'alt=' not in img.lower():
                imgs_missing_alt += 1
            elif re.search(r'alt=["\']["\']', img, re.IGNORECASE):
                imgs_empty_alt += 1
        data["total_images"] = len(images)
        data["images_missing_alt"] = imgs_missing_alt
        data["images_empty_alt"] = imgs_empty_alt

        # Links
        all_links = re.findall(r'<a[^>]+href=["\']([^"\'#]+)["\']', html, re.IGNORECASE)
        internal = 0
        external = 0
        for link in all_links:
            full = urljoin(url, link)
            parsed = urlparse(full)
            if parsed.netloc == urlparse(url).netloc:
                internal += 1
            elif parsed.scheme in ("http", "https"):
                external += 1
        data["internal_links"] = internal
        data["external_links"] = external

        # Word count
        text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        words = len(text.split())
        data["word_count"] = words

        # Structured data — parse and validate each JSON-LD block
        data["schema_blocks"] = _parse_structured_data(html)
        data["has_schema"] = len(data["schema_blocks"]) > 0

        # Viewport meta (mobile)
        data["has_viewport"] = bool(re.search(r'<meta[^>]+name=["\']viewport["\']', html, re.IGNORECASE))

        # Issues with evidence
        issues = []
        evidence = []

        if not data["title"]:
            issues.append("MISSING: Page title")
            evidence.append({"field": "title", "found": None, "expected": "50-60 chars", "context": "No <title> tag found"})
        elif data["title_length"] > 60:
            issues.append(f"LONG TITLE: {data['title_length']} chars (target: 50-60)")
            evidence.append({"field": "title", "found": data["title"], "found_length": data["title_length"], "expected": "50-60 chars"})
        elif data["title_length"] < 30:
            issues.append(f"SHORT TITLE: {data['title_length']} chars (target: 50-60)")
            evidence.append({"field": "title", "found": data["title"], "found_length": data["title_length"], "expected": "50-60 chars"})

        if not data["meta_description"]:
            issues.append("MISSING: Meta description")
            evidence.append({"field": "meta_description", "found": None, "expected": "120-160 chars"})
        elif data["meta_description_length"] > 160:
            issues.append(f"LONG META DESC: {data['meta_description_length']} chars (target: 120-160)")
            evidence.append({"field": "meta_description", "found": data["meta_description"][:120], "found_length": data["meta_description_length"], "expected": "120-160 chars"})
        elif data["meta_description_length"] < 70:
            issues.append(f"SHORT META DESC: {data['meta_description_length']} chars (target: 120-160)")
            evidence.append({"field": "meta_description", "found": data["meta_description"], "found_length": data["meta_description_length"], "expected": "120-160 chars"})

        if data["h1_count"] == 0:
            issues.append("MISSING: H1 tag")
            evidence.append({"field": "h1", "found": None, "expected": "Exactly one H1"})
        elif data["h1_count"] > 1:
            issues.append(f"MULTIPLE H1s: {data['h1_count']} found (should be 1)")
            evidence.append({"field": "h1", "found": data["h1_texts"], "expected": "Exactly one H1"})

        if data["images_missing_alt"] > 0:
            issues.append(f"IMAGES: {data['images_missing_alt']}/{data['total_images']} missing alt text")
            evidence.append({"field": "images_alt", "found": f"{data['images_missing_alt']} images without alt", "expected": "All images have descriptive alt text"})

        if not data["og_title"]:
            issues.append("MISSING: Open Graph title (og:title)")
            evidence.append({"field": "og_title", "found": None, "expected": "og:title meta tag"})
        if not data["og_image"]:
            issues.append("MISSING: Open Graph image (og:image)")
            evidence.append({"field": "og_image", "found": None, "expected": "og:image meta tag"})
        if not data["canonical"]:
            issues.append("MISSING: Canonical URL")
            evidence.append({"field": "canonical", "found": None, "expected": "<link rel='canonical'>"})
        if not data["has_schema"]:
            issues.append("MISSING: Schema.org structured data (JSON-LD)")
            evidence.append({"field": "schema", "found": None, "expected": "JSON-LD structured data block"})
        if not data["has_viewport"]:
            issues.append("MISSING: Viewport meta tag (mobile-unfriendly)")
            evidence.append({"field": "viewport", "found": None, "expected": "<meta name='viewport' content='width=device-width, initial-scale=1'>"})

        if data["word_count"] < 300 and "/blog" in url.lower():
            issues.append(f"THIN CONTENT: {data['word_count']} words (target: 800+ for blog)")
            evidence.append({"field": "word_count", "found": data["word_count"], "expected": "800+ words for blog content"})

        # Structured data validation issues
        for block_issue in _validate_schema_blocks(data["schema_blocks"], url):
            issues.append(block_issue["label"])
            evidence.append(block_issue["evidence"])

        data["issues"] = issues
        data["evidence"] = evidence
        data["issue_count"] = len(issues)

        return data

    except Exception as e:
        log.warning("SEO audit failed for %s: %s", url, e)
        return None


def _parse_structured_data(html: str) -> list[dict]:
    """Extract and parse all JSON-LD blocks from the page."""
    blocks = []
    scripts = re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                         html, re.DOTALL | re.IGNORECASE)
    for raw in scripts:
        try:
            data = json.loads(raw.strip())
            schema_type = data.get("@type", "Unknown") if isinstance(data, dict) else "Array"
            blocks.append({"type": schema_type, "data": data, "parse_error": None})
        except json.JSONDecodeError as e:
            blocks.append({"type": "ParseError", "data": None, "parse_error": str(e)})
    return blocks


def _validate_schema_blocks(blocks: list[dict], url: str) -> list[dict]:
    """Check each schema block for required fields per type."""
    issues = []
    REQUIRED_FIELDS = {
        "Article": ["headline", "author", "datePublished"],
        "BlogPosting": ["headline", "author", "datePublished"],
        "Product": ["name", "description"],
        "FAQPage": ["mainEntity"],
        "Organization": ["name", "url"],
        "WebPage": ["name"],
        "BreadcrumbList": ["itemListElement"],
        "HowTo": ["name", "step"],
        "LocalBusiness": ["name", "address"],
    }
    for block in blocks:
        if block.get("parse_error"):
            issues.append({
                "label": f"SCHEMA ERROR: JSON-LD block failed to parse — {block['parse_error'][:100]}",
                "evidence": {"field": "schema_parse", "url": url, "error": block["parse_error"]},
            })
            continue
        data = block.get("data")
        schema_type = block.get("type", "")
        required = REQUIRED_FIELDS.get(schema_type, [])
        if isinstance(data, dict):
            for field in required:
                if field not in data or not data[field]:
                    issues.append({
                        "label": f"SCHEMA: {schema_type} missing required field '{field}'",
                        "evidence": {"field": "schema_field", "schema_type": schema_type, "missing_field": field, "url": url},
                    })
    return issues


def _discover_internal_links(html: str, base_url: str, base_host: str) -> list[str]:
    """Find internal page URLs from HTML for further auditing."""
    hrefs = re.findall(r'<a[^>]+href=["\']([^"\'#]+)["\']', html, re.IGNORECASE)
    seen = set()
    urls = []

    for href in hrefs:
        url = urljoin(base_url, href)
        parsed = urlparse(url)

        if parsed.netloc != base_host:
            continue

        path = parsed.path.rstrip("/")
        if any(path.endswith(ext) for ext in (".png", ".jpg", ".svg", ".css", ".js", ".xml", ".pdf")):
            continue
        skip = ["login", "signup", "register", "cart", "checkout", "account",
                "privacy", "terms", "cookie", "legal"]
        if any(s in path.lower() for s in skip):
            continue

        clean_url = f"{parsed.scheme}://{parsed.netloc}{path}"
        if clean_url in seen or clean_url == base_url:
            continue

        seen.add(clean_url)
        urls.append(clean_url)

    return urls


# ─────────────────────────────────────────────────────────────
# Claude analysis
# ─────────────────────────────────────────────────────────────

async def _analyze_seo(pages: list[dict], domain: str, sitewide: dict, api_key: str | None = None) -> dict:
    """Claude analyzes everything — pages, robots, llms.txt, sitemap, PageSpeed — and returns structured action items."""
    summary_parts = [f"SEO AUDIT RESULTS FOR {domain}\n{len(pages)} pages crawled.\n"]

    # Sitewide section
    robots = sitewide.get("robots", {})
    llms = sitewide.get("llms_txt", {})
    sitemap = sitewide.get("sitemap", {})
    pagespeed = sitewide.get("pagespeed", {})

    summary_parts.append("\n=== SITEWIDE CHECKS ===")
    summary_parts.append(f"robots.txt: {'FOUND' if robots.get('found') else 'MISSING'}")
    if robots.get("found"):
        if robots.get("blocked_bots"):
            summary_parts.append(f"  AI bots BLOCKED: {', '.join(robots['blocked_bots'])}")
        if robots.get("allowed_bots"):
            summary_parts.append(f"  AI bots allowed: {', '.join(robots['allowed_bots'])}")
        summary_parts.append(f"  Sitemap referenced: {'Yes' if robots.get('has_sitemap_reference') else 'No'}")
        if robots.get("content"):
            summary_parts.append(f"  Content:\n{robots['content'][:1500]}")

    summary_parts.append(f"\nllms.txt: {'FOUND' if llms.get('found') else 'MISSING'}")
    if llms.get("found") and llms.get("content"):
        summary_parts.append(f"  Content:\n{llms['content'][:2000]}")

    summary_parts.append(f"\nSitemap: {'FOUND' if sitemap.get('found') else 'MISSING'} — {sitemap.get('page_count', 0)} URLs")

    if pagespeed.get("found"):
        summary_parts.append(f"\nPageSpeed (mobile): {pagespeed.get('mobile_score')}/100")
        if pagespeed.get("lcp"):
            summary_parts.append(f"  LCP: {pagespeed['lcp']} | CLS: {pagespeed.get('cls', 'N/A')} | FID: {pagespeed.get('fid', 'N/A')}")

    # Per-page summary
    total_issues = 0
    summary_parts.append("\n=== PAGE-LEVEL FINDINGS ===")
    for p in pages:
        issues = p.get("issues", [])
        total_issues += len(issues)
        summary_parts.append(f"\n--- {p['url']} ---")
        summary_parts.append(f"Title ({p.get('title_length', 0)} chars): {p.get('title', 'MISSING')}")
        summary_parts.append(f"Meta desc ({p.get('meta_description_length', 0)} chars): {p.get('meta_description', 'MISSING')[:100]}")
        summary_parts.append(f"H1s: {p.get('h1_count', 0)} | H2s: {p.get('h2_count', 0)} | H3s: {p.get('h3_count', 0)} | Words: {p.get('word_count', 0)}")
        summary_parts.append(f"Images: {p.get('total_images', 0)} total, {p.get('images_missing_alt', 0)} missing alt")
        summary_parts.append(f"Schema: {'Yes' if p.get('has_schema') else 'No'} | Canonical: {'Yes' if p.get('canonical') else 'No'} | OG Image: {'Yes' if p.get('og_image') else 'No'} | Viewport: {'Yes' if p.get('has_viewport') else 'No'}")
        if p.get("schema_blocks"):
            for b in p["schema_blocks"]:
                summary_parts.append(f"  Schema type: {b.get('type')}")
        if issues:
            summary_parts.append(f"Issues: {'; '.join(issues[:8])}")

    summary_parts.append(f"\nTOTAL PAGE ISSUES: {total_issues} across {len(pages)} pages")

    try:
        response = _get_client(api_key).messages.create(
            model=settings.claude_model_fast,
            max_tokens=3000,
            system="""You are a senior SEO and GEO (Generative Engine Optimization) specialist.
You have been given a full technical audit of a website. Produce a structured analysis in this EXACT format:

SCORE: [0-100] — [one-line justification]

CRITICAL:
- [specific actionable fix with URL and exact instruction]

QUICK WINS:
- [easy improvement, specific URL, what to change]

CONTENT GAPS:
- [missing content type or topic with SEO rationale]

TECHNICAL:
- [technical fix with specific location/URL]

GEO:
- [Generative Engine Optimization finding — how AI engines will handle this content]

ROBOTS_REVIEW:
- [assessment of robots.txt configuration and its impact on crawlability and AI visibility]

LLMS_REVIEW:
- [assessment of llms.txt: if missing, explain what it is and why to add it; if present, review quality]

Rules:
- Every item must be specific and actionable
- Reference actual URLs and actual values where possible
- GEO section should evaluate AI citation potential, E-E-A-T signals, structured data for AI parsing
- If robots.txt blocks major AI bots, flag this as critical
- If llms.txt is missing, explain clearly why it matters for AI discoverability""",
            messages=[{"role": "user", "content": "\n".join(summary_parts)}],
        )

        await log_token_usage(None, "seo_audit", response)
        analysis_text = response.content[0].text

        score = 0
        score_match = re.search(r'SCORE:\s*(\d+)', analysis_text)
        if score_match:
            score = min(100, max(0, int(score_match.group(1))))

        def _extract_section(text, header):
            pattern = rf'{header}:\s*\n((?:[ \t]*[-•]\s*.+\n?)+)'
            m = re.search(pattern, text, re.IGNORECASE)
            if not m:
                return []
            items = re.findall(r'[-•]\s*(.+)', m.group(1))
            return [i.strip() for i in items if i.strip()]

        score_line = ""
        score_line_match = re.search(r'SCORE:\s*.+', analysis_text)
        if score_line_match:
            score_line = score_line_match.group(0).replace('SCORE:', '').strip()

        return {
            "score": score,
            "score_summary": score_line,
            "total_issues": total_issues,
            "critical": _extract_section(analysis_text, "CRITICAL"),
            "quick_wins": _extract_section(analysis_text, "QUICK WINS"),
            "content_gaps": _extract_section(analysis_text, "CONTENT GAPS"),
            "technical": _extract_section(analysis_text, "TECHNICAL"),
            "geo": _extract_section(analysis_text, "GEO"),
            "robots_review": _extract_section(analysis_text, "ROBOTS_REVIEW"),
            "llms_review": _extract_section(analysis_text, "LLMS_REVIEW"),
            "analysis": analysis_text,
        }

    except Exception as e:
        log.error("SEO analysis failed: %s", e)
        return {
            "score": 0, "score_summary": "", "total_issues": total_issues,
            "critical": [], "quick_wins": [], "content_gaps": [], "technical": [],
            "geo": [], "robots_review": [], "llms_review": [],
            "analysis": f"Analysis failed: {str(e)}",
        }


# ─────────────────────────────────────────────────────────────
# Action item builder
# ─────────────────────────────────────────────────────────────

def _build_action_items(pages: list[dict], sitewide: dict, recommendations: dict) -> list[dict]:
    """Convert all findings into structured action items with evidence for persistence."""
    items = []

    SECTION_META = {
        "critical":     {"priority": "critical", "category": "on-page"},
        "quick_wins":   {"priority": "high",     "category": "on-page"},
        "content_gaps": {"priority": "medium",   "category": "content"},
        "technical":    {"priority": "high",     "category": "technical"},
        "geo":          {"priority": "medium",   "category": "geo"},
        "robots_review":{"priority": "high",     "category": "robots"},
        "llms_review":  {"priority": "medium",   "category": "llms"},
    }

    for section, meta in SECTION_META.items():
        for text in recommendations.get(section, []):
            items.append({
                "priority": meta["priority"],
                "category": meta["category"],
                "title": text[:500],
                "evidence": {
                    "source": "claude_analysis",
                    "section": section,
                    "full_text": text,
                },
                "fix_instructions": text,
                "score_impact": PRIORITY_SCORE_IMPACT.get(meta["priority"], 4),
            })

    # Sitewide findings
    robots = sitewide.get("robots", {})
    if not robots.get("found"):
        items.append({
            "priority": "high",
            "category": "technical",
            "title": "robots.txt is missing",
            "evidence": {"source": "robots_check", "url": robots.get("url"), "found": False},
            "fix_instructions": "Create /robots.txt at your domain root. Include User-agent: * Allow: / and a Sitemap: directive pointing to your sitemap.xml.",
            "score_impact": 6,
        })
    elif robots.get("blocked_bots"):
        items.append({
            "priority": "critical",
            "category": "geo",
            "title": f"robots.txt blocks AI crawlers: {', '.join(robots['blocked_bots'])}",
            "evidence": {
                "source": "robots_check",
                "url": robots.get("url"),
                "blocked_bots": robots["blocked_bots"],
                "robots_content": robots.get("content", "")[:500],
            },
            "fix_instructions": (
                "Remove Disallow rules for AI crawlers. "
                "Blocking GPTBot, ClaudeBot, and PerplexityBot prevents your content from appearing in AI-generated answers. "
                "Add explicit Allow: / rules for these bots."
            ),
            "score_impact": 15,
        })

    llms = sitewide.get("llms_txt", {})
    if not llms.get("found"):
        items.append({
            "priority": "medium",
            "category": "geo",
            "title": "llms.txt is missing — AI engines cannot easily understand your site",
            "evidence": {"source": "llms_check", "url": llms.get("url"), "found": False},
            "fix_instructions": (
                "Create /llms.txt at your domain root following the llmstxt.org specification. "
                "It should include: company description, key product information, important pages with descriptions, "
                "and contact/support links. This file is read by AI engines to understand your site for use in answers."
            ),
            "score_impact": 8,
        })

    sitemap = sitewide.get("sitemap", {})
    if not sitemap.get("found"):
        items.append({
            "priority": "high",
            "category": "technical",
            "title": "sitemap.xml is missing or inaccessible",
            "evidence": {"source": "sitemap_check", "url": sitemap.get("url"), "found": False},
            "fix_instructions": "Generate a sitemap.xml and submit it to Google Search Console and Bing Webmaster Tools. Reference it in robots.txt with 'Sitemap: https://yourdomain.com/sitemap.xml'.",
            "score_impact": 8,
        })

    pagespeed = sitewide.get("pagespeed", {})
    if pagespeed.get("found") and pagespeed.get("mobile_score") is not None:
        score = pagespeed["mobile_score"]
        if score < 50:
            items.append({
                "priority": "critical",
                "category": "performance",
                "title": f"Mobile PageSpeed score is {score}/100 — critical performance issue",
                "evidence": {
                    "source": "pagespeed",
                    "mobile_score": score,
                    "lcp": pagespeed.get("lcp"),
                    "cls": pagespeed.get("cls"),
                    "fid": pagespeed.get("fid"),
                },
                "fix_instructions": (
                    f"Mobile score: {score}/100. "
                    f"LCP: {pagespeed.get('lcp', 'N/A')}, CLS: {pagespeed.get('cls', 'N/A')}. "
                    "Run a full PageSpeed Insights audit at pagespeed.web.dev to see specific opportunities. "
                    "Common fixes: optimize images (WebP, lazy load), reduce JavaScript, use a CDN."
                ),
                "score_impact": 12,
            })
        elif score < 75:
            items.append({
                "priority": "medium",
                "category": "performance",
                "title": f"Mobile PageSpeed score is {score}/100 — improvement needed",
                "evidence": {
                    "source": "pagespeed",
                    "mobile_score": score,
                    "lcp": pagespeed.get("lcp"),
                    "cls": pagespeed.get("cls"),
                },
                "fix_instructions": (
                    f"Mobile score: {score}/100. Review pagespeed.web.dev for specific opportunities. "
                    "Focus on image optimization and render-blocking resources."
                ),
                "score_impact": 6,
            })

    # Per-page action items (homepage issues get highest priority)
    for i, page in enumerate(pages):
        is_homepage = i == 0
        for j, issue in enumerate(page.get("issues", [])):
            evidence_data = {}
            if j < len(page.get("evidence", [])):
                evidence_data = page["evidence"][j]
            evidence_data["url"] = page["url"]
            evidence_data["source"] = "page_crawl"

            priority = "critical" if is_homepage and "MISSING" in issue else \
                       "high" if is_homepage else \
                       "medium" if "MISSING" in issue else "low"

            items.append({
                "priority": priority,
                "category": "on-page",
                "title": f"{issue} — {page['url']}",
                "evidence": evidence_data,
                "fix_instructions": _fix_instruction_for_issue(issue, page),
                "score_impact": PRIORITY_SCORE_IMPACT.get(priority, 4),
            })

    return items


def _fix_instruction_for_issue(issue: str, page: dict) -> str:
    """Map a raw issue string to a human-readable fix instruction."""
    url = page.get("url", "")
    if "MISSING: Page title" in issue:
        return f"Add a <title> tag to {url}. Aim for 50-60 characters that include your primary keyword near the front."
    if "LONG TITLE" in issue:
        return f"Shorten the title on {url} to 50-60 characters. Current: '{page.get('title', '')[:80]}'"
    if "SHORT TITLE" in issue:
        return f"Expand the title on {url} to 50-60 characters. Current: '{page.get('title', '')}'"
    if "MISSING: Meta description" in issue:
        return f"Add <meta name='description' content='...'> to {url}. Target 120-160 characters summarizing the page for search results."
    if "LONG META DESC" in issue:
        return f"Shorten the meta description on {url} to 120-160 characters. Search engines truncate longer descriptions."
    if "MISSING: H1" in issue:
        return f"Add a single H1 tag to {url} containing your primary keyword. The H1 should summarize what the page is about."
    if "MULTIPLE H1" in issue:
        return f"Reduce to one H1 on {url}. Currently has {page.get('h1_count', '?')}. Keep the most descriptive one, convert others to H2."
    if "IMAGES" in issue and "alt text" in issue:
        return f"Add descriptive alt text to all images on {url}. Alt text must describe the image content, not be empty or generic."
    if "Open Graph title" in issue:
        return f"Add <meta property='og:title' content='...'> to {url}. Controls how the page appears when shared on LinkedIn, Twitter, etc."
    if "Open Graph image" in issue:
        return f"Add <meta property='og:image' content='...'> to {url}. Use a 1200x630px image. Critical for social sharing appearance."
    if "Canonical" in issue:
        return f"Add <link rel='canonical' href='{url}'> to {url}. Prevents duplicate content issues."
    if "Schema.org" in issue:
        return f"Add JSON-LD structured data to {url}. Minimum: WebPage or Article schema. Use schema.org for reference."
    if "Viewport" in issue:
        return f"Add <meta name='viewport' content='width=device-width, initial-scale=1'> to the <head> of {url}."
    if "THIN CONTENT" in issue:
        wc = page.get("word_count", 0)
        return f"Expand content on {url} from {wc} words to 800+. Thin blog content rarely ranks. Add examples, data, or expert commentary."
    return issue
