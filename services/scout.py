"""Scout — Signal ingestion from GitHub, Hacker News, Reddit, RSS.

Org-aware: reads scout sources from per-org settings, not global config.
Includes LLM relevance filtering to discard off-topic signals.
"""

import json
import logging
import httpx
import feedparser
import anthropic
from datetime import datetime, timedelta

from config import settings
from models import SignalType
from services.token_tracker import log_token_usage
from services.github_auth import get_github_token, get_github_headers

log = logging.getLogger("pressroom")


# ──────────────────────────────────────
# GitHub Org/User Repo Discovery
# ──────────────────────────────────────

async def discover_github_repos(github_url: str, gh_token: str = "", max_repos: int = 200) -> list[str]:
    """Discover all active repos under a GitHub org or user.

    Takes a GitHub org/user name (e.g. 'teamtreehouse') or URL
    (e.g. 'https://github.com/dreamfactorysoftware') and returns
    a list of 'owner/repo' strings, sorted by most recently pushed.
    Paginates to get all repos.
    """
    import re
    # Accept bare org name or full URL
    match = re.search(r'github\.com/([^/\s?#]+)', github_url)
    owner = match.group(1) if match else github_url.strip().strip('/')
    if not owner:
        log.debug("[scout] GitHub discovery — no owner found in '%s'", github_url)
        return []
    log.info("[scout] GitHub discovery — scanning repos for '%s'...", owner)

    token = gh_token or await get_github_token()
    # Validate token — a 401 is worse than no token (it won't retry as unauth)
    if token:
        async with httpx.AsyncClient(timeout=5) as probe:
            check = await probe.get("https://api.github.com/user", headers=get_github_headers(token))
            if check.status_code == 401:
                log.warning("GITHUB DISCOVERY — token invalid, proceeding unauthenticated")
                token = ""
    headers = get_github_headers(token)

    repos = []
    async with httpx.AsyncClient(timeout=15) as client:
        # Try as org first, fall back to user
        for endpoint in [f"orgs/{owner}/repos", f"users/{owner}/repos"]:
            try:
                page = 1
                while True:
                    resp = await client.get(
                        f"https://api.github.com/{endpoint}",
                        headers=headers,
                        params={"per_page": 100, "sort": "pushed", "direction": "desc", "page": page},
                    )
                    if resp.status_code != 200:
                        break
                    data = resp.json()
                    if not data:
                        break
                    for r in data:
                        if r.get("archived") or r.get("disabled"):
                            continue
                        repos.append(r["full_name"])
                    if len(data) < 100 or len(repos) >= max_repos:
                        break
                    page += 1
                if repos:
                    break  # got results, don't try the other endpoint
            except Exception:
                continue

    log.info("GITHUB DISCOVERY — %s → %d repos found", owner, len(repos))
    return repos[:max_repos]


async def scout_github_releases(repo: str, since_hours: int = 24, gh_token: str = "") -> list[dict]:
    """Pull recent releases from a GitHub repo.

    Uses a minimum 30-day lookback for releases regardless of since_hours —
    releases are infrequent and high-value, so the short scout window is wrong for them.
    """
    log.debug("[scout] Checking releases for %s...", repo)
    token = gh_token or await get_github_token()
    headers = get_github_headers(token)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.github.com/repos/{repo}/releases",
            headers=headers,
            params={"per_page": 10},
        )
        if resp.status_code != 200:
            log.warning("GitHub releases %s — HTTP %s: %s", repo, resp.status_code, resp.text[:200])
            return []

        all_releases = resp.json()
        if not all_releases:
            log.info("GitHub releases %s — no releases found", repo)
            return []

        # Use at least 30 days for releases — they're infrequent and high-value
        release_lookback = max(since_hours, 30 * 24)
        cutoff = datetime.utcnow() - timedelta(hours=release_lookback)
        signals = []
        for release in all_releases:
            published = datetime.fromisoformat(release["published_at"].replace("Z", "+00:00")).replace(tzinfo=None)
            if published > cutoff:
                signals.append({
                    "type": SignalType.github_release,
                    "source": repo,
                    "title": f"{repo} — {release['tag_name']}: {release['name']}",
                    "body": (release.get("body") or "")[:2000],
                    "url": release["html_url"],
                    "raw_data": str(release)[:5000],
                })
        if not signals and all_releases:
            log.info("GitHub releases %s — %d releases found but all older than %d days",
                     repo, len(all_releases), release_lookback // 24)
        return signals


async def scout_github_commits(repo: str, since_hours: int = 24, gh_token: str = "") -> list[dict]:
    """Pull recent commits from a GitHub repo."""
    token = gh_token or await get_github_token()
    headers = get_github_headers(token)
    since = (datetime.utcnow() - timedelta(hours=since_hours)).isoformat() + "Z"
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.github.com/repos/{repo}/commits",
            headers=headers,
            params={"since": since, "per_page": 20},
        )
        if resp.status_code != 200:
            log.warning("GitHub commits %s — HTTP %s: %s", repo, resp.status_code, resp.text[:200])
            return []

        commits = resp.json()
        if not commits:
            return []

        messages = [c["commit"]["message"].split("\n")[0] for c in commits[:20]]
        return [{
            "type": SignalType.github_commit,
            "source": repo,
            "title": f"{repo} — {len(commits)} new commits",
            "body": "\n".join(f"• {m}" for m in messages),
            "url": f"https://github.com/{repo}/commits",
            "raw_data": str(commits[:5])[:5000],
        }]


