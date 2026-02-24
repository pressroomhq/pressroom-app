"""Wire API — company-owned feeds (GitHub, blog, changelog, docs).

Wire is the internal pulse of a company. Always relevant — no scoring needed.
Separate from Scout/SIGINT, which is external industry intelligence.

Wire source types:
  github_repo   — a specific repo (releases + commits)
  github_org    — auto-discover all repos under an org/user
  blog_rss      — company blog RSS feed
  changelog     — changelog RSS or URL
  docs_rss      — documentation RSS

Wire signals feed directly into content gen alongside SIGINT signals.
"""

import json
import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

from database import get_data_layer
from services.data_layer import DataLayer

router = APIRouter(prefix="/api/wire", tags=["wire"])


# ── Request models ────────────────────────────────────────────────────────────

class WireSourceCreate(BaseModel):
    type: str                 # github_repo | github_org | blog_rss | changelog | docs_rss
    name: str                 # human label
    config: dict = {}         # type-specific: {repo: "owner/repo"} or {url: "..."} etc.


class WireSourceUpdate(BaseModel):
    name: Optional[str] = None
    config: Optional[dict] = None
    active: Optional[int] = None


class FetchRequest(BaseModel):
    wire_source_id: Optional[int] = None   # None = fetch all for this org


# ── Wire sources ──────────────────────────────────────────────────────────────

@router.get("/sources")
async def list_wire_sources(dl: DataLayer = Depends(get_data_layer)):
    """List all Wire sources for this org."""
    from database import async_session
    from models import WireSource
    from sqlalchemy import select

    async with async_session() as session:
        result = await session.execute(
            select(WireSource)
            .where(WireSource.org_id == dl.org_id)
            .order_by(WireSource.type, WireSource.name)
        )
        sources = result.scalars().all()
        return [_serialize_wire_source(s) for s in sources]


@router.post("/sources")
async def create_wire_source(req: WireSourceCreate, dl: DataLayer = Depends(get_data_layer)):
    """Add a Wire source for this org."""
    from database import async_session
    from models import WireSource

    if not dl.org_id:
        return {"error": "No org selected"}

    async with async_session() as session:
        source = WireSource(
            org_id=dl.org_id,
            type=req.type,
            name=req.name,
            config=json.dumps(req.config),
            active=1,
        )
        session.add(source)
        await session.commit()
        return _serialize_wire_source(source)


@router.patch("/sources/{source_id}")
async def update_wire_source(
    source_id: int, req: WireSourceUpdate, dl: DataLayer = Depends(get_data_layer)
):
    """Update a Wire source."""
    from database import async_session
    from models import WireSource
    from sqlalchemy import select

    async with async_session() as session:
        result = await session.execute(
            select(WireSource).where(
                WireSource.id == source_id, WireSource.org_id == dl.org_id
            )
        )
        source = result.scalar_one_or_none()
        if not source:
            return {"error": "Wire source not found"}

        if req.name is not None:
            source.name = req.name
        if req.config is not None:
            source.config = json.dumps(req.config)
        if req.active is not None:
            source.active = req.active

        await session.commit()
        return _serialize_wire_source(source)


@router.delete("/sources/{source_id}")
async def delete_wire_source(source_id: int, dl: DataLayer = Depends(get_data_layer)):
    """Delete a Wire source and its signals."""
    from database import async_session
    from models import WireSource
    from sqlalchemy import select

    async with async_session() as session:
        result = await session.execute(
            select(WireSource).where(
                WireSource.id == source_id, WireSource.org_id == dl.org_id
            )
        )
        source = result.scalar_one_or_none()
        if not source:
            return {"error": "Wire source not found"}
        await session.delete(source)
        await session.commit()
        return {"deleted": source_id}


# ── Wire fetch ────────────────────────────────────────────────────────────────

@router.post("/fetch")
async def fetch_wire(req: FetchRequest = FetchRequest(), dl: DataLayer = Depends(get_data_layer)):
    """Fetch fresh signals from Wire sources for this org."""
    from database import async_session
    from models import WireSource, WireSignal
    from sqlalchemy import select

    if not dl.org_id:
        return {"error": "No org selected"}

    async with async_session() as session:
        query = select(WireSource).where(
            WireSource.org_id == dl.org_id, WireSource.active == 1
        )
        if req.wire_source_id:
            query = query.where(WireSource.id == req.wire_source_id)

        result = await session.execute(query)
        sources = result.scalars().all()

        results = []
        for source in sources:
            res = await _fetch_wire_source(source, dl.org_id, session)
            results.append(res)

        total_new = sum(r.get("new", 0) for r in results)
        return {"fetched_sources": len(sources), "total_new": total_new, "sources": results}


