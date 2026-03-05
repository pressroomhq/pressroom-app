"""SEO Audit — deep crawl with robots.txt, llms.txt, sitemap, PageSpeed, structured data, GEO,
redirect chains, broken links, security headers, content freshness, E-E-A-T, and orphan detection."""

import re
import json
import logging
import asyncio
from urllib.parse import urlparse, urljoin
from email.utils import parsedate_to_datetime

import httpx

log = logging.getLogger("pressroom")

HEADERS = {"User-Agent": "Pressroom/0.1 (seo-audit)"}

# ─────────────────────────────────────────────────────────────
# Platform detection — adjust audit behavior for known CMS types
# ─────────────────────────────────────────────────────────────

# MediaWiki URL path segments that are internal/special and should not be
# treated as content pages or counted as broken links.
_MEDIAWIKI_SKIP_PATHS = (
    "/Special:", "/MediaWiki:", "/Template:", "/Category:",
    "/User:", "/Talk:", "/Help:", "/File:",
)


def _detect_platform(html: str) -> dict:
    """Detect the CMS/platform powering a site from HTML fingerprints.

    Returns a dict with:
      platform: "mediawiki" | "wordpress" | "unknown"
      version: str | None
      site_suffix: str | None   (e.g. " - DreamFactory Wiki (Staging)")
    """
    info: dict = {"platform": "unknown", "version": None, "site_suffix": None}

    # MediaWiki: <meta name="generator" content="MediaWiki 1.x.y">
    mw = re.search(
        r'<meta\s+name=["\']generator["\'][^>]+content=["\']MediaWiki\s+([\d.]+)["\']',
        html, re.IGNORECASE,
    )
    if mw:
        info["platform"] = "mediawiki"
        info["version"] = mw.group(1)
        # Extract site suffix from <title> — MW appends " - SiteName" to every page
        title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
        if title_match:
            title = re.sub(r'\s+', ' ', title_match.group(1)).strip()
            # MW titles are "PageTitle - SiteName"; find the suffix pattern
            dash_idx = title.rfind(" - ")
            if dash_idx > 0:
                info["site_suffix"] = title[dash_idx:]
        return info

    # WordPress: <meta name="generator" content="WordPress x.y.z">
    wp = re.search(
        r'<meta\s+name=["\']generator["\'][^>]+content=["\']WordPress\s+([\d.]+)["\']',
        html, re.IGNORECASE,
    )
    if wp:
        info["platform"] = "wordpress"
        info["version"] = wp.group(1)
        return info

    return info


PRIORITY_SCORE_IMPACT = {
    "critical": 15,
    "high": 8,
    "medium": 4,
    "low": 2,
}

# ─────────────────────────────────────────────────────────────
# Deterministic scoring
# ─────────────────────────────────────────────────────────────