async def scout_github_org_commits(org: str, since_hours: int = 24, gh_token: str = "") -> list[dict]:
    """Pull recent commit activity across an entire GitHub org via the events feed.

    One API call instead of N per-repo calls. Returns one signal per repo
    that had push activity in the window.
    """
    token = gh_token or await get_github_token()
    headers = get_github_headers(token)
    cutoff = datetime.utcnow() - timedelta(hours=since_hours)

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.github.com/orgs/{org}/events",
            headers=headers,
            params={"per_page": 100},
        )
        if resp.status_code != 200:
            log.warning("GitHub org events %s — HTTP %s: %s", org, resp.status_code, resp.text[:200])
            return []

        events = resp.json()

    # Collect PushEvents within the window, grouped by repo
    repo_commits: dict[str, list[str]] = {}
    for event in events:
        if event.get("type") != "PushEvent":
            continue
        created = datetime.fromisoformat(event["created_at"].replace("Z", "+00:00")).replace(tzinfo=None)
        if created < cutoff:
            continue
        repo_name = event["repo"]["name"]
        payload = event.get("payload", {})
        for commit in payload.get("commits", []):
            msg = commit.get("message", "").split("\n")[0]
            if msg:
                repo_commits.setdefault(repo_name, []).append(msg)

    signals = []
    for repo_name, messages in repo_commits.items():
        signals.append({
            "type": SignalType.github_commit,
            "source": repo_name,
            "title": f"{repo_name} — {len(messages)} new commits",
            "body": "\n".join(f"• {m}" for m in messages[:20]),
            "url": f"https://github.com/{repo_name}/commits",
            "raw_data": str(messages[:5])[:5000],
        })

    return signals


async def scout_hackernews(keywords: list[str] | None = None) -> list[dict]:
    """Pull HN stories via Algolia search for better keyword matching."""
    log.info("[scout] Scanning Hacker News (keywords: %s)...", keywords or settings.scout_hn_keywords)
    kw = keywords or settings.scout_hn_keywords
    async with httpx.AsyncClient() as client:
        if kw:
            # Use Algolia HN search — way better than scanning top stories
            signals = []
            seen_ids = set()
            for term in kw[:8]:
                try:
                    resp = await client.get(
                        "https://hn.algolia.com/api/v1/search_by_date",
                        params={"query": term, "tags": "story", "hitsPerPage": 5},
                        timeout=10,
                    )
                    if resp.status_code != 200:
                        continue
                    hits = resp.json().get("hits", [])
                    for hit in hits:
                        oid = hit.get("objectID", "")
                        if oid in seen_ids:
                            continue
                        seen_ids.add(oid)
                        signals.append({
                            "type": SignalType.hackernews,
                            "source": "hackernews",
                            "title": hit.get("title", ""),
                            "body": f"Score: {hit.get('points', 0)} | Comments: {hit.get('num_comments', 0)} | Matched: \"{term}\"",
                            "url": hit.get("url") or f"https://news.ycombinator.com/item?id={oid}",
                            "raw_data": str(hit)[:5000],
                        })
                except Exception:
                    continue
            return signals

        # Fallback: top stories if no keywords
        resp = await client.get("https://hacker-news.firebaseio.com/v0/topstories.json")
        if resp.status_code != 200:
            return []

        story_ids = resp.json()[:15]
        signals = []
        for sid in story_ids:
            sr = await client.get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
            if sr.status_code != 200:
                continue
            story = sr.json()
            if not story or "title" not in story:
                continue
            signals.append({
                "type": SignalType.hackernews,
                "source": "hackernews",
                "title": story["title"],
                "body": f"Score: {story.get('score', 0)} | Comments: {story.get('descendants', 0)}",
                "url": story.get("url", f"https://news.ycombinator.com/item?id={sid}"),
                "raw_data": str(story)[:5000],
            })
        return signals


async def scout_reddit(subreddits: list[str] | None = None) -> list[dict]:
    """Pull hot posts from subreddits."""
    subs = subreddits or settings.scout_subreddits
    log.info("[scout] Scanning Reddit (subreddits: %s)...", subs)
    signals = []
    async with httpx.AsyncClient() as client:
        for sub in subs:
            try:
                resp = await client.get(
                    f"https://www.reddit.com/r/{sub}/hot.json",
                    headers={"User-Agent": "Pressroom/0.1"},
                    params={"limit": 5},
                    timeout=6,
                )
                if resp.status_code != 200:
                    continue
                data = resp.json().get("data", {}).get("children", [])
                for post in data:
                    p = post["data"]
                    if p.get("stickied"):
                        continue  # skip pinned mod posts
                    signals.append({
                        "type": SignalType.reddit,
                        "source": f"r/{sub}",
                        "title": p["title"],
                        "body": p.get("selftext", "")[:1000],
                        "url": f"https://reddit.com{p['permalink']}",
                        "raw_data": str(p)[:5000],
                    })
            except Exception:
                continue
    return signals


async def scout_rss(feeds: list[str] | None = None) -> list[dict]:
    """Pull recent entries from RSS feeds."""
    feed_urls = feeds or settings.scout_rss_feeds
    log.info("[scout] Scanning %d RSS feeds...", len(feed_urls))
    signals = []
    for url in feed_urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                signals.append({
                    "type": SignalType.rss,
                    "source": feed.feed.get("title", url),
                    "title": entry.get("title", "Untitled"),
                    "body": entry.get("summary", "")[:1000],
                    "url": entry.get("link", ""),
                    "raw_data": str(entry)[:5000],
                })
        except Exception:
            continue
    return signals


async def scout_google_news(keywords: list[str]) -> list[dict]:
    """Pull recent news articles from Google News RSS by keyword."""
    log.info("[scout] Scanning Google News (%d keywords)...", len(keywords))
    signals = []
    for kw in keywords[:8]:
        try:
            url = f"https://news.google.com/rss/search?q={kw}&hl=en-US&gl=US&ceid=US:en"
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                signals.append({
                    "type": SignalType.google_news,
                    "source": f"gnews:{kw}",
                    "title": entry.get("title", "Untitled"),
                    "body": entry.get("summary", "")[:1000],
                    "url": entry.get("link", ""),
                    "raw_data": str(entry)[:5000],
                })
        except Exception:
            continue
    return signals


async def scout_devto(tags: list[str]) -> list[dict]:
    """Pull top recent articles from Dev.to by tag."""
    log.info("[scout] Scanning Dev.to (tags: %s)...", tags)
    signals = []
    async with httpx.AsyncClient() as client:
        for tag in tags[:8]:
            try:
                resp = await client.get(
                    "https://dev.to/api/articles",
                    params={"tag": tag, "per_page": 5, "top": 7},
                    timeout=8,
                )
                if resp.status_code != 200:
                    continue
                articles = resp.json()
                for a in articles:
                    signals.append({
                        "type": SignalType.devto,
                        "source": f"dev.to/{tag}",
                        "title": a.get("title", "Untitled"),
                        "body": f"{a.get('description', '')} | Reactions: {a.get('positive_reactions_count', 0)} | Comments: {a.get('comments_count', 0)}",
                        "url": a.get("url", ""),
                        "raw_data": str(a)[:5000],
                    })
            except Exception:
                continue
    return signals


async def scout_producthunt() -> list[dict]:
    """Pull trending products from Product Hunt RSS feed."""
    log.info("[scout] Scanning Product Hunt...")
    signals = []
    try:
        feed = feedparser.parse("https://www.producthunt.com/feed")
        for entry in feed.entries[:10]:
            signals.append({
                "type": SignalType.producthunt,
                "source": "producthunt",
                "title": entry.get("title", "Untitled"),
                "body": entry.get("summary", "")[:1000],
                "url": entry.get("link", ""),
                "raw_data": str(entry)[:5000],
            })
    except Exception:
        pass
    return signals


