"""Signal/Wire endpoints — view incoming signals."""

import logging
from fastapi import APIRouter, Depends

from api.auth import get_authenticated_data_layer
from services.data_layer import DataLayer

log = logging.getLogger("pressroom")

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("")
async def list_signals(limit: int = 50, dl: DataLayer = Depends(get_authenticated_data_layer)):
    return await dl.list_signals(limit=limit)


@router.get("/stats/performance")
async def signal_stats(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Signal performance — usage and spike counts for the feedback loop."""
    return await dl.get_signal_stats()


@router.get("/{signal_id}")
async def get_signal(signal_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    signal = await dl.get_signal(signal_id)
    if not signal:
        return {"error": "Signal not found"}, 404
    return signal


@router.patch("/{signal_id}/prioritize")
async def prioritize_signal(signal_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Toggle signal priority — prioritized signals get weighted higher in content gen."""
    signal = await dl.get_signal(signal_id)
    if not signal:
        return {"error": "Signal not found"}
    new_priority = not bool(signal.get("prioritized", 0))
    result = await dl.prioritize_signal(signal_id, new_priority)
    await dl.commit()
    return result


@router.post("/{signal_id}/dig-deeper")
async def dig_deeper(signal_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Fetch a signal's source URL, extract content, summarize with Claude.

    Appends a DEEP DIVE section to the signal body with key facts, quotes, data.
    """
    signal = await dl.get_signal(signal_id)
    if not signal:
        return {"error": "Signal not found"}

    url = signal.get("url", "")
    if not url:
        return {"error": "Signal has no URL to dig into"}

    try:
        from services.engine import dig_deeper_signal
        api_key = await dl.resolve_api_key()
        updated = await dig_deeper_signal(signal, dl, api_key=api_key)
        return updated
    except Exception as e:
        log.error("Dig deeper failed (signal=%s): %s", signal_id, e)
        return {"error": str(e)}


@router.delete("/{signal_id}")
async def delete_signal(signal_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    deleted = await dl.delete_signal(signal_id)
    await dl.commit()
    if not deleted:
        return {"error": "Signal not found"}
    return {"deleted": signal_id}