def _compute_score(pages: list[dict], sitewide: dict) -> tuple[int, list[str]]:
    """Compute a deterministic SEO score from audit data.

    Starts at 100, applies deductions based on actual findings.
    Claude's qualitative score is ignored — this is the authoritative number.

    Returns (score, reasons) where reasons explains the main deductions.
    """
    score = 100
    reasons = []

    platform = sitewide.get("platform", {})
    _is_mw = platform.get("platform") == "mediawiki" if platform else False

    robots = sitewide.get("robots", {})
    llms = sitewide.get("llms_txt", {})
    sitemap = sitewide.get("sitemap", {})
    pagespeed = sitewide.get("pagespeed", {})

    # ── Sitewide deductions (one-time, not per-page) ──

    if not robots.get("found"):
        score -= 6
        reasons.append("robots.txt missing (-6)")
    elif robots.get("blocked_bots"):
        score -= 15
        reasons.append(f"AI bots blocked in robots.txt: {', '.join(robots['blocked_bots'])} (-15)")

    if not sitemap.get("found"):
        score -= 8
        reasons.append("sitemap.xml missing (-8)")

    if not llms.get("found"):
        score -= 5
        reasons.append("llms.txt missing (-5)")

    ps_score = pagespeed.get("mobile_score")
    if ps_score is not None:
        if ps_score < 50:
            score -= 12
            reasons.append(f"mobile PageSpeed {ps_score}/100 — critical (-12)")
        elif ps_score < 75:
            score -= 6
            reasons.append(f"mobile PageSpeed {ps_score}/100 — needs work (-6)")

    # ── Homepage-specific deductions (higher weight) ──

    homepage = pages[0] if pages else {}
    hp_issues = homepage.get("issues", [])

    # Schema.org — MediaWiki doesn't emit JSON-LD natively; WikiSEO provides OG tags.
    # Reduced penalty for MW sites (OG is partial structured data).
    if not homepage.get("has_schema"):
        if _is_mw:
            score -= 3
            reasons.append("homepage missing JSON-LD (MediaWiki — WikiSEO OG tags used instead) (-3)")
        else:
            score -= 8
            reasons.append("homepage missing Schema.org structured data (-8)")
    if not homepage.get("canonical"):
        score -= 5
        reasons.append("homepage missing canonical URL (-5)")
    if not homepage.get("og_image"):
        score -= 3
        reasons.append("homepage missing og:image (-3)")
    if not homepage.get("title"):
        score -= 8
        reasons.append("homepage missing title tag (-8)")
    if not homepage.get("meta_description"):
        score -= 6
        reasons.append("homepage missing meta description (-6)")

    # ── New checks ──

    # Redirect chains
    redirect_chains = sitewide.get("redirect_chains", [])
    if redirect_chains:
        score -= min(len(redirect_chains) * 2, 8)
        reasons.append(f"{len(redirect_chains)} redirect chain(s) detected (-{min(len(redirect_chains)*2,8)})")

    # Broken internal links
    broken_links = sitewide.get("broken_links", [])
    if broken_links:
        score -= min(len(broken_links) * 3, 12)
        reasons.append(f"{len(broken_links)} broken internal link(s) (-{min(len(broken_links)*3,12)})")

    # Security headers
    sec = sitewide.get("security_headers", {})
    missing_headers = [h for h, present in sec.items() if not present]
    if len(missing_headers) >= 2:
        score -= 4
        reasons.append(f"security headers missing: {', '.join(missing_headers)} (-4)")

    # Content freshness
    freshness = sitewide.get("freshness", {})
    if freshness.get("stale"):
        score -= 4
        reasons.append(f"content stale — last modified {freshness.get('last_modified_display', 'unknown')} (-4)")

    # E-E-A-T — MediaWiki tracks authorship via edit history, not bylines/author schema.
    # Don't penalize wikis for missing bylines or author schema.
    eeat = sitewide.get("eeat", {})
    eeat_missing = [k for k, v in eeat.items() if not v]
    if _is_mw:
        eeat_missing = [k for k in eeat_missing if k not in ("byline_present", "author_schema")]
    if len(eeat_missing) >= 3:
        score -= 6
        reasons.append(f"weak E-E-A-T signals — missing {', '.join(eeat_missing[:3])} (-6)")
    elif len(eeat_missing) >= 1:
        score -= 3
        reasons.append(f"E-E-A-T gaps: {', '.join(eeat_missing)} (-3)")

    # Orphaned pages
    orphans = sitewide.get("orphaned_pages", [])
    if orphans:
        score -= min(len(orphans) * 2, 6)
        reasons.append(f"{len(orphans)} orphaned page(s) with no inbound links (-{min(len(orphans)*2,6)})")

    # ── Per-page issue deductions (capped to avoid runaway scores) ──

    critical_count = 0
    high_count = 0
    medium_count = 0
    low_count = 0

    for i, page in enumerate(pages):
        is_homepage = (i == 0)
        for issue in page.get("issues", []):
            # Already handled homepage-specific structural ones above
            if is_homepage and any(x in issue for x in [
                "Schema.org", "Canonical", "og:image", "MISSING: Page title", "MISSING: Meta desc"
            ]):
                continue

            if is_homepage and "MISSING" in issue:
                critical_count += 1
            elif is_homepage:
                high_count += 1
            elif "MISSING" in issue:
                medium_count += 1
            else:
                low_count += 1

    # Apply capped deductions
    score -= min(critical_count * 6, 18)
    score -= min(high_count * 3, 12)
    score -= min(medium_count * 2, 16)
    score -= min(low_count * 1, 8)

    if critical_count:
        reasons.append(f"{critical_count} critical page issues (-{min(critical_count * 6, 18)})")
    if high_count:
        reasons.append(f"{high_count} high page issues (-{min(high_count * 3, 12)})")
    if medium_count:
        reasons.append(f"{medium_count} medium page issues (-{min(medium_count * 2, 16)})")

    score = max(0, min(100, score))
    return score, reasons

AI_BOTS = [
    "GPTBot", "ChatGPT-User", "OAI-SearchBot",
    "PerplexityBot", "ClaudeBot", "anthropic-ai",
    "Google-Extended",  # Google's AI training crawler — distinct from Googlebot
]


