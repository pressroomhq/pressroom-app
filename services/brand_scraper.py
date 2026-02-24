"""Brand scraper — extract visual identity from a company website.

Scrapes logo, colors, fonts, and company name from a homepage.
Used to personalize Remotion video packages with real brand assets.
"""

import re
import logging
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger("pressroom")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PressroomBot/1.0; +https://pressroomhq.com)"
}

# CSS variable names that commonly hold brand colors
COLOR_VAR_NAMES = [
    "--primary", "--brand", "--accent", "--color-primary", "--color-brand",
    "--main-color", "--theme-color", "--brand-color",
]

HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")


async def scrape_brand(url: str) -> dict:
    """Scrape a company's website and extract brand assets.

    Returns dict with: logo_url, primary_color, secondary_color,
    font_family, company_name, favicon_url. None for anything not found.
    """
    result = {
        "logo_url": None,
        "primary_color": None,
        "secondary_color": None,
        "font_family": None,
        "company_name": None,
        "favicon_url": None,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=HEADERS)
            resp.raise_for_status()
            html = resp.text
    except Exception as e:
        log.warning("Brand scrape failed for %s: %s", url, e)
        return result

    soup = BeautifulSoup(html, "lxml")

    # --- Company name ---
    og_site = soup.find("meta", property="og:site_name")
    if og_site and og_site.get("content"):
        result["company_name"] = og_site["content"].strip()
    elif soup.title and soup.title.string:
        # Take first part before separator
        title = soup.title.string.strip()
        for sep in [" | ", " - ", " — ", " – ", " : "]:
            if sep in title:
                title = title.split(sep)[0].strip()
                break
        result["company_name"] = title

    # --- Logo URL ---
    # Priority: og:image, apple-touch-icon, header img
    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        result["logo_url"] = _abs(url, og_image["content"])

    if not result["logo_url"]:
        touch = soup.find("link", rel=lambda r: r and "apple-touch-icon" in r)
        if touch and touch.get("href"):
            result["logo_url"] = _abs(url, touch["href"])

    if not result["logo_url"]:
        # Look for logo in header/nav
        header = soup.find(["header", "nav"])
        if header:
            img = header.find("img")
            if img and img.get("src"):
                result["logo_url"] = _abs(url, img["src"])

    # --- Favicon ---
    fav = soup.find("link", rel=lambda r: r and "icon" in str(r).lower())
    if fav and fav.get("href"):
        result["favicon_url"] = _abs(url, fav["href"])

    # --- Theme color from meta tag ---
    theme_meta = soup.find("meta", attrs={"name": "theme-color"})
    if theme_meta and theme_meta.get("content"):
        color = theme_meta["content"].strip()
        if HEX_RE.match(color):
            result["primary_color"] = color

    # --- Colors and fonts from CSS ---
    css_text = ""

    # Inline styles
    for style in soup.find_all("style"):
        if style.string:
            css_text += style.string + "\n"

    # First external stylesheet
    if not result["primary_color"] or not result["font_family"]:
        for link in soup.find_all("link", rel="stylesheet"):
            href = link.get("href", "")
            if href:
                try:
                    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                        css_resp = await client.get(_abs(url, href), headers=HEADERS)
                        if css_resp.status_code == 200:
                            css_text += css_resp.text + "\n"
                            break  # Only fetch first stylesheet
                except Exception:
                    pass

    if css_text:
        _extract_from_css(css_text, result)

    return result


def _extract_from_css(css: str, result: dict):
    """Extract colors and fonts from CSS text."""
    # Look for brand color CSS variables
    if not result["primary_color"]:
        for var_name in COLOR_VAR_NAMES:
            pattern = re.compile(re.escape(var_name) + r"\s*:\s*(#[0-9a-fA-F]{3,6})\b")
            m = pattern.search(css)
            if m:
                result["primary_color"] = m.group(1)
                break

    # Count hex colors to find most common (excluding black/white/gray)
    all_colors = HEX_RE.findall(css)
    skip = {"#000", "#000000", "#fff", "#ffffff", "#333", "#333333",
            "#666", "#666666", "#999", "#999999", "#ccc", "#cccccc",
            "#eee", "#eeeeee", "#111", "#111111", "#222", "#222222",
            "#ddd", "#dddddd", "#aaa", "#aaaaaa", "#bbb", "#bbbbbb",
            "#f5f5f5", "#fafafa", "#f0f0f0", "#e0e0e0", "#d0d0d0"}

    color_counts = {}
    for c in all_colors:
        c_lower = c.lower()
        if c_lower not in skip:
            # Normalize 3-char to 6-char
            if len(c_lower) == 4:  # #abc
                c_lower = f"#{c_lower[1]*2}{c_lower[2]*2}{c_lower[3]*2}"
            color_counts[c_lower] = color_counts.get(c_lower, 0) + 1

    sorted_colors = sorted(color_counts.items(), key=lambda x: -x[1])

    if not result["primary_color"] and sorted_colors:
        result["primary_color"] = sorted_colors[0][0]

    if not result["secondary_color"] and len(sorted_colors) > 1:
        result["secondary_color"] = sorted_colors[1][0]
    elif not result["secondary_color"] and sorted_colors:
        result["secondary_color"] = sorted_colors[0][0]

    # Font family from body or :root
    font_patterns = [
        re.compile(r"body\s*\{[^}]*font-family\s*:\s*([^;]+)", re.DOTALL),
        re.compile(r":root\s*\{[^}]*font-family\s*:\s*([^;]+)", re.DOTALL),
        re.compile(r"html\s*\{[^}]*font-family\s*:\s*([^;]+)", re.DOTALL),
        re.compile(r"h1\s*\{[^}]*font-family\s*:\s*([^;]+)", re.DOTALL),
    ]
    if not result["font_family"]:
        for pat in font_patterns:
            m = pat.search(css)
            if m:
                result["font_family"] = m.group(1).strip().strip("'\"")
                break


def _abs(base: str, path: str) -> str:
    """Make a URL absolute."""
    if path.startswith(("http://", "https://", "//")):
        if path.startswith("//"):
            return "https:" + path
        return path
    return urljoin(base, path)
