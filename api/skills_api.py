"""Skills Library API — org-aware skill management.

Skills have two tiers:
1. Global templates (file-based, ship with the app)
2. Org skills (database, per-org customized copies)

Resolution: org skill > template. Editing saves to org_skills, not disk.
"""

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.auth import get_authenticated_data_layer
from services.data_layer import DataLayer
from skills.invoke import list_templates, resolve_template, infer_category

log = logging.getLogger("pressroom")

router = APIRouter(prefix="/api/skills", tags=["skills"])


class SkillContent(BaseModel):
    content: str


class NewSkill(BaseModel):
    name: str
    category: str = "marketing"
    content: str = ""


@router.get("")
async def list_skills(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """List all skills — templates merged with org overrides, grouped by category."""
    # Start with all templates
    templates = list_templates()
    skill_map: dict[str, dict] = {}
    for t in templates:
        skill_map[t["name"]] = {
            "name": t["name"],
            "category": t["category"],
            "first_line": t["first_line"],
            "is_customized": False,
            "source": "template",
            "has_template": True,
        }

    # Overlay org skills
    if dl.org_id:
        org_skills = await dl.get_org_skills()
        for s in org_skills:
            name = s["skill_name"]
            if name in skill_map:
                # Override template entry
                skill_map[name]["is_customized"] = True
                skill_map[name]["source"] = s["source"]
            else:
                # Custom org skill (no template)
                skill_map[name] = {
                    "name": name,
                    "category": s["category"],
                    "first_line": s["content"].split("\n")[0][:100] if s["content"] else "",
                    "is_customized": True,
                    "source": s["source"],
                    "has_template": False,
                }

    # Group by category
    grouped: dict[str, list] = {}
    for skill in skill_map.values():
        cat = skill["category"]
        grouped.setdefault(cat, []).append(skill)

    # Sort within each category
    for cat in grouped:
        grouped[cat].sort(key=lambda s: s["name"])

    return {"skills": grouped, "total": len(skill_map)}


@router.get("/{name}")
async def get_skill(name: str, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Get skill content — org copy if exists, else template."""
    # Check org override first
    if dl.org_id:
        org_content = await dl.get_org_skill(name)
        if org_content:
            template = resolve_template(name)
            return {
                "name": name,
                "content": org_content,
                "source": "org",
                "is_customized": True,
                "has_template": template is not None,
                "category": infer_category(name),
            }

    # Fall back to template
    template = resolve_template(name)
    if template:
        return {
            "name": name,
            "content": template,
            "source": "template",
            "is_customized": False,
            "has_template": True,
            "category": infer_category(name),
        }

    return JSONResponse(status_code=404, content={"error": f"Skill '{name}' not found."})


@router.put("/{name}")
async def save_skill(name: str, req: SkillContent,
                     dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Save skill content — creates/updates org override. Does not modify templates."""
    if not req.content.strip():
        return JSONResponse(status_code=400, content={"error": "Content must be non-empty."})

    if not dl.org_id:
        return JSONResponse(status_code=400, content={"error": "No organization context."})

    category = infer_category(name)
    result = await dl.save_org_skill(name, category, req.content, source="manual")
    await dl.commit()
    return {"saved": True, **result}


@router.post("")
async def create_skill(req: NewSkill,
                       dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Create a new custom skill (org-only, no template on disk)."""
    name = "".join(c for c in req.name.lower() if c.isalnum() or c == "_")
    if not name:
        return JSONResponse(status_code=400, content={"error": "Invalid skill name."})

    if not dl.org_id:
        return JSONResponse(status_code=400, content={"error": "No organization context."})

    # Check if already exists
    existing = await dl.get_org_skill(name)
    if existing or resolve_template(name):
        return JSONResponse(status_code=409, content={"error": f"Skill '{name}' already exists."})

    category = req.category if req.category in ("channel", "marketing", "seo", "processing") else "marketing"
    content = req.content or f"# {name}\n\nYour skill prompt here.\n"
    result = await dl.save_org_skill(name, category, content, source="manual")
    await dl.commit()
    return {"created": True, **result}


@router.delete("/{name}")
async def delete_skill(name: str, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Delete org override — reverts to template if one exists. Deletes custom skills entirely."""
    if not dl.org_id:
        return JSONResponse(status_code=400, content={"error": "No organization context."})

    deleted = await dl.delete_org_skill(name)
    if not deleted:
        return JSONResponse(status_code=404, content={"error": f"No org skill '{name}' to delete."})

    await dl.commit()
    has_template = resolve_template(name) is not None
    return {
        "deleted": True,
        "name": name,
        "reverted_to_template": has_template,
    }


@router.post("/{name}/reset")
async def reset_skill(name: str, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Reset skill to template — deletes org override."""
    if not dl.org_id:
        return JSONResponse(status_code=400, content={"error": "No organization context."})

    template = resolve_template(name)
    if not template:
        return JSONResponse(status_code=404, content={"error": f"No template for '{name}' to reset to."})

    await dl.delete_org_skill(name)
    await dl.commit()
    return {"reset": True, "name": name}


@router.post("/rewrite")
async def rewrite_all_skills(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Re-run skill rewrite from the org's current profile. Manual refresh button."""
    if not dl.org_id:
        return JSONResponse(status_code=400, content={"error": "No organization context."})

    # Build profile from stored settings
    stored = await dl.get_all_settings()
    profile = {
        "company_name": stored.get("onboard_company_name", ""),
        "industry": stored.get("onboard_industry", ""),
        "persona": stored.get("voice_persona", ""),
        "tone": stored.get("voice_tone", ""),
        "bio": stored.get("voice_bio", ""),
        "audience": stored.get("voice_audience", ""),
        "golden_anchor": stored.get("voice_golden_anchor", ""),
        "brand_keywords": _parse_list(stored.get("voice_brand_keywords", "[]")),
        "never_say": _parse_list(stored.get("voice_never_say", "[]")),
        "always": stored.get("voice_always", ""),
        "topics": _parse_list(stored.get("onboard_topics", "[]")),
        "competitors": _parse_list(stored.get("onboard_competitors", "[]")),
        "linkedin_style": stored.get("voice_linkedin_style", ""),
        "x_style": stored.get("voice_x_style", ""),
        "blog_style": stored.get("voice_blog_style", ""),
    }

    if not profile["company_name"]:
        return JSONResponse(status_code=400, content={
            "error": "No company profile found. Complete onboarding first."
        })

    try:
        from services.skill_rewriter import rewrite_skills_for_org
        api_key = await dl.resolve_api_key()
        rewritten = await rewrite_skills_for_org(profile, api_key=api_key, org_id=dl.org_id)
        count = 0
        for skill_name, content in rewritten.items():
            category = infer_category(skill_name)
            await dl.save_org_skill(skill_name, category, content, source="onboarding")
            count += 1
        await dl.commit()
        return {"rewritten": count, "skills": list(rewritten.keys())}
    except Exception as e:
        log.error("Skill rewrite failed: %s", e)
        return JSONResponse(status_code=500, content={"error": f"Skill rewrite failed: {e}"})


def _parse_list(val: str) -> list:
    """Parse a JSON list string, returning empty list on failure."""
    import json
    try:
        parsed = json.loads(val)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []
