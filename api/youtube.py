"""YouTube Studio — script generation, Remotion export, metadata."""

import json
import datetime
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select, desc

from database import get_data_layer
from models import YouTubeScript
from services.data_layer import DataLayer
from config import settings

log = logging.getLogger("pressroom")

router = APIRouter(prefix="/api/youtube", tags=["youtube"])


class GenerateRequest(BaseModel):
    content_id: int | None = None
    brief: str = ""


class UpdateRequest(BaseModel):
    title: str | None = None
    hook: str | None = None
    cta: str | None = None
    metadata_title: str | None = None
    metadata_description: str | None = None
    status: str | None = None


@router.post("/generate")
async def generate_script(req: GenerateRequest, dl: DataLayer = Depends(get_data_layer)):
    """Generate a YouTube script from content or a free-form brief."""
    api_key = await dl.resolve_api_key()
    if not api_key:
        return {"error": "No Anthropic API key configured."}

    # Build source material
    source_text = req.brief or ""
    if req.content_id:
        content = await dl.get_content(req.content_id)
        if content:
            source_text = f"Channel: {content.get('channel', '')}\nHeadline: {content.get('headline', '')}\n\n{content.get('body', '')}"
        else:
            return {"error": f"Content {req.content_id} not found."}

    if not source_text.strip():
        return {"error": "Provide content_id or brief text."}

    # Get voice and team info
    voice = await dl.get_voice_settings()
    team_members = await dl.list_team_members()

    # Build Claude prompt
    company_name = voice.get("onboard_company_name", "Company")
    team_info = ""
    if team_members:
        team_info = "\n".join(f"- {m.get('name', '')} ({m.get('title', '')})" for m in team_members[:5])

    import anthropic
    client = anthropic.AsyncAnthropic(api_key=api_key)

    system = """You are a YouTube script writer for B2B tech companies. Generate structured scripts that are:
- Conversational and direct
- 2-4 minutes long (300-600 words spoken)
- Hook-first: the first 15 seconds must grab attention
- Include [B-ROLL] markers for visual overlays

Return ONLY valid JSON with this structure:
{
  "title": "Video title",
  "hook": "Opening 15 seconds — must grab attention",
  "sections": [
    {"heading": "Section Name", "talking_points": ["point 1", "point 2"], "duration_seconds": 60}
  ],
  "cta": "Call to action closing",
  "lower_thirds": [
    {"at_second": 5, "name": "Person Name", "title": "Title", "company": "Company"}
  ],
  "metadata_title": "YouTube title (max 60 chars)",
  "metadata_description": "Full YouTube description with timestamps",
  "metadata_tags": ["tag1", "tag2", "tag3"]
}"""

    user_msg = f"""Company: {company_name}
Team members:
{team_info or "Not specified"}

Source material:
{source_text[:3000]}

Generate a YouTube script from this content. Make it compelling, technical but accessible."""

    try:
        response = await client.messages.create(
            model=settings.claude_model,
            max_tokens=3000,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = response.content[0].text.strip()
        # Parse JSON
        text = text.strip("`").removeprefix("json").strip()
        data = json.loads(text)
    except json.JSONDecodeError:
        return JSONResponse(status_code=500, content={"error": "Failed to parse Claude response as JSON."})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Script generation failed: {str(e)}"})

    # Fetch brand data for per-company branding
    brand_settings = await dl.get_all_settings()
    brand_raw = brand_settings.get("brand_data", "")
    brand = {}
    if brand_raw:
        try:
            brand = json.loads(brand_raw) if isinstance(brand_raw, str) else brand_raw
        except (json.JSONDecodeError, TypeError):
            pass

    # Build Remotion package with real brand assets
    remotion = {
        "org": company_name,
        "title": data.get("title", ""),
        "duration_seconds": sum(s.get("duration_seconds", 60) for s in data.get("sections", [])),
        "branding": {
            "logo_url": brand.get("logo_url") or "",
            "primary_color": brand.get("primary_color") or "#ffb000",
            "secondary_color": brand.get("secondary_color") or "",
            "font": brand.get("font_family") or "IBM Plex Mono",
            "company_name": company_name,
        },
        "lower_thirds": data.get("lower_thirds", []),
        "chyrons": [],
        "sections": [
            {"heading": s["heading"], "start_second": sum(ss.get("duration_seconds", 60) for ss in data["sections"][:i]), "end_second": sum(ss.get("duration_seconds", 60) for ss in data["sections"][:i+1])}
            for i, s in enumerate(data.get("sections", []))
        ],
        "opening_card": {
            "text": "Everything in this video except the webcam recording was made by Pressroom HQ",
            "duration_seconds": 4,
        },
        "credits": "Script and graphics generated by Pressroom HQ — pressroomhq.com",
    }

    # Add credit line to description
    desc = data.get("metadata_description", "")
    if desc and "pressroomhq.com" not in desc:
        desc += "\n\n---\nScript generated by Pressroom HQ | pressroomhq.com"

    # Save to DB
    script = YouTubeScript(
        org_id=dl.org_id,
        content_id=req.content_id,
        title=data.get("title", "Untitled"),
        hook=data.get("hook", ""),
        sections=json.dumps(data.get("sections", [])),
        cta=data.get("cta", ""),
        lower_thirds=json.dumps(data.get("lower_thirds", [])),
        metadata_title=data.get("metadata_title", "")[:60],
        metadata_description=desc,
        metadata_tags=json.dumps(data.get("metadata_tags", [])),
        remotion_package=json.dumps(remotion),
        status="draft",
    )
    dl.session.add(script)
    await dl.commit()

    return _script_to_dict(script)


@router.get("/scripts")
async def list_scripts(dl: DataLayer = Depends(get_data_layer)):
    """List YouTube scripts for the current org."""
    query = select(YouTubeScript).order_by(desc(YouTubeScript.created_at)).limit(50)
    if dl.org_id:
        query = query.where(YouTubeScript.org_id == dl.org_id)
    result = await dl.session.execute(query)
    return [_script_to_dict(s) for s in result.scalars().all()]


@router.get("/scripts/{script_id}")
async def get_script(script_id: int, dl: DataLayer = Depends(get_data_layer)):
    """Get a full YouTube script."""
    result = await dl.session.execute(select(YouTubeScript).where(YouTubeScript.id == script_id))
    script = result.scalars().first()
    if not script:
        return {"error": "Script not found"}
    return _script_to_dict(script)


@router.get("/scripts/{script_id}/export")
async def export_remotion(script_id: int, dl: DataLayer = Depends(get_data_layer)):
    """Export Remotion JSON package."""
    result = await dl.session.execute(select(YouTubeScript).where(YouTubeScript.id == script_id))
    script = result.scalars().first()
    if not script:
        return {"error": "Script not found"}
    try:
        return json.loads(script.remotion_package or '{}')
    except json.JSONDecodeError:
        return {}


@router.put("/scripts/{script_id}")
async def update_script(script_id: int, req: UpdateRequest, dl: DataLayer = Depends(get_data_layer)):
    """Update script fields."""
    result = await dl.session.execute(select(YouTubeScript).where(YouTubeScript.id == script_id))
    script = result.scalars().first()
    if not script:
        return {"error": "Script not found"}
    for field, val in req.model_dump().items():
        if val is not None:
            setattr(script, field, val)
    await dl.commit()
    return _script_to_dict(script)


@router.post("/scripts/{script_id}/publish")
async def publish_script(script_id: int, dl: DataLayer = Depends(get_data_layer)):
    """Mark a script as published."""
    result = await dl.session.execute(select(YouTubeScript).where(YouTubeScript.id == script_id))
    script = result.scalars().first()
    if not script:
        return {"error": "Script not found"}
    script.status = "published"
    await dl.commit()
    return _script_to_dict(script)


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
