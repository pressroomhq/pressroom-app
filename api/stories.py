"""Story Workbench — curate signals, add editorial context, generate targeted content.

A Story is an editorial container: selected signals + angle + notes.
Instead of generating from all signals blindly, the editor builds a focused
story and generates content from that curated context.
"""

import json
import logging
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.auth import get_authenticated_data_layer
from services.data_layer import DataLayer
from services.token_tracker import log_token_usage

log = logging.getLogger("pressroom")

router = APIRouter(prefix="/api/stories", tags=["stories"])


# ── Request models ──

class StoryCreate(BaseModel):
    title: str
    angle: str = ""
    editorial_notes: str = ""
    signal_ids: list[int] = []  # optionally attach signals at creation time


class StoryUpdate(BaseModel):
    title: str | None = None
    angle: str | None = None
    editorial_notes: str | None = None


class AddSignalRequest(BaseModel):
    signal_id: int | str   # int for Scout signals, "wire:N" for WireSignals
    editor_notes: str = ""


class UpdateSignalNotesRequest(BaseModel):
    editor_notes: str


class GenerateRequest(BaseModel):
    channels: list[str] = []  # which channels to generate — empty = all enabled
    team_member_id: int | None = None  # write as this team member (None = company voice)


# ── CRUD ──

@router.get("")
async def list_stories(limit: int = 20, dl: DataLayer = Depends(get_authenticated_data_layer)):
    return await dl.list_stories(limit=limit)


@router.post("")
async def create_story(req: StoryCreate, dl: DataLayer = Depends(get_authenticated_data_layer)):
    story = await dl.create_story({
        "title": req.title,
        "angle": req.angle,
        "editorial_notes": req.editorial_notes,
    })
    # Attach initial signals if provided
    for sid in req.signal_ids:
        await dl.add_signal_to_story(story["id"], sid)
    await dl.commit()
    # Re-fetch to include signals
    return await dl.get_story(story["id"])


@router.get("/{story_id}")
async def get_story(story_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    story = await dl.get_story(story_id)
    if not story:
        return {"error": "Story not found"}
    return story


@router.put("/{story_id}")
async def update_story(story_id: int, req: StoryUpdate, dl: DataLayer = Depends(get_authenticated_data_layer)):
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    if not fields:
        return {"error": "No fields to update"}
    story = await dl.update_story(story_id, **fields)
    if not story:
        return {"error": "Story not found"}
    await dl.commit()
    return story


@router.delete("/{story_id}")
async def delete_story(story_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    deleted = await dl.delete_story(story_id)
    if not deleted:
        return {"error": "Story not found"}
    await dl.commit()
    return {"deleted": story_id}


# ── Signal management ──

@router.post("/{story_id}/signals")
async def add_signal(story_id: int, req: AddSignalRequest, dl: DataLayer = Depends(get_authenticated_data_layer)):
    sid = req.signal_id
    if isinstance(sid, str) and sid.startswith("wire:"):
        wire_id = int(sid.split(":")[1])
        ss = await dl.add_wire_signal_to_story(story_id, wire_id, req.editor_notes)
    else:
        ss = await dl.add_signal_to_story(story_id, int(sid), req.editor_notes)
    if not ss:
        return {"error": "Failed to add signal — check story and signal exist"}
    await dl.commit()
    return ss


@router.delete("/{story_id}/signals/{story_signal_id}")
async def remove_signal(story_id: int, story_signal_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    removed = await dl.remove_signal_from_story(story_signal_id)
    if not removed:
        return {"error": "Story-signal not found"}
    await dl.commit()
    return {"deleted": story_signal_id}


@router.put("/{story_id}/signals/{story_signal_id}")
async def update_signal_notes(story_id: int, story_signal_id: int,
                               req: UpdateSignalNotesRequest,
                               dl: DataLayer = Depends(get_authenticated_data_layer)):
    ss = await dl.update_story_signal_notes(story_signal_id, req.editor_notes)
    if not ss:
        return {"error": "Story-signal not found"}
    await dl.commit()
    return ss


# ── Generate from story ──

@router.post("/{story_id}/generate")
async def generate_from_story(story_id: int, req: GenerateRequest,
                               dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Generate content from a curated story — uses story signals + editorial context."""
    from services.engine import generate_from_story as engine_generate

    story = await dl.get_story(story_id)
    if not story:
        return {"error": "Story not found"}

    # Mark story as generating
    await dl.update_story(story_id, status="generating")
    await dl.commit()

    try:
        api_key = await dl.resolve_api_key()
        team_member = None
        if req.team_member_id:
            members = await dl.list_team_members()
            team_member = next((m for m in members if m["id"] == req.team_member_id), None)
        results = await engine_generate(story, dl, channels=req.channels or None, api_key=api_key, team_member=team_member)
        await dl.update_story(story_id, status="complete")
        await dl.commit()
        return {"story_id": story_id, "generated": len(results), "content": results}
    except Exception as e:
        log.error("Story generation failed (story=%s): %s", story_id, e)
        await dl.update_story(story_id, status="draft")
        await dl.commit()
        return {"error": str(e)}


@router.get("/{story_id}/content")
async def get_story_content(story_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """All content generated from this story."""
    return await dl.list_content(story_id=story_id, limit=50)


# ── Signal Discovery ──

class DiscoverRequest(BaseModel):
    mode: str = "web"  # "web" = search the web, "wire" = search existing signals


@router.post("/{story_id}/discover")
async def discover_signals(story_id: int, req: DiscoverRequest,
                            dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Find new signals related to a story's angle.

    mode="web": Uses Claude web search to find fresh external signals.
    mode="wire": Uses Claude to rank existing signals by relevance to the story.
    """
    story = await dl.get_story(story_id)
    if not story:
        return {"error": "Story not found"}

    api_key = await dl.resolve_api_key()
    if not api_key:
        return {"error": "No Anthropic API key configured."}

    # Build story context from title + angle + editorial notes + attached signal titles
    story_signals = story.get("signals", [])
    signal_titles = [ss.get("signal", {}).get("title", "") for ss in story_signals if ss.get("signal")]
    context = f"Story: {story['title']}"
    if story.get("angle"):
        context += f"\nAngle: {story['angle']}"
    if story.get("editorial_notes"):
        context += f"\nNotes: {story['editorial_notes']}"
    if signal_titles:
        context += f"\nExisting signals: {'; '.join(signal_titles[:5])}"

    if req.mode == "wire":
        return await _discover_from_wire(context, story_id, story_signals, dl, api_key)
    else:
        return await _discover_from_web(context, story_id, dl, api_key)


async def _discover_from_wire(context: str, story_id: int, story_signals: list,
                               dl: DataLayer, api_key: str) -> dict:
    """Rank existing signals (Scout + Wire) by relevance to the story."""
    import anthropic
    from models import WireSignal
    from sqlalchemy import select, desc as sa_desc

    # Scout signals (external intel)
    scout_signals = await dl.list_signals(limit=50)
    for s in scout_signals:
        s["_table"] = "signal"

    # Wire signals (GitHub releases, commits, blog posts — company's own feeds)
    wire_signals = []
    try:
        q = select(WireSignal).where(WireSignal.org_id == dl.org_id).order_by(sa_desc(WireSignal.fetched_at)).limit(50)
        result = await dl.db.execute(q)
        for ws in result.scalars().all():
            wire_signals.append({
                "id": f"wire:{ws.id}",
                "type": ws.type,
                "source": ws.source_name,
                "title": ws.title,
                "body": ws.body or "",
                "url": ws.url or "",
                "_table": "wire",
                "_wire_id": ws.id,
            })
    except Exception:
        pass

    all_candidates = scout_signals + wire_signals
    attached_ids = {ss.get("signal", {}).get("id") or ss.get("signal_id") for ss in story_signals}
    candidates = [s for s in all_candidates if s["id"] not in attached_ids]

    if not candidates:
        return {"mode": "wire", "signals": [], "message": "No unattached signals available."}

    # Build a compact signal list for Claude
    signal_list = "\n".join(
        f"[{s['id']}] ({s.get('type', '')}) {s.get('title', '')} — {(s.get('body', '') or '')[:100]}"
        for s in candidates[:40]
    )

    client = anthropic.Anthropic(api_key=api_key)
    from config import settings as cfg
    response = client.messages.create(
        model=cfg.claude_model_fast,
        max_tokens=500,
        system="You are a content strategist. Return ONLY a JSON array of signal IDs, most relevant first. No commentary.",
        messages=[{"role": "user", "content": (
            f"Given this story context:\n{context}\n\n"
            f"Which of these signals are most relevant? Return the top 8 most relevant IDs as a JSON array.\n\n"
            f"{signal_list}"
        )}],
    )
    await log_token_usage(dl.org_id, "story_discover_wire", response)

    text = response.content[0].text.strip()
    # Parse the JSON array of IDs — IDs may be ints (scout) or "wire:N" strings (wire)
    try:
        text = text.strip("`").removeprefix("json").strip()
        ranked_ids = json.loads(text)
        if not isinstance(ranked_ids, list):
            ranked_ids = []
    except (json.JSONDecodeError, ValueError):
        # Fallback: extract wire:N and plain integer IDs from raw text
        import re
        ranked_ids = []
        for m in re.finditer(r'wire:\d+|\d+', text):
            val = m.group()
            ranked_ids.append(val if val.startswith("wire:") else int(val))

    # Normalize IDs — Claude may return ints for wire signals too; coerce to canonical form
    signal_map = {s["id"]: s for s in candidates}
    # Build map from numeric portion of wire IDs as well, for fuzzy matching
    wire_num_map = {}
    for s in candidates:
        if isinstance(s["id"], str) and s["id"].startswith("wire:"):
            wire_num_map[int(s["id"].split(":")[1])] = s

    ranked = []
    for sid in ranked_ids:
        if sid in signal_map:
            ranked.append(signal_map[sid])
        elif isinstance(sid, int) and sid in wire_num_map:
            ranked.append(wire_num_map[sid])

    return {"mode": "wire", "signals": ranked[:8]}


async def _discover_from_web(context: str, story_id: int,
                              dl: DataLayer, api_key: str) -> dict:
    """Search the web for new signals related to the story."""
    from services.scout import scout_web_search

    # Generate 2-3 targeted search queries from the story context
    import anthropic
    from config import settings as cfg
    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model=cfg.claude_model_fast,
        max_tokens=300,
        system="Return ONLY a JSON array of 3 search query strings. No commentary.",
        messages=[{"role": "user", "content": (
            f"Generate 3 specific web search queries to find fresh news, data, and developments "
            f"related to this editorial story:\n\n{context}\n\n"
            f"Make queries specific enough to find real articles, not generic. "
            f"Include current year 2026 where relevant."
        )}],
    )
    await log_token_usage(dl.org_id, "story_discover_web", response)

    text = response.content[0].text.strip().strip("`").removeprefix("json").strip()
    try:
        queries = json.loads(text)
        if not isinstance(queries, list):
            queries = []
    except (json.JSONDecodeError, ValueError):
        queries = [story.get("title", "")]

    # Run web search with those queries
    signals = await scout_web_search(queries[:3], company_context=context, api_key=api_key)

    # Save discovered signals to the wire
    saved = []
    for s in signals:
        url = s.get("url", "")
        if url and await dl.signal_exists(url):
            continue
        result = await dl.save_signal(s)
        saved.append(result)
    await dl.commit()

    return {
        "mode": "web",
        "queries": queries[:3],
        "signals_found": len(signals),
        "signals_saved": len(saved),
        "signals": saved,
    }