async def audit_domain(domain: str, max_pages: int = 20, api_key: str | None = None) -> dict:
    """Run a deep SEO audit on a domain. Returns page-level findings, sitewide checks,
    and structured action items with evidence."""
    if not domain.startswith("http"):
        domain = f"https://{domain}"
    domain = domain.rstrip("/")
    base_host = urlparse(domain).netloc

    pages = []
    sitewide = {}
    # track all internal links found during crawl for orphan detection
    _all_internal_hrefs: set[str] = set()
    _crawled_urls: set[str] = set()

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        # Sitewide checks — run in parallel
        robots_task = asyncio.create_task(_check_robots(client, domain))
        llms_task = asyncio.create_task(_check_llms_txt(client, domain))
        pagespeed_task = asyncio.create_task(_check_pagespeed(domain))
        sec_task = asyncio.create_task(_check_security_headers(client, domain))
        freshness_task = asyncio.create_task(_check_content_freshness(client, domain))

        sitewide["robots"] = await robots_task
        sitewide["llms_txt"] = await llms_task
        sitewide["sitemap"] = await _check_sitemap(client, domain, sitewide["robots"])
        sitewide["pagespeed"] = await pagespeed_task
        sitewide["security_headers"] = await sec_task
        sitewide["freshness"] = await freshness_task

        # Homepage first
        homepage_data = await _audit_page(client, domain)
        if homepage_data:
            pages.append(homepage_data)
            _crawled_urls.add(domain)

        # Detect CMS platform from homepage HTML (adjusts audit behavior)
        hp_html_for_detect = homepage_data.get("_html", "") if homepage_data else ""
        platform = _detect_platform(hp_html_for_detect)
        sitewide["platform"] = platform
        is_mediawiki = platform["platform"] == "mediawiki"

        # Discover and crawl internal pages, tracking redirect chains
        redirect_chains = []
        if homepage_data and homepage_data.get("_html"):
            links = _discover_internal_links(homepage_data["_html"], domain, base_host,
                                             is_mediawiki=is_mediawiki)
            _all_internal_hrefs.update(links)
            for url in links[:max_pages - 1]:
                # Check for redirect chains before full audit
                chain = await _check_redirect_chain(client, url)
                if chain and len(chain) > 2:
                    redirect_chains.append({"url": url, "chain": chain, "hops": len(chain) - 1})
                page_data = await _audit_page(client, url, platform=platform)
                if page_data:
                    pages.append(page_data)
                    _crawled_urls.add(url)
                    # Collect outbound internal hrefs from this page too
                    if page_data.get("_html"):
                        sub_links = _discover_internal_links(page_data["_html"], domain, base_host,
                                                             is_mediawiki=is_mediawiki)
                        _all_internal_hrefs.update(sub_links)

        sitewide["redirect_chains"] = redirect_chains

        # Broken internal links — HEAD-check a sample of discovered links not yet crawled
        # For MediaWiki, filter out Special:/Category:/etc. URLs before checking
        uncrawled = list(_all_internal_hrefs - _crawled_urls)[:30]
        if is_mediawiki:
            uncrawled = [u for u in uncrawled
                         if not any(seg in urlparse(u).path for seg in _MEDIAWIKI_SKIP_PATHS)
                         and "action=" not in u and "oldid=" not in u]
        broken = await _check_broken_links(client, uncrawled)
        sitewide["broken_links"] = broken

        # E-E-A-T signals from homepage HTML
        hp_html = homepage_data.get("_html", "") if homepage_data else ""
        sitewide["eeat"] = _check_eeat(hp_html, pages)

        # Orphaned pages — crawled pages with no inbound internal links from other pages
        inbound: dict[str, int] = {}
        for page in pages:
            ph = page.get("_html", "")
            if not ph:
                continue
            for href in _discover_internal_links(ph, domain, base_host):
                clean = href.rstrip("/")
                inbound[clean] = inbound.get(clean, 0) + 1
        orphans = [p["url"] for p in pages[1:] if p["url"].rstrip("/") not in inbound]
        sitewide["orphaned_pages"] = orphans

    # Strip raw HTML before analysis
    for p in pages:
        p.pop("_html", None)

    # Deterministic score — computed from data, not Claude's opinion
    computed_score, score_reasons = _compute_score(pages, sitewide)

    # Programmatic analysis — compiled from deterministic findings, no Claude
    recommendations = _compile_analysis(pages, domain, sitewide, platform=platform)

    recommendations["score"] = computed_score
    recommendations["score_reasons"] = score_reasons
    recommendations["score_summary"] = f"{computed_score}/100 — " + "; ".join(score_reasons[:3])

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
                    # Only flag as blocked if root (/) is disallowed, not just a sub-path
                    block = re.search(r'Disallow:\s*/\s*$', m.group(0), re.IGNORECASE | re.MULTILINE)
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
        "inp": None,
        "ttfb": None,
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
                inp_data = audits.get("interaction-to-next-paint", {})  # INP replaced FID March 2024
                ttfb_data = audits.get("server-response-time", {})

                result["lcp"] = lcp_data.get("displayValue", "")
                result["cls"] = cls_data.get("displayValue", "")
                result["inp"] = inp_data.get("displayValue", "")
                result["ttfb"] = ttfb_data.get("displayValue", "")

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


async def _check_security_headers(client: httpx.AsyncClient, domain: str) -> dict:
    """Check for important security headers that also signal site quality to crawlers."""
    target_headers = {
        "strict-transport-security": False,
        "x-content-type-options": False,
        "x-frame-options": False,
    }
    try:
        resp = await client.head(domain, headers=HEADERS)
        for header in target_headers:
            if header in {k.lower() for k in resp.headers}:
                target_headers[header] = True
    except Exception:
        pass
    return target_headers


async def _check_content_freshness(client: httpx.AsyncClient, domain: str) -> dict:
    """Check Last-Modified header and dateModified in homepage schema for freshness signals."""
    result = {"stale": False, "last_modified": None, "last_modified_display": None, "has_date_schema": False}
    try:
        resp = await client.get(domain, headers=HEADERS)
        lm = resp.headers.get("last-modified")
        if lm:
            result["last_modified"] = lm
            try:
                dt = parsedate_to_datetime(lm)
                from datetime import datetime, timezone
                age_days = (datetime.now(timezone.utc) - dt).days
                result["last_modified_display"] = f"{age_days} days ago"
                result["stale"] = age_days > 365
            except Exception:
                pass

        # Check dateModified in JSON-LD
        schema_blocks = _parse_structured_data(resp.text)
        for block in schema_blocks:
            d = block.get("data")
            if isinstance(d, dict) and d.get("dateModified"):
                result["has_date_schema"] = True
                break
    except Exception:
        pass
    return result


async def _check_redirect_chain(client: httpx.AsyncClient, url: str) -> list[str]:
    """Follow a URL and return the full redirect chain. Returns list of URLs traversed."""
    chain = [url]
    try:
        # Use a client that does NOT auto-follow so we can trace manually
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as c:
            current = url
            for _ in range(6):  # max 6 hops
                resp = await c.get(current, headers=HEADERS)
                if resp.status_code in (301, 302, 307, 308):
                    location = resp.headers.get("location", "")
                    if location:
                        next_url = urljoin(current, location)
                        chain.append(next_url)
                        current = next_url
                    else:
                        break
                else:
                    break
    except Exception:
        pass
    return chain


async def _check_broken_links(client: httpx.AsyncClient, urls: list[str]) -> list[dict]:
    """HEAD-check a list of URLs, return those that 4xx/5xx."""
    broken = []
    for url in urls:
        try:
            resp = await client.head(url, headers=HEADERS)
            if resp.status_code >= 400:
                broken.append({"url": url, "status": resp.status_code})
        except Exception:
            broken.append({"url": url, "status": "timeout"})
    return broken


def _check_eeat(homepage_html: str, pages: list[dict]) -> dict:
    """Check E-E-A-T signals: author schema, byline, about page, authoritative outbound links."""
    signals = {
        "author_schema": False,
        "byline_present": False,
        "about_page": False,
        "authoritative_outbound": False,
    }

    if homepage_html:
        # Author schema in any page's JSON-LD
        blocks = _parse_structured_data(homepage_html)
        for block in blocks:
            d = block.get("data")
            if isinstance(d, dict):
                if block.get("type") in ("Person", "Author") or d.get("author"):
                    signals["author_schema"] = True
                    break

        # Byline patterns in HTML
        if re.search(r'(by\s+<[^>]+>|class=["\'][^"\']*author[^"\']*["\']|rel=["\']author["\'])', homepage_html, re.IGNORECASE):
            signals["byline_present"] = True

        # Authoritative outbound links
        outbound = re.findall(r'href=["\']https?://([^/"\']+)', homepage_html, re.IGNORECASE)
        auth_domains = ('.gov', '.edu', 'wikipedia.org', 'reuters.com', 'apnews.com',
                        'techcrunch.com', 'wired.com', 'nature.com', 'pubmed.ncbi')
        if any(any(a in d for a in auth_domains) for d in outbound):
            signals["authoritative_outbound"] = True

    # About page — check if any crawled page URL contains /about
    for page in pages:
        if '/about' in page.get('url', '').lower():
            signals["about_page"] = True
            break

    return signals


# ─────────────────────────────────────────────────────────────
# Per-page audit
# ─────────────────────────────────────────────────────────────