# ── Wire signals feed ─────────────────────────────────────────────────────────

@router.get("/signals")
async def get_wire_signals(
    limit: int = 40,
    type: Optional[str] = None,
    dl: DataLayer = Depends(get_data_layer),
):
    """Return recent Wire signals for this org."""
    from database import async_session
    from models import WireSignal
    from sqlalchemy import select

    if not dl.org_id:
        return []

    async with async_session() as session:
        query = (
            select(WireSignal)
            .where(WireSignal.org_id == dl.org_id)
            .order_by(WireSignal.fetched_at.desc())
            .limit(limit)
        )
        if type:
            query = query.where(WireSignal.type == type)

        result = await session.execute(query)
        signals = result.scalars().all()
        return [_serialize_wire_signal(s) for s in signals]


@router.get("/gist-suggestions")
async def get_gist_suggestions(dl: DataLayer = Depends(get_data_layer)):
    """Return pending gist suggestions for team members, newest first."""
    from database import async_session
    from models import WireSignal
    from sqlalchemy import select

    if not dl.org_id:
        return []

    async with async_session() as session:
        result = await session.execute(
            select(WireSignal)
            .where(
                WireSignal.org_id == dl.org_id,
                WireSignal.type == "github_gist_suggestion",
            )
            .order_by(WireSignal.fetched_at.desc())
            .limit(50)
        )
        signals = result.scalars().all()
        return [_serialize_wire_signal(s) for s in signals]


@router.get("/members")
async def get_github_members(dl: DataLayer = Depends(get_data_layer)):
    """Return team members with their matched GitHub usernames."""
    from database import async_session
    from models import TeamMember
    from sqlalchemy import select

    if not dl.org_id:
        return []

    async with async_session() as session:
        result = await session.execute(
            select(TeamMember)
            .where(TeamMember.org_id == dl.org_id)
            .order_by(TeamMember.name)
        )
        members = result.scalars().all()
        return [
            {
                "id": m.id,
                "name": m.name,
                "title": m.title,
                "github_username": m.github_username,
                "github_url": f"https://github.com/{m.github_username}" if m.github_username else None,
                "matched": bool(m.github_username),
            }
            for m in members
        ]


@router.patch("/members/{member_id}/github")
async def set_member_github(
    member_id: int,
    body: dict,
    dl: DataLayer = Depends(get_data_layer),
):
    """Manually set or correct a team member's GitHub username."""
    from database import async_session
    from models import TeamMember
    from sqlalchemy import select

    username = body.get("github_username", "").strip()

    async with async_session() as session:
        result = await session.execute(
            select(TeamMember).where(
                TeamMember.id == member_id,
                TeamMember.org_id == dl.org_id,
            )
        )
        member = result.scalar_one_or_none()
        if not member:
            return {"error": "Team member not found"}
        member.github_username = username
        await session.commit()
        return {"id": member.id, "name": member.name, "github_username": member.github_username}


# ── Wire fetchers ─────────────────────────────────────────────────────────────

async def _fetch_wire_source(source, org_id: int, session) -> dict:
    """Dispatch to the correct fetcher for this source type."""
    config = {}
    try:
        config = json.loads(source.config) if source.config else {}
    except Exception:
        pass

    fetchers = {
        "github_repo": _fetch_github_repo,
        "blog_rss": _fetch_feed,
        "changelog": _fetch_feed,
        "docs_rss": _fetch_feed,
    }

    fetcher = fetchers.get(source.type)

    try:
        if source.type == "github_org":
            items = await _fetch_github_org(config, org_id=org_id)
        elif fetcher:
            items = await fetcher(config)
        else:
            return {"source": source.name, "new": 0, "error": "unknown type"}
    except Exception as e:
        return {"source": source.name, "new": 0, "error": str(e)}

    if not items:
        return {"source": source.name, "new": 0}

    from models import WireSignal
    from sqlalchemy import select

    # URL dedup
    urls = [i["url"] for i in items if i.get("url")]
    if urls:
        existing_res = await session.execute(
            select(WireSignal.url).where(
                WireSignal.org_id == org_id,
                WireSignal.url.in_(urls),
            )
        )
        existing_urls = set(r[0] for r in existing_res.fetchall())
        items = [i for i in items if i.get("url") not in existing_urls]

    new_count = 0
    for item in items:
        sig = WireSignal(
            org_id=org_id,
            wire_source_id=source.id,
            type=item.get("type", source.type),
            source_name=source.name,
            title=item["title"][:500],
            body=item.get("body", "")[:2000],
            url=item.get("url", ""),
            raw_data=item.get("raw_data", "{}"),
            fetched_at=datetime.datetime.utcnow(),
        )
        session.add(sig)
        new_count += 1

    source.last_fetched_at = datetime.datetime.utcnow()
    await session.commit()
    return {"source": source.name, "new": new_count}