async def scout_web_search(queries: list[str], company_context: str = "",
                           api_key: str | None = None) -> list[dict]:
    """Use Claude web search to find industry trends and news for content creation."""
    if not queries:
        return []

    log.info("[scout] Running web search (%d queries)...", len(queries))
    signals = []
    try:
        client = anthropic.Anthropic(api_key=api_key or settings.anthropic_api_key)

        for query in queries[:6]:  # cap at 6 queries to limit cost
            try:
                response = client.messages.create(
                    model=settings.claude_model_fast,
                    max_tokens=2000,
                    tools=[{"type": "web_search_20250305", "name": "web_search"}],
                    messages=[{"role": "user", "content": (
                        f"Search the web for recent news and trends about: {query}\n\n"
                        f"Company context: {company_context}\n\n"
                        "Find 3-5 recent, specific stories or developments that a content "
                        "team could write about. For each, give me:\n"
                        "- A headline\n"
                        "- A 1-2 sentence summary\n"
                        "- The source URL\n\n"
                        "Focus on things from the last 7 days. Be specific — real stories, "
                        "real URLs, real developments. No generic advice."
                    )}],
                )

                await log_token_usage(None, "scout_web_search", response)
                # Extract text and citations from the response
                text_parts = []
                urls_found = []
                for block in response.content:
                    if block.type == "text":
                        text_parts.append(block.text)
                    elif block.type == "web_search_tool_result":
                        for result in (block.content or []):
                            url = result.get("url") if isinstance(result, dict) else getattr(result, "url", None)
                            if url:
                                title = result.get("title", "") if isinstance(result, dict) else getattr(result, "title", "")
                                urls_found.append({"url": url, "title": title})

                full_text = "\n".join(text_parts)
                if not full_text.strip():
                    continue

                # Create one signal per query with the full response
                signals.append({
                    "type": SignalType.web_search,
                    "source": f"web:{query}",
                    "title": f"Web trends: {query}",
                    "body": full_text[:3000],
                    "url": urls_found[0]["url"] if urls_found else "",
                    "raw_data": json.dumps({"query": query, "urls": urls_found[:10]})[:5000],
                })

                log.info("WEB SEARCH — query=%s → %d chars, %d URLs", query, len(full_text), len(urls_found))

            except Exception as e:
                log.warning("Web search failed for query '%s': %s", query, e)
                continue

    except Exception as e:
        log.warning("Web search scout failed: %s", e)

    return signals


async def scout_visibility_check(queries: list[str], domain: str,
                                  api_key: str | None = None) -> dict:
    """Check how visible a company's domain is when Claude searches for related topics.

    Returns a report with per-query visibility scores.
    """
    if not queries or not domain:
        return {"error": "Need queries and domain to check visibility"}

    # Normalize domain — strip protocol and trailing slash
    domain_clean = domain.lower().replace("https://", "").replace("http://", "").rstrip("/")

    results = []
    total_found = 0
    total_queries = 0

    try:
        client = anthropic.Anthropic(api_key=api_key or settings.anthropic_api_key)

        for query in queries[:10]:
            total_queries += 1
            try:
                response = client.messages.create(
                    model=settings.claude_model_fast,
                    max_tokens=1500,
                    tools=[{"type": "web_search_20250305", "name": "web_search"}],
                    messages=[{"role": "user", "content": (
                        f"Search the web for: {query}\n\n"
                        "List ALL the websites and URLs that appear in the search results. "
                        "Include every URL you find. Be thorough."
                    )}],
                )

                await log_token_usage(None, "scout_visibility", response)
                # Scan all response content for domain mentions
                found = False
                all_urls = []
                domain_urls = []
                position = None

                for block in response.content:
                    if block.type == "web_search_tool_result":
                        idx = 0
                        for result in (block.content or []):
                            url = result.get("url") if isinstance(result, dict) else getattr(result, "url", None)
                            if url:
                                idx += 1
                                all_urls.append(url)
                                if domain_clean in url.lower():
                                    found = True
                                    domain_urls.append(url)
                                    if position is None:
                                        position = idx
                    elif block.type == "text":
                        text = block.text.lower()
                        if domain_clean in text:
                            found = True

                if found:
                    total_found += 1

                results.append({
                    "query": query,
                    "found": found,
                    "position": position,
                    "domain_urls": domain_urls,
                    "total_results": len(all_urls),
                })

                log.info("VISIBILITY — query=%s domain=%s found=%s pos=%s (%d results)",
                         query, domain_clean, found, position, len(all_urls))

            except Exception as e:
                log.warning("Visibility check failed for query '%s': %s", query, e)
                results.append({"query": query, "found": False, "error": str(e)})

    except Exception as e:
        log.warning("Visibility check failed: %s", e)
        return {"error": str(e)}

    score = round((total_found / total_queries * 100)) if total_queries > 0 else 0

    return {
        "domain": domain_clean,
        "score": score,
        "queries_checked": total_queries,
        "queries_found": total_found,
        "results": results,
    }


