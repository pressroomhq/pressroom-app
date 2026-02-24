"""Content Engine — Claude-powered content generation from signals and briefs.

Uses:
- Voice settings from the DB (onboarding-configured or manually set)
- Memory context (approved examples, spiked anti-patterns, recent topics)
- DF intelligence (customer data, analytics, CRM data from connected services)
- Structured brief with per-channel signal routing
"""

import json
import logging
import re
import httpx
import anthropic
from config import settings
from models import ContentChannel
from services.token_tracker import log_token_usage

log = logging.getLogger("pressroom")


def _get_client(api_key: str | None = None):
    """Lazy client — uses explicit key if provided, else runtime config."""
    return anthropic.Anthropic(api_key=api_key or settings.anthropic_api_key)

# Fallback voice if no settings configured
DEFAULT_VOICE = {
    "voice_persona": "A company sharing updates and insights with their audience.",
    "voice_audience": "Industry professionals and customers",
    "voice_tone": "Professional, clear, informative",
    "voice_never_say": '["excited to share", "game-changer", "leverage", "synergy"]',
    "voice_always": "Be specific, share real data, focus on value",
}

CHANNEL_RULES = {
    ContentChannel.linkedin: {
        "rules": """- 150-300 words max
- Hook in first line (pattern interrupt, bold claim, or question)
- No hashtags unless they're genuinely useful (max 3)
- End with a thought or question, not a CTA
- Write like a human sharing insight, not a marketer
- No bullet-point listicles unless the content genuinely demands it
- Don't start with "I" — start with the insight""",
        "headline_prefix": "LINKEDIN",
        "style_key": "voice_linkedin_style",
        "signal_affinity": ["hackernews", "reddit", "rss", "github_release"],
    },
    ContentChannel.x_thread: {
        "rules": """- 5-8 tweets
- Tweet 1 is the hook — must stand alone and stop the scroll
- Each tweet under 280 characters
- Number them 1/, 2/, etc.
- Last tweet: takeaway or link
- Conversational, not performative
- No "thread" opener — just start with the insight
- Use concrete numbers and specifics, not vague claims""",
        "headline_prefix": "X THREAD",
        "style_key": "voice_x_style",
        "signal_affinity": ["hackernews", "github_release", "github_commit", "reddit"],
    },
    ContentChannel.blog: {
        "rules": """- 800-1500 words
- SEO-aware title (include primary keyword naturally)
- H2 subheadings every 200-300 words
- Technical depth — code snippets where relevant
- No fluff intro paragraphs. Start with the point.
- End with what's next, not a generic conclusion
- Include specific examples, benchmarks, or comparisons where possible
- Internal linking suggestions in [LINK: topic] markers""",
        "headline_prefix": "BLOG DRAFT",
        "style_key": "voice_blog_style",
        "signal_affinity": ["github_release", "github_commit", "rss", "hackernews"],
    },
    ContentChannel.release_email: {
        "rules": """- Subject line that gets opened (not clickbait, just clear value)
- 200-400 words
- What shipped, why it matters, how to use it
- One clear CTA
- Plain text feel, not HTML newsletter energy
- Lead with the benefit, not the feature""",
        "headline_prefix": "RELEASE EMAIL",
        "style_key": "voice_email_style",
        "signal_affinity": ["github_release", "github_commit"],
    },
    ContentChannel.newsletter: {
        "rules": """- 300-500 words
- "This week in [company]" format
- What shipped, what's coming, one community highlight
- Links to docs/blog where relevant
- Casual, informative, not salesy""",
        "headline_prefix": "NEWSLETTER",
        "style_key": "voice_newsletter_style",
        "signal_affinity": ["github_release", "hackernews", "reddit", "rss"],
    },
    ContentChannel.yt_script: {
        "rules": """- 2-4 minutes when read aloud (~300-600 words)
- Open with the hook (what you'll learn / why this matters)
- Conversational — written for speaking, not reading
- Include [B-ROLL: description] markers for visual cuts
- End with a clear next step""",
        "headline_prefix": "YT SCRIPT",
        "style_key": "voice_yt_style",
        "signal_affinity": ["github_release", "hackernews", "rss"],
    },
}


