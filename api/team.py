"""Team Members — CRUD + AI-powered team discovery from company web pages."""

import json
import logging
import re

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from config import settings as app_settings
from database import get_data_layer
from services.data_layer import DataLayer
from services.team_scraper import extract_team_members

log = logging.getLogger("pressroom")

router = APIRouter(prefix="/api/team", tags=["team"])


class TeamMemberCreate(BaseModel):
    name: str
    title: str = ""
    bio: str = ""
    photo_url: str = ""
    linkedin_url: str = ""
    email: str = ""
    expertise_tags: list[str] = []


class TeamMemberUpdate(BaseModel):
    name: str | None = None
    title: str | None = None
    bio: str | None = None
    photo_url: str | None = None
    linkedin_url: str | None = None
    github_username: str | None = None
    email: str | None = None
    expertise_tags: list[str] | None = None
    voice_style: str | None = None
    linkedin_post_samples: str | None = None


# Team page URL patterns to look for in assets
_TEAM_LABEL_PATTERNS = re.compile(
    r"about|team|leadership|people|staff|who.?we.?are|our.?team|meet",
    re.IGNORECASE,
)

# Common team page paths to try if nothing found in assets
_TEAM_PATH_GUESSES = [
    "/about", "/about-us", "/team", "/our-team", "/about/team",
    "/company", "/company/team", "/leadership", "/people",
]


@router.get("")
async def list_team(dl: DataLayer = Depends(get_data_layer)):
    """List team members for the current org."""
    return await dl.list_team_members()


@router.post("")
async def add_team_member(req: TeamMemberCreate, dl: DataLayer = Depends(get_data_layer)):
    """Manually add a team member."""
    member = await dl.save_team_member(req.model_dump())
    await dl.commit()
    return member


@router.put("/{member_id}")
async def update_member(member_id: int, req: TeamMemberUpdate, dl: DataLayer = Depends(get_data_layer)):
    """Update a team member's info."""
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    if not fields:
        return {"error": "No fields to update"}
    member = await dl.update_team_member(member_id, **fields)
    if not member:
        return {"error": "Member not found"}
    await dl.commit()
    return member


@router.delete("/{member_id}")
async def delete_member(member_id: int, dl: DataLayer = Depends(get_data_layer)):
    """Remove a team member."""
    deleted = await dl.delete_team_member(member_id)
    if not deleted:
        return {"error": "Member not found"}
    await dl.commit()
    return {"deleted": member_id}


@router.post("/{member_id}/analyze-voice")
async def analyze_member_voice(member_id: int, dl: DataLayer = Depends(get_data_layer)):
    """Analyze a team member's writing style from their pasted LinkedIn post samples."""
    members = await dl.list_team_members()
    member = next((m for m in members if m["id"] == member_id), None)
    if not member:
        return {"error": "Member not found"}

    samples = (member.get("linkedin_post_samples") or "").strip()
    if not samples:
        return {"error": "No post samples saved — paste some LinkedIn posts first."}

    post_texts = [p.strip() for p in samples.split("\n---\n") if p.strip()]
    if not post_texts:
        post_texts = [samples]

    key = app_settings.anthropic_api_key
    if not key:
        return {"error": "No Anthropic API key configured."}

    import anthropic
    client = anthropic.Anthropic(api_key=key)

    posts_block = "\n\n---\n\n".join(post_texts[:15])
    name = member.get("name", "this person")

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        system="""Analyze LinkedIn posts and extract the author's writing voice and style.
Be specific and concrete — describe HOW they write, not just what they write about.
Keep your response to 3-5 sentences max.""",
        messages=[{"role": "user", "content": f"""Here are LinkedIn posts from {name}:

{posts_block}

Describe their LinkedIn writing style: sentence length, tone (personal/professional/conversational),
use of formatting (bullets/line breaks/emojis), how they open posts, storytelling patterns,
vocabulary level, and anything distinctive about how they communicate."""}],
    )

    style = response.content[0].text.strip()
    await dl.update_team_member(member_id, voice_style=style)
    await dl.commit()

    return {"success": True, "posts_analyzed": len(post_texts), "style": style}