async def scout_gsc(property_url: str, sa_json_raw: str = "", access_token: str = "") -> list[dict]:
    """Pull Google Search Console performance data as scout signals.

    Generates two signal types:
    - gsc_opportunity: queries with high impressions but low CTR (title/content gap)
    - gsc_ranking: queries already driving clicks (reinforce these topics)

    Requires either a service account JSON or a cached access token.
    """
    log.info("[scout] Scanning Google Search Console (%s)...", property_url)
    from services.gsc_client import GSCClient, service_account_access_token
    import json as _json
    import time as _time

    token = access_token

    # Mint fresh token from service account if needed
    if sa_json_raw and not token:
        try:
            sa = _json.loads(sa_json_raw)
            result = await service_account_access_token(sa)
            token = result.get("access_token", "")
        except Exception as e:
            log.warning("GSC scout — token mint failed: %s", e)
            return []

    if not token:
        return []

    try:
        client = GSCClient(token)
        # 28-day window, top 50 queries
        data = await client.search_analytics(property_url, days=28, dimensions=["query"], row_limit=50)
        rows = data.get("rows", [])
        if not rows:
            return []

        signals = []
        for row in rows:
            query = row.get("keys", [""])[0]
            clicks = row.get("clicks", 0)
            impressions = row.get("impressions", 0)
            ctr = row.get("ctr", 0)
            position = row.get("position", 0)

            # High-impression, low-CTR = content/title gap — good signal for new content
            if impressions >= 50 and ctr < 0.03 and position <= 20:
                signals.append({
                    "type": SignalType.web_search,
                    "source": "gsc_opportunity",
                    "title": f"GSC gap: '{query}' — {impressions} impressions, {ctr*100:.1f}% CTR (pos {position:.1f})",
                    "body": (
                        f"Search query '{query}' is getting {impressions} impressions/month but only "
                        f"{ctr*100:.1f}% CTR at position {position:.1f}. "
                        f"Strong content opportunity — write something that better matches search intent."
                    ),
                    "url": f"https://search.google.com/search-console/performance/search-analytics?resource_id={property_url}",
                    "score": min(100, int(impressions / 10)),
                })

            # Solid performing queries — reinforce these topics
            elif clicks >= 10 and position <= 10:
                signals.append({
                    "type": SignalType.web_search,
                    "source": "gsc_ranking",
                    "title": f"GSC ranking: '{query}' — {clicks} clicks, pos {position:.1f}",
                    "body": (
                        f"Already ranking well for '{query}' ({clicks} clicks, position {position:.1f}). "
                        f"Consider fresh content on this topic to maintain and extend the ranking."
                    ),
                    "url": f"https://search.google.com/search-console/performance/search-analytics?resource_id={property_url}",
                    "score": min(100, int(clicks * 2)),
                })

        log.info("GSC SCOUT — %s: %d signals from %d queries", property_url, len(signals), len(rows))
        return signals[:10]  # cap at 10 to avoid flooding the wire

    except Exception as e:
        log.warning("GSC scout failed: %s", e)
        return []


