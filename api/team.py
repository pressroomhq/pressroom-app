"""Team Members — CRUD + AI-powered team discovery from company web pages."""

import logging
import re

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

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

    if not all_members:
        return {
            "members": [],
            "pages_checked": pages_checked,
            "message": "No team members found on checked pages.",
        }

    # Step 4: Save discovered members (avoid duplicates by name)
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
    }