@router.post("/link-github")
async def link_github(dl: DataLayer = Depends(get_data_layer)):
    """Auto-link team members to GitHub org members by name matching.

    Fetches the org's GitHub org members, then fuzzy-matches names against
    existing team members and sets github_username where confident.
    """
    from services.github_auth import get_github_token, get_github_headers
    import difflib

    settings_map = await dl.get_all_settings()
    social_profiles = {}
    try:
        import json
        social_profiles = json.loads(settings_map.get("social_profiles", "{}") or "{}")
    except Exception:
        pass

    github_url = social_profiles.get("github", "")
    if not github_url:
        return {"error": "No GitHub URL in social profiles. Run onboarding or add it in Settings."}

    # Extract org name from URL
    import re
    match = re.search(r'github\.com/([^/\s?#]+)', github_url)
    if not match:
        return {"error": f"Can't parse org name from {github_url}"}
    org_name = match.group(1)

    # Resolve token: GitHub App → org DB token → error with instructions
    token = await get_github_token()

    # If App token not available, try org-level personal token from settings
    if not token:
        token = settings_map.get("github_token", "")

    if not token:
        return {
            "error": "No GitHub token configured. Add a GitHub Personal Access Token in Settings → GitHub Token. "
                     "It needs 'read:org' scope to list org members."
        }

    # Quick auth check before burning API calls
    async with httpx.AsyncClient(timeout=10) as probe:
        check = await probe.get("https://api.github.com/user", headers=get_github_headers(token))
        if check.status_code == 401:
            return {
                "error": "GitHub token is invalid or expired. Update it in Settings → GitHub Token. "
                         "Generate a new one at github.com/settings/tokens with 'read:org' scope."
            }

    gh_headers = get_github_headers(token)

    # Fetch org members with pagination
    gh_members = []
    async with httpx.AsyncClient(timeout=15) as client:
        page = 1
        while True:
            resp = await client.get(
                f"https://api.github.com/orgs/{org_name}/members",
                headers=gh_headers,
                params={"per_page": 100, "page": page},
            )
            if resp.status_code == 403:
                return {
                    "error": f"GitHub token doesn't have permission to list members of '{org_name}'. "
                             "Make sure the token has 'read:org' scope."
                }
            if resp.status_code != 200:
                return {
                    "error": f"GitHub API error {resp.status_code} fetching org members for '{org_name}'. "
                             f"Response: {resp.text[:200]}"
                }
            batch = resp.json()
            if not batch:
                break
            # Fetch full profile for each to get display name
            for member in batch:
                try:
                    prof = await client.get(
                        f"https://api.github.com/users/{member['login']}",
                        headers=gh_headers,
                    )
                    if prof.status_code == 200:
                        data = prof.json()
                        gh_members.append({
                            "login": member["login"],
                            "name": data.get("name") or member["login"],
                        })
                except Exception:
                    gh_members.append({"login": member["login"], "name": member["login"]})
            if len(batch) < 100:
                break
            page += 1

    if not gh_members:
        return {"error": f"No members found in GitHub org '{org_name}'"}

    team = await dl.list_team_members()
    linked = 0
    matches = []

    def normalize(s: str) -> str:
        return re.sub(r'[^a-z0-9]', '', s.lower())

    for member in team:
        if member.get("github_username"):
            continue  # already linked
        member_norm = normalize(member["name"])
        best_score = 0
        best_login = None
        for gh in gh_members:
            gh_norm = normalize(gh["name"])
            score = difflib.SequenceMatcher(None, member_norm, gh_norm).ratio()
            if score > best_score:
                best_score = score
                best_login = gh["login"]
        if best_score >= 0.8 and best_login:
            await dl.update_team_member(member["id"], github_username=best_login)
            matches.append({"name": member["name"], "github": best_login, "confidence": round(best_score, 2)})
            linked += 1

    await dl.commit()
    return {
        "linked": linked,
        "matches": matches,
        "github_members_found": len(gh_members),
        "message": f"Linked {linked} team members to GitHub profiles from org '{org_name}'",
    }