async def _audit_page(client: httpx.AsyncClient, url: str, *,
                      platform: dict | None = None) -> dict | None:
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

        # MediaWiki: strip site suffix for title length evaluation.
        # MW appends " - SiteName" to every page title. WikiSEO can override,
        # but default titles include the suffix. Measure the content part only.
        _effective_title_length = data["title_length"]
        if platform and platform.get("platform") == "mediawiki" and platform.get("site_suffix"):
            suffix = platform["site_suffix"]
            if data["title"].endswith(suffix):
                _effective_title_length = len(data["title"]) - len(suffix)
        data["_effective_title_length"] = _effective_title_length

        # Meta description
        desc_match = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']', html, re.IGNORECASE)
        if not desc_match:
            desc_match = re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+name=["\']description["\']', html, re.IGNORECASE)
        data["meta_description"] = desc_match.group(1).strip() if desc_match else ""
        data["meta_description_length"] = len(data["meta_description"])

        # Canonical (handle both attribute orders: rel before href, or href before rel)
        canonical_match = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']*)["\']', html, re.IGNORECASE)
        if not canonical_match:
            canonical_match = re.search(r'<link[^>]+href=["\']([^"\']*)["\'][^>]+rel=["\']canonical["\']', html, re.IGNORECASE)
        data["canonical"] = canonical_match.group(1) if canonical_match else ""

        # Open Graph (handle both attribute orders: property before content, or content before property)
        og_title = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']*)["\']', html, re.IGNORECASE)
        if not og_title:
            og_title = re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+property=["\']og:title["\']', html, re.IGNORECASE)
        og_desc = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']*)["\']', html, re.IGNORECASE)
        if not og_desc:
            og_desc = re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+property=["\']og:description["\']', html, re.IGNORECASE)
        og_image = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']*)["\']', html, re.IGNORECASE)
        if not og_image:
            og_image = re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+property=["\']og:image["\']', html, re.IGNORECASE)
        data["og_title"] = og_title.group(1) if og_title else ""
        data["og_desc"] = og_desc.group(1) if og_desc else ""
        data["og_image"] = bool(og_image)

        # Twitter Card (handle both attribute orders)
        twitter_card = re.search(r'<meta[^>]+name=["\']twitter:card["\'][^>]+content=["\']([^"\']*)["\']', html, re.IGNORECASE)
        if not twitter_card:
            twitter_card = re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+name=["\']twitter:card["\']', html, re.IGNORECASE)
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
        _is_mw = platform and platform.get("platform") == "mediawiki"

        # Title length — for MediaWiki, use effective length (without site suffix)
        _tlen = data.get("_effective_title_length", data["title_length"])
        if not data["title"]:
            issues.append("MISSING: Page title")
            evidence.append({"field": "title", "found": None, "expected": "50-60 chars", "context": "No <title> tag found"})
        elif _tlen > 60:
            issues.append(f"LONG TITLE: {_tlen} chars (target: 50-60)")
            evidence.append({"field": "title", "found": data["title"], "found_length": _tlen, "expected": "50-60 chars"})
        elif _tlen < 30:
            issues.append(f"SHORT TITLE: {_tlen} chars (target: 50-60)")
            evidence.append({"field": "title", "found": data["title"], "found_length": _tlen, "expected": "50-60 chars"})

        if not data["meta_description"]:
            issues.append("MISSING: Meta description")
            evidence.append({"field": "meta_description", "found": None, "expected": "120-160 chars"})
        elif data["meta_description_length"] > 160:
            issues.append(f"LONG META DESC: {data['meta_description_length']} chars (target: 120-160)")
            evidence.append({"field": "meta_description", "found": data["meta_description"][:120], "found_length": data["meta_description_length"], "expected": "120-160 chars"})
        elif data["meta_description_length"] < 70:
            issues.append(f"SHORT META DESC: {data['meta_description_length']} chars (target: 120-160)")
            evidence.append({"field": "meta_description", "found": data["meta_description"], "found_length": data["meta_description_length"], "expected": "120-160 chars"})

        # H1 count — MediaWiki always generates one H1 from the page title.
        # Only flag if there are 0 or >1 H1s. MW sites with exactly 1 H1 are correct.
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
        # Structured data — MediaWiki doesn't output JSON-LD by default; WikiSEO
        # provides OG tags but not schema.org blocks. Flag as informational, not critical.
        if not data["has_schema"] and not _is_mw:
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


def _discover_internal_links(html: str, base_url: str, base_host: str,
                             *, is_mediawiki: bool = False) -> list[str]:
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

        # MediaWiki: skip Special:, Category:, Template:, action= URLs etc.
        if is_mediawiki:
            if any(seg in path for seg in _MEDIAWIKI_SKIP_PATHS):
                continue
            if "action=" in parsed.query or "oldid=" in parsed.query:
                continue

        clean_url = f"{parsed.scheme}://{parsed.netloc}{path}"
        if clean_url in seen or clean_url == base_url:
            continue

        seen.add(clean_url)
        urls.append(clean_url)

    return urls


# ─────────────────────────────────────────────────────────────
# Programmatic analysis — no Claude for factual findings
# ─────────────────────────────────────────────────────────────

