"""YouTube Studio — script generation, Remotion export, metadata."""

import asyncio
import json
import datetime
import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select, desc

from api.auth import get_authenticated_data_layer
from models import YouTubeScript, Story, StorySignal, Signal
from services.data_layer import DataLayer
from config import settings
from services.token_tracker import log_token_usage
from services.brand_scraper import scrape_brand
from services.seo_audit import audit_domain

log = logging.getLogger("pressroom")

router = APIRouter(prefix="/api/youtube", tags=["youtube"])

# Load the video script skill file
_SKILL_PATH = Path(__file__).parent.parent / "skills" / "video_script.md"


def _load_skill() -> str:
    try:
        return _SKILL_PATH.read_text()
    except Exception:
        return ""


async def _build_audit_report(target_url: str, target_company: str, org_name: str, api_key: str) -> dict | None:
    """Run SEO audit on target URL and convert results into Ralph's scenes format for Remotion."""
    try:
        audit = await audit_domain(target_url, max_pages=8, api_key=api_key)
    except Exception as e:
        log.warning("Audit failed for %s: %s", target_url, e)
        return None

    recs = audit.get("recommendations", {})
    score = recs.get("score", 0)
    total_issues = recs.get("total_issues", 0)
    analysis = recs.get("analysis", "")
    pages = audit.get("pages", [])

    # Count issue categories from page-level data
    categories = {"Technical": 0, "Content": 0, "GEO": 0, "Links": 0}
    for p in pages:
        for issue in p.get("issues", []):
            if any(k in issue for k in ("SCHEMA", "CANONICAL", "OG", "H1")):
                categories["Technical"] += 1
            elif any(k in issue for k in ("THIN", "TITLE", "META")):
                categories["Content"] += 1
            elif "LINK" in issue:
                categories["Links"] += 1
            else:
                categories["GEO"] += 1

    # Detect missing channels (YouTube, Podcast) from analysis text
    missing_channels = []
    analysis_lower = analysis.lower()
    if "youtube" not in analysis_lower or any(p in analysis_lower for p in ["no youtube", "missing youtube", "no video", "youtube channel not"]):
        missing_channels.append("YouTube")
    pages_with_schema = sum(1 for p in pages if p.get("has_schema"))
    schema_pct = pages_with_schema / max(len(pages), 1) * 100

    # Use Claude to extract structured top_issues + geo_factors from analysis text
    import anthropic as _anthropic
    _client = _anthropic.AsyncAnthropic(api_key=api_key)

    extract_prompt = f"""From this SEO audit analysis, extract structured data. Return ONLY valid JSON, no markdown.

AUDIT ANALYSIS:
{analysis[:3000]}

PAGES AUDITED: {len(pages)}
TOTAL ISSUES: {total_issues}
SCHEMA COVERAGE: {schema_pct:.0f}%

Return this exact JSON structure:
{{
  "top_issues": [
    {{"priority": "P0", "title": "short title", "detail": "one sentence with specific data"}},
    {{"priority": "P1", "title": "short title", "detail": "one sentence with specific data"}},
    {{"priority": "P2", "title": "short title", "detail": "one sentence with specific data"}}
  ],
  "geo_factors": {{
    "Schema Markup": 0,
    "Freshness": 0,
    "Citations": 0,
    "Statistics": 0,
    "Expert Quotes": 0,
    "Authority Links": 0
  }},
  "score_caption": "one line explaining the score"
}}

For geo_factors: score 0-100 each based on evidence in the audit. Schema Markup = {schema_pct:.0f} unless you see evidence otherwise."""

    try:
        extract_resp = await _client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{"role": "user", "content": extract_prompt}],
        )
        extracted_text = extract_resp.content[0].text.strip()
        if extracted_text.startswith("```"):
            extracted_text = extracted_text.split("```")[1]
            if extracted_text.startswith("json"):
                extracted_text = extracted_text[4:]
        extracted = json.loads(extracted_text.strip())
    except Exception as e:
        log.warning("Audit extraction failed: %s", e)
        extracted = {
            "top_issues": [
                {"priority": "P0", "title": "SEO improvements needed", "detail": analysis[:200]},
            ],
            "geo_factors": {"Schema Markup": int(schema_pct), "Freshness": 40, "Citations": 30, "Statistics": 20, "Expert Quotes": 15, "Authority Links": 35},
            "score_caption": "Room for improvement",
        }

    top_issues = extracted.get("top_issues", [])[:3]
    geo_factors = extracted.get("geo_factors", {})
    score_caption = extracted.get("score_caption", "")

    # Build scenes in Ralph's format
    domain = target_url.replace("https://", "").replace("http://", "").split("/")[0]
    scenes = {
        "opening": {
            "duration_seconds": 4,
            "text": f"{org_name} | Digital Presence Audit",
            "subtext": domain,
        },
        "seo_score": {
            "duration_seconds": 6,
            "score": score,
            "color": "green" if score >= 70 else ("amber" if score >= 45 else "red"),
            "caption": score_caption,
        },
        "issues_breakdown": {
            "duration_seconds": 7,
            "title": "WHAT WE FOUND",
            "bars": [
                {"category": cat, "count": count, "color": c}
                for (cat, count), c in zip(
                    categories.items(),
                    ["#e74c3c", "#f39c12", "#3498db", "#2ecc71"]
                )
                if count > 0
            ],
        },
        "missing_channels": [
            {
                "duration_seconds": 3,
                "channel": ch,
                "text": "NOT DETECTED BY AI SEARCH",
                "subtext": f"No {ch} presence detected",
            }
            for ch in missing_channels
        ],
        "geo_readiness": {
            "duration_seconds": 6,
            "title": "AI CITABILITY BREAKDOWN",
            "factors": [
                {"name": k, "score": v, "max": 100}
                for k, v in geo_factors.items()
            ],
        },
        "top_fixes": {
            "duration_seconds": 8,
            "fixes": top_issues,
        },
        "credits": {
            "duration_seconds": 4,
            "text": f"Audit prepared by {org_name}",
            "url": "pressroomhq.com",
            "tagline": "Let's fix this together.",
        },
    }

    total_duration = sum([
        scenes["opening"]["duration_seconds"],
        scenes["seo_score"]["duration_seconds"],
        scenes["issues_breakdown"]["duration_seconds"],
        sum(m["duration_seconds"] for m in scenes["missing_channels"]),
        scenes["geo_readiness"]["duration_seconds"],
        scenes["top_fixes"]["duration_seconds"],
        scenes["credits"]["duration_seconds"],
    ])

    return {
        "domain": domain,
        "score": score,
        "total_issues": total_issues,
        "categories": categories,
        "top_issues": top_issues,
        "geo_factors": geo_factors,
        "missing_channels": missing_channels,
        "scenes": scenes,
        "total_duration_seconds": total_duration,
    }