@router.get("/gist-check")
async def gist_check(dl: DataLayer = Depends(get_data_layer)):
    """Check gist activity for all team members who have a github_username.

    Returns each member's gist count and a generated suggestion if they have none.
    """
    from services.github_auth import get_github_token, get_github_headers

    settings_map = await dl.get_all_settings()
    token = await get_github_token()
    if not token:
        token = settings_map.get("github_token", "")

    gh_headers = get_github_headers(token) if token else {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    team = await dl.list_team_members()
    results = []

    async with httpx.AsyncClient(timeout=10) as client:
        for member in team:
            username = member.get("github_username", "").strip()
            if not username:
                results.append({
                    "id": member["id"],
                    "name": member["name"],
                    "github_username": None,
                    "gist_count": None,
                    "recent_gists": [],
                    "status": "no_github",
                })
                continue

            try:
                resp = await client.get(
                    f"https://api.github.com/users/{username}/gists",
                    headers=gh_headers,
                    params={"per_page": 5},
                )
                if resp.status_code == 404:
                    results.append({
                        "id": member["id"],
                        "name": member["name"],
                        "github_username": username,
                        "gist_count": 0,
                        "recent_gists": [],
                        "status": "not_found",
                    })
                    continue
                if resp.status_code != 200:
                    results.append({
                        "id": member["id"],
                        "name": member["name"],
                        "github_username": username,
                        "gist_count": None,
                        "recent_gists": [],
                        "status": "api_error",
                    })
                    continue

                gists = resp.json()
                recent = [
                    {
                        "id": g["id"],
                        "description": g.get("description") or list(g.get("files", {}).keys())[0] if g.get("files") else "Untitled",
                        "url": g.get("html_url", ""),
                        "updated_at": g.get("updated_at", ""),
                    }
                    for g in (gists[:3] if isinstance(gists, list) else [])
                ]
                results.append({
                    "id": member["id"],
                    "name": member["name"],
                    "github_username": username,
                    "gist_count": len(gists),
                    "recent_gists": recent,
                    "status": "ok",
                    "needs_gist": len(gists) == 0,
                    "bio": member.get("bio", ""),
                    "title": member.get("title", ""),
                    "expertise_tags": member.get("expertise_tags", []),
                })
            except Exception as e:
                log.warning("Gist check failed for %s: %s", username, e)
                results.append({
                    "id": member["id"],
                    "name": member["name"],
                    "github_username": username,
                    "gist_count": None,
                    "recent_gists": [],
                    "status": "error",
                })

    return {"members": results}


@router.post("/{member_id}/generate-gist")
async def generate_gist_suggestion(member_id: int, dl: DataLayer = Depends(get_data_layer)):
    """Generate a gist idea + starter content for a team member who hasn't posted one.

    Uses their bio, title, and expertise tags to come up with something practical.
    Returns the suggested title, description, and markdown content ready to paste.
    """
    members = await dl.list_team_members()
    member = next((m for m in members if m["id"] == member_id), None)
    if not member:
        return {"error": "Member not found"}

    key = app_settings.anthropic_api_key
    if not key:
        return {"error": "No Anthropic API key configured"}

    name = member.get("name", "this person")
    title = member.get("title", "")
    bio = member.get("bio", "")
    tags = member.get("expertise_tags", [])
    tags_str = ", ".join(tags) if tags else "software development"
    voice_style = member.get("voice_style", "")

    import anthropic
    client = anthropic.Anthropic(api_key=key)

    voice_block = f"\nTheir writing style: {voice_style}\n" if voice_style else ""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1200,
        system="""You generate GitHub Gist ideas for developers who haven't shared any public gists yet.
A good gist is: practical, specific, useful to others, shows real expertise.
Examples: a bash script, a config snippet, a useful regex cheat sheet, a quick how-to in markdown.
Return ONLY valid JSON — no markdown fences, no commentary.""",
        messages=[{"role": "user", "content": f"""Generate a GitHub Gist for {name}.

Profile:
- Title: {title or 'Software Engineer'}
- Bio: {bio or 'No bio provided'}
- Expertise: {tags_str}{voice_block}

Return a JSON object with:
- "title": short gist title (filename style, e.g. "git-aliases.sh" or "docker-cleanup.md")
- "description": one-sentence description shown in GitHub gist list
- "content": the actual gist content (code, markdown, whatever fits best — 20-60 lines)
- "rationale": one sentence explaining why this gist fits this person

Make it genuinely useful, not generic. Pick the most specific, practical thing given their expertise."""}],
    )

    try:
        text = response.content[0].text.strip()
        # Strip markdown fences if Haiku wraps it anyway
        import re
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        data = json.loads(text)
        return {
            "member_id": member_id,
            "member_name": name,
            "suggestion": {
                "title": data.get("title", "snippet.md"),
                "description": data.get("description", ""),
                "content": data.get("content", ""),
                "rationale": data.get("rationale", ""),
            }
        }
    except Exception as e:
        log.error("Gist suggestion parse failed for member %s: %s — raw: %s", member_id, e, response.content[0].text[:200])
        return {"error": f"Failed to parse gist suggestion: {e}"}