def _build_voice_block(voice_settings: dict | None) -> str:
    """Build the voice profile section from DB settings."""
    v = voice_settings or DEFAULT_VOICE

    parts = []
    company = v.get("onboard_company_name", "")
    if company:
        parts.append(f"Company: {company}")
    industry = v.get("onboard_industry", "")
    if industry:
        parts.append(f"Industry: {industry}")
    parts.append(f"Voice: {v.get('voice_persona', DEFAULT_VOICE['voice_persona'])}")
    parts.append(f"Audience: {v.get('voice_audience', DEFAULT_VOICE['voice_audience'])}")
    parts.append(f"Tone: {v.get('voice_tone', DEFAULT_VOICE['voice_tone'])}")

    # Never say
    never_raw = v.get("voice_never_say", DEFAULT_VOICE["voice_never_say"])
    try:
        never_list = json.loads(never_raw) if isinstance(never_raw, str) else never_raw
        if never_list:
            quoted = ', '.join('"' + w + '"' for w in never_list)
            parts.append(f"Never say: {quoted}")
    except (json.JSONDecodeError, TypeError):
        pass

    parts.append(f"Always: {v.get('voice_always', DEFAULT_VOICE['voice_always'])}")

    # Brand keywords
    brand_raw = v.get("voice_brand_keywords", "")
    try:
        brand_list = json.loads(brand_raw) if isinstance(brand_raw, str) and brand_raw else []
        if brand_list:
            parts.append(f"Brand keywords (use naturally): {', '.join(brand_list)}")
    except (json.JSONDecodeError, TypeError):
        pass

    # Topics
    topics_raw = v.get("onboard_topics", "")
    try:
        topics = json.loads(topics_raw) if isinstance(topics_raw, str) and topics_raw else []
        if topics:
            parts.append(f"Key topics: {', '.join(topics)}")
    except (json.JSONDecodeError, TypeError):
        pass

    # Competitors
    comp_raw = v.get("onboard_competitors", "")
    try:
        comps = json.loads(comp_raw) if isinstance(comp_raw, str) and comp_raw else []
        if comps:
            parts.append(f"Competitors (differentiate from): {', '.join(comps)}")
    except (json.JSONDecodeError, TypeError):
        pass

    return "\n".join(parts)


