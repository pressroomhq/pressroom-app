"""Skill invocation — load a .md skill file as a Claude system prompt and run it."""

from pathlib import Path
from anthropic import AsyncAnthropic
from config import settings
from services.token_tracker import log_token_usage

_client = None


def _get_client(api_key: str | None = None) -> AsyncAnthropic:
    global _client
    key = api_key or settings.anthropic_api_key
    if _client and not api_key:
        return _client
    c = AsyncAnthropic(api_key=key)
    if not api_key:
        _client = c
    return c


async def invoke(skill_name: str, content: str, context: dict | None = None,
                 api_key: str | None = None) -> str:
    """Load a skill by name and run it against content.

    Args:
        skill_name: Name of the skill file (without .md extension)
        content: The content to process
        context: Optional context dict (key/value pairs added to user message)
        api_key: Optional API key override

    Returns:
        Claude's response text
    """
    skill_path = Path(__file__).parent / f"{skill_name}.md"
    if not skill_path.exists():
        raise ValueError(f"Skill not found: {skill_name}")

    system_prompt = skill_path.read_text()

    # Build user message from content + context
    user_msg = content
    if context:
        ctx_lines = "\n".join(f"{k}: {v}" for k, v in context.items())
        user_msg = f"Context:\n{ctx_lines}\n\n---\n\n{user_msg}"

    client = _get_client(api_key)
    response = await client.messages.create(
        model=settings.claude_model,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )
    await log_token_usage(None, f"skill_{skill_name}", response)
    return response.content[0].text