@router.post("/{member_id}/publish-gist")
async def publish_gist(member_id: int, req: dict, dl: DataLayer = Depends(get_data_layer)):
    """Publish a gist to GitHub as the team member.

    Requires the member to have connected GitHub via OAuth (github_access_token).
    Body: { title, description, content, public? }
    """
    from sqlalchemy import select as sa_select
    from models import TeamMember as TM

    members = await dl.list_team_members()
    member = next((m for m in members if m["id"] == member_id), None)
    if not member:
        return {"error": "Member not found"}

    # Fetch token directly — list_team_members doesn't include sensitive fields
    row = await dl.db.execute(sa_select(TM).where(TM.id == member_id))
    tm = row.scalars().first()
    if not tm:
        return {"error": "Member not found"}

    token = tm.github_access_token or ""
    if not token:
        return {
            "error": "GitHub not connected for this member. Connect via OAuth first.",
            "oauth_url": f"/api/oauth/github?member_id={member_id}",
        }

    title = req.get("title", "snippet.md")
    description = req.get("description", "")
    content = req.get("content", "")
    public = req.get("public", True)

    if not content.strip():
        return {"error": "Gist content cannot be empty"}

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://api.github.com/gists",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={
                "description": description,
                "public": public,
                "files": {
                    title: {"content": content},
                },
            },
        )

    if resp.status_code == 401:
        return {"error": "GitHub token expired or revoked. Reconnect via OAuth."}
    if resp.status_code not in (200, 201):
        log.error("Gist publish failed for member %s: %s %s", member_id, resp.status_code, resp.text[:200])
        return {"error": f"GitHub API error {resp.status_code}"}

    gist = resp.json()
    log.info("Gist published for member %s: %s", member_id, gist.get("html_url"))
    return {
        "success": True,
        "gist_url": gist.get("html_url", ""),
        "gist_id": gist.get("id", ""),
        "member_name": member.get("name", ""),
    }


