"""Skills Library API — list, read, create, edit, delete skill .md files."""

import os
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/skills", tags=["skills"])

SKILLS_DIR = Path(__file__).parent.parent / "skills"
CORE_SKILLS = {"humanizer", "seo_geo"}


class SkillContent(BaseModel):
    content: str


class NewSkill(BaseModel):
    name: str
    content: str = ""


@router.get("")
async def list_skills():
    """List all .md skill files."""
    skills = []
    if not SKILLS_DIR.exists():
        return skills

    for f in sorted(SKILLS_DIR.iterdir()):
        if f.suffix != ".md" or f.name in ("README.md",):
            continue
        name = f.stem
        first_line = ""
        try:
            first_line = f.read_text().split("\n")[0][:100]
        except Exception:
            pass
        stat = f.stat()
        skills.append({
            "name": name,
            "filename": f.name,
            "size_bytes": stat.st_size,
            "modified_at": stat.st_mtime,
            "first_line": first_line,
        })
    return skills


@router.get("/{name}")
async def get_skill(name: str):
    """Return full content of a skill file."""
    path = SKILLS_DIR / f"{name}.md"
    if not path.exists():
        return JSONResponse(status_code=404, content={"error": f"Skill '{name}' not found."})
    return {"name": name, "content": path.read_text()}


@router.put("/{name}")
async def save_skill(name: str, req: SkillContent):
    """Save updated content to a skill file."""
    if not req.content.strip():
        return JSONResponse(status_code=400, content={"error": "Content must be non-empty."})

    path = SKILLS_DIR / f"{name}.md"
    if not path.exists():
        return JSONResponse(status_code=404, content={"error": f"Skill '{name}' not found."})

    path.write_text(req.content)
    return {"saved": True, "name": name, "size_bytes": path.stat().st_size}


@router.post("")
async def create_skill(req: NewSkill):
    """Create a new skill file."""
    # Sanitize name
    name = "".join(c for c in req.name.lower() if c.isalnum() or c == "_")
    if not name:
        return JSONResponse(status_code=400, content={"error": "Invalid skill name."})

    path = SKILLS_DIR / f"{name}.md"
    if path.exists():
        return JSONResponse(status_code=409, content={"error": f"Skill '{name}' already exists."})

    content = req.content or f"# {name}\n\nYour skill prompt here.\n"
    path.write_text(content)
    return {"created": True, "name": name, "size_bytes": path.stat().st_size}


@router.delete("/{name}")
async def delete_skill(name: str):
    """Delete a skill file. Refuses to delete core skills."""
    if name in CORE_SKILLS:
        return JSONResponse(status_code=403, content={"error": f"Cannot delete core skill '{name}'."})

    path = SKILLS_DIR / f"{name}.md"
    if not path.exists():
        return JSONResponse(status_code=404, content={"error": f"Skill '{name}' not found."})

    path.unlink()
    return {"deleted": True, "name": name}
