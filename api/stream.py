"""Stream endpoints — SSE streaming for pipeline operations with live Claude output."""

import json
import datetime
import asyncio
import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from database import get_data_layer, async_session
from models import ContentChannel
from services.data_layer import DataLayer
from services.humanizer import humanize
from config import settings
from services.token_tracker import log_token_usage

log = logging.getLogger("pressroom")

router = APIRouter(prefix="/api/stream", tags=["stream"])


def _sse(event_type: str, content: str, **extra) -> str:
    """Format an SSE event."""
    payload = {"type": event_type, "content": content, **extra}
    return f"data: {json.dumps(payload)}\n\n"


@router.get("/generate")
async def stream_generate(
    channels: str = "",
    team_member_id: int | None = None,
    x_org_id: int | None = None,
):
    """Stream the generate pipeline as SSE — brief + content generation with live Claude tokens."""
    import anthropic
    from services.scout import run_full_scout, filter_signals_for_relevance
    from services.engine import (
        generate_brief, generate_all_content, _build_voice_block,
        _build_system_prompt, _rank_signals_for_channel, _build_memory_block,
        _build_intelligence_block, _extract_headline, CHANNEL_RULES,
    )

    async def event_generator():
        try:
            async with async_session() as session:
                dl = DataLayer(session, org_id=x_org_id)

                # Parse channels
                channel_list = [c.strip() for c in channels.split(",") if c.strip()] if channels else []

                # Resolve team member
                team_member = None
                if team_member_id:
                    members = await dl.list_team_members()
                    team_member = next((m for m in members if m["id"] == team_member_id), None)

                signal_dicts = await dl.list_signals(limit=20)
                if not signal_dicts:
                    yield _sse("error", "No signals found. Run SCOUT first.")
                    return

                voice = await dl.get_voice_settings()
                memory = await dl.get_memory_context()
                api_key = await dl.resolve_api_key()
                assets = await dl.list_assets()

                yield _sse("log", f"GENERATE — writing brief from {len(signal_dicts)} signals...")

                # Generate brief (non-streaming — it's fast)
                brief_data = await generate_brief(signal_dicts, memory=memory, voice_settings=voice, api_key=api_key)
                brief = await dl.save_brief({
                    "date": str(datetime.date.today()),
                    "summary": brief_data["summary"],
                    "angle": brief_data["angle"],
                    "signal_ids": ",".join(str(s.get("id", "")) for s in signal_dicts[:10]),
                })

                yield _sse("log", f"BRIEF — angle: {brief_data.get('angle', 'n/a')}")

                # Determine target channels
                target_channels = [ContentChannel(c) for c in channel_list] if channel_list else [
                    ContentChannel.linkedin,
                    ContentChannel.x_thread,
                    ContentChannel.release_email,
                    ContentChannel.blog,
                ]

                # Filter by brief recommendations
                channel_angles = brief_data.get("channel_angles", {})
                if channel_angles:
                    active = []
                    for ch in target_channels:
                        if ch.value in channel_angles or ch.value not in ("release_email", "newsletter"):
                            active.append(ch)
                    target_channels = active or target_channels

                yield _sse("log", f"GENERATE — writing {len(target_channels)} pieces...")

                client = anthropic.AsyncAnthropic(api_key=api_key or settings.anthropic_api_key)
                author = f"team:{team_member['id']}" if team_member else "company"
                saved_content = []

                for channel in target_channels:
                    channel_config = CHANNEL_RULES.get(channel)
                    if not channel_config:
                        continue

                    yield _sse("log", f"  [{channel_config['headline_prefix']}] generating...")
                    yield _sse("stream_start", "", channel=channel.value)

                    # Build the prompt (reuse engine logic)
                    system_prompt = _build_system_prompt(channel, voice, assets=assets, team_member=team_member)
                    ranked_signals = _rank_signals_for_channel(signal_dicts, channel)
                    signal_context = "\n\n".join(
                        f"[{s.get('type', 'unknown')}] {s.get('source', '')} — {s.get('title', '')}\n{s.get('body', '')[:400]}"
                        for s in ranked_signals
                    )
                    memory_block = _build_memory_block(memory, channel)
                    memory_section = f"\n\nContent memory:\n{memory_block}" if memory_block else ""
                    intel_block = _build_intelligence_block(memory)
                    intel_section = f"\n\nCompany intelligence:\n{intel_block}" if intel_block else ""
                    brief_text = brief_data.get("summary", "")
                    channel_angle = brief_data.get("channel_angles", {}).get(channel.value, "")
                    angle_line = f"\n\nEDITORIAL DIRECTION: {channel_angle}" if channel_angle else ""

                    user_content = f"Today's editorial brief:\n{brief_text}\n\nSignals:\n{signal_context}{angle_line}{memory_section}{intel_section}\n\nWrite the {channel_config['headline_prefix']} now."

                    # Stream the Claude response
                    full_body = ""
                    async with client.messages.stream(
                        model=settings.claude_model,
                        max_tokens=2000,
                        system=system_prompt,
                        messages=[{"role": "user", "content": user_content}],
                    ) as stream:
                        async for text in stream.text_stream:
                            full_body += text
                            yield _sse("token", text, channel=channel.value)
                        final_msg = await stream.get_final_message()
                        await log_token_usage(org_id, "stream_generate", final_msg)

                    yield _sse("stream_end", "", channel=channel.value)

                    # Extract headline and save
                    headline = _extract_headline(full_body, channel_config["headline_prefix"])
                    raw_body = full_body
                    clean_body = humanize(raw_body)
                    source_ids = ",".join(str(s.get("id", "")) for s in ranked_signals if s.get("id"))

                    result = await dl.save_content({
                        "brief_id": brief.get("id"),
                        "signal_id": signal_dicts[0].get("id") if signal_dicts else None,
                        "channel": channel,
                        "status": "queued",
                        "headline": f"{channel_config['headline_prefix']}  {headline[:200]}",
                        "body": clean_body,
                        "body_raw": raw_body,
                        "author": author,
                        "source_signal_ids": source_ids,
                    })
                    saved_content.append(result)

                    # Increment signal usage
                    for sid in source_ids.split(","):
                        sid = sid.strip()
                        if sid and sid.isdigit():
                            await dl.increment_signal_usage(int(sid))

                    yield _sse("log", f"  [{channel_config['headline_prefix']}] complete — {headline[:60]}")

                await dl.commit()

                yield _sse("log", f"GENERATE COMPLETE — {len(saved_content)} pieces written")
                items = [{"id": c.get("id"), "channel": c.get("channel", ""), "headline": c.get("headline", "")} for c in saved_content]
                yield _sse("done", "", items=items, brief_angle=brief_data.get("angle", ""))

        except Exception as e:
            log.exception("Stream generate error")
            yield _sse("error", str(e))

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/run")
async def stream_full_run(
    channels: str = "",
    team_member_id: int | None = None,
    since_hours: int = 24,
    x_org_id: int | None = None,
):
    """Stream the full pipeline: scout + brief + generate with live Claude tokens."""
    import anthropic
    from services.scout import run_full_scout, filter_signals_for_relevance
    from services.engine import (
        generate_brief, _build_voice_block,
        _build_system_prompt, _rank_signals_for_channel, _build_memory_block,
        _build_intelligence_block, _extract_headline, CHANNEL_RULES,
    )
    from api.pipeline import _build_company_context

    async def event_generator():
        try:
            async with async_session() as session:
                dl = DataLayer(session, org_id=x_org_id)

                channel_list = [c.strip() for c in channels.split(",") if c.strip()] if channels else []
                team_member = None
                if team_member_id:
                    members = await dl.list_team_members()
                    team_member = next((m for m in members if m["id"] == team_member_id), None)

                api_key = await dl.resolve_api_key()
                org_settings = await dl.get_all_settings()
                voice = await dl.get_voice_settings()
                company_ctx = _build_company_context(voice)

                yield _sse("log", "SCOUT — scanning GitHub, HN, Reddit, RSS...")

                raw_signals = await run_full_scout(
                    since_hours, org_settings=org_settings,
                    api_key=api_key, company_context=company_ctx,
                )

                yield _sse("log", f"SCOUT — {len(raw_signals)} raw signals, filtering for relevance...")

                filtered_signals = await filter_signals_for_relevance(raw_signals, company_ctx, api_key=api_key)
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
                    yield _sse("log", "WIRE QUIET — no new signals found.")
                    yield _sse("done", "", status="no_signals")
                    return

                yield _sse("log", f"SCOUT COMPLETE — {len(saved_signals)} signals saved")

                signal_dicts = saved_signals
                voice = await dl.get_voice_settings()
                memory = await dl.get_memory_context()
                assets = await dl.list_assets()

                yield _sse("log", f"GENERATE — writing brief from {len(signal_dicts)} signals...")

                brief_data = await generate_brief(signal_dicts, memory=memory, voice_settings=voice, api_key=api_key)
                brief = await dl.save_brief({
                    "date": str(datetime.date.today()),
                    "summary": brief_data["summary"],
                    "angle": brief_data["angle"],
                    "signal_ids": ",".join(str(s.get("id", "")) for s in signal_dicts[:10]),
                })

                yield _sse("log", f"BRIEF — angle: {brief_data.get('angle', 'n/a')}")

                target_channels = [ContentChannel(c) for c in channel_list] if channel_list else [
                    ContentChannel.linkedin,
                    ContentChannel.x_thread,
                    ContentChannel.release_email,
                    ContentChannel.blog,
                ]

                channel_angles = brief_data.get("channel_angles", {})
                if channel_angles:
                    active = []
                    for ch in target_channels:
                        if ch.value in channel_angles or ch.value not in ("release_email", "newsletter"):
                            active.append(ch)
                    target_channels = active or target_channels

                yield _sse("log", f"GENERATE — writing {len(target_channels)} pieces...")

                client = anthropic.AsyncAnthropic(api_key=api_key or settings.anthropic_api_key)
                author = f"team:{team_member['id']}" if team_member else "company"
                saved_content = []

                for channel in target_channels:
                    channel_config = CHANNEL_RULES.get(channel)
                    if not channel_config:
                        continue

                    yield _sse("log", f"  [{channel_config['headline_prefix']}] generating...")
                    yield _sse("stream_start", "", channel=channel.value)

                    system_prompt = _build_system_prompt(channel, voice, assets=assets, team_member=team_member)
                    ranked_signals = _rank_signals_for_channel(signal_dicts, channel)
                    signal_context = "\n\n".join(
                        f"[{s.get('type', 'unknown')}] {s.get('source', '')} — {s.get('title', '')}\n{s.get('body', '')[:400]}"
                        for s in ranked_signals
                    )
                    memory_block = _build_memory_block(memory, channel)
                    memory_section = f"\n\nContent memory:\n{memory_block}" if memory_block else ""
                    intel_block = _build_intelligence_block(memory)
                    intel_section = f"\n\nCompany intelligence:\n{intel_block}" if intel_block else ""
                    brief_text = brief_data.get("summary", "")
                    channel_angle = brief_data.get("channel_angles", {}).get(channel.value, "")
                    angle_line = f"\n\nEDITORIAL DIRECTION: {channel_angle}" if channel_angle else ""

                    user_content = f"Today's editorial brief:\n{brief_text}\n\nSignals:\n{signal_context}{angle_line}{memory_section}{intel_section}\n\nWrite the {channel_config['headline_prefix']} now."

                    full_body = ""
                    async with client.messages.stream(
                        model=settings.claude_model,
                        max_tokens=2000,
                        system=system_prompt,
                        messages=[{"role": "user", "content": user_content}],
                    ) as stream:
                        async for text in stream.text_stream:
                            full_body += text
                            yield _sse("token", text, channel=channel.value)
                        final_msg = await stream.get_final_message()
                        await log_token_usage(x_org_id, "stream_run", final_msg)

                    yield _sse("stream_end", "", channel=channel.value)

                    headline = _extract_headline(full_body, channel_config["headline_prefix"])
                    raw_body = full_body
                    clean_body = humanize(raw_body)
                    source_ids = ",".join(str(s.get("id", "")) for s in ranked_signals if s.get("id"))

                    result = await dl.save_content({
                        "brief_id": brief.get("id"),
                        "signal_id": signal_dicts[0].get("id") if signal_dicts else None,
                        "channel": channel,
                        "status": "queued",
                        "headline": f"{channel_config['headline_prefix']}  {headline[:200]}",
                        "body": clean_body,
                        "body_raw": raw_body,
                        "author": author,
                        "source_signal_ids": source_ids,
                    })
                    saved_content.append(result)

                    for sid in source_ids.split(","):
                        sid = sid.strip()
                        if sid and sid.isdigit():
                            await dl.increment_signal_usage(int(sid))

                    yield _sse("log", f"  [{channel_config['headline_prefix']}] complete — {headline[:60]}")

                await dl.commit()

                yield _sse("log", f"FULL RUN COMPLETE — {len(saved_content)} pieces on the desk")
                items = [{"id": c.get("id"), "channel": c.get("channel", ""), "headline": c.get("headline", "")} for c in saved_content]
                yield _sse("done", "", items=items, signals_count=len(saved_signals), brief_angle=brief_data.get("angle", ""))

        except Exception as e:
            log.exception("Stream full run error")
            yield _sse("error", str(e))

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