import httpx
import feedparser
import re


async def _fetch_github_repo(config: dict) -> list[dict]:
    """Fetch releases and recent commits from a GitHub repo."""
    repo = config.get("repo", "")
    token = config.get("token", "")
    if not repo:
        return []

    headers = {"Accept": "application/vnd.github+json", "User-Agent": "PressroomHQ/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    items = []
    since_hours = config.get("since_hours", 72)
    since = (datetime.datetime.utcnow() - datetime.timedelta(hours=since_hours)).isoformat() + "Z"

    async with httpx.AsyncClient(timeout=15, headers=headers) as client:
        # Releases
        try:
            resp = await client.get(f"https://api.github.com/repos/{repo}/releases?per_page=5")
            if resp.status_code == 200:
                for rel in resp.json():
                    items.append({
                        "type": "github_release",
                        "title": f"{repo} {rel.get('tag_name', '')} — {rel.get('name', '')}",
                        "body": (rel.get("body") or "")[:1000],
                        "url": rel.get("html_url", ""),
                        "raw_data": json.dumps({"tag": rel.get("tag_name"), "prerelease": rel.get("prerelease")}),
                    })
        except Exception:
            pass

        # Recent commits (bundled as one signal)
        try:
            resp = await client.get(
                f"https://api.github.com/repos/{repo}/commits?per_page=10&since={since}"
            )
            if resp.status_code == 200:
                commits = resp.json()
                if commits:
                    messages = [c["commit"]["message"].split("\n")[0] for c in commits[:5]]
                    items.append({
                        "type": "github_commit",
                        "title": f"{repo}: {len(commits)} recent commits",
                        "body": "\n".join(f"• {m}" for m in messages),
                        "url": f"https://github.com/{repo}/commits",
                        "raw_data": json.dumps({"count": len(commits), "repo": repo}),
                    })
        except Exception:
            pass

    return items


async def _fetch_github_org(config: dict, org_id: int = None) -> list[dict]:
    """Auto-discover active repos, scan org members, match to team members, suggest gists."""
    org = config.get("org", "")
    token = config.get("token", "")
    if not org:
        return []

    headers = {"Accept": "application/vnd.github+json", "User-Agent": "PressroomHQ/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    items = []

    async with httpx.AsyncClient(timeout=20, headers=headers) as client:
        # ── 1. Repos + releases ───────────────────────────────────────────────
        repos = []
        try:
            resp = await client.get(
                f"https://api.github.com/orgs/{org}/repos?per_page=20&sort=updated&type=public"
            )
            if resp.status_code == 200:
                repos = [r for r in resp.json() if not r.get("archived") and not r.get("disabled")]
                for repo in repos[:10]:
                    repo_name = repo["full_name"]
                    rel_resp = await client.get(
                        f"https://api.github.com/repos/{repo_name}/releases?per_page=2"
                    )
                    if rel_resp.status_code == 200:
                        for rel in rel_resp.json():
                            items.append({
                                "type": "github_release",
                                "title": f"{repo_name} {rel.get('tag_name', '')} — {rel.get('name', '')}",
                                "body": (rel.get("body") or "")[:1000],
                                "url": rel.get("html_url", ""),
                                "raw_data": json.dumps({"repo": repo_name, "tag": rel.get("tag_name")}),
                            })
        except Exception:
            pass

        # ── 2. Org members scan ───────────────────────────────────────────────
        gh_members = []
        try:
            resp = await client.get(
                f"https://api.github.com/orgs/{org}/members?per_page=50"
            )
            if resp.status_code == 200:
                for member in resp.json():
                    login = member.get("login", "")
                    if not login:
                        continue
                    # Fetch full profile for name
                    profile_resp = await client.get(f"https://api.github.com/users/{login}")
                    if profile_resp.status_code == 200:
                        profile = profile_resp.json()
                        gh_members.append({
                            "login": login,
                            "name": profile.get("name") or login,
                            "bio": profile.get("bio") or "",
                            "blog": profile.get("blog") or "",
                            "avatar_url": profile.get("avatar_url") or "",
                            "profile_url": profile.get("html_url") or f"https://github.com/{login}",
                            "public_repos": profile.get("public_repos", 0),
                        })
        except Exception:
            pass

        # ── 3. Match GH members → TeamMembers, generate gist suggestions ─────
        if gh_members and org_id:
            gist_suggestions = await _match_members_and_suggest_gists(
                gh_members, repos, org_id, client
            )
            items.extend(gist_suggestions)

        # ── 4. Emit member scan signal (summary) ─────────────────────────────
        if gh_members:
            items.append({
                "type": "github_member_scan",
                "title": f"{org} GitHub org: {len(gh_members)} members scanned",
                "body": ", ".join(m["login"] for m in gh_members[:20]),
                "url": f"https://github.com/orgs/{org}/people",
                "raw_data": json.dumps({
                    "org": org,
                    "member_count": len(gh_members),
                    "members": [{"login": m["login"], "name": m["name"]} for m in gh_members],
                }),
            })

    return items


async def _match_members_and_suggest_gists(
    gh_members: list[dict],
    repos: list[dict],
    org_id: int,
    client: "httpx.AsyncClient",
) -> list[dict]:
    """Match GitHub org members to TeamMembers in DB, update github_username,
    then suggest gists based on what they've been working on recently."""
    from database import async_session
    from models import TeamMember
    from sqlalchemy import select

    suggestions = []

    async with async_session() as session:
        result = await session.execute(
            select(TeamMember).where(TeamMember.org_id == org_id)
        )
        team_members = result.scalars().all()

        for gh in gh_members:
            matched_member = None

            # Already matched by username
            for tm in team_members:
                if tm.github_username and tm.github_username.lower() == gh["login"].lower():
                    matched_member = tm
                    break

            # Name fuzzy match — normalize and compare
            if not matched_member and gh["name"] != gh["login"]:
                gh_name_norm = _normalize_name(gh["name"])
                for tm in team_members:
                    if gh_name_norm and _normalize_name(tm.name) == gh_name_norm:
                        matched_member = tm
                        break

            # Persist github_username on match
            if matched_member and not matched_member.github_username:
                matched_member.github_username = gh["login"]

            # Build gist suggestion regardless of match (unmatched = suggest linking)
            suggestion = await _build_gist_suggestion(
                gh, repos, matched_member, client
            )
            if suggestion:
                suggestions.append(suggestion)

        await session.commit()

    return suggestions


async def _build_gist_suggestion(
    gh_member: dict,
    org_repos: list[dict],
    team_member,   # TeamMember ORM object or None
    client: "httpx.AsyncClient",
) -> dict | None:
    """Fetch a member's recent public activity, pick the most interesting event,
    and generate a gist topic suggestion."""
    login = gh_member["login"]

    # Grab recent public events for this user
    recent_work = []
    try:
        resp = await client.get(
            f"https://api.github.com/users/{login}/events/public?per_page=10"
        )
        if resp.status_code == 200:
            for event in resp.json():
                etype = event.get("type", "")
                repo_name = event.get("repo", {}).get("name", "")
                payload = event.get("payload", {})

                if etype == "PushEvent":
                    commits = payload.get("commits", [])
                    messages = [c["message"].split("\n")[0] for c in commits[:3]]
                    if messages:
                        recent_work.append({
                            "type": "push",
                            "repo": repo_name,
                            "summary": "; ".join(messages),
                        })
                elif etype == "PullRequestEvent" and payload.get("action") == "closed" and payload.get("pull_request", {}).get("merged"):
                    pr = payload["pull_request"]
                    recent_work.append({
                        "type": "merged_pr",
                        "repo": repo_name,
                        "summary": pr.get("title", ""),
                        "url": pr.get("html_url", ""),
                    })
                elif etype == "CreateEvent" and payload.get("ref_type") == "branch":
                    recent_work.append({
                        "type": "new_branch",
                        "repo": repo_name,
                        "summary": f"New branch: {payload.get('ref', '')}",
                    })
    except Exception:
        pass

    if not recent_work:
        return None

    # Use the most recent interesting event as the gist seed
    best = next(
        (w for w in recent_work if w["type"] in ("merged_pr", "push")),
        recent_work[0],
    )

    display_name = team_member.name if team_member else gh_member["name"] or login
    member_title = (team_member.title if team_member else "") or "engineer"

    # Build a gist topic prompt from their recent work
    topic = _derive_gist_topic(best, member_title)

    body_lines = [
        f"**GitHub:** [{login}](https://github.com/{login})",
        f"**Recent work:** {best['summary']}",
        f"**Repo:** {best['repo']}",
        "",
        f"**Suggested gist:** {topic}",
    ]
    if not team_member:
        body_lines.append("\n⚠️ Not matched to a team member — add their GitHub username to link them.")

    member_ref = f"team:{team_member.id}" if team_member else f"gh:{login}"

    return {
        "type": "github_gist_suggestion",
        "title": f"Gist idea for {display_name}: {topic}",
        "body": "\n".join(body_lines),
        "url": f"https://github.com/{login}",
        "raw_data": json.dumps({
            "login": login,
            "display_name": display_name,
            "member_ref": member_ref,
            "team_member_id": team_member.id if team_member else None,
            "gist_topic": topic,
            "recent_work": best,
        }),
    }


def _normalize_name(name: str) -> str:
    """Lowercase, strip punctuation, normalize whitespace for fuzzy name matching."""
    import unicodedata
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = re.sub(r"[^\w\s]", "", name).lower().strip()
    return re.sub(r"\s+", " ", name)


def _derive_gist_topic(work: dict, member_title: str) -> str:
    """Turn a recent work event into a concrete gist topic suggestion."""
    summary = work.get("summary", "").lower()
    repo = work.get("repo", "").lower()
    wtype = work.get("type", "")

    # Pattern-based topic generation
    if "auth" in summary or "oauth" in summary or "jwt" in summary:
        return "How we handle authentication in our API layer"
    if "docker" in summary or "container" in summary or "k8s" in summary or "kubernetes" in summary:
        return "Our container deployment workflow"
    if "test" in summary or "spec" in summary or "coverage" in summary:
        return "How we approach testing in this codebase"
    if "perf" in summary or "optim" in summary or "cache" in summary or "speed" in summary:
        return "A performance optimization that made a real difference"
    if "migration" in summary or "schema" in summary or "db" in summary:
        return "Database migration patterns we use"
    if "ci" in summary or "deploy" in summary or "pipeline" in summary or "action" in summary:
        return "Our CI/CD pipeline explained"
    if "api" in summary or "endpoint" in summary or "rest" in summary or "graphql" in summary:
        return "Building clean API endpoints: what we learned"
    if "refactor" in summary or "cleanup" in summary:
        return "A refactor worth writing about — what changed and why"
    if wtype == "merged_pr":
        return f"What this PR taught me: {work['summary'][:60]}"
    if "fix" in summary or "bug" in summary:
        return "Debugging a tricky issue — walkthrough"

    # Generic fallback based on repo name
    repo_short = repo.split("/")[-1] if "/" in repo else repo
    return f"What I've been working on in {repo_short}"


async def _fetch_feed(config: dict) -> list[dict]:
    """Fetch any RSS/Atom feed for blog, changelog, docs."""
    url = config.get("url", "")
    if not url:
        return []
    limit = config.get("limit", 10)
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "PressroomHQ/1.0"})
            raw = resp.text

        feed = feedparser.parse(raw)
        items = []
        for entry in feed.entries[:limit]:
            title = entry.get("title", "")
            body = entry.get("summary", "") or ""
            body = re.sub(r"<[^>]+>", " ", body)
            body = re.sub(r"\s+", " ", body).strip()[:600]
            link = entry.get("link", "")
            items.append({
                "type": "blog_post",
                "title": title,
                "body": body,
                "url": link,
                "raw_data": json.dumps({"feed_url": url, "published": entry.get("published", "")}),
            })
        return items
    except Exception:
        return []


# ── Serializers ───────────────────────────────────────────────────────────────

def _serialize_wire_source(s) -> dict:
    config = {}
    try:
        config = json.loads(s.config) if s.config else {}
    except Exception:
        pass
    # Don't expose tokens
    config.pop("token", None)
    return {
        "id": s.id,
        "org_id": s.org_id,
        "type": s.type,
        "name": s.name,
        "config": config,
        "active": s.active,
        "last_fetched_at": s.last_fetched_at.isoformat() if s.last_fetched_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


def _serialize_wire_signal(s) -> dict:
    return {
        "id": s.id,
        "type": s.type,
        "source_name": s.source_name,
        "title": s.title,
        "body": s.body,
        "url": s.url,
        "prioritized": s.prioritized,
        "times_used": s.times_used,
        "fetched_at": s.fetched_at.isoformat() if s.fetched_at else None,
    }