def _build_system_prompt(channel: ContentChannel, voice_settings: dict | None,
                         assets: list[dict] | None = None,
                         team_member: dict | None = None) -> str:
    """Build the system prompt — positions as the company's writer, not a generic engine."""
    channel_config = CHANNEL_RULES.get(channel)
    if not channel_config:
        return "You are a content writer. Generate content."

    v = voice_settings or DEFAULT_VOICE
    company = v.get("onboard_company_name", "the company")
    persona = v.get("voice_persona", "")
    audience = v.get("voice_audience", DEFAULT_VOICE["voice_audience"])
    tone = v.get("voice_tone", DEFAULT_VOICE["voice_tone"])

    voice_block = _build_voice_block(voice_settings)

    # Get channel-specific style override
    style_key = channel_config.get("style_key", "")
    channel_style = v.get(style_key, "")
    style_line = f"\nChannel-specific style notes: {channel_style}" if channel_style else ""

    # Writing examples
    examples = v.get("voice_writing_examples", "")
    examples_block = ""
    if examples and len(examples) > 20:
        examples_block = f"\n\nWRITING EXAMPLES (match this voice and style closely):\n{examples[:2000]}"

    # Competitive positioning
    comp_raw = v.get("onboard_competitors", "")
    comp_block = ""
    try:
        comps = json.loads(comp_raw) if isinstance(comp_raw, str) and comp_raw else []
        if comps:
            comp_block = f"""

COMPETITIVE POSITIONING:
You are writing for {company}, NOT for {', '.join(comps)}.
When these competitors come up in signals, frame them as context — what {company} does differently, why the audience should care about {company}'s approach.
Never trash competitors. Position through strength, not comparison."""
    except (json.JSONDecodeError, TypeError):
        pass

    # Golden anchor statement
    golden_anchor = v.get("golden_anchor", "")
    anchor_block = ""
    if golden_anchor and golden_anchor.strip():
        anchor_block = f"""\

GOLDEN ANCHOR: The following statement is this company's north star message. Weave it into the content naturally when relevant: '{golden_anchor}'"""

    asset_block = ""
    if assets:
        asset_block = "\n\n" + _build_asset_map_block(assets)

    # Team member persona injection
    if team_member:
        member_name = team_member.get("name", "")
        member_title = team_member.get("title", "")
        member_bio = team_member.get("bio", "")
        member_expertise = team_member.get("expertise_tags", [])
        if isinstance(member_expertise, str):
            try:
                member_expertise = json.loads(member_expertise)
            except (json.JSONDecodeError, TypeError):
                member_expertise = []
        expertise_str = ", ".join(member_expertise) if member_expertise else ""

        author_line = f"You are writing as {member_name}, {member_title} at {company}."
        author_block = f"""

AUTHOR VOICE:
You are posting as {member_name} ({member_title}), a real person at {company}. Write in first person.
{f'Their bio: {member_bio}' if member_bio else ''}
{f'Their expertise: {expertise_str}' if expertise_str else ''}
The post should sound like a knowledgeable professional sharing their perspective — not a company press release.
Use "I" and "we" naturally. Draw on {member_name}'s expertise to add credibility."""
    else:
        author_line = f"You are writing as {company}'s content team."
        author_block = ""

    return f"""{author_line} {persona}

Your audience: {audience}
Your tone: {tone}

You're writing a {channel_config['headline_prefix']} post based on today's intelligence signals.{style_line}

{voice_block}{author_block}{comp_block}{anchor_block}{asset_block}

CONTENT RULES FOR {channel_config['headline_prefix']}:
{channel_config['rules']}

CRITICAL:
- Write as {company}. Not as an AI. Not as "a content engine." As {company}'s voice.
- Every piece must have a specific, defensible point of view. No "it depends" hedging.
- If the signal is about your company, own it. If it's industry news, give your take on it.
- Prefer concrete specifics over vague claims. Numbers, examples, real scenarios.{examples_block}"""


def _build_memory_block(memory: dict | None, channel: ContentChannel) -> str:
    """Build a memory context block for the generation prompt."""
    if not memory:
        return ""

    ch = channel.value
    parts = []

    approved = memory.get("approved", {}).get(ch, [])
    if approved:
        parts.append("PREVIOUSLY APPROVED (write MORE like these):")
        for item in approved[:3]:
            headline = item.get("headline", "N/A")
            body_preview = item.get("body", "")[:150]
            parts.append(f"  - {headline}")
            if body_preview:
                parts.append(f"    Preview: {body_preview}...")

    spiked = memory.get("spiked", {}).get(ch, [])
    if spiked:
        parts.append("PREVIOUSLY SPIKED (write LESS like these — the editor rejected these):")
        for item in spiked[:3]:
            parts.append(f"  - {item.get('headline', 'N/A')}")

    recent = memory.get("recent_topics", [])
    if recent:
        recent_headlines = [r.get("headline", "") for r in recent[:15] if r.get("headline")]
        if recent_headlines:
            parts.append("RECENT TOPICS (DO NOT repeat these angles — find a fresh take):")
            for h in recent_headlines:
                parts.append(f"  - {h}")

    return "\n".join(parts) if parts else ""


