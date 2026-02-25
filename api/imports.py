"""Import endpoints — bulk data intake for signals, content, voice samples, and support tickets."""

import csv
import datetime
import io
import json
import logging
import re

from fastapi import APIRouter, Depends, UploadFile, File, Form
from pydantic import BaseModel

from database import get_data_layer
from services.data_layer import DataLayer

log = logging.getLogger("pressroom")

router = APIRouter(prefix="/api/import", tags=["import"])


class PasteImport(BaseModel):
    target: str  # "signals" | "content" | "voice_examples" | "support_tickets"
    format: str = "json"  # "json" | "csv" | "text"
    data: str


@router.post("/paste")
async def import_paste(req: PasteImport, dl: DataLayer = Depends(get_data_layer)):
    """Import data from pasted text — JSON array, CSV, or plain text."""
    try:
        records = _parse_data(req.data, req.format)
    except Exception as e:
        return {"error": f"Parse error: {str(e)}", "imported": 0}

    return await _route_import(req.target, records, dl)


@router.post("/file")
async def import_file(
    target: str = Form(...),
    file: UploadFile = File(...),
    dl: DataLayer = Depends(get_data_layer),
):
    """Import data from uploaded file (JSON or CSV)."""
    content = await file.read()
    text = content.decode("utf-8")
    fmt = "csv" if file.filename and file.filename.endswith(".csv") else "json"

    try:
        records = _parse_data(text, fmt)
    except Exception as e:
        return {"error": f"Parse error: {str(e)}", "imported": 0}

    return await _route_import(target, records, dl)


@router.get("/templates")
async def import_templates():
    """Return example templates for each import target."""
    return {
        "signals": {
            "format": "json",
            "example": json.dumps([{
                "type": "rss",
                "source": "techcrunch.com",
                "title": "New API platform launches",
                "body": "Article body text...",
                "url": "https://example.com/article",
            }], indent=2),
            "fields": ["type", "source", "title", "body", "url"],
            "required": ["type", "source", "title"],
        },
        "content": {
            "format": "json",
            "example": json.dumps([{
                "channel": "linkedin",
                "status": "approved",
                "headline": "We just shipped v2.0",
                "body": "Full post text...",
                "author": "company",
            }], indent=2),
            "fields": ["channel", "status", "headline", "body", "author"],
            "required": ["channel", "body"],
        },
        "voice_examples": {
            "format": "text",
            "example": "Paste examples of your ideal writing style here.\n\nEach block separated by a blank line becomes one example.\n\nThe engine uses these as few-shot references.",
            "fields": ["text"],
            "required": ["text"],
        },
        "support_tickets": {
            "format": "json",
            "note": "Accepts DreamFactory export format ({\"resource\": [...]}) or a plain JSON array.",
            "example": json.dumps({"resource": [{
                "id": "215470697477687",
                "title": "Nginx upgrade question",
                "state": "closed",
                "open": False,
                "priority": "priority",
                "source_type": "email",
                "source_subject": "Nginx upgrade question",
                "source_body": "Hi, we need help upgrading Nginx...",
                "source_author": {"id": "123", "name": "Jane Doe", "type": "user", "email": "jane@example.com"},
                "contacts": [{"id": "456", "name": "Jane Doe", "email": "jane@example.com"}],
                "tags": [{"name": "nginx"}, {"name": "upgrade"}],
                "created_at": 1761764823,
                "updated_at": 1761764900,
            }]}, indent=2),
            "fields": ["id", "title", "state", "open", "priority", "source_type",
                        "source_subject", "source_body", "source_author", "contacts",
                        "tags", "created_at", "updated_at"],
            "required": ["title", "source_body"],
        },
    }


def _parse_data(data: str, fmt: str) -> list[dict]:
    """Parse input data into a list of dicts.

    Supports DreamFactory envelope: {"resource": [...]} is unwrapped automatically.
    """
    if fmt == "json":
        parsed = json.loads(data)
        # Unwrap DF envelope
        if isinstance(parsed, dict) and "resource" in parsed and isinstance(parsed["resource"], list):
            parsed = parsed["resource"]
        elif isinstance(parsed, dict):
            parsed = [parsed]
        return parsed

    if fmt == "csv":
        reader = csv.DictReader(io.StringIO(data))
        return list(reader)

    if fmt == "text":
        # Split on double newlines, each block is one record
        blocks = [b.strip() for b in data.split("\n\n") if b.strip()]
        return [{"text": b} for b in blocks]

    raise ValueError(f"Unknown format: {fmt}")


async def _route_import(target: str, records: list[dict], dl: DataLayer) -> dict:
    """Route parsed records to the right storage."""
    imported = 0

    if target == "signals":
        for r in records:
            if not r.get("type") or not r.get("source") or not r.get("title"):
                continue
            await dl.save_signal(r)
            imported += 1
        await dl.commit()
        return {"imported": imported, "target": "signals"}

    if target == "content":
        for r in records:
            if not r.get("channel") or not r.get("body"):
                continue
            r.setdefault("status", "approved")
            r.setdefault("headline", r["body"][:100])
            r.setdefault("author", "imported")
            await dl.save_content(r)
            imported += 1
        await dl.commit()
        return {"imported": imported, "target": "content"}

    if target == "voice_examples":
        # Store as a single setting value
        from sqlalchemy import select
        from models import Setting
        examples = [r.get("text", "") for r in records if r.get("text")]
        combined = "\n---\n".join(examples)
        result = await dl.db.execute(select(Setting).where(Setting.key == "voice_writing_examples"))
        existing = result.scalar_one_or_none()
        if existing:
            # Append to existing
            if existing.value:
                existing.value = existing.value + "\n---\n" + combined
            else:
                existing.value = combined
        else:
            dl.db.add(Setting(key="voice_writing_examples", value=combined))
        await dl.commit()
        return {"imported": len(examples), "target": "voice_examples"}

    if target == "support_tickets":
        skipped = 0
        for r in records:
            # Derive a usable title — prefer title, fall back to source_subject
            title = r.get("title") or r.get("source_subject") or ""
            # Strip HTML tags from subject if present
            title = re.sub(r"<[^>]+>", "", title).strip()
            body = r.get("source_body") or ""
            if not title and not body:
                skipped += 1
                continue
            if not title:
                title = body[:120]

            # Build tag string from Intercom tags array
            tags = r.get("tags") or []
            tag_names = ", ".join(t.get("name", "") for t in tags if isinstance(t, dict) and t.get("name"))

            # Extract contact info
            contacts = r.get("contacts") or []
            contact_summary = ""
            if isinstance(contacts, list):
                for c in contacts[:3]:
                    if isinstance(c, dict):
                        parts = [c.get("name", ""), c.get("email", "")]
                        contact_summary += " | ".join(p for p in parts if p) + "; "

            # Build source label
            source = r.get("source_type", "support")
            if tag_names:
                source = f"{source} [{tag_names}]"

            # Use original ticket timestamp, not import time
            ticket_ts = r.get("created_at")
            created_at = None
            if isinstance(ticket_ts, (int, float)) and ticket_ts > 0:
                created_at = datetime.datetime.utcfromtimestamp(ticket_ts)

            sig_data = {
                "type": "support",
                "source": source,
                "title": title,
                "body": body,
                "url": r.get("source_url", ""),
                "raw_data": json.dumps(r, default=str),
            }
            if created_at:
                sig_data["created_at"] = created_at

            await dl.save_signal(sig_data)
            imported += 1
        await dl.commit()
        return {"imported": imported, "skipped": skipped, "target": "support_tickets"}

    return {"error": f"Unknown target: {target}", "imported": 0}