class GenerateRequest(BaseModel):
    content_id: int | None = None
    story_id: int | None = None
    brief: str = ""
    duration_minutes: float = 3.0        # target duration
    topics: list[str] = []               # additional topics / directions
    target_person: str = ""              # personalized video: recipient name
    target_company: str = ""            # personalized video: recipient company
    target_role: str = ""               # personalized video: recipient role/title
    target_url: str = ""                # personalized video: crawl for target brand
    script_type: str = "standard"       # standard | personalized | release
    presenter: str = "person"           # person | company
    presenter_name: str = ""            # who's on camera (name)
    presenter_title: str = ""           # their title/role


class UpdateRequest(BaseModel):
    title: str | None = None
    hook: str | None = None
    cta: str | None = None
    sections: list | None = None   # full sections array — also resyncs remotion_package
    metadata_title: str | None = None
    metadata_description: str | None = None
    status: str | None = None


@router.post("/generate")
async def generate_script(req: GenerateRequest, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Generate a YouTube script from a story, content item, or free-form brief."""
    api_key = await dl.resolve_api_key()
    if not api_key:
        return {"error": "No Anthropic API key configured."}

    # ── Build source material ──────────────────────────────────────────────────
    source_parts = []

    # From story (preferred — rich signal context)
    if req.story_id:
        story_query = select(Story).where(Story.id == req.story_id)
        if dl.org_id is not None:
            story_query = story_query.where(Story.org_id == dl.org_id)
        result = await dl.db.execute(story_query)
        story = result.scalars().first()
        if not story:
            return {"error": f"Story {req.story_id} not found."}

        source_parts.append(f"Story: {story.title}")
        if story.angle:
            source_parts.append(f"Angle: {story.angle}")
        if story.editorial_notes:
            source_parts.append(f"Editorial notes: {story.editorial_notes}")

        # Pull signals attached to the story
        sig_result = await dl.db.execute(
            select(StorySignal).where(StorySignal.story_id == req.story_id).limit(10)
        )
        story_signals = sig_result.scalars().all()
        if story_signals:
            source_parts.append("\nSignals:")
            for ss in story_signals:
                # Try to get the actual signal
                sig_q = await dl.db.execute(
                    select(Signal).where(Signal.id == ss.signal_id)
                )
                sig = sig_q.scalars().first()
                if sig:
                    source_parts.append(f"  [{sig.type}] {sig.title}")
                    if sig.body:
                        source_parts.append(f"  {sig.body[:500]}")

    # From specific content item
    elif req.content_id:
        content = await dl.get_content(req.content_id)
        if not content:
            return {"error": f"Content {req.content_id} not found."}
        source_parts.append(
            f"Channel: {content.get('channel', '')}\n"
            f"Headline: {content.get('headline', '')}\n\n"
            f"{content.get('body', '')}"
        )

    # From free-form brief
    if req.brief:
        source_parts.append(f"Brief: {req.brief}")

    # Additional topics
    if req.topics:
        source_parts.append(f"Cover these topics: {', '.join(req.topics)}")

    if not source_parts:
        return {"error": "Provide a story, content item, or brief to generate from."}

    source_text = "\n\n".join(source_parts)

    # ── Voice, team, brand settings (in parallel) ──────────────────────────────
    voice, team_members, brand_settings = await asyncio.gather(
        dl.get_voice_settings(),
        dl.list_team_members(),
        dl.get_all_settings(),
    )
    company_name = voice.get("onboard_company_name", "Company")
    team_info = "\n".join(
        f"- {m.get('name', '')} ({m.get('title', '')})"
        for m in team_members[:5]
    ) if team_members else "Not specified"

    brand_raw = brand_settings.get("brand_data", "")
    brand = {}
    if brand_raw:
        try:
            brand = json.loads(brand_raw) if isinstance(brand_raw, str) else brand_raw
        except (json.JSONDecodeError, TypeError):
            pass

    # ── Target brand + audit — run BEFORE Claude so findings feed into the script
    target_brand = None
    audit_report = None
    if req.target_url:
        url = req.target_url
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        tasks = [scrape_brand(url)]
        if req.script_type == "personalized":
            tasks.append(_build_audit_report(url, req.target_company, company_name, api_key))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        raw = results[0] if not isinstance(results[0], Exception) else {}
        target_brand = {
            "logo_url": raw.get("logo_url") or "",
            "primary_color": raw.get("primary_color") or "",
            "secondary_color": raw.get("secondary_color") or "",
            "font": raw.get("font_family") or "",
            "company_name": raw.get("company_name") or req.target_company,
            "favicon_url": raw.get("favicon_url") or "",
        }
        log.info("Scraped target brand for %s: %s", req.target_url, target_brand.get("company_name"))

        if len(results) > 1 and not isinstance(results[1], Exception):
            audit_report = results[1]
            if audit_report:
                audit_report["branding"] = target_brand
                log.info("Built audit report for %s: score=%s", url, audit_report.get("score"))

    # ── Skill file as system prompt ────────────────────────────────────────────
    skill = _load_skill()

    # Build script type context — inject real audit data for personalized scripts
    type_context = ""
    if req.script_type == "personalized" or req.target_person:
        audit_context = ""
        if audit_report:
            top = audit_report.get("top_issues", [])
            score = audit_report.get("score", 0)
            domain = audit_report.get("domain", req.target_url)
            missing = audit_report.get("missing_channels", [])
            geo = audit_report.get("geo_factors", {})
            worst_geo = sorted(geo.items(), key=lambda x: x[1])[:3] if geo else []
            issues_block = "\n".join(
                f"  [{i.get('priority')}] {i.get('title')} — {i.get('detail', '')}"
                for i in top[:3]
            )
            geo_block = "\n".join(f"  {k}: {v}/100" for k, v in worst_geo)
            pages_audited = audit_report.get("categories", {})
            total_issues = audit_report.get("total_issues", 0)
            audit_context = f"""

=== AUDIT FINDINGS — USE THESE EXACT NUMBERS, NO SOFTENING ===
Domain: {domain}
Score: {score}/100
Pages crawled: {sum(pages_audited.values()) or '?'}
Total issues found: {total_issues}
Top issues:
{issues_block}
Weakest AI citability:
{geo_block}
Missing channels: {', '.join(missing) if missing else 'none detected'}

SCRIPT CONSTRUCTION RULES:
1. The video opens with an animated data reveal — {req.target_person or 'the viewer'} has already seen the score ({score}/100) and top issues on screen before your script plays. Do NOT re-introduce the data.
2. Your hook reacts to what they just watched. Open mid-sentence, land the sharpest insight immediately. Name a specific number or finding in the first line.
3. One section explains what the data means for their actual business — not generic SEO advice, business impact.
4. One section introduces Pressroom and why we're the right fix — specific, not a pitch deck.
5. CTA is a single concrete ask.

TONE: Direct. Slightly blunt. Like you've done the work and you're telling them what you found, not trying to sell them something. If the finding is bad, say it's bad."""

        type_context = f"""
SCRIPT TYPE: Personalized outreach video
Target: {req.target_person or 'Unknown'} — {req.target_role or ''} at {req.target_company or 'Unknown'}
Duration: ~{int(req.duration_minutes * 60)} seconds{audit_context}
"""
    elif req.script_type == "release":
        type_context = f"""
SCRIPT TYPE: Product/release announcement
Duration: ~{int(req.duration_minutes * 60)} seconds
Lead with what changed and why it matters to developers/users.
"""
    else:
        type_context = f"""
SCRIPT TYPE: Standard YouTube / thought leadership
Duration: ~{int(req.duration_minutes * 60)} seconds (~{int(req.duration_minutes * 150)} words spoken)
"""

    # Presenter identity
    if req.presenter == "person" and req.presenter_name:
        presenter_line = f"Presenter: {req.presenter_name}" + (f" — {req.presenter_title}" if req.presenter_title else "")
        presenter_context = f"\nThe script is written for {req.presenter_name} to deliver on camera. Write in first person, in their voice."
    elif req.presenter == "company":
        presenter_line = f"Presenter: {company_name} (company / no on-camera host)"
        presenter_context = "\nThis is a company video — no personal 'I' — write in brand voice (we, our, the team)."
    else:
        presenter_line = "Presenter: Not specified"
        presenter_context = ""

    user_msg = f"""Company: {company_name}
{presenter_line}
Team members:
{team_info}
{type_context}{presenter_context}
Source material:
{source_text[:4000]}

Generate the script now."""

    # ── Claude call ────────────────────────────────────────────────────────────
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=api_key)

    try:
        response = await client.messages.create(
            model=settings.claude_model,
            max_tokens=4000,
            system=skill or _fallback_system(),
            messages=[{"role": "user", "content": user_msg}],
        )
        await log_token_usage(dl.org_id, "youtube_script", response)
        text = response.content[0].text.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        data = json.loads(text)
    except json.JSONDecodeError as e:
        log.error("Script JSON parse failed: %s", e)
        return JSONResponse(status_code=500, content={"error": "Failed to parse Claude response as JSON."})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Script generation failed: {str(e)}"})

    # ── Remotion package ───────────────────────────────────────────────────────
    sections = data.get("sections", [])
    remotion = {
        "org": company_name,
        "title": data.get("title", ""),
        "duration_seconds": sum(s.get("duration_seconds", 60) for s in sections),
        "target": {
            "person": req.target_person,
            "company": req.target_company,
            "role": req.target_role,
            "url": req.target_url,
        } if req.target_person else None,
        "branding": {
            "logo_url": brand.get("logo_url") or "",
            "primary_color": brand.get("primary_color") or "#ffb000",
            "secondary_color": brand.get("secondary_color") or "",
            "font": brand.get("font_family") or "IBM Plex Mono",
            "company_name": company_name,
        },
        "target_brand": target_brand,
        "audit_report": audit_report,
        "hook": data.get("hook", ""),
        "cta": data.get("cta", ""),
        "lower_thirds": data.get("lower_thirds", []),
        "chyrons": [],
        # Full section data for Remotion YouTubeScript composition
        "sections_detail": [
            {
                "heading": s.get("heading", ""),
                "talking_points": s.get("talking_points", []),
                "duration_seconds": s.get("duration_seconds", 30),
                "b_roll": s.get("b_roll", ""),
                "start_second": sum(ss.get("duration_seconds", 30) for ss in sections[:i]),
                "end_second": sum(ss.get("duration_seconds", 30) for ss in sections[:i+1]),
            }
            for i, s in enumerate(sections)
        ],
        # Simplified sections for timeline/chyron use
        "sections": [
            {
                "heading": s.get("heading", ""),
                "start_second": sum(ss.get("duration_seconds", 30) for ss in sections[:i]),
                "end_second": sum(ss.get("duration_seconds", 30) for ss in sections[:i+1]),
            }
            for i, s in enumerate(sections)
        ],
        "opening_card": {
            "text": "Script and graphics generated by Pressroom HQ",
            "duration_seconds": 3,
        },
        "credits": "Script generated by Pressroom HQ — pressroomhq.com",
    }

    desc = data.get("metadata_description", "")
    if desc and "pressroomhq.com" not in desc:
        desc += "\n\n---\nScript generated by Pressroom HQ | pressroomhq.com"

    # ── Save ───────────────────────────────────────────────────────────────────
    script = YouTubeScript(
        org_id=dl.org_id,
        content_id=req.content_id,
        title=data.get("title", "Untitled"),
        hook=data.get("hook", ""),
        sections=json.dumps(sections),
        cta=data.get("cta", ""),
        lower_thirds=json.dumps(data.get("lower_thirds", [])),
        metadata_title=data.get("metadata_title", "")[:100],
        metadata_description=desc,
        metadata_tags=json.dumps(data.get("metadata_tags", [])),
        remotion_package=json.dumps(remotion),
        status="draft",
    )
    dl.db.add(script)
    await dl.commit()

    return _script_to_dict(script)