def _compile_analysis(pages: list[dict], domain: str, sitewide: dict, *,
                      platform: dict | None = None) -> dict:
    """Build structured recommendations purely from deterministic audit data.

    Claude is NOT called here. Every finding is traced to a specific data field.
    This replaces the old _analyze_seo() which sent everything to Claude and
    got hallucinated issues back.
    """
    critical = []
    quick_wins = []
    technical = []
    geo = []
    robots_review = []
    llms_review = []
    content_gaps = []
    total_issues = 0

    _is_mw = platform and platform.get("platform") == "mediawiki"

    # ── Per-page findings ──
    for p in pages:
        url = p.get("url", "")
        short_url = url.replace(domain, "")
        issues = p.get("issues", [])
        total_issues += len(issues)

        # Critical: missing title, missing H1, multiple H1s
        if not p.get("title"):
            critical.append(f"{short_url} — missing page title. Add a descriptive <title> (50-60 chars).")
        if p.get("h1_count", 0) == 0:
            critical.append(f"{short_url} — missing H1 tag. Add exactly one H1 matching the page topic.")
        elif p.get("h1_count", 0) > 1:
            h1_texts = ", ".join(f'"{h}"' for h in p.get("h1_texts", [])[:3])
            critical.append(f"{short_url} — {p['h1_count']} H1 tags found (should be 1): {h1_texts}")

        # Quick wins: title length — use effective length for MW (strips site suffix)
        _tlen = p.get("_effective_title_length", p.get("title_length", 0))
        if p.get("title") and _tlen > 60:
            quick_wins.append(f"{short_url} — title too long ({_tlen} chars, target 50-60): \"{p['title'][:70]}\"")
        elif p.get("title") and _tlen < 30:
            quick_wins.append(f"{short_url} — title too short ({_tlen} chars, target 50-60): \"{p['title']}\"")

        if not p.get("meta_description"):
            quick_wins.append(f"{short_url} — missing meta description. Add 120-160 char description.")
        elif p.get("meta_description_length", 0) > 160:
            quick_wins.append(f"{short_url} — meta description too long ({p['meta_description_length']} chars, target 120-160)")
        elif p.get("meta_description_length", 0) < 70:
            quick_wins.append(f"{short_url} — meta description too short ({p['meta_description_length']} chars, target 120-160)")

        if not p.get("og_title"):
            quick_wins.append(f"{short_url} — missing og:title tag")
        if not p.get("og_image"):
            quick_wins.append(f"{short_url} — missing og:image tag")
        if not p.get("canonical"):
            quick_wins.append(f"{short_url} — missing canonical URL")
        # JSON-LD: MediaWiki doesn't emit schema.org by default — skip this check
        if not p.get("has_schema") and not _is_mw:
            quick_wins.append(f"{short_url} — no JSON-LD structured data")

        if p.get("images_missing_alt", 0) > 0:
            quick_wins.append(f"{short_url} — {p['images_missing_alt']}/{p['total_images']} images missing alt text")

    # ── Sitewide: robots.txt ──
    robots = sitewide.get("robots", {})
    if not robots.get("found"):
        critical.append("robots.txt is missing. Create /robots.txt with User-agent: * Allow: / and a Sitemap: directive.")
        robots_review.append("robots.txt not found — crawlers have no guidance on your site structure.")
    else:
        blocked = robots.get("blocked_bots", [])
        allowed = robots.get("allowed_bots", [])
        if blocked:
            critical.append(f"robots.txt blocks AI crawlers: {', '.join(blocked)}. Remove Disallow rules for these bots to appear in AI search results.")
            robots_review.append(f"BLOCKED: {', '.join(blocked)} — these AI platforms will not index or cite this site.")
        if allowed:
            robots_review.append(f"Allowed: {', '.join(allowed)} — correctly accessible.")
        if not robots.get("has_sitemap_reference"):
            technical.append("robots.txt has no Sitemap: directive. Add Sitemap: https://yourdomain.com/sitemap.xml")
            robots_review.append("No Sitemap: directive found in robots.txt.")
        if not blocked and robots.get("has_sitemap_reference"):
            robots_review.append("robots.txt is well-configured — no AI bots blocked, sitemap referenced.")

    # ── Sitewide: llms.txt ──
    llms = sitewide.get("llms_txt", {})
    if not llms.get("found"):
        geo.append("llms.txt is missing. This file (llmstxt.org spec) helps AI engines understand your site for citation. Create /llms.txt with company description, key pages, and product info.")
        llms_review.append("llms.txt not found. This is a structured file that AI engines read to understand what your company does and which pages to cite. Adding one improves AI discoverability.")
    else:
        llms_review.append("llms.txt is present. AI engines can read your site description for citation context.")

    # ── Sitewide: sitemap ──
    sitemap = sitewide.get("sitemap", {})
    if not sitemap.get("found"):
        technical.append("sitemap.xml is missing. Generate one and submit to Google Search Console and Bing Webmaster Tools.")
    else:
        page_count = sitemap.get("page_count", 0)
        if page_count > 0:
            technical.append(f"sitemap.xml found with {page_count} URLs.") if page_count < 10 else None

    # ── Sitewide: PageSpeed ──
    pagespeed = sitewide.get("pagespeed", {})
    if pagespeed.get("found"):
        mobile_score = pagespeed.get("mobile_score")
        if mobile_score is not None and mobile_score < 50:
            critical.append(f"Mobile PageSpeed score is {mobile_score}/100 — critical performance issue. Check LCP, CLS, and INP.")
        elif mobile_score is not None and mobile_score < 75:
            technical.append(f"Mobile PageSpeed score is {mobile_score}/100 — needs improvement. Target 90+.")

    # ── Sitewide: broken links ──
    broken_links = sitewide.get("broken_links", [])
    if broken_links:
        for bl in broken_links[:5]:
            critical.append(f"Broken internal link: {bl['url']} (HTTP {bl['status']})")

    # ── Sitewide: redirect chains ──
    redirect_chains = sitewide.get("redirect_chains", [])
    if redirect_chains:
        for rc in redirect_chains[:3]:
            technical.append(f"Redirect chain ({rc['hops']} hops): {rc['url']} → {' → '.join(rc['chain'][-2:])}")

    # ── Sitewide: security headers ──
    sec = sitewide.get("security_headers", {})
    missing_sec = [h for h, v in sec.items() if not v]
    if missing_sec:
        technical.append(f"Missing security headers: {', '.join(missing_sec)}")

    # ── Sitewide: content freshness ──
    freshness = sitewide.get("freshness", {})
    if freshness.get("stale"):
        technical.append(f"Content may be stale — last modified {freshness.get('last_modified_display', 'unknown')}. Update homepage content or add dateModified to schema.")

    # ── Sitewide: E-E-A-T ──
    eeat = sitewide.get("eeat", {})
    eeat_missing = [k for k, v in eeat.items() if not v]
    # MediaWiki: edit history IS the authorship signal — don't flag missing bylines/author schema
    if _is_mw:
        eeat_missing = [k for k in eeat_missing if k not in ("byline_present", "author_schema")]
    if eeat_missing:
        labels = {
            "author_schema": "no author schema in JSON-LD",
            "byline_present": "no author bylines on content",
            "about_page": "no /about page found",
            "authoritative_outbound": "no authoritative outbound links (.gov, .edu, research)",
        }
        details = [labels.get(k, k) for k in eeat_missing]
        geo.append(f"E-E-A-T gaps: {'; '.join(details)}. These signals help AI engines assess content trustworthiness.")

    # ── Sitewide: orphaned pages ──
    orphans = sitewide.get("orphaned_pages", [])
    if orphans:
        technical.append(f"{len(orphans)} orphaned page(s) with no inbound internal links: {', '.join(orphans[:3])}")

    # ── Content gaps (deterministic: thin content, missing FAQ schema, no blog) ──
    thin_pages = [p for p in pages if p.get("word_count", 0) < 300 and "/blog" in p.get("url", "").lower()]
    if thin_pages:
        content_gaps.append(f"{len(thin_pages)} blog page(s) with thin content (<300 words): {', '.join(p['url'].replace(domain, '') for p in thin_pages[:3])}")
    # FAQ schema and blog checks — not applicable to MediaWiki sites
    # (wikis don't have blogs; MW doesn't support FAQ schema natively)
    if not _is_mw:
        has_faq_schema = any(
            any(b.get("type") == "FAQPage" for b in p.get("schema_blocks", []))
            for p in pages
        )
        if not has_faq_schema and len(pages) > 1:
            content_gaps.append("No FAQPage schema found on any page — FAQ structured data improves AI citation visibility.")
        blog_pages = [p for p in pages if "/blog" in p.get("url", "").lower()]
        if not blog_pages and len(pages) > 3:
            content_gaps.append("No /blog pages found in crawl — regular content publishing improves domain authority and AI citability.")

    # ── GEO summary ──
    # Always add a GEO status line based on deterministic signals
    geo_positive = []
    if robots.get("found") and not robots.get("blocked_bots"):
        geo_positive.append("AI bots allowed")
    if llms.get("found"):
        geo_positive.append("llms.txt present")
    homepage = pages[0] if pages else {}
    if homepage.get("has_schema"):
        geo_positive.append("homepage has structured data")
    elif _is_mw and homepage.get("og_title"):
        # MediaWiki with WikiSEO provides OG tags (no JSON-LD), count as partial structured data
        geo_positive.append("WikiSEO OpenGraph tags present")
    if not eeat_missing:
        geo_positive.append("E-E-A-T signals present")

    if geo_positive:
        geo.insert(0, f"AI citation readiness: {', '.join(geo_positive)}.")

    # ── Build analysis text (human-readable summary for UI) ──
    platform_label = ""
    if _is_mw:
        mw_ver = platform.get("version", "unknown") if platform else "unknown"
        platform_label = f"  |  Platform: MediaWiki {mw_ver}"
    analysis_lines = [f"SEO + GEO AUDIT — {domain}", f"{len(pages)} pages scanned.{platform_label}\n"]

    def _section_to_text(header, items):
        if not items:
            return f"{header}:\n- None — all checks passing.\n"
        return f"{header}:\n" + "\n".join(f"- {item}" for item in items) + "\n"

    analysis_lines.append(_section_to_text("CRITICAL", critical))
    analysis_lines.append(_section_to_text("QUICK WINS", quick_wins))
    analysis_lines.append(_section_to_text("TECHNICAL", technical))
    analysis_lines.append(_section_to_text("GEO", geo))
    analysis_lines.append(_section_to_text("ROBOTS_REVIEW", robots_review))
    analysis_lines.append(_section_to_text("LLMS_REVIEW", llms_review))
    analysis_lines.append(_section_to_text("CONTENT GAPS", content_gaps))

    return {
        "score": 0,  # overridden by deterministic score in audit_domain()
        "score_summary": "",
        "total_issues": total_issues,
        "critical": critical,
        "quick_wins": quick_wins,
        "content_gaps": content_gaps,
        "technical": technical,
        "geo": geo,
        "robots_review": robots_review,
        "llms_review": llms_review,
        "analysis": "\n".join(analysis_lines),
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
                    "source": "programmatic",
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
                    f"LCP: {pagespeed.get('lcp', 'N/A')}, CLS: {pagespeed.get('cls', 'N/A')}, INP: {pagespeed.get('inp', 'N/A')}. "
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

    # Redirect chains
    for rc in sitewide.get("redirect_chains", []):
        items.append({
            "priority": "high",
            "category": "technical",
            "title": f"Redirect chain ({rc['hops']} hops) starting at {rc['url']}",
            "evidence": {"source": "redirect_chain", "url": rc["url"], "chain": rc["chain"]},
            "fix_instructions": (
                f"This URL redirects through {rc['hops']} hops before reaching its destination. "
                "Each hop costs crawl budget and reduces link equity passed. "
                "Update all internal links and any external references to point directly to the final URL."
            ),
            "score_impact": 4,
        })

    # Broken internal links
    for bl in sitewide.get("broken_links", []):
        items.append({
            "priority": "high",
            "category": "technical",
            "title": f"Broken internal link: {bl['url']} (HTTP {bl['status']})",
            "evidence": {"source": "broken_link", "url": bl["url"], "status": bl["status"]},
            "fix_instructions": (
                f"Internal link to {bl['url']} returns HTTP {bl['status']}. "
                "Find all internal pages linking to this URL and either fix the destination or remove the link."
            ),
            "score_impact": 5,
        })

    # Security headers
    sec = sitewide.get("security_headers", {})
    missing_sec = [h for h, present in sec.items() if not present]
    if missing_sec:
        items.append({
            "priority": "medium",
            "category": "technical",
            "title": f"Security headers missing: {', '.join(missing_sec)}",
            "evidence": {"source": "security_headers", "missing": missing_sec},
            "fix_instructions": (
                f"Add the following HTTP response headers to your server/CDN configuration: {', '.join(missing_sec)}. "
                "Strict-Transport-Security enforces HTTPS. X-Content-Type-Options prevents MIME sniffing. "
                "X-Frame-Options prevents clickjacking. These signal infrastructure quality to both users and crawlers."
            ),
            "score_impact": 3,
        })

    # Content freshness
    freshness = sitewide.get("freshness", {})
    if freshness.get("stale"):
        items.append({
            "priority": "medium",
            "category": "content",
            "title": f"Site content appears stale — last modified {freshness.get('last_modified_display', 'unknown')}",
            "evidence": {"source": "freshness", "last_modified": freshness.get("last_modified")},
            "fix_instructions": (
                "Content freshness is a ranking signal. Update key pages and add dateModified to your JSON-LD schema. "
                "At minimum, refresh your homepage content and ensure your blog is publishing regularly."
            ),
            "score_impact": 4,
        })

    # E-E-A-T
    eeat = sitewide.get("eeat", {})
    eeat_missing = [k for k, v in eeat.items() if not v]
    if eeat_missing:
        items.append({
            "priority": "medium",
            "category": "geo",
            "title": f"E-E-A-T signals weak — missing: {', '.join(eeat_missing)}",
            "evidence": {"source": "eeat", "missing": eeat_missing, "present": [k for k, v in eeat.items() if v]},
            "fix_instructions": (
                "Google and AI systems evaluate Experience, Expertise, Authoritativeness, and Trustworthiness. "
                + ("Add author schema (Person JSON-LD) to content pages. " if "author_schema" in eeat_missing else "")
                + ("Add bylines to authored content. " if "byline_present" in eeat_missing else "")
                + ("Create a thorough /about page with team credentials. " if "about_page" in eeat_missing else "")
                + ("Link out to authoritative sources (.gov, .edu, industry publications) to signal credibility. " if "authoritative_outbound" in eeat_missing else "")
            ),
            "score_impact": 4,
        })

    # Orphaned pages
    for orphan_url in sitewide.get("orphaned_pages", []):
        items.append({
            "priority": "low",
            "category": "technical",
            "title": f"Orphaned page — no internal links point to: {orphan_url}",
            "evidence": {"source": "orphan_detection", "url": orphan_url},
            "fix_instructions": (
                f"{orphan_url} was discovered during crawl but has no internal links pointing to it. "
                "Orphaned pages receive minimal crawl frequency and no internal link equity. "
                "Either link to this page from relevant content, or consolidate/remove it."
            ),
            "score_impact": 2,
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
