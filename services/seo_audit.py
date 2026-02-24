"""SEO Audit — crawl a domain's pages, extract SEO elements, Claude analyzes and recommends."""

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


def _get_client(api_key: str | None = None):
    return anthropic.Anthropic(api_key=api_key or settings.anthropic_api_key)


async def audit_domain(domain: str, max_pages: int = 15, api_key: str | None = None) -> dict:
    """Run a full SEO audit on a domain. Returns page-level findings + overall recommendations."""
    if not domain.startswith("http"):
        domain = f"https://{domain}"
    domain = domain.rstrip("/")
    base_host = urlparse(domain).netloc

    pages = []

    async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
        # Homepage first
        homepage_data = await _audit_page(client, domain)
        if homepage_data:
            pages.append(homepage_data)

        # Discover internal links from homepage
        if homepage_data and homepage_data.get("_html"):
            links = _discover_internal_links(homepage_data["_html"], domain, base_host)
            for url in links[:max_pages - 1]:
                page_data = await _audit_page(client, url)
                if page_data:
                    pages.append(page_data)

    # Strip raw HTML from results before analysis
    for p in pages:
        p.pop("_html", None)

    # Claude analysis
    recommendations = await _analyze_seo(pages, domain, api_key=api_key)

    return {
        "domain": domain,
        "pages_audited": len(pages),
        "pages": pages,
        "recommendations": recommendations,
    }


async def _audit_page(client: httpx.AsyncClient, url: str) -> dict | None:
    """Audit a single page — extract all SEO-relevant elements."""
    try:
        resp = await client.get(url, headers=HEADERS)
        if resp.status_code != 200:
            return None

        html = resp.text
        data = {
            "url": url,
            "status_code": resp.status_code,
            "_html": html,  # kept temporarily for link discovery
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

        # Headings
        h1s = re.findall(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL | re.IGNORECASE)
        data["h1_count"] = len(h1s)
        data["h1_texts"] = [re.sub(r'<[^>]+>', '', h).strip()[:200] for h in h1s[:3]]

        h2s = re.findall(r'<h2[^>]*>(.*?)</h2>', html, re.DOTALL | re.IGNORECASE)
        data["h2_count"] = len(h2s)
        data["h2_texts"] = [re.sub(r'<[^>]+>', '', h).strip()[:200] for h in h2s[:8]]

        # Images without alt text
        images = re.findall(r'<img[^>]*>', html, re.IGNORECASE)
        imgs_missing_alt = 0
        for img in images:
            if 'alt=' not in img.lower() or re.search(r'alt=["\']["\']', img, re.IGNORECASE):
                imgs_missing_alt += 1
        data["total_images"] = len(images)
        data["images_missing_alt"] = imgs_missing_alt

        # Internal vs external links
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

        # Content length (rough word count)
        text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        words = len(text.split())
        data["word_count"] = words

        # Schema.org structured data
        data["has_schema"] = bool(re.search(r'application/ld\+json', html, re.IGNORECASE))

        # Issues found
        issues = []
        if not data["title"]:
            issues.append("MISSING: Page title")
        elif data["title_length"] > 60:
            issues.append(f"LONG TITLE: {data['title_length']} chars (target: 50-60)")
        elif data["title_length"] < 30:
            issues.append(f"SHORT TITLE: {data['title_length']} chars (target: 50-60)")

        if not data["meta_description"]:
            issues.append("MISSING: Meta description")
        elif data["meta_description_length"] > 160:
            issues.append(f"LONG META DESC: {data['meta_description_length']} chars (target: 120-160)")
        elif data["meta_description_length"] < 70:
            issues.append(f"SHORT META DESC: {data['meta_description_length']} chars (target: 120-160)")

        if data["h1_count"] == 0:
            issues.append("MISSING: H1 tag")
        elif data["h1_count"] > 1:
            issues.append(f"MULTIPLE H1s: {data['h1_count']} found (should be 1)")

        if data["images_missing_alt"] > 0:
            issues.append(f"IMAGES: {data['images_missing_alt']}/{data['total_images']} missing alt text")

        if not data["og_title"]:
            issues.append("MISSING: Open Graph title")
        if not data["og_image"]:
            issues.append("MISSING: Open Graph image")
        if not data["canonical"]:
            issues.append("MISSING: Canonical URL")
        if not data["has_schema"]:
            issues.append("MISSING: Schema.org structured data (JSON-LD)")

        if data["word_count"] < 300 and "/blog" in url.lower():
            issues.append(f"THIN CONTENT: {data['word_count']} words (target: 800+ for blog)")

        data["issues"] = issues
        data["issue_count"] = len(issues)

        return data

    except Exception as e:
        log.warning("SEO audit failed for %s: %s", url, e)
        return None


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


async def _analyze_seo(pages: list[dict], domain: str, api_key: str | None = None) -> dict:
    """Claude analyzes the SEO audit data and generates recommendations."""
    # Build a summary for Claude
    summary_parts = [f"SEO AUDIT RESULTS FOR {domain}\n{len(pages)} pages crawled.\n"]

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
        summary_parts.append(f"Schema: {'Yes' if p.get('has_schema') else 'No'} | Canonical: {'Yes' if p.get('canonical') else 'No'} | OG Image: {'Yes' if p.get('og_image') else 'No'}")
        if issues:
            summary_parts.append(f"Issues: {', '.join(issues)}")

    summary_parts.append(f"\nTOTAL ISSUES: {total_issues} across {len(pages)} pages")

    try:
        response = _get_client(api_key).messages.create(
            model=settings.claude_model_fast,
            max_tokens=2000,
            system="""You are an SEO specialist auditing a website. Based on the crawl data, provide:

1. SCORE: Overall SEO health score (0-100) with one-line justification.
2. CRITICAL: Top 3 issues that need immediate attention, with specific fix instructions.
3. QUICK WINS: 3-5 easy improvements that would have outsized impact.
4. CONTENT GAPS: What pages or content types are missing that would help SEO?
5. TECHNICAL: Any technical SEO issues (canonical, schema, OG tags, etc.)

Be specific. Reference actual page URLs and exact issues. Don't give generic advice — every recommendation should be actionable with the specific data provided.""",
            messages=[{"role": "user", "content": "\n".join(summary_parts)}],
        )

        await log_token_usage(None, "seo_audit", response)
        analysis_text = response.content[0].text

        # Extract score
        score = 0
        score_match = re.search(r'(?:SCORE|score)[:\s]*(\d+)', analysis_text)
        if score_match:
            score = min(100, max(0, int(score_match.group(1))))

        return {
            "score": score,
            "total_issues": total_issues,
            "analysis": analysis_text,
        }

    except Exception as e:
        log.error("SEO analysis failed: %s", e)
        return {
            "score": 0,
            "total_issues": total_issues,
            "analysis": f"Analysis failed: {str(e)}",
        }