async def run_full_scout(since_hours: int = 24, org_settings: dict | None = None,
                         api_key: str | None = None,
                         company_context: str = "",
                         on_progress=None,
                         sources: list[str] | None = None) -> list[dict]:
    """Run all scout sources. Uses org-specific settings if provided.

    on_progress: optional async callable(msg: str) for streaming log updates.
    sources: optional list of source keys to run. If None/empty, all are run.
             Valid keys: 'github', 'hn', 'reddit', 'rss', 'google_news', 'devto', 'producthunt', 'web', 'gsc'
    """
    log.info("=" * 60)
    log.info("[scout] FULL SCOUT — starting (lookback=%dh, sources=%s)", since_hours, sources or "all")
    log.info("=" * 60)
    enabled = set(sources) if sources else None  # None = all enabled
    all_signals = []

    async def _progress(msg: str):
        log.info("SCOUT — %s", msg)
        if on_progress:
            await on_progress(msg)

    # Parse org settings or fall back to global config
    if org_settings:
        repos = _parse_json_list(org_settings.get("scout_github_repos", ""), settings.scout_github_repos)
        gh_orgs = _parse_json_list(org_settings.get("scout_github_orgs", ""), [])
        hn_kw = _parse_json_list(org_settings.get("scout_hn_keywords", ""), settings.scout_hn_keywords)
        subs = _parse_json_list(org_settings.get("scout_subreddits", ""), settings.scout_subreddits)
        rss = _parse_json_list(org_settings.get("scout_rss_feeds", ""), settings.scout_rss_feeds)
        web_queries = _parse_json_list(org_settings.get("scout_web_queries", ""), [])
        # Token priority: org DB setting → GitHub App installation token → global config
        gh_token = org_settings.get("github_token", "") or await get_github_token() or settings.github_token

        # Expand GitHub orgs into repos
        existing = set(r.lower() for r in repos)
        for org_name in gh_orgs:
            try:
                discovered = await discover_github_repos(org_name, gh_token=gh_token)
                for r in discovered:
                    if r.lower() not in existing:
                        repos.append(r)
                        existing.add(r.lower())
                await _progress(f"GitHub org {org_name} → {len(discovered)} repos discovered")
            except Exception:
                await _progress(f"GitHub org {org_name} → discovery failed, skipping")

        # Also auto-discover from social profile GitHub URL if few repos
        if len(repos) < 3:
            social_raw = org_settings.get("social_profiles", "")
            if social_raw:
                try:
                    socials = json.loads(social_raw) if isinstance(social_raw, str) else social_raw
                    github_url = socials.get("github", "")
                    if github_url:
                        discovered = await discover_github_repos(github_url, gh_token=gh_token)
                        for r in discovered:
                            if r.lower() not in existing:
                                repos.append(r)
                                existing.add(r.lower())
                        await _progress(f"GitHub social profile → {len(discovered)} repos discovered (total: {len(repos)})")
                except Exception:
                    pass
    else:
        repos = settings.scout_github_repos
        hn_kw = settings.scout_hn_keywords
        subs = settings.scout_subreddits
        rss = settings.scout_rss_feeds
        web_queries = []
        gh_token = settings.github_token

    await _progress(
        f"sources: {len(repos)} GitHub repos, {len(hn_kw)} HN terms, "
        f"{len(subs)} subreddits, {len(rss)} RSS feeds"
        + (f", {len(web_queries)} web queries" if web_queries else "")
    )

    def _src_on(key: str) -> bool:
        return enabled is None or key in enabled

    # GitHub
    if _src_on('github'):
        # Commits: use org events feed (1 call per org) instead of per-repo calls
        org_covered_repos: set[str] = set()
        for org_name in (gh_orgs if org_settings else []):
            org_commits = await scout_github_org_commits(org_name, since_hours, gh_token)
            all_signals.extend(org_commits)
            org_covered_repos.update(s["source"].lower() for s in org_commits)
            # Also get releases for repos in this org that had recent activity
            active_repos = list({s["source"] for s in org_commits})
            rel_count = 0
            for repo in active_repos[:10]:
                releases = await scout_github_releases(repo, since_hours, gh_token)
                all_signals.extend(releases)
                rel_count += len(releases)
            await _progress(
                f"GitHub org {org_name} → {len(org_commits)} repos with commits, {rel_count} releases"
            )

        # Per-repo for explicit repos not covered by an org events feed
        uncovered = [r for r in repos if r.lower() not in org_covered_repos]
        for repo in uncovered:
            releases = await scout_github_releases(repo, since_hours, gh_token)
            commits = await scout_github_commits(repo, since_hours, gh_token)
            count = len(releases) + len(commits)
            all_signals.extend(releases)
            all_signals.extend(commits)
            await _progress(f"GitHub {repo} → {count} signals ({len(releases)} releases, {len(commits)} commits)")
    else:
        await _progress("GitHub → skipped")

    # Hacker News
    if _src_on('hn'):
        hn_signals = await scout_hackernews(hn_kw)
        all_signals.extend(hn_signals)
        await _progress(f"Hacker News → {len(hn_signals)} signals")
    else:
        await _progress("Hacker News → skipped")

    # Reddit
    if _src_on('reddit'):
        if subs:
            reddit_signals = await scout_reddit(subs)
            all_signals.extend(reddit_signals)
            await _progress(f"Reddit ({', '.join('r/'+s for s in subs[:3])}{'...' if len(subs) > 3 else ''}) → {len(reddit_signals)} signals")
        else:
            await _progress("Reddit → skipped (no subreddits configured)")
    else:
        await _progress("Reddit → skipped")

    # RSS
    if _src_on('rss'):
        if rss:
            rss_signals = await scout_rss(rss)
            all_signals.extend(rss_signals)
            await _progress(f"RSS ({len(rss)} feeds) → {len(rss_signals)} signals")
        else:
            await _progress("RSS → skipped (no feeds configured)")
    else:
        await _progress("RSS → skipped")

    # Google News
    if _src_on('google_news') and org_settings:
        gn_keywords = _parse_json_list(org_settings.get("scout_google_news_keywords", ""), [])
        if gn_keywords:
            gn_signals = await scout_google_news(gn_keywords)
            all_signals.extend(gn_signals)
            await _progress(f"Google News ({len(gn_keywords)} keywords) → {len(gn_signals)} signals")
        else:
            await _progress("Google News → skipped (no keywords configured)")
    elif _src_on('google_news'):
        await _progress("Google News → skipped")

    # Dev.to
    if _src_on('devto') and org_settings:
        devto_tags = _parse_json_list(org_settings.get("scout_devto_tags", ""), [])
        if devto_tags:
            devto_signals = await scout_devto(devto_tags)
            all_signals.extend(devto_signals)
            await _progress(f"Dev.to ({', '.join(devto_tags[:3])}) → {len(devto_signals)} signals")
        else:
            await _progress("Dev.to → skipped (no tags configured)")
    elif _src_on('devto'):
        await _progress("Dev.to → skipped")

    # Product Hunt
    if _src_on('producthunt') and org_settings:
        ph_enabled = org_settings.get("scout_producthunt_enabled", "")
        if ph_enabled == "true":
            ph_signals = await scout_producthunt()
            all_signals.extend(ph_signals)
            await _progress(f"Product Hunt → {len(ph_signals)} signals")
        else:
            await _progress("Product Hunt → skipped (not enabled)")
    elif _src_on('producthunt'):
        await _progress("Product Hunt → skipped")

    # Web search
    if _src_on('web') and web_queries:
        await _progress(f"Web search → running {len(web_queries)} queries...")
        web_signals = await scout_web_search(
            web_queries, company_context=company_context, api_key=api_key,
        )
        all_signals.extend(web_signals)
        await _progress(f"Web search → {len(web_signals)} signals")

    # GSC
    if _src_on('gsc') and org_settings:
        gsc_sa_json = org_settings.get("gsc_service_account_json", "")
        gsc_access_token = org_settings.get("gsc_access_token", "")
        gsc_property = org_settings.get("gsc_property", "")
        if (gsc_sa_json or gsc_access_token) and gsc_property:
            await _progress(f"GSC → checking {gsc_property}...")
            gsc_signals = await scout_gsc(gsc_property, gsc_sa_json, gsc_access_token)
            all_signals.extend(gsc_signals)
            await _progress(f"GSC → {len(gsc_signals)} signals")
        else:
            await _progress("GSC → skipped (not connected)")

    await _progress(f"scout complete — {len(all_signals)} total signals collected")
    log.info("[scout] FULL SCOUT — complete: %d total signals from all sources", len(all_signals))
    return all_signals


