"""Humanizer — Strip AI slop and rewrite with brand voice.

Two modes:
1. Claude humanizer (preferred) — humanize_with_claude()
2. Regex humanizer (fast fallback) — humanize()
"""

import logging
import re

import anthropic

log = logging.getLogger("pressroom")

# Anti-patterns from Wikipedia "Signs of AI writing" + our own list
SLOP_PATTERNS = [
    (r"\bexcited to (?:share|announce)\b", ""),
    (r"\bgame[- ]?changer\b", "significant"),
    (r"\bleverage\b", "use"),
    (r"\bsynergy\b", "overlap"),
    (r"\bthrilled\b", "glad"),
    (r"\bcomprehensive\b", "full"),
    (r"\brobust\b", "solid"),
    (r"\bseamless(?:ly)?\b", "smooth"),
    (r"\btransformative\b", "meaningful"),
    (r"\binnovative\b", "new"),
    (r"\bcutting[- ]?edge\b", "modern"),
    (r"\bstate[- ]?of[- ]?the[- ]?art\b", "current"),
    (r"\bunlock(?:ing)?\b", "enable"),
    (r"\bempower(?:ing|s)?\b", "help"),
    (r"\bdelve\b", "dig"),
    (r"\btapestry\b", "mix"),
    (r"\blandscape\b", "space"),
    (r"\bparadigm\b", "model"),
    (r"\bholistic\b", "complete"),
    (r"\bin today'?s (?:fast[- ]?paced|rapidly evolving|digital)\b", ""),
    (r"\bIt'?s worth noting that\b", ""),
    (r"\bIt'?s important to (?:note|remember) that\b", ""),
    (r"\bIn conclusion\b", ""),
]

# Structural patterns
STRUCTURAL_SLOP = [
    # Triple exclamation / emoji spam
    (r"!{3,}", "!"),
    # Excessive em-dashes used as filler
    (r" — (?:and|but|so|yet) — ", " — "),
    # "Let's dive in" and variants
    (r"\bLet'?s (?:dive|jump|get) (?:in|into|started)[.!]?\s*", ""),
    # "Without further ado"
    (r"\b[Ww]ithout further ado[,.]?\s*", ""),
]


def humanize(text: str) -> str:
    """Regex humanizer — fast, no API call required."""
    log.info("[humanizer] Running regex humanizer on %d chars...", len(text))
    result = text

    replacements_made = 0
    for pattern, replacement in SLOP_PATTERNS:
        new_result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        if new_result != result:
            replacements_made += 1
        result = new_result

    for pattern, replacement in STRUCTURAL_SLOP:
        new_result = re.sub(pattern, replacement, result)
        if new_result != result:
            replacements_made += 1
        result = new_result

    # Clean up double spaces from removals
    result = re.sub(r"  +", " ", result)
    # Clean up lines that are now just whitespace
    result = re.sub(r"\n\s*\n\s*\n", "\n\n", result)
    # Clean up leading spaces on lines
    result = "\n".join(line.rstrip() for line in result.split("\n"))

    diff = len(text) - len(result.strip())
    log.info("[humanizer] Regex pass complete — %d patterns matched, %d chars removed", replacements_made, diff)
    return result.strip()


async def humanize_with_claude(text: str, voice_settings: dict | None = None,
                                api_key: str | None = None) -> str:
    """Claude-powered humanizer — rewrites to sound human, matches brand voice.

    Falls back to regex humanizer if API call fails.
    """
    if not api_key:
        log.info("[humanizer] No API key — using regex fallback")
        return humanize(text)
    log.info("[humanizer] Running Claude humanizer on %d chars...", len(text))

    try:
        v = voice_settings or {}
        persona = v.get("voice_persona", "")
        tone = v.get("voice_tone", "conversational")
        audience = v.get("voice_audience", "professionals")
        never_say = v.get("voice_never_say", "")
        linkedin_style = v.get("voice_linkedin_style", "")

        voice_block = ""
        if persona:
            voice_block += f"\nVoice persona: {persona}"
        if tone:
            voice_block += f"\nTone: {tone}"
        if audience:
            voice_block += f"\nAudience: {audience}"
        if never_say:
            voice_block += f"\nNever use these words/phrases: {never_say}"
        if linkedin_style:
            voice_block += f"\nWriting style reference: {linkedin_style}"

        system = f"""You are a writing editor. Your job is to make AI-generated content sound like it was written by a real person.

Rules:
- Keep the same meaning, facts, and structure
- Remove all AI slop: "excited to share", "game-changer", "leverage", "seamless", "robust", "comprehensive", "tapestry", "landscape", "delve", "paradigm", "transformative", etc.
- Remove filler openers: "In today's fast-paced world", "It's worth noting that", "Let's dive in"
- Vary sentence length — mix short punchy sentences with longer ones
- Use contractions naturally (it's, don't, we're)
- Replace passive voice with active where natural
- Keep any URLs, hashtags, @mentions, and formatting (line breaks, bullets) exactly as-is
- Do NOT add new ideas, sections, or calls-to-action
- Do NOT add a disclaimer or explain what you changed
- Output ONLY the rewritten content, nothing else{voice_block}"""

        log.info("[humanizer] Calling Claude (haiku) to humanize...")
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": text}],
        )

        result = response.content[0].text.strip()
        input_tokens = getattr(response.usage, "input_tokens", 0)
        output_tokens = getattr(response.usage, "output_tokens", 0)
        log.info("[humanizer] Claude humanizer complete — %d -> %d chars, tokens: %d in / %d out",
                 len(text), len(result), input_tokens, output_tokens)

        # Log token usage if we can get org context — best effort
        try:
            from services.token_tracker import log_token_usage
            await log_token_usage(None, "humanize", response)
        except Exception:
            pass

        return result if result else humanize(text)

    except Exception as e:
        log.warning("Claude humanizer failed, using regex fallback: %s", e)
        return humanize(text)


async def humanize_with_skill(text: str, voice_settings: dict | None = None,
                               api_key: str | None = None) -> str:
    """Alias for humanize_with_claude — kept for backwards compat."""
    return await humanize_with_claude(text, voice_settings=voice_settings, api_key=api_key)
