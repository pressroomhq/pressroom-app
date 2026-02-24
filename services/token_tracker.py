"""Token usage tracker — logs Claude API cost per org per operation."""

import logging
from database import async_session
from models import TokenUsage

log = logging.getLogger("pressroom")

# Cost rates per 1K tokens (Sonnet defaults — update if model changes)
COST_RATES = {
    # Sonnet
    "claude-sonnet-4-5-20250929": {"in": 0.003, "out": 0.015},
    "claude-3-5-sonnet-20241022": {"in": 0.003, "out": 0.015},
    # Haiku
    "claude-haiku-4-5-20251001": {"in": 0.0008, "out": 0.004},
    "claude-3-5-haiku-20241022": {"in": 0.0008, "out": 0.004},
    # Opus
    "claude-opus-4-6": {"in": 0.015, "out": 0.075},
}

# Default fallback rate (Sonnet pricing)
DEFAULT_RATE = {"in": 0.003, "out": 0.015}


def _calc_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    rates = COST_RATES.get(model, DEFAULT_RATE)
    return (tokens_in / 1000) * rates["in"] + (tokens_out / 1000) * rates["out"]


async def log_token_usage(org_id: int | None, operation: str, response) -> None:
    """Log token usage from an Anthropic API response.

    Works with both messages.create() responses and stream final messages.
    Call this after every Claude API call.
    """
    try:
        usage = getattr(response, "usage", None)
        if not usage:
            return
        tokens_in = getattr(usage, "input_tokens", 0) or 0
        tokens_out = getattr(usage, "output_tokens", 0) or 0
        model = getattr(response, "model", "") or ""
        cost = _calc_cost(model, tokens_in, tokens_out)

        async with async_session() as session:
            record = TokenUsage(
                org_id=org_id,
                operation=operation,
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
            )
            session.add(record)
            await session.commit()
    except Exception as e:
        log.warning(f"token_tracker: failed to log usage for {operation}: {e}")
