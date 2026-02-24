"""Pipeline endpoints — trigger scout, generate, regenerate, and full runs."""

import datetime
import json
import re

import anthropic

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from database import get_data_layer
from models import ContentChannel
from services.data_layer import DataLayer
from services.scout import run_full_scout, filter_signals_for_relevance, scout_visibility_check, suggest_scout_sources
from services.engine import generate_brief, generate_all_content, regenerate_single
from services.humanizer import humanize

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


class GenerateRequest(BaseModel):
    channels: list[str] = []
    team_member_id: int | None = None


def _build_company_context(voice: dict) -> str:
    """Build a compact company description for the relevance filter."""
    parts = []
    name = voice.get("onboard_company_name", "")
    if name:
        parts.append(f"Company: {name}")
    industry = voice.get("onboard_industry", "")
    if industry:
        parts.append(f"Industry: {industry}")
    topics = voice.get("onboard_topics", "")
    if topics:
        parts.append(f"Topics: {topics}")
    competitors = voice.get("onboard_competitors", "")
    if competitors:
        parts.append(f"Competitors: {competitors}")
    audience = voice.get("voice_audience", "")
    if audience:
        parts.append(f"Audience: {audience}")
    persona = voice.get("voice_persona", "")
    if persona:
        parts.append(f"Persona: {persona}")
    return "\n".join(parts) if parts else "General technology company"


@router.post("/scout")
async def trigger_scout(since_hours: int = 24, dl: DataLayer = Depends(get_data_layer)):
    """Run the scout — pull signals from all sources."""
    api_key = await dl.resolve_api_key()
    org_settings = await dl.get_all_settings()
    voice = await dl.get_voice_settings()
    company_ctx = _build_company_context(voice)
    raw_signals = await run_full_scout(
        since_hours, org_settings=org_settings,
        api_key=api_key, company_context=company_ctx,
    )

    # Relevance filter — discard off-topic noise
    signals = await filter_signals_for_relevance(raw_signals, company_ctx, api_key=api_key)

    # Prune signals older than 7 days
    pruned = await dl.prune_old_signals(days=7)

    # Save with URL dedup — skip signals we already have
    saved = []
    skipped = 0
    for s in signals:
        url = s.get("url", "")
        if url and await dl.signal_exists(url):
            skipped += 1
            continue
        result = await dl.save_signal(s)
        saved.append(result)

    await dl.commit()
    return {
        "signals_raw": len(raw_signals),
        "signals_relevant": len(signals),
        "signals_saved": len(saved),
        "signals_skipped_dupes": skipped,
        "signals_pruned": pruned,
        "signals": [{"title": s.get("title", ""), "type": s.get("type", ""), "source": s.get("source", "")} for s in saved],
    }


@router.post("/generate")
async def trigger_generate(
    req: GenerateRequest = GenerateRequest(),
    dl: DataLayer = Depends(get_data_layer),
):
    """Generate content from today's signals. Runs brief → content → humanizer."""
    channels = req.channels or None
    team_member = None
    if req.team_member_id:
        members = await dl.list_team_members()
        team_member = next((m for m in members if m["id"] == req.team_member_id), None)
    signal_dicts = await dl.list_signals(limit=20)

    if not signal_dicts:
        return {"error": "No signals found. Run /api/pipeline/scout first."}

    # Load voice settings and memory context
    voice = await dl.get_voice_settings()
    memory = await dl.get_memory_context()

    # Resolve API key for this org
    api_key = await dl.resolve_api_key()

    # Generate structured brief with per-channel angles
    brief_data = await generate_brief(signal_dicts, memory=memory, voice_settings=voice, api_key=api_key)
    brief = await dl.save_brief({
        "date": str(datetime.date.today()),
        "summary": brief_data["summary"],
        "angle": brief_data["angle"],
        "signal_ids": ",".join(str(s.get("id", "")) for s in signal_dicts[:10]),
    })

    # Parse channels
    target_channels = None
    if channels:
        target_channels = [ContentChannel(c) for c in channels]

    # Load assets for system prompt context
    assets = await dl.list_assets()

    # Generate content — each channel gets its own signal selection and angle
    content_items = await generate_all_content(
        brief_data, signal_dicts, target_channels,
        memory=memory, voice_settings=voice, assets=assets,
        api_key=api_key, team_member=team_member,
    )

    author = f"team:{team_member['id']}" if team_member else "company"
    saved_content = []
    for item in content_items:
        raw_body = item["body"]
        clean_body = humanize(raw_body)
        result = await dl.save_content({
            "brief_id": brief.get("id"),
            "signal_id": signal_dicts[0].get("id") if signal_dicts else None,
            "channel": item["channel"],
            "status": "queued",
            "headline": item["headline"],
            "body": clean_body,
            "body_raw": raw_body,
            "author": author,
            "source_signal_ids": item.get("source_signal_ids", ""),
        })
        saved_content.append(result)
        # Increment usage count on each source signal
        for sid in (item.get("source_signal_ids", "") or "").split(","):
            sid = sid.strip()
            if sid and sid.isdigit():
                await dl.increment_signal_usage(int(sid))

    await dl.commit()
    return {
        "brief": {"id": brief.get("id"), "angle": brief_data["angle"]},
        "content_generated": len(saved_content),
        "items": [{"id": c.get("id"), "channel": c.get("channel", ""), "headline": c.get("headline", "")} for c in saved_content],
    }


class RegenerateRequest(BaseModel):
    feedback: str = ""


@router.post("/regenerate/{content_id}")
async def regenerate_content(content_id: int, req: RegenerateRequest,
                              dl: DataLayer = Depends(get_data_layer)):
    """Regenerate a single piece of content with optional editor feedback."""
    existing = await dl.get_content(content_id)
    if not existing:
        return {"error": "Content not found"}

    channel = ContentChannel(existing["channel"])
    voice = await dl.get_voice_settings()
    memory = await dl.get_memory_context()
    api_key = await dl.resolve_api_key()

    # Use the raw (pre-humanizer) body as source, fall back to cleaned body
    source_body = existing.get("body_raw", "") or existing.get("body", "")

    try:
        result = await regenerate_single(
            source_body, channel,
            feedback=req.feedback,
            memory=memory, voice_settings=voice,
            api_key=api_key,
        )

        # Humanize and update the content record
        raw_body = result["body"]
        clean_body = humanize(raw_body)

        await dl.update_content_status(content_id, "queued",
                                        headline=result["headline"],
                                        body=clean_body,
                                        body_raw=raw_body)
        await dl.commit()

        return {
            "id": content_id,
            "channel": channel.value,
            "headline": result["headline"],
            "status": "queued",
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Regeneration failed: {str(e)}", "id": content_id},
        )