def _parse_json_list(raw: str, default: list) -> list:
    """Parse a JSON list from settings string, with fallback."""
    if not raw:
        return default
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) and parsed else default
    except (json.JSONDecodeError, TypeError):
        return default


# ──────────────────────────────────────
# Relevance Filter
# ──────────────────────────────────────

async def filter_signals_for_relevance(signals: list[dict], company_context: str,
                                       api_key: str | None = None) -> list[dict]:
    """Use Claude to score signals for relevance to this company. Discard junk."""
    log.info("[scout] RELEVANCE FILTER — scoring %d signals for relevance...", len(signals))
    if not signals or len(signals) <= 3:
        log.info("[scout] Skipping filter — only %d signals (threshold: 4)", len(signals))
        return signals  # not worth filtering tiny batches

    # Build a compact list for Claude
    signal_list = []
    for i, s in enumerate(signals):
        title = s.get("title", "?")
        body_preview = s.get("body", "")[:100].replace("\n", " ")
        signal_list.append(f"{i}. [{s.get('type', '?')}] {s.get('source', '?')}: {title}")
        if body_preview:
            signal_list.append(f"   {body_preview}")

    signals_text = "\n".join(signal_list)

    prompt = f"""Rate each signal for relevance to this company's content engine.

COMPANY:
{company_context}

SIGNALS:
{signals_text}

Return ONLY a JSON array:
[{{"i": 0, "r": true}}, {{"i": 1, "r": false}}, ...]

Rules:
- r=true if the signal could inspire content this company's audience cares about
- r=false if off-topic, about unrelated software/tools, or generic noise
- Own GitHub repos/releases → ALWAYS relevant
- Be strict. Quality over quantity."""

    try:
        log.info("[scout] Calling Claude (%s) for relevance scoring...", settings.claude_model_fast)
        client = anthropic.Anthropic(api_key=api_key or settings.anthropic_api_key)
        response = client.messages.create(
            model=settings.claude_model_fast,
            max_tokens=1500,
            system="Strict relevance filter. Return valid JSON array only.",
            messages=[{"role": "user", "content": prompt}],
        )
        await log_token_usage(None, "scout_relevance_filter", response)

        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        # Find the array
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            text = text[start:end + 1]

        ratings = json.loads(text)
        if not isinstance(ratings, list):
            return signals

        relevant_indices = {r.get("i", r.get("index", -1)) for r in ratings if r.get("r", r.get("relevant"))}
        filtered = [s for i, s in enumerate(signals) if i in relevant_indices]

        dropped = len(signals) - len(filtered)
        if dropped:
            log.info("RELEVANCE FILTER — kept %d/%d signals (dropped %d)",
                     len(filtered), len(signals), dropped)

        return filtered if filtered else signals  # never return empty

    except Exception as e:
        log.warning("Relevance filter failed (%s), keeping all signals", e)
        return signals