async def _get_script(dl: DataLayer, script_id: int):
    """Fetch a script scoped to the authenticated org."""
    query = select(YouTubeScript).where(YouTubeScript.id == script_id)
    if dl.org_id is not None:
        query = query.where(YouTubeScript.org_id == dl.org_id)
    result = await dl.db.execute(query)
    return result.scalars().first()


@router.get("/scripts")
async def list_scripts(dl: DataLayer = Depends(get_authenticated_data_layer)):
    query = select(YouTubeScript).order_by(desc(YouTubeScript.created_at)).limit(50)
    if dl.org_id is not None:
        query = query.where(YouTubeScript.org_id == dl.org_id)
    result = await dl.db.execute(query)
    return [_script_to_dict(s) for s in result.scalars().all()]


@router.get("/scripts/{script_id}")
async def get_script(script_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    script = await _get_script(dl, script_id)
    if not script:
        return {"error": "Script not found"}
    return _script_to_dict(script)


@router.get("/scripts/{script_id}/export")
async def export_remotion(script_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    script = await _get_script(dl, script_id)
    if not script:
        return {"error": "Script not found"}
    try:
        return json.loads(script.remotion_package or '{}')
    except json.JSONDecodeError:
        return {}


@router.patch("/scripts/{script_id}")
async def update_script(script_id: int, req: UpdateRequest, dl: DataLayer = Depends(get_authenticated_data_layer)):
    script = await _get_script(dl, script_id)
    if not script:
        return {"error": "Script not found"}

    simple_fields = {"title", "hook", "cta", "metadata_title", "metadata_description", "status"}
    for field, val in req.model_dump().items():
        if val is not None and field in simple_fields:
            setattr(script, field, val)

    # Sections update — persist JSON and resync remotion_package sections_detail
    if req.sections is not None:
        script.sections = json.dumps(req.sections)
        # Rebuild sections_detail in remotion package
        if script.remotion_package:
            try:
                pkg = json.loads(script.remotion_package)
                pkg["sections_detail"] = [
                    {
                        "heading": s.get("heading", ""),
                        "talking_points": s.get("talking_points", []),
                        "duration_seconds": s.get("duration_seconds", 30),
                        "b_roll": s.get("b_roll", ""),
                        "start_second": sum(ss.get("duration_seconds", 30) for ss in req.sections[:i]),
                        "end_second": sum(ss.get("duration_seconds", 30) for ss in req.sections[:i+1]),
                    }
                    for i, s in enumerate(req.sections)
                ]
                # Also sync hook/cta if provided in same request
                if req.hook is not None:
                    pkg["hook"] = req.hook
                if req.cta is not None:
                    pkg["cta"] = req.cta
                script.remotion_package = json.dumps(pkg)
            except (json.JSONDecodeError, TypeError):
                pass

    # Sync hook/cta to remotion_package even without section update
    elif (req.hook is not None or req.cta is not None) and script.remotion_package:
        try:
            pkg = json.loads(script.remotion_package)
            if req.hook is not None:
                pkg["hook"] = req.hook
            if req.cta is not None:
                pkg["cta"] = req.cta
            script.remotion_package = json.dumps(pkg)
        except (json.JSONDecodeError, TypeError):
            pass

    await dl.commit()
    return _script_to_dict(script)


@router.delete("/scripts/{script_id}")
async def delete_script(script_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    script = await _get_script(dl, script_id)
    if not script:
        return {"error": "Script not found"}
    await dl.db.delete(script)
    await dl.commit()
    return {"deleted": script_id}


@router.post("/scripts/{script_id}/publish")
async def publish_script(script_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    script = await _get_script(dl, script_id)
    if not script:
        return {"error": "Script not found"}
    script.status = "published"
    await dl.commit()
    return _script_to_dict(script)


import os as _os
_env_renderer = _os.getenv("REMOTION_RENDERER_DIR", "")
_RENDERER_DIR = Path(_env_renderer) if _env_renderer else \
    Path(__file__).resolve().parent.parent / "remotion-renderer"
_RENDER_OUT_DIR = _RENDERER_DIR / "out"
_FOOTAGE_DIR = Path(__file__).resolve().parent.parent / "out"  # pressroom-app/out/
_REMOTION_BIN = _RENDERER_DIR / "node_modules" / ".bin" / "remotion"


from fastapi import UploadFile, File
import shutil as _shutil


@router.post("/scripts/{script_id}/upload-footage")
async def upload_footage(
    script_id: int,
    video: UploadFile = File(...),
    dl: DataLayer = Depends(get_authenticated_data_layer),
):
    """Accept uploaded MP4, save locally, patch remotion_package to overlay mode, render."""
    script = await _get_script(dl, script_id)
    if not script:
        return JSONResponse(status_code=404, content={"error": "Script not found"})

    if not script.remotion_package:
        return JSONResponse(status_code=400, content={"error": "No remotion package on this script"})

    # Save uploaded footage
    _FOOTAGE_DIR.mkdir(parents=True, exist_ok=True)
    footage_path = _FOOTAGE_DIR / f"footage_{script_id}.mp4"
    with footage_path.open("wb") as f:
        content = await video.read()
        f.write(content)
    log.info("Footage saved: %s (%d bytes)", footage_path, len(content))

    # Patch remotion_package — overlay mode + footage path
    pkg_data = json.loads(script.remotion_package)
    pkg_data["mode"] = "overlay"
    pkg_data["footage_path"] = str(footage_path)
    script.remotion_package = json.dumps(pkg_data)
    await dl.commit()

    # Trigger render inline (same logic as /render endpoint)
    if not _RENDERER_DIR.exists():
        return JSONResponse(status_code=500, content={"error": f"Remotion renderer not found at {_RENDERER_DIR}"})

    _RENDER_OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Copy footage to remotion public/ so staticFile() can serve it
    public_dir = _RENDERER_DIR / "public"
    public_dir.mkdir(exist_ok=True)
    footage_dest_name = f"footage_{script_id}.mp4"
    footage_dest = public_dir / footage_dest_name
    _shutil.copy2(footage_path, footage_dest)
    pkg_data["footage_path"] = footage_dest_name  # staticFile() relative name

    wrapped = json.dumps({"data": pkg_data})
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        f.write(wrapped)
        data_path = Path(f.name)

    output_path = _RENDER_OUT_DIR / f"script_{script_id}.mp4"

    try:
        proc = await asyncio.create_subprocess_exec(
            "node", str(_REMOTION_BIN), "render",
            "src/index.jsx",
            "YouTubeScript",
            "--output", str(output_path),
            "--props", str(data_path),
            "--concurrency", "8",
            cwd=str(_RENDERER_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

        if proc.returncode != 0:
            log.error("Overlay render failed: %s", stderr.decode())
            return JSONResponse(status_code=500, content={
                "error": "Render failed",
                "detail": stderr.decode()[-2000:],
            })

        # Store rendered video
        from services.storage import storage
        storage_key = f"renders/script_{script_id}.mp4"
        mp4_data = output_path.read_bytes()
        storage_url = await storage.put(storage_key, mp4_data, content_type="video/mp4")

        script.status = "rendered"
        await dl.commit()

        return {
            "script_id": script_id,
            "storage_url": storage_url,
            "duration_seconds": pkg_data.get("duration_seconds"),
        }
    except asyncio.TimeoutError:
        return JSONResponse(status_code=504, content={"error": "Render timed out"})
    finally:
        data_path.unlink(missing_ok=True)
        if footage_dest.exists():
            footage_dest.unlink(missing_ok=True)


# In-memory OBS render job tracker — { job_id: { status, output_path, error } }
_obs_jobs: dict = {}


async def _run_obs_render(job_id: str, script_id: int, pkg_data: dict):
    """Background task: render OBS overlay webm, update job status when done."""
    output_path = _RENDER_OUT_DIR / f"script_{script_id}_obs.webm"
    _obs_jobs[job_id] = {"status": "rendering", "output_path": None, "error": None}

    wrapped = json.dumps({"data": pkg_data})
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        f.write(wrapped)
        data_path = Path(f.name)

    try:
        proc = await asyncio.create_subprocess_exec(
            "node", str(_REMOTION_BIN), "render",
            "src/index.jsx",
            "OBSOverlay",
            "--output", str(output_path),
            "--props", str(data_path),
            "--codec", "vp9",
            "--concurrency", "8",
            cwd=str(_RENDERER_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)

        if proc.returncode != 0:
            err = stderr.decode()[-1000:]
            log.error("OBS render failed: %s", err)
            _obs_jobs[job_id] = {"status": "error", "output_path": None, "error": err}
        else:
            _obs_jobs[job_id] = {"status": "done", "output_path": str(output_path), "error": None}
            log.info("OBS render complete: %s", output_path)
    except asyncio.TimeoutError:
        _obs_jobs[job_id] = {"status": "error", "output_path": None, "error": "Render timed out"}
    finally:
        data_path.unlink(missing_ok=True)


@router.post("/scripts/{script_id}/render-obs")
async def render_obs(script_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Kick off async OBS overlay render. Returns job_id — poll /render-obs-status/{job_id}."""
    return JSONResponse(status_code=503, content={"error": "Video rendering coming soon.", "coming_soon": True})
    script = await _get_script(dl, script_id)
    if not script:
        return JSONResponse(status_code=404, content={"error": "Script not found"})
    if not script.remotion_package:
        return JSONResponse(status_code=400, content={"error": "No remotion package on this script"})
    if not _RENDERER_DIR.exists():
        return JSONResponse(status_code=500, content={"error": f"Remotion renderer not found"})

    _RENDER_OUT_DIR.mkdir(parents=True, exist_ok=True)

    pkg_data = json.loads(script.remotion_package)
    pkg_data["mode"] = "obs"

    import uuid
    job_id = str(uuid.uuid4())[:8]
    asyncio.create_task(_run_obs_render(job_id, script_id, pkg_data))

    return {"job_id": job_id, "status": "rendering"}


class ChyronRequest(BaseModel):
    name: str = "Nic Davidson"
    title: str = "Head of Engineering"
    logo_url: str = ""
    accent_color: str = "#ffb000"
    duration_seconds: int = 30


@router.post("/render-chyron")
async def render_chyron(req: ChyronRequest, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Render a standalone brand chyron — transparent webm, no script needed.
    Logo left, name + title right. Drop into OBS as a media source."""
    return JSONResponse(status_code=503, content={"error": "Video rendering coming soon.", "coming_soon": True})
    if not _RENDERER_DIR.exists():
        return JSONResponse(status_code=500, content={"error": "Remotion renderer not found"})

    _RENDER_OUT_DIR.mkdir(parents=True, exist_ok=True)

    props = {"data": {
        "name": req.name,
        "title": req.title,
        "logo_url": req.logo_url,
        "accent_color": req.accent_color,
        "duration_seconds": req.duration_seconds,
    }}

    import uuid
    job_id = str(uuid.uuid4())[:8]
    output_path = _RENDER_OUT_DIR / f"chyron_{job_id}.webm"

    async def _run():
        _obs_jobs[job_id] = {"status": "rendering", "output_path": None, "error": None}
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(props, f)
            data_path = Path(f.name)
        try:
            proc = await asyncio.create_subprocess_exec(
                "node", str(_REMOTION_BIN), "render",
                "src/index.jsx", "BrandChyron",
                "--output", str(output_path),
                "--props", str(data_path),
                "--codec", "vp9",
                "--concurrency", "8",
                cwd=str(_RENDERER_DIR),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
            if proc.returncode != 0:
                err = stderr.decode()[-800:]
                log.error("Chyron render failed: %s", err)
                _obs_jobs[job_id] = {"status": "error", "output_path": None, "error": err}
            else:
                _obs_jobs[job_id] = {"status": "done", "output_path": str(output_path), "error": None}
        except asyncio.TimeoutError:
            _obs_jobs[job_id] = {"status": "error", "output_path": None, "error": "Timed out"}
        finally:
            data_path.unlink(missing_ok=True)

    asyncio.create_task(_run())
    return {"job_id": job_id, "status": "rendering"}


@router.get("/render-obs-status/{job_id}")
async def render_obs_status(job_id: str, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Poll OBS render job status. Returns status + download URL when done."""
    job = _obs_jobs.get(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"error": "Job not found"})
    return job


@router.get("/render-obs-download/{job_id}")
async def render_obs_download(job_id: str, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Download completed OBS webm by job ID."""
    from fastapi.responses import FileResponse
    job = _obs_jobs.get(job_id)
    if not job or job["status"] != "done":
        return JSONResponse(status_code=404, content={"error": "Not ready"})
    output_path = Path(job["output_path"])
    if not output_path.exists():
        return JSONResponse(status_code=404, content={"error": "File missing"})
    # Extract script_id from filename for the download name
    return FileResponse(
        path=str(output_path),
        media_type="video/webm",
        filename=output_path.name,
    )


@router.post("/scripts/{script_id}/render")
async def render_script(script_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Trigger a Remotion render for this script. Returns output file path."""
    return JSONResponse(status_code=503, content={"error": "Video rendering coming soon.", "coming_soon": True})
    script = await _get_script(dl, script_id)
    if not script:
        return {"error": "Script not found"}

    remotion_pkg = script.remotion_package
    if not remotion_pkg:
        return {"error": "No remotion package data on this script."}

    if not _RENDERER_DIR.exists():
        return {"error": f"Remotion renderer not found at {_RENDERER_DIR}"}

    _RENDER_OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Choose composition — PersonalizedReport when audit data is present
    pkg_data = json.loads(remotion_pkg)
    has_audit = bool(pkg_data.get("audit_report"))
    composition = "PersonalizedReport" if has_audit else "YouTubeScript"

    # If overlay mode with a local footage file, copy it into remotion's public/ dir
    # so it can be referenced as staticFile('footage_<id>.mp4') — Remotion's headless
    # Chromium can't load bare file:// paths, but it can serve from the public dir.
    footage_cleanup = None
    if pkg_data.get("mode") == "overlay" and pkg_data.get("footage_path"):
        footage_src = Path(pkg_data["footage_path"])
        if footage_src.exists():
            public_dir = _RENDERER_DIR / "public"
            public_dir.mkdir(exist_ok=True)
            footage_dest_name = f"footage_{script_id}.mp4"
            footage_dest = public_dir / footage_dest_name
            import shutil
            shutil.copy2(footage_src, footage_dest)
            footage_cleanup = footage_dest
            # Update pkg_data to use the public-served path (Remotion serves /public as root)
            pkg_data["footage_path"] = f"footage_{footage_dest_name}"  # staticFile() path
        else:
            log.warning("Footage file not found: %s — rendering without footage", footage_src)
            pkg_data.pop("footage_path", None)

    wrapped = json.dumps({"data": pkg_data})
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        f.write(wrapped)
        data_path = Path(f.name)

    output_path = _RENDER_OUT_DIR / f"script_{script_id}.mp4"

    try:
        proc = await asyncio.create_subprocess_exec(
            "node", str(_REMOTION_BIN), "render",
            "src/index.jsx",
            composition,
            "--output", str(output_path),
            "--props", str(data_path),
            "--concurrency", "8",
            cwd=str(_RENDERER_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

        if proc.returncode != 0:
            log.error("Remotion render failed: %s", stderr.decode())
            return JSONResponse(status_code=500, content={
                "error": "Render failed",
                "detail": stderr.decode()[-2000:],
            })

        # Upload rendered MP4 to storage (Tigris in prod, local disk in dev)
        from services.storage import storage
        storage_key = f"renders/script_{script_id}.mp4"
        mp4_data = output_path.read_bytes()
        storage_url = await storage.put(storage_key, mp4_data, content_type="video/mp4")
        log.info("Render stored at %s (backend=%s)", storage_url, storage.backend)

        script.status = "rendered"
        await dl.commit()

        return {
            "script_id": script_id,
            "output": str(output_path),
            "storage_key": storage_key,
            "storage_url": storage_url,
            "backend": storage.backend,
            "duration_seconds": json.loads(remotion_pkg).get("duration_seconds"),
        }
    except asyncio.TimeoutError:
        return JSONResponse(status_code=504, content={"error": "Render timed out (5 min limit)"})
    finally:
        data_path.unlink(missing_ok=True)
        if footage_cleanup and footage_cleanup.exists():
            footage_cleanup.unlink(missing_ok=True)


def _script_to_dict(s):
    return {
        "id": s.id,
        "org_id": s.org_id,
        "content_id": s.content_id,
        "title": s.title,
        "hook": s.hook,
        "sections": s.sections,
        "cta": s.cta,
        "lower_thirds": s.lower_thirds,
        "metadata_title": s.metadata_title,
        "metadata_description": s.metadata_description,
        "metadata_tags": s.metadata_tags,
        "remotion_package": s.remotion_package,
        "status": s.status,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


def _fallback_system() -> str:
    """Minimal fallback if skill file is missing."""
    return (
        "You are a YouTube script writer. Generate structured B2B video scripts. "
        "Return ONLY valid JSON with: title, hook, sections (array of heading/talking_points/duration_seconds), "
        "cta, lower_thirds, metadata_title, metadata_description, metadata_tags."
    )