@router.post("/run")
async def full_run(req: GenerateRequest = GenerateRequest(), since_hours: int = 24, dl: DataLayer = Depends(get_data_layer)):
    """Full pipeline: scout → brief → generate → humanize → queue."""
    channels = req.channels or None
    team_member = None
    if req.team_member_id:
        members = await dl.list_team_members()
        team_member = next((m for m in members if m["id"] == req.team_member_id), None)
    api_key = await dl.resolve_api_key()
    org_settings = await dl.get_all_settings()
    voice = await dl.get_voice_settings()
    company_ctx = _build_company_context(voice)
    raw_signals = await run_full_scout(
        since_hours, org_settings=org_settings,
        api_key=api_key, company_context=company_ctx,
    )

    # Relevance filter — discard off-topic noise before generating content
    filtered_signals = await filter_signals_for_relevance(raw_signals, company_ctx, api_key=api_key)

    # Prune old signals + dedup
    await dl.prune_old_signals(days=7)

    saved_signals = []
    for s in filtered_signals:
        url = s.get("url", "")
        if url and await dl.signal_exists(url):
            continue
        result = await dl.save_signal(s)
        saved_signals.append(result)

    if not saved_signals:
        await dl.commit()
        return {"status": "no_signals", "message": "Scout found nothing. Wire is quiet."}

    signal_dicts = saved_signals

    # Load voice settings and memory context
    voice = await dl.get_voice_settings()
    memory = await dl.get_memory_context()

    # Structured brief with per-channel angles
    brief_data = await generate_brief(signal_dicts, memory=memory, voice_settings=voice, api_key=api_key)
    brief = await dl.save_brief({
        "date": str(datetime.date.today()),
        "summary": brief_data["summary"],
        "angle": brief_data["angle"],
        "signal_ids": ",".join(str(s.get("id", "")) for s in signal_dicts[:10]),
    })

    # Load assets for system prompt context
    assets = await dl.list_assets()

    # Parse channels
    target_channels = [ContentChannel(c) for c in channels] if channels else None

    # Generate all channels — each gets targeted signals and its own angle
    content_items = await generate_all_content(
        brief_data, signal_dicts, target_channels,
        memory=memory, voice_settings=voice, assets=assets,
        api_key=api_key, team_member=team_member,
    )

    author = f"team:{team_member['id']}" if team_member else "company"
    saved_content = []
    for item in content_items:
        raw_body = item["body"]
        clean_body = humanize(raw_body)
        result = await dl.save_content({
            "brief_id": brief.get("id"),
            "signal_id": signal_dicts[0].get("id") if signal_dicts else None,
            "channel": item["channel"],
            "status": "queued",
            "headline": item["headline"],
            "body": clean_body,
            "body_raw": raw_body,
            "author": author,
            "source_signal_ids": item.get("source_signal_ids", ""),
        })
        saved_content.append(result)
        # Increment usage count on each source signal
        for sid in (item.get("source_signal_ids", "") or "").split(","):
            sid = sid.strip()
            if sid and sid.isdigit():
                await dl.increment_signal_usage(int(sid))

    await dl.commit()

    return {
        "status": "complete",
        "signals": len(saved_signals),
        "brief": {"id": brief.get("id"), "angle": brief_data["angle"]},
        "content": [{"id": c.get("id"), "channel": c.get("channel", ""), "headline": c.get("headline", "")} for c in saved_content],
    }


class VisibilityRequest(BaseModel):
    domain: str
    queries: list[str] = []


@router.post("/visibility")
async def check_visibility(req: VisibilityRequest, dl: DataLayer = Depends(get_data_layer)):
    """Check how visible a company's domain is in Claude web search results.

    Searches for each query and checks if the domain appears.
    Returns per-query results + overall visibility score.
    """
    if not req.domain:
        return {"error": "Domain is required"}

    queries = req.queries
    if not queries:
        # Fall back to web queries from settings, then HN keywords
        org_settings = await dl.get_all_settings()
        queries = _parse_json_list_safe(org_settings.get("scout_web_queries", ""))
        if not queries:
            queries = _parse_json_list_safe(org_settings.get("scout_hn_keywords", ""))
        if not queries:
            return {"error": "No queries provided and none configured in scout settings"}

    api_key = await dl.resolve_api_key()
    result = await scout_visibility_check(queries, req.domain, api_key=api_key)
    return result