def _build_intelligence_block(memory: dict | None) -> str:
    """Build intelligence section from DF data + connected DataSources."""
    if not memory:
        return ""

    parts = []

    # DF intelligence (from service map queries)
    intelligence = memory.get("df_intelligence", {})
    if intelligence:
        parts.append("COMPANY INTELLIGENCE (from connected data sources):")
        for svc_name, svc_data in intelligence.items():
            role = svc_data.get("role", "").replace("_", " ")
            desc = svc_data.get("description", "")
            parts.append(f"\n[{role.upper()}] {svc_name}: {desc}")

            for table_data in svc_data.get("data", []):
                table = table_data.get("table", "")
                rows = table_data.get("recent_rows", [])
                if rows:
                    parts.append(f"  Recent from {table}:")
                    for row in rows[:5]:
                        highlights = []
                        for k, v in list(row.items())[:4]:
                            if v and k not in ("id", "created_at", "updated_at"):
                                highlights.append(f"{k}: {v[:100]}")
                        if highlights:
                            parts.append(f"    - {' | '.join(highlights)}")

    # DataSource records (from Connections tab)
    datasources = memory.get("datasources", [])
    if datasources:
        if not parts:
            parts.append("CONNECTED DATA SOURCES:")
        else:
            parts.append("\nADDITIONAL CONNECTED SOURCES:")
        for ds in datasources:
            cat = ds.get("category", "").upper()
            name = ds.get("name", "")
            desc = ds.get("description", "")
            conn_type = ds.get("connection_type", "")
            parts.append(f"  [{cat}] {name} ({conn_type}): {desc}")

    return "\n".join(parts) if parts else ""


def _build_asset_map_block(assets: list[dict]) -> str:
    """Build a COMPANY DIGITAL FOOTPRINT section from asset records."""
    if not assets:
        return ""

    grouped: dict[str, list[dict]] = {}
    for a in assets:
        grouped.setdefault(a.get("asset_type", "other"), []).append(a)

    parts = ["COMPANY DIGITAL FOOTPRINT:"]
    for atype, items in sorted(grouped.items()):
        parts.append(f"\n  [{atype.upper()}]")
        for item in items:
            label = item.get("label", "")
            url = item.get("url", "")
            desc = item.get("description", "")
            line = f"    - {url}"
            if label:
                line += f'  ({label})'
            if desc:
                line += f'  — {desc}'
            parts.append(line)

    return "\n".join(parts)


def _rank_signals_for_channel(signals: list[dict], channel: ContentChannel) -> list[dict]:
    """Rank and select the best signals for a specific channel."""
    channel_config = CHANNEL_RULES.get(channel, {})
    affinity = channel_config.get("signal_affinity", [])

    # Score each signal based on channel affinity
    scored = []
    for s in signals:
        score = 0
        sig_type = s.get("type", "")
        if sig_type in affinity:
            score = len(affinity) - affinity.index(sig_type)  # higher rank = higher score
        else:
            score = -1  # not preferred but still usable

        # Boost signals with more body content (richer source material)
        body_len = len(s.get("body", ""))
        if body_len > 200:
            score += 1
        if body_len > 500:
            score += 1

        # Editor-prioritized signals get a significant boost
        if s.get("prioritized"):
            score += 10

        scored.append((score, s))

    # Sort by score descending, take top signals
    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in scored[:5]]