async def _discover_from_github(github_url: str, api_key: str | None = None) -> list[dict]:
    """Fallback: pull top contributors from GitHub org and convert to team member records."""
    from services.github_auth import get_github_token, get_github_headers

    match = re.search(r'github\.com/([^/\s?#]+)', github_url)
    if not match:
        return []
    org_name = match.group(1)

    token = await get_github_token()
    gh_headers = get_github_headers(token)

    # Fetch org repos, collect top contributors by commit count
    contributor_counts: dict[str, int] = {}
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        # Get org repos (most recently pushed first, cap at 20)
        repos_resp = await client.get(
            f"https://api.github.com/orgs/{org_name}/repos",
            headers=gh_headers,
            params={"per_page": 20, "sort": "pushed", "type": "public"},
        )
        if repos_resp.status_code != 200:
            log.warning("GitHub repos fetch failed for %s: %d", org_name, repos_resp.status_code)
            return []

        repos = repos_resp.json()
        if not isinstance(repos, list):
            return []

        # Collect contributors across top repos (cap at 5 repos to stay fast)
        for repo in repos[:5]:
            try:
                contrib_resp = await client.get(
                    f"https://api.github.com/repos/{org_name}/{repo['name']}/contributors",
                    headers=gh_headers,
                    params={"per_page": 30, "anon": "false"},
                )
                if contrib_resp.status_code != 200:
                    continue
                for c in contrib_resp.json():
                    if not isinstance(c, dict) or c.get("type") == "Bot":
                        continue
                    login = c.get("login", "")
                    if login:
                        contributor_counts[login] = contributor_counts.get(login, 0) + c.get("contributions", 0)
            except Exception:
                continue

        if not contributor_counts:
            return []

        # Top 10 contributors by total commits
        top_logins = sorted(contributor_counts, key=lambda k: contributor_counts[k], reverse=True)[:10]

        # Fetch full profiles
        profiles = []
        for login in top_logins:
            try:
                prof_resp = await client.get(
                    f"https://api.github.com/users/{login}",
                    headers=gh_headers,
                )
                if prof_resp.status_code == 200:
                    profiles.append(prof_resp.json())
            except Exception:
                continue

    if not profiles:
        return []

    # Use Claude Haiku to convert GitHub profiles → team member records
    key = api_key or app_settings.anthropic_api_key
    if not key:
        # Manual conversion without Claude
        members = []
        for p in profiles:
            name = p.get("name") or p.get("login", "")
            if not name:
                continue
            members.append({
                "name": name,
                "title": p.get("company", "").strip("@ ") or "Contributor",
                "bio": p.get("bio") or "",
                "photo_url": p.get("avatar_url") or "",
                "linkedin_url": "",
                "email": p.get("email") or "",
                "expertise_tags": [],
            })
        return members

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        profile_text = json.dumps([{
            "login": p.get("login"),
            "name": p.get("name"),
            "bio": p.get("bio"),
            "company": p.get("company"),
            "blog": p.get("blog"),
            "email": p.get("email"),
            "avatar_url": p.get("avatar_url"),
            "public_repos": p.get("public_repos"),
            "followers": p.get("followers"),
        } for p in profiles], indent=2)

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            system="""Convert GitHub contributor profiles into team member records.
Return a JSON array only — no markdown, no commentary.""",
            messages=[{"role": "user", "content": f"""GitHub org: {org_name}

Contributor profiles:
{profile_text}

Return a JSON array of team members. For each person:
- name: their display name (or login if no name set)
- title: infer from bio/company (e.g. "Software Engineer", "Open Source Contributor")
- bio: their GitHub bio, cleaned up (empty string if none)
- photo_url: their avatar_url
- linkedin_url: empty string (we don't have this)
- email: their public email (empty string if none)
- expertise_tags: 2-4 tags inferred from bio, company, and repos they contribute to

Only include people who appear to be actual team members (not bots, not obvious outsiders).
Return ONLY the JSON array."""}],
        )
        text = response.content[0].text.strip()
        # Strip markdown fences if present
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            return []
        result = []
        for m in parsed:
            if not isinstance(m, dict) or not m.get("name"):
                continue
            result.append({
                "name": str(m.get("name", "")).strip(),
                "title": str(m.get("title", "")).strip(),
                "bio": str(m.get("bio", "")).strip(),
                "photo_url": str(m.get("photo_url", "")).strip(),
                "linkedin_url": str(m.get("linkedin_url", "")).strip(),
                "email": str(m.get("email", "")).strip(),
                "expertise_tags": m.get("expertise_tags", []) if isinstance(m.get("expertise_tags"), list) else [],
            })
        log.info("TEAM GITHUB — found %d contributors from org '%s'", len(result), org_name)
        return result
    except Exception as e:
        log.warning("GitHub team conversion failed: %s", e)
        return []


@router.post("/discover")
async def discover_team(dl: DataLayer = Depends(get_data_layer)):
    """Discover team members by scraping About/Team pages.

    Looks through existing org assets for team-related pages first,
    then tries common URL patterns on the org domain.
    """
    api_key = await dl.resolve_api_key()

    # Get the org's domain
    domain = ""
    if dl.org_id:
        org = await dl.get_org(dl.org_id)
        domain = org.get("domain", "") if org else ""
    if not domain:
        settings = await dl.get_all_settings()
        domain = settings.get("onboard_domain", "")

    if not domain:
        return {"error": "No domain configured. Onboard a company first."}

    if not domain.startswith("http"):
        domain = f"https://{domain}"
    domain = domain.rstrip("/")

    # Step 1: Check existing assets for team-related pages
    assets = await dl.list_assets()
    candidate_urls = []

    for asset in assets:
        label = (asset.get("label", "") + " " + asset.get("url", "")).lower()
        if _TEAM_LABEL_PATTERNS.search(label):
            candidate_urls.append(asset["url"])

    # Step 2: If no candidates in assets, try common paths
    if not candidate_urls:
        for path in _TEAM_PATH_GUESSES:
            candidate_urls.append(f"{domain}{path}")

    # Step 3: Fetch pages and extract team members
    all_members = []
    pages_checked = []
    headers = {"User-Agent": "Pressroom/0.1 (content-engine)"}

    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        for url in candidate_urls[:5]:  # Cap at 5 pages
            try:
                resp = await client.get(url, headers=headers)
                if resp.status_code != 200:
                    continue
                # Only process if there's meaningful content
                if len(resp.text) < 200:
                    continue
                pages_checked.append(url)
                members = await extract_team_members(resp.text, url, api_key=api_key)
                if members:
                    all_members.extend(members)
                    break  # Got results, stop checking more pages
            except Exception as e:
                log.warning("TEAM DISCOVER — failed to fetch %s: %s", url, str(e))
                continue

    # Step 4: GitHub fallback if page scraping found nothing
    github_fallback_used = False
    if not all_members:
        settings_map = await dl.get_all_settings()
        social_profiles = {}
        try:
            social_profiles = json.loads(settings_map.get("social_profiles", "{}") or "{}")
        except Exception:
            pass

        github_url = social_profiles.get("github", "")
        if github_url:
            log.info("TEAM DISCOVER — no members from pages, trying GitHub org: %s", github_url)
            all_members = await _discover_from_github(github_url, api_key=api_key)
            github_fallback_used = bool(all_members)
        else:
            log.info("TEAM DISCOVER — no GitHub URL in social profiles, giving up")

    if not all_members:
        return {
            "members": [],
            "pages_checked": pages_checked,
            "message": "No team members found on checked pages or GitHub org.",
        }

    # Step 5: Save discovered members (avoid duplicates by name)
    existing = await dl.list_team_members()
    existing_names = {m["name"].lower().strip() for m in existing}

    saved = []
    skipped = 0
    for member_data in all_members:
        if member_data["name"].lower().strip() in existing_names:
            skipped += 1
            continue
        member = await dl.save_team_member(member_data)
        saved.append(member)
        existing_names.add(member_data["name"].lower().strip())

    await dl.commit()

    return {
        "members": saved,
        "pages_checked": pages_checked,
        "total_found": len(all_members),
        "saved": len(saved),
        "skipped_duplicates": skipped,
        "source": "github" if github_fallback_used else "web",
    }