def _parse_json_list_safe(raw: str) -> list:
    """Parse a JSON list from a settings string."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


@router.post("/recommend")
async def recommend_content(dl: DataLayer = Depends(get_data_layer)):
    """Ask Claude to look at current signals and suggest specific content actions.

    Returns 3-5 prioritized recommendations: channel, angle, source signals, reasoning.
    These are *suggestions* — the editor picks which to act on.
    """
    api_key = await dl.resolve_api_key()
    if not api_key:
        return {"error": "No Anthropic API key configured."}

    voice = await dl.get_voice_settings()
    company_ctx = _build_company_context(voice)
    signals = await dl.list_signals(limit=20)

    if not signals:
        return {"recommendations": [], "message": "No signals on the wire. Run Scout first."}

    # Build a compact signal digest for the prompt
    signal_lines = []
    for s in signals[:15]:
        sig_type = s.get("type", "unknown")
        title = s.get("title", "")
        source = s.get("source", "")
        body_preview = (s.get("body", "") or "")[:200]
        prioritized = "★ " if s.get("prioritized") else ""
        line = f"[{s['id']}] {prioritized}[{sig_type}] {source}: {title}"
        if body_preview:
            line += f"\n     → {body_preview}"
        signal_lines.append(line)

    channels_available = [c.value for c in ContentChannel]

    prompt = f"""You are an editorial advisor for {company_ctx}.

Here are the current signals on the wire:

{chr(10).join(signal_lines)}

Available content channels: {', '.join(channels_available)}

Your job: suggest 3-5 specific, actionable content pieces this company should create RIGHT NOW based on these signals.

Think like an editor — what would move the needle? What's timely? What gives this company a unique angle?

For each suggestion, respond with this exact JSON structure:
{{
  "recommendations": [
    {{
      "channel": "linkedin",
      "headline": "A specific, concrete headline for this piece",
      "angle": "One sentence: what's the specific editorial angle or take",
      "reasoning": "Why this matters now — 1-2 sentences max",
      "urgency": "high|medium|low",
      "signal_ids": [1, 2]
    }}
  ]
}}

Rules:
- Be specific. "Post about our new release" is useless. "LinkedIn post: why our v2.3 multi-tenant support solves the exact problem HN is debating today" is useful.
- Match channel to content type — GitHub releases → release email or blog; HN trends → LinkedIn/X thread
- ★ prioritized signals should get at least one recommendation
- Urgency = high if the signal is time-sensitive (trending, breaking), medium if relevant, low if evergreen
- Only return JSON. No prose outside the JSON.
"""

    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # Extract JSON if wrapped in code fences
        json_match = re.search(r'\{[\s\S]*\}', raw)
        if json_match:
            data = json.loads(json_match.group(0))
            recs = data.get("recommendations", [])
            # Attach signal metadata to each recommendation for frontend display
            sig_map = {s["id"]: s for s in signals}
            for rec in recs:
                rec["signals"] = [
                    {"id": sid, "type": sig_map[sid]["type"], "title": sig_map[sid]["title"][:80]}
                    for sid in (rec.get("signal_ids") or [])
                    if sid in sig_map
                ]
            return {"recommendations": recs}
        return {"error": "Model returned unparseable response", "recommendations": []}
    except json.JSONDecodeError as e:
        return {"error": f"JSON parse failed: {str(e)}", "recommendations": []}
    except Exception as e:
        return {"error": str(e), "recommendations": []}


@router.post("/suggest-sources")
async def suggest_sources(dl: DataLayer = Depends(get_data_layer)):
    """Use Claude to suggest scout sources based on company context.

    Returns suggested subreddits, HN keywords, RSS feeds, and web search queries.
    Excludes sources already configured.
    """
    api_key = await dl.resolve_api_key()
    if not api_key:
        return {"error": "No Anthropic API key configured."}

    voice = await dl.get_voice_settings()
    company_ctx = _build_company_context(voice)

    if company_ctx == "General technology company":
        return {"error": "No company profile found. Complete onboarding first so we know what to suggest."}

    # Gather existing sources to avoid duplicates
    org_settings = await dl.get_all_settings()
    existing = {}
    for key in ["scout_subreddits", "scout_hn_keywords", "scout_rss_feeds", "scout_web_queries"]:
        existing[key] = _parse_json_list_safe(org_settings.get(key, ""))

    result = await suggest_scout_sources(company_ctx, existing_sources=existing, api_key=api_key)
    return result
