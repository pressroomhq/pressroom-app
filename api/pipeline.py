"""Pipeline endpoints — trigger scout, generate, regenerate, and full runs."""

import datetime
import json
import logging
import re

import anthropic

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.auth import get_authenticated_data_layer
from models import ContentChannel
from services.data_layer import DataLayer
from services.scout import run_full_scout, filter_signals_for_relevance, scout_visibility_check, suggest_scout_sources
from services.engine import generate_brief, generate_all_content, regenerate_single, generate_ideas, generate_strategy
from services.humanizer import humanize

log = logging.getLogger("pressroom")

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
async def trigger_scout(since_hours: int = 24, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Run the scout — pull signals from all sources."""
    log.info("=" * 60)
    log.info("[pipeline] SCOUT — starting (lookback=%dh)", since_hours)
    log.info("=" * 60)

    api_key = await dl.resolve_api_key()
    org_settings = await dl.get_all_settings()
    voice = await dl.get_voice_settings()
    company_ctx = _build_company_context(voice)
    log.info("[pipeline] Company context loaded: %s", company_ctx[:120])

    log.info("[pipeline] Running full scout across all sources...")
    raw_signals = await run_full_scout(
        since_hours, org_settings=org_settings,
        api_key=api_key, company_context=company_ctx,
    )
    log.info("[pipeline] Scout returned %d raw signals", len(raw_signals))

    # Relevance filter — discard off-topic noise
    log.info("[pipeline] Running relevance filter on %d signals...", len(raw_signals))
    signals = await filter_signals_for_relevance(raw_signals, company_ctx, api_key=api_key)
    log.info("[pipeline] Relevance filter: %d/%d signals kept", len(signals), len(raw_signals))

    # Prune signals older than 7 days
    pruned = await dl.prune_old_signals(days=7)
    if pruned:
        log.info("[pipeline] Pruned %d old signals (>7 days)", pruned)

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
    log.info("[pipeline] SCOUT — complete: %d saved, %d dupes skipped, %d pruned",
             len(saved), skipped, pruned)
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
    dl: DataLayer = Depends(get_authenticated_data_layer),
):
    """Generate content from today's signals. Runs brief → content → humanizer."""
    log.info("=" * 60)
    log.info("[pipeline] GENERATE — starting content generation pipeline")
    log.info("=" * 60)

    channels = req.channels or None
    team_member = None
    if req.team_member_id:
        members = await dl.list_team_members()
        team_member = next((m for m in members if m["id"] == req.team_member_id), None)
        log.info("[pipeline] Team member: %s", team_member.get("name") if team_member else "not found")
    signal_dicts = await dl.list_signals(limit=20)

    if not signal_dicts:
        log.warning("[pipeline] No signals found — aborting generation")
        return {"error": "No signals found. Run /api/pipeline/scout first."}
    log.info("[pipeline] Loaded %d signals from wire", len(signal_dicts))

    # Load voice settings and memory context
    log.info("[pipeline] Loading voice settings and memory context...")
    voice = await dl.get_voice_settings()
    memory = await dl.get_memory_context()
    log.info("[pipeline] Voice=%s, memory=%s",
             "configured" if voice else "default",
             "loaded" if memory else "empty")

    # Resolve API key for this org
    api_key = await dl.resolve_api_key()

    # Generate structured brief with per-channel angles
    log.info("[pipeline] Step 1/3: Generating editorial brief...")
    brief_data = await generate_brief(signal_dicts, memory=memory, voice_settings=voice, api_key=api_key)
    brief = await dl.save_brief({
        "date": str(datetime.date.today()),
        "summary": brief_data["summary"],
        "angle": brief_data["angle"],
        "signal_ids": ",".join(str(s.get("id", "")) for s in signal_dicts[:10]),
    })
    log.info("[pipeline] Brief saved (id=%s, angle: %s)", brief.get("id"), brief_data["angle"][:100] if brief_data["angle"] else "none")

    # Parse channels
    target_channels = None
    if channels:
        target_channels = [ContentChannel(c) for c in channels]
        log.info("[pipeline] Target channels: %s", [ch.value for ch in target_channels])

    # Load assets for system prompt context
    assets = await dl.list_assets()
    log.info("[pipeline] Assets loaded: %d", len(assets) if assets else 0)

    # Generate content — each channel gets its own signal selection and angle
    log.info("[pipeline] Step 2/3: Generating content across channels...")
    content_items = await generate_all_content(
        brief_data, signal_dicts, target_channels,
        memory=memory, voice_settings=voice, assets=assets,
        api_key=api_key, team_member=team_member, dl=dl,
    )
    log.info("[pipeline] Content generation complete — %d pieces", len(content_items))

    author = f"team:{team_member['id']}" if team_member else "company"
    log.info("[pipeline] Step 3/3: Humanizing and saving to queue...")
    saved_content = []
    for i, item in enumerate(content_items):
        raw_body = item["body"]
        log.info("[pipeline] Humanizing %d/%d: %s...", i + 1, len(content_items),
                 item["channel"].value if hasattr(item["channel"], "value") else item["channel"])
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
        log.info("[pipeline] Saved content id=%s (%s) to queue", result.get("id"),
                 item["channel"].value if hasattr(item["channel"], "value") else item["channel"])
        # Increment usage count on each source signal
        for sid in (item.get("source_signal_ids", "") or "").split(","):
            sid = sid.strip()
            if sid and sid.isdigit():
                await dl.increment_signal_usage(int(sid))

    await dl.commit()
    log.info("[pipeline] GENERATE — complete: %d content pieces queued", len(saved_content))
    return {
        "brief": {"id": brief.get("id"), "angle": brief_data["angle"]},
        "content_generated": len(saved_content),
        "items": [{"id": c.get("id"), "channel": c.get("channel", ""), "headline": c.get("headline", "")} for c in saved_content],
    }


class RegenerateRequest(BaseModel):
    feedback: str = ""


@router.post("/regenerate/{content_id}")
async def regenerate_content(content_id: int, req: RegenerateRequest,
                              dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Regenerate a single piece of content with optional editor feedback."""
    log.info("[pipeline] REGENERATE — content #%s (feedback=%s)", content_id,
             f'"{req.feedback[:60]}"' if req.feedback else "none")

    existing = await dl.get_content(content_id)
    if not existing:
        log.warning("[pipeline] Content #%s not found", content_id)
        return {"error": "Content not found"}

    channel = ContentChannel(existing["channel"])
    log.info("[pipeline] Regenerating %s content #%s", channel.value, content_id)

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
            api_key=api_key, dl=dl,
        )

        # Humanize and update the content record
        raw_body = result["body"]
        log.info("[pipeline] Humanizing regenerated content...")
        clean_body = humanize(raw_body)

        await dl.update_content_status(content_id, "queued",
                                        headline=result["headline"],
                                        body=clean_body,
                                        body_raw=raw_body)
        await dl.commit()

        log.info("[pipeline] REGENERATE — content #%s updated and re-queued", content_id)
        return {
            "id": content_id,
            "channel": channel.value,
            "headline": result["headline"],
            "status": "queued",
        }
    except Exception as e:
        log.error("[pipeline] Regeneration failed for #%s: %s", content_id, e)
        return JSONResponse(
            status_code=500,
            content={"error": f"Regeneration failed: {str(e)}", "id": content_id},
        )


@router.post("/run")
async def full_run(req: GenerateRequest = GenerateRequest(), since_hours: int = 24, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Full pipeline: scout → brief → generate → humanize → queue."""
    log.info("*" * 60)
    log.info("[pipeline] FULL RUN — scout -> brief -> generate -> humanize -> queue")
    log.info("*" * 60)

    channels = req.channels or None
    team_member = None
    if req.team_member_id:
        members = await dl.list_team_members()
        team_member = next((m for m in members if m["id"] == req.team_member_id), None)
        log.info("[pipeline] Team member: %s", team_member.get("name") if team_member else "not found")

    api_key = await dl.resolve_api_key()
    org_settings = await dl.get_all_settings()
    voice = await dl.get_voice_settings()
    company_ctx = _build_company_context(voice)

    # STEP 1: Scout
    log.info("[pipeline] STEP 1/4: Running scout (lookback=%dh)...", since_hours)
    raw_signals = await run_full_scout(
        since_hours, org_settings=org_settings,
        api_key=api_key, company_context=company_ctx,
    )
    log.info("[pipeline] Scout returned %d raw signals", len(raw_signals))

    # Relevance filter — discard off-topic noise before generating content
    log.info("[pipeline] Running relevance filter...")
    filtered_signals = await filter_signals_for_relevance(raw_signals, company_ctx, api_key=api_key)
    log.info("[pipeline] Relevance filter: %d/%d kept", len(filtered_signals), len(raw_signals))

    # Prune old signals + dedup
    pruned = await dl.prune_old_signals(days=7)
    if pruned:
        log.info("[pipeline] Pruned %d old signals", pruned)

    saved_signals = []
    skipped = 0
    for s in filtered_signals:
        url = s.get("url", "")
        if url and await dl.signal_exists(url):
            skipped += 1
            continue
        result = await dl.save_signal(s)
        saved_signals.append(result)
    log.info("[pipeline] Signals saved: %d new, %d dupes skipped", len(saved_signals), skipped)

    if not saved_signals:
        await dl.commit()
        log.info("[pipeline] FULL RUN — no new signals found, wire is quiet")
        return {"status": "no_signals", "message": "Scout found nothing. Wire is quiet."}

    signal_dicts = saved_signals

    # STEP 2: Brief
    log.info("[pipeline] STEP 2/4: Generating editorial brief from %d signals...", len(signal_dicts))
    voice = await dl.get_voice_settings()
    memory = await dl.get_memory_context()

    brief_data = await generate_brief(signal_dicts, memory=memory, voice_settings=voice, api_key=api_key)
    brief = await dl.save_brief({
        "date": str(datetime.date.today()),
        "summary": brief_data["summary"],
        "angle": brief_data["angle"],
        "signal_ids": ",".join(str(s.get("id", "")) for s in signal_dicts[:10]),
    })
    log.info("[pipeline] Brief saved (id=%s)", brief.get("id"))

    # Load assets for system prompt context
    assets = await dl.list_assets()

    # Parse channels
    target_channels = [ContentChannel(c) for c in channels] if channels else None

    # STEP 3: Generate
    log.info("[pipeline] STEP 3/4: Generating content across channels...")
    content_items = await generate_all_content(
        brief_data, signal_dicts, target_channels,
        memory=memory, voice_settings=voice, assets=assets,
        api_key=api_key, team_member=team_member, dl=dl,
    )
    log.info("[pipeline] Content generated: %d pieces", len(content_items))

    # STEP 4: Humanize + Queue
    log.info("[pipeline] STEP 4/4: Humanizing and queueing %d pieces...", len(content_items))
    author = f"team:{team_member['id']}" if team_member else "company"
    saved_content = []
    for i, item in enumerate(content_items):
        raw_body = item["body"]
        log.info("[pipeline] Humanizing %d/%d: %s", i + 1, len(content_items),
                 item["channel"].value if hasattr(item["channel"], "value") else item["channel"])
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
        log.info("[pipeline] Queued content id=%s (%s)", result.get("id"),
                 item["channel"].value if hasattr(item["channel"], "value") else item["channel"])
        # Increment usage count on each source signal
        for sid in (item.get("source_signal_ids", "") or "").split(","):
            sid = sid.strip()
            if sid and sid.isdigit():
                await dl.increment_signal_usage(int(sid))

    await dl.commit()

    log.info("[pipeline] FULL RUN — complete: %d signals -> %d content pieces queued", len(saved_signals), len(saved_content))
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
async def check_visibility(req: VisibilityRequest, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Check how visible a company's domain is in Claude web search results.

    Searches for each query and checks if the domain appears.
    Returns per-query results + overall visibility score.
    """
    log.info("[pipeline] VISIBILITY CHECK — domain=%s, %d queries", req.domain, len(req.queries))
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
    log.info("[pipeline] Running visibility check: %d queries against %s", len(queries), req.domain)
    result = await scout_visibility_check(queries, req.domain, api_key=api_key)
    log.info("[pipeline] VISIBILITY CHECK — complete: score=%s%%", result.get("score", "?"))
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


class RecommendIn(BaseModel):
    channels: list[str] = []


@router.post("/recommend")
async def recommend_content(req: RecommendIn = RecommendIn(), dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Ask Claude to look at current signals and suggest specific content actions.

    Returns 3-5 prioritized recommendations: channel, angle, source signals, reasoning.
    These are *suggestions* — the editor picks which to act on.
    """
    log.info("[pipeline] RECOMMEND — generating editorial recommendations")
    api_key = await dl.resolve_api_key()
    if not api_key:
        log.warning("[pipeline] No API key — cannot generate recommendations")
        return {"error": "No Anthropic API key configured."}

    voice = await dl.get_voice_settings()
    company_ctx = _build_company_context(voice)
    signals = await dl.list_signals(limit=20)

    if not signals:
        log.info("[pipeline] No signals on wire — skipping recommendations")
        return {"recommendations": [], "message": "No signals on the wire. Run Scout first."}
    log.info("[pipeline] Building recommendations from %d signals...", len(signals))

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

    # Use selected channels if provided, otherwise all available
    if req.channels:
        channels_available = [c for c in req.channels if c in [ch.value for ch in ContentChannel]]
    else:
        channels_available = [c.value for c in ContentChannel]

    channels_note = (
        f"The editor has selected these channels: {', '.join(channels_available)}. "
        "Only suggest content for these channels."
        if req.channels else
        f"Available content channels: {', '.join(channels_available)}"
    )

    prompt = f"""You are an editorial advisor for {company_ctx}.

Here are the current signals on the wire:

{chr(10).join(signal_lines)}

{channels_note}

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
    log.info("[pipeline] Calling Claude (claude-opus-4-6) for recommendations...")
    try:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        log.info("[pipeline] Recommendations response received (%d chars)", len(raw))
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
            log.info("[pipeline] RECOMMEND — complete: %d recommendations generated", len(recs))
            for r in recs:
                log.info("[pipeline]   [%s] %s (%s)", r.get("channel"), r.get("headline", "")[:60], r.get("urgency"))
            return {"recommendations": recs}
        log.warning("[pipeline] Model returned unparseable response")
        return {"error": "Model returned unparseable response", "recommendations": []}
    except json.JSONDecodeError as e:
        log.error("[pipeline] Recommendation JSON parse failed: %s", e)
        return {"error": f"JSON parse failed: {str(e)}", "recommendations": []}
    except Exception as e:
        log.error("[pipeline] Recommendation failed: %s", e)
        return {"error": str(e), "recommendations": []}


@router.post("/suggest-sources")
async def suggest_sources(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Use Claude to suggest scout sources based on company context.

    Returns suggested subreddits, HN keywords, RSS feeds, and web search queries.
    Excludes sources already configured.
    """
    log.info("[pipeline] SUGGEST SOURCES — generating source recommendations")
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
    log.info("[pipeline] Existing sources: %s", {k: len(v) for k, v in existing.items() if v})

    result = await suggest_scout_sources(company_ctx, existing_sources=existing, api_key=api_key)
    log.info("[pipeline] SUGGEST SOURCES — complete")
    return result


class IdeasRequest(BaseModel):
    count: int = 5
    priority_signal_ids: list[int] = []


@router.post("/ideas")
async def generate_content_ideas(req: IdeasRequest, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Generate N content ideas from recent signals — concepts only, no full posts."""
    log.info("[pipeline] IDEAS — generating %d ideas (priority signals: %s)",
             req.count, req.priority_signal_ids or "none")
    api_key = await dl.resolve_api_key()
    if not api_key:
        return {"error": "No Anthropic API key configured."}

    org_id = dl.org_id
    voice = await dl.get_voice_settings()

    signals = await dl.list_signals(limit=50)
    if not signals:
        log.info("[pipeline] No signals for ideas generation")
        return {"ideas": [], "note": "No signals in the wire yet — run Scout first."}

    log.info("[pipeline] Generating ideas from %d signals...", len(signals))
    signal_dicts = [dict(s) if not isinstance(s, dict) else s for s in signals]

    ideas = await generate_ideas(
        signals=signal_dicts,
        count=max(1, min(req.count, 20)),
        priority_signal_ids=req.priority_signal_ids,
        voice_settings=voice,
        api_key=api_key,
        org_id=org_id,
    )

    # Persist to org settings so they survive tab switches
    await dl.set_setting("saved_ideas", json.dumps(ideas))
    await dl.commit()

    log.info("[pipeline] IDEAS — complete: %d ideas generated from %d signals", len(ideas), len(signal_dicts))
    return {"ideas": ideas, "signal_count": len(signal_dicts)}


@router.get("/ideas")
async def get_saved_ideas(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Return persisted ideas for this org."""
    raw = await dl.get_setting("saved_ideas") or "[]"
    try:
        ideas = json.loads(raw)
    except Exception:
        ideas = []
    return {"ideas": ideas}


@router.delete("/ideas")
async def clear_saved_ideas(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Clear persisted ideas for this org."""
    await dl.set_setting("saved_ideas", "[]")
    await dl.commit()
    return {"cleared": True}


class StrategyRequest(BaseModel):
    available_channels: list[str] = ["linkedin", "devto", "blog", "release_email", "newsletter"]


@router.post("/strategy")
async def get_content_strategy(req: StrategyRequest, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """One strategic Claude call — looks at signals, audit data, content history.
    Returns recommended channels + angles before the engine fires."""
    api_key = await dl.resolve_api_key()
    if not api_key:
        return {"error": "No Anthropic API key configured."}

    org_id = dl.org_id
    voice = await dl.get_voice_settings()
    memory = await dl.get_memory_context()
    signals = await dl.list_signals(limit=50)

    if not signals:
        return {"error": "No signals yet — run Scout first."}

    signal_dicts = [dict(s) if not isinstance(s, dict) else s for s in signals]

    # Pull latest audit data if available
    audit_data = []
    try:
        audits = await dl.list_audits(limit=3)
        audit_data = audits or []
    except Exception:
        pass

    strategy = await generate_strategy(
        signals=signal_dicts,
        voice_settings=voice,
        memory=memory,
        audit_data=audit_data,
        available_channels=req.available_channels,
        api_key=api_key,
        org_id=org_id,
    )

    return strategy