async def generate_brief(signals: list[dict], memory: dict | None = None,
                          voice_settings: dict | None = None,
                          api_key: str | None = None,
                          org_id: int | None = None) -> dict:
    """Synthesize signals into a structured content plan with per-channel recommendations."""
    signal_text = "\n\n".join(
        f"[{i+1}] [{s.get('type', 'unknown')}] {s.get('source', '')} — {s.get('title', '')}\n{s.get('body', '')[:500]}"
        for i, s in enumerate(signals)
    )

    intel_block = _build_intelligence_block(memory)
    intel_section = f"\n\nCompany data from connected sources:\n{intel_block}" if intel_block else ""

    voice_block = _build_voice_block(voice_settings)
    v = voice_settings or DEFAULT_VOICE
    company = v.get("onboard_company_name", "the company")

    # Include recent topics so the brief avoids them
    recent_block = ""
    if memory:
        recent = memory.get("recent_topics", [])
        if recent:
            recent_headlines = [r.get("headline", "") for r in recent[:10] if r.get("headline")]
            if recent_headlines:
                recent_block = "\n\nRECENT CONTENT (avoid these topics — find fresh angles):\n" + "\n".join(f"  - {h}" for h in recent_headlines)

    response = _get_client(api_key).messages.create(
        model=settings.claude_model_fast,
        max_tokens=1500,
        system=f"""You are the editorial director at {company}. You receive today's intelligence signals and decide what content to produce.

Company context:
{voice_block}

Your job: analyze signals, identify the strongest content angles, and create a content plan.
Think like an editor — what's the story? What angle will resonate with {v.get('voice_audience', 'the audience')}?
Don't just summarize signals. Find the INSIGHT in them.

Output format:
SUMMARY: 2-3 sentence overview of today's signal landscape.
ANGLE: The single strongest content angle (one sentence, specific and opinionated).
TOP SIGNALS: Ranked 3-5 signals by content potential, with one-line angle for each.
LINKEDIN: Specific angle and hook for a LinkedIn post (one sentence).
X_THREAD: Specific angle and hook for an X thread (one sentence).
BLOG: Specific angle and working title for a blog post (one sentence).
RELEASE_EMAIL: If there's a release/shipping signal, the angle. If not, write "SKIP".
NEWSLETTER: Weekly roundup angle if applicable, or "SKIP".""",
        messages=[{"role": "user", "content": f"Today's wire ({len(signals)} signals):\n\n{signal_text}{intel_section}{recent_block}"}],
    )

    await log_token_usage(org_id, "generate_brief", response)
    text = response.content[0].text
    log.info("BRIEF generated (%d chars)", len(text))

    # Extract structured angles
    brief_data = {"summary": text, "angle": "", "channel_angles": {}}

    if "ANGLE:" in text:
        brief_data["angle"] = text.split("ANGLE:")[-1].split("\n")[0].strip()

    # Parse per-channel recommendations
    for ch_key in ["LINKEDIN:", "X_THREAD:", "BLOG:", "RELEASE_EMAIL:", "NEWSLETTER:"]:
        if ch_key in text:
            ch_angle = text.split(ch_key)[-1].split("\n")[0].strip()
            if ch_angle.upper() != "SKIP":
                brief_data["channel_angles"][ch_key.rstrip(":").lower()] = ch_angle

    return brief_data


async def generate_content(brief: dict, signals: list[dict], channel: ContentChannel,
                           memory: dict | None = None,
                           voice_settings: dict | None = None,
                           assets: list[dict] | None = None,
                           api_key: str | None = None,
                           team_member: dict | None = None,
                           org_id: int | None = None) -> dict:
    """Generate content for a specific channel with targeted signals and channel-specific angle."""
    channel_config = CHANNEL_RULES.get(channel)
    if not channel_config:
        raise ValueError(f"No config for channel: {channel}")

    system_prompt = _build_system_prompt(channel, voice_settings, assets=assets, team_member=team_member)

    # Select the best signals for this channel
    ranked_signals = _rank_signals_for_channel(signals, channel)

    signal_context = "\n\n".join(
        f"[{s.get('type', 'unknown')}] {s.get('source', '')} — {s.get('title', '')}\n{s.get('body', '')[:400]}"
        for s in ranked_signals
    )

    memory_block = _build_memory_block(memory, channel)
    memory_section = f"\n\nContent memory (learn from past approvals/rejections):\n{memory_block}" if memory_block else ""

    intel_block = _build_intelligence_block(memory)
    intel_section = f"\n\nCompany intelligence:\n{intel_block}" if intel_block else ""

    # Get channel-specific angle from the brief
    brief_text = brief.get("summary", "")
    channel_angle = brief.get("channel_angles", {}).get(channel.value, "")
    angle_line = f"\n\nEDITORIAL DIRECTION for this piece: {channel_angle}" if channel_angle else ""

    response = _get_client(api_key).messages.create(
        model=settings.claude_model,
        max_tokens=2000,
        system=system_prompt,
        messages=[{
            "role": "user",
            "content": f"Today's editorial brief:\n{brief_text}\n\nSignals selected for this piece:\n{signal_context}{angle_line}{memory_section}{intel_section}\n\nWrite the {channel_config['headline_prefix']} now.",
        }],
    )

    await log_token_usage(org_id, "generate_content", response)
    body = response.content[0].text

    # Better headline extraction
    headline = _extract_headline(body, channel_config["headline_prefix"])

    return {
        "channel": channel,
        "headline": f"{channel_config['headline_prefix']}  {headline[:200]}",
        "body": body,
        "source_signal_ids": ",".join(str(s.get("id", "")) for s in ranked_signals if s.get("id")),
    }