# ──────────────────────────────────────
# Source Suggestions
# ──────────────────────────────────────

SUGGEST_PROMPT = """You are a marketing intelligence analyst. Given a company profile, suggest monitoring sources for a news scout system.

Return a JSON object with these keys:
- scout_subreddits: array of subreddit names (no r/ prefix) where this company's audience or competitors are active
- scout_hn_keywords: array of Hacker News search keywords/phrases relevant to this company's space
- scout_rss_feeds: array of RSS feed URLs for industry blogs, news sites, or competitors
- scout_web_queries: array of search queries to find trending topics in this space

Guidelines:
- 3-6 items per category
- Subreddits should be active communities, not dead ones
- HN keywords should catch relevant discussions (product names, tech terms, industry phrases)
- RSS feeds should be real, working feed URLs from known tech/industry blogs
- Web queries should find emerging trends, not just the company's own content
- Focus on the company's specific niche, not generic tech news

Return ONLY valid JSON. No explanation."""


async def suggest_scout_sources(company_context: str, existing_sources: dict | None = None, api_key: str | None = None) -> dict:
    """Use Claude to suggest scout sources based on company context.

    Returns dict with keys matching SOURCE_TYPES settings keys, each an array of suggestions.
    """
    log.info("[scout] SUGGEST SOURCES — generating source recommendations...")
    api_key = api_key or settings.anthropic_api_key
    client = anthropic.Anthropic(api_key=api_key)

    user_msg = f"COMPANY PROFILE:\n{company_context}"

    if existing_sources:
        already = []
        for key, vals in existing_sources.items():
            if vals:
                already.append(f"  {key}: {', '.join(vals)}")
        if already:
            user_msg += f"\n\nALREADY CONFIGURED (suggest NEW ones, not duplicates):\n" + "\n".join(already)

    try:
        response = client.messages.create(
            model=settings.claude_model_fast,
            max_tokens=1500,
            system=SUGGEST_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        await log_token_usage(None, "scout_suggest_sources", response)

        text = response.content[0].text.strip()

        # Extract JSON from response
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        suggestions = json.loads(text)

        # Filter out any that are already configured
        if existing_sources:
            for key in suggestions:
                if key in existing_sources and isinstance(suggestions[key], list):
                    existing_set = {v.lower().strip() for v in existing_sources.get(key, [])}
                    suggestions[key] = [v for v in suggestions[key] if v.lower().strip() not in existing_set]

        log.info("[scout] SUGGEST SOURCES — generated: %s", {k: len(v) for k, v in suggestions.items() if isinstance(v, list)})
        return suggestions

    except Exception as e:
        log.error("Source suggestion failed: %s", e)
        return {"error": str(e)}