def _extract_headline(body: str, prefix: str) -> str:
    """Extract headline from generated content — handles markdown, quotes, etc."""
    lines = body.strip().split("\n")
    for line in lines[:3]:  # check first 3 lines
        clean = line.strip()
        if not clean:
            continue
        # Strip markdown headers, quotes, bold markers
        clean = clean.lstrip("#").strip().strip('"').strip("'").strip("*").strip("_").strip()
        # Strip the channel prefix if the LLM echoed it (avoids "X THREAD  X THREAD: ...")
        if prefix and clean.upper().startswith(prefix.upper()):
            clean = clean[len(prefix):].lstrip(":").lstrip("-").strip()
        # Also strip "Subject:" prefix from emails
        if clean.lower().startswith("subject:"):
            clean = clean[len("subject:"):].strip()
        # Skip if it's a tweet number (for X threads)
        if clean.startswith("1/") or clean.startswith("1."):
            # For threads, use the first tweet content as headline
            clean = clean.split("/", 1)[-1].strip() if "/" in clean else clean.split(".", 1)[-1].strip()
        if len(clean) > 10:
            return clean

    # Fallback: first non-empty line
    for line in lines:
        if line.strip():
            return line.strip()[:200]
    return "Untitled"


async def generate_all_content(brief: dict, signals: list[dict],
                                channels: list[ContentChannel] | None = None,
                                memory: dict | None = None,
                                voice_settings: dict | None = None,
                                assets: list[dict] | None = None,
                                api_key: str | None = None,
                                team_member: dict | None = None) -> list[dict]:
    """Generate content across all channels (or specified subset).
    Each channel gets its own signal selection and editorial angle."""
    target_channels = channels or [
        ContentChannel.linkedin,
        ContentChannel.x_thread,
        ContentChannel.release_email,
        ContentChannel.blog,
    ]

    # Filter out channels that the brief said to skip
    channel_angles = brief.get("channel_angles", {})
    if channel_angles:
        # Keep channels that have angles OR weren't mentioned (generate anyway)
        active_channels = []
        for ch in target_channels:
            ch_name = ch.value
            if ch_name in channel_angles or ch_name not in ("release_email", "newsletter"):
                active_channels.append(ch)
            else:
                log.info("Skipping %s — brief said SKIP", ch_name)
        target_channels = active_channels or target_channels  # fallback to all if none left

    results = []
    for channel in target_channels:
        result = await generate_content(brief, signals, channel, memory=memory, voice_settings=voice_settings, assets=assets, api_key=api_key, team_member=team_member)
        results.append(result)

    return results


async def regenerate_single(content_body: str, channel: ContentChannel,
                             feedback: str = "",
                             memory: dict | None = None,
                             voice_settings: dict | None = None,
                             api_key: str | None = None,
                             org_id: int | None = None) -> dict:
    """Regenerate a single piece of content with optional editor feedback."""
    channel_config = CHANNEL_RULES.get(channel)
    if not channel_config:
        raise ValueError(f"No config for channel: {channel}")

    system_prompt = _build_system_prompt(channel, voice_settings)

    feedback_line = f"\n\nEDITOR FEEDBACK: {feedback}\nRewrite to address this feedback." if feedback else "\nRewrite this piece with a fresh angle. Same topic, different approach."

    response = _get_client(api_key).messages.create(
        model=settings.claude_model,
        max_tokens=2000,
        system=system_prompt,
        messages=[{
            "role": "user",
            "content": f"Here is a draft that needs revision:\n\n{content_body}{feedback_line}",
        }],
    )

    await log_token_usage(org_id, "regenerate_content", response)
    body = response.content[0].text
    headline = _extract_headline(body, channel_config["headline_prefix"])

    return {
        "channel": channel,
        "headline": f"{channel_config['headline_prefix']}  {headline[:200]}",
        "body": body,
    }


# ─── Story-based generation ─────────────────────────────

async def generate_from_story(story: dict, dl, channels: list[str] | None = None,
                               api_key: str | None = None,
                               team_member: dict | None = None) -> list[dict]:
    """Generate content from a curated story — editorial context + curated signals.

    Reuses the existing generate_content pipeline by packing the story's
    editorial context into a synthetic brief dict.
    """
    from services.humanizer import humanize, humanize_with_skill

    story_signals = story.get("signals", [])
    if not story_signals:
        raise ValueError("Story has no signals — add signals before generating.")

    # Build signal context with editor notes
    signal_dicts = []
    signal_parts = []
    for ss in story_signals:
        sig = ss.get("signal", ss)
        signal_dicts.append(sig)
        part = f"[{sig.get('type', 'unknown')}] {sig.get('source', '')} — {sig.get('title', '')}"
        notes = ss.get("editor_notes", "")
        if notes:
            part += f"\nEDITOR NOTES: {notes}"
        part += f"\n{sig.get('body', '')[:600]}"
        signal_parts.append(part)

    signal_summary = "\n\n".join(signal_parts)
    editorial = f"STORY: {story.get('title', '')}"
    if story.get("angle"):
        editorial += f"\nANGLE: {story['angle']}"
    if story.get("editorial_notes"):
        editorial += f"\nEDITORIAL NOTES: {story['editorial_notes']}"
    editorial += f"\n\nCURATED SIGNALS ({len(story_signals)}):\n{signal_summary}"

    synthetic_brief = {
        "summary": editorial,
        "angle": story.get("angle", ""),
        "channel_angles": {},
    }

    voice = await dl.get_voice_settings()
    memory = await dl.get_memory_context()
    assets = await dl.list_assets()

    target_channels = None
    if channels:
        target_channels = [ContentChannel(c) for c in channels]

    content_items = await generate_all_content(
        synthetic_brief, signal_dicts, target_channels,
        memory=memory, voice_settings=voice, assets=assets,
        api_key=api_key, team_member=team_member,
    )

    author = f"team:{team_member['id']}" if team_member else "company"
    saved = []
    for item in content_items:
        raw_body = item["body"]
        clean_body = await humanize_with_skill(raw_body, voice_settings=voice, api_key=api_key)
        result = await dl.save_content({
            "story_id": story["id"],
            "signal_id": signal_dicts[0].get("id") if signal_dicts else None,
            "channel": item["channel"],
            "status": "queued",
            "headline": item["headline"],
            "body": clean_body,
            "body_raw": raw_body,
            "author": author,
            "source_signal_ids": item.get("source_signal_ids", ""),
        })
        saved.append(result)

    await dl.commit()
    return saved


async def dig_deeper_signal(signal: dict, dl, api_key: str | None = None) -> dict:
    """Fetch a signal's source URL, extract content, summarize key facts with Claude."""
    url = signal.get("url", "")
    if not url:
        raise ValueError("Signal has no URL")

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": "Pressroom/0.1 (content-engine)"})
        resp.raise_for_status()
        html = resp.text

    # Extract text
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()[:8000]

    response = _get_client(api_key).messages.create(
        model=settings.claude_model_fast,
        max_tokens=1500,
        system="You are a research analyst extracting key facts from a web page for editorial use. Be specific — pull exact quotes, numbers, data points, and key claims.",
        messages=[{
            "role": "user",
            "content": f"URL: {url}\nOriginal signal: {signal.get('title', '')}\n\nFull page content:\n{text}\n\nExtract the key facts, quotes, data points, and arguments. Format as a concise deep dive summary with bullet points.",
        }],
    )

    await log_token_usage(dl.org_id if dl else None, "dig_deeper", response)
    deep_dive = response.content[0].text
    existing_body = signal.get("body", "")

    new_body = existing_body
    if "\n\n--- DEEP DIVE ---" in existing_body:
        new_body = existing_body.split("\n\n--- DEEP DIVE ---")[0]
    new_body += f"\n\n--- DEEP DIVE ---\n{deep_dive}"

    updated = await dl.update_signal_body(signal["id"], new_body)
    await dl.commit()
    return updated or signal
