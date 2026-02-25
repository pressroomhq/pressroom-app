"""Data layer — routes to DF when available, falls back to local SQLite.

This is the abstraction that lets Pressroom work standalone (SQLite) or
with DreamFactory as the backend. The API endpoints don't care which.

All queries are scoped by org_id for multi-tenant isolation.
"""

import datetime
import json
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from models import (Signal, Brief, Content, Setting, Organization, DataSource, TeamMember,
                    CompanyAsset, Story, StorySignal, WireSignal, ApiKey, AuditResult, AuditActionItem, BlogPost, EmailDraft, SeoPrRun, SiteProperty,
                    SignalType, ContentChannel, ContentStatus, StoryStatus)
from services.df_client import df


# DF database service name for pressroom tables
DF_DB_SERVICE = "pressroom_db"


class DataLayer:
    """Unified data access — checks DF first, falls back to SQLite.
    All operations scoped to org_id."""

    def __init__(self, db_session: AsyncSession, org_id: int | None = None):
        self.db = db_session
        self.org_id = org_id
        self._use_df = None  # lazy check

    async def _should_use_df(self) -> bool:
        """Check once per request if DF is available and has our DB service."""
        if self._use_df is not None:
            return self._use_df
        if not df.available:
            self._use_df = False
            return False
        try:
            health = await df.health_check()
            if not health.get("connected", False):
                self._use_df = False
                return False
            # Verify the pressroom_db service actually exists in DF
            schema = await df.get_service_schema(DF_DB_SERVICE)
            self._use_df = bool(schema.get("table"))
        except Exception:
            self._use_df = False
        return self._use_df

    # ──────────────────────────────────────
    # Organizations
    # ──────────────────────────────────────

    async def create_org(self, name: str, domain: str = "") -> dict:
        org = Organization(name=name, domain=domain)
        self.db.add(org)
        await self.db.flush()
        return {"id": org.id, "name": org.name, "domain": org.domain,
                "created_at": org.created_at.isoformat() if org.created_at else None}

    async def list_orgs(self) -> list[dict]:
        result = await self.db.execute(select(Organization).order_by(Organization.created_at.desc()))
        return [{"id": o.id, "name": o.name, "domain": o.domain,
                 "created_at": o.created_at.isoformat() if o.created_at else None}
                for o in result.scalars().all()]

    async def get_org(self, org_id: int) -> dict | None:
        result = await self.db.execute(select(Organization).where(Organization.id == org_id))
        o = result.scalar_one_or_none()
        if not o:
            return None
        return {"id": o.id, "name": o.name, "domain": o.domain,
                "created_at": o.created_at.isoformat() if o.created_at else None}

    async def delete_org(self, org_id: int) -> bool:
        result = await self.db.execute(select(Organization).where(Organization.id == org_id))
        o = result.scalar_one_or_none()
        if not o:
            return False
        await self.db.delete(o)
        return True

    # ──────────────────────────────────────
    # Signals
    # ──────────────────────────────────────

    async def save_signal(self, data: dict) -> dict:
        if await self._should_use_df():
            record = {
                "type": data["type"] if isinstance(data["type"], str) else data["type"].value,
                "source": data["source"],
                "title": data["title"],
                "body": data.get("body", ""),
                "url": data.get("url", ""),
                "raw_data": data.get("raw_data", ""),
                "created_at": datetime.datetime.utcnow().isoformat(),
            }
            if self.org_id:
                record["org_id"] = self.org_id
            records = await df.db_create(DF_DB_SERVICE, "pressroom_signals", [record])
            return records[0] if records else {}

        signal = Signal(
            org_id=self.org_id,
            type=data["type"] if isinstance(data["type"], SignalType) else SignalType(data["type"]),
            source=data["source"],
            title=data["title"],
            body=data.get("body", ""),
            url=data.get("url", ""),
            raw_data=data.get("raw_data", ""),
        )
        if data.get("created_at"):
            signal.created_at = data["created_at"]
        self.db.add(signal)
        await self.db.flush()
        return {"id": signal.id, "type": signal.type.value, "source": signal.source,
                "title": signal.title, "body": signal.body, "prioritized": 0}

    async def get_signal(self, signal_id: int) -> dict | None:
        if await self._should_use_df():
            try:
                return await df.db_get(DF_DB_SERVICE, "pressroom_signals", signal_id)
            except Exception:
                return None

        query = select(Signal).where(Signal.id == signal_id)
        if self.org_id:
            query = query.where(Signal.org_id == self.org_id)
        result = await self.db.execute(query)
        s = result.scalar_one_or_none()
        if not s:
            return None
        return {"id": s.id, "type": s.type.value, "source": s.source, "title": s.title,
                "body": s.body, "url": s.url, "prioritized": s.prioritized or 0,
                "created_at": s.created_at.isoformat() if s.created_at else None}

    async def delete_signal(self, signal_id: int) -> bool:
        query = select(Signal).where(Signal.id == signal_id)
        if self.org_id:
            query = query.where(Signal.org_id == self.org_id)
        result = await self.db.execute(query)
        s = result.scalar_one_or_none()
        if not s:
            return False
        await self.db.delete(s)
        return True

    async def prioritize_signal(self, signal_id: int, prioritized: bool) -> dict | None:
        query = select(Signal).where(Signal.id == signal_id)
        if self.org_id:
            query = query.where(Signal.org_id == self.org_id)
        result = await self.db.execute(query)
        s = result.scalar_one_or_none()
        if not s:
            return None
        s.prioritized = 1 if prioritized else 0
        await self.db.flush()
        return {"id": s.id, "type": s.type.value, "source": s.source, "title": s.title,
                "prioritized": s.prioritized}

    async def list_signals(self, limit: int = 200) -> list[dict]:
        if await self._should_use_df():
            filter_str = f"org_id = {self.org_id}" if self.org_id else None
            return await df.db_query(DF_DB_SERVICE, "pressroom_signals",
                                     filter_str=filter_str, order="created_at DESC", limit=limit)

        query = select(Signal).order_by(Signal.created_at.desc()).limit(limit)
        if self.org_id:
            query = query.where(Signal.org_id == self.org_id)
        result = await self.db.execute(query)
        return [{"id": s.id, "type": s.type.value, "source": s.source, "title": s.title,
                 "body": s.body, "url": s.url, "prioritized": s.prioritized or 0,
                 "created_at": s.created_at.isoformat() if s.created_at else None}
                for s in result.scalars().all()]

    async def signal_exists(self, url: str) -> bool:
        """Check if a signal with this URL already exists for this org."""
        if not url:
            return False
        query = select(Signal.id).where(Signal.url == url).limit(1)
        if self.org_id:
            query = query.where(Signal.org_id == self.org_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None

    async def prune_old_signals(self, days: int = 7) -> int:
        """Delete signals older than N days. Returns count deleted."""
        from sqlalchemy import delete as sql_delete
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=days)
        stmt = sql_delete(Signal).where(Signal.created_at < cutoff)
        if self.org_id:
            stmt = stmt.where(Signal.org_id == self.org_id)
        result = await self.db.execute(stmt)
        return result.rowcount

    # ──────────────────────────────────────
    # Briefs
    # ──────────────────────────────────────

    async def save_brief(self, data: dict) -> dict:
        if await self._should_use_df():
            record = {
                "date": data["date"],
                "summary": data["summary"],
                "angle": data.get("angle", ""),
                "signal_ids": data.get("signal_ids", ""),
                "created_at": datetime.datetime.utcnow().isoformat(),
            }
            if self.org_id:
                record["org_id"] = self.org_id
            records = await df.db_create(DF_DB_SERVICE, "pressroom_briefs", [record])
            return records[0] if records else {}

        brief = Brief(
            org_id=self.org_id,
            date=data["date"],
            summary=data["summary"],
            angle=data.get("angle", ""),
            signal_ids=data.get("signal_ids", ""),
        )
        self.db.add(brief)
        await self.db.flush()
        return {"id": brief.id, "date": brief.date, "summary": brief.summary, "angle": brief.angle}

    # ──────────────────────────────────────
    # Content
    # ──────────────────────────────────────

    async def save_content(self, data: dict) -> dict:
        if await self._should_use_df():
            record = {
                "signal_id": data.get("signal_id"),
                "brief_id": data.get("brief_id"),
                "story_id": data.get("story_id"),
                "channel": data["channel"] if isinstance(data["channel"], str) else data["channel"].value,
                "status": data.get("status", "queued"),
                "headline": data.get("headline", ""),
                "body": data["body"],
                "body_raw": data.get("body_raw", ""),
                "author": data.get("author", "company"),
                "source_signal_ids": data.get("source_signal_ids", ""),
                "created_at": datetime.datetime.utcnow().isoformat(),
            }
            if self.org_id:
                record["org_id"] = self.org_id
            records = await df.db_create(DF_DB_SERVICE, "pressroom_content", [record])
            return records[0] if records else {}

        content = Content(
            org_id=self.org_id,
            signal_id=data.get("signal_id"),
            brief_id=data.get("brief_id"),
            story_id=data.get("story_id"),
            channel=data["channel"] if isinstance(data["channel"], ContentChannel) else ContentChannel(data["channel"]),
            status=ContentStatus(data.get("status", "queued")),
            headline=data.get("headline", ""),
            body=data["body"],
            body_raw=data.get("body_raw", ""),
            author=data.get("author", "company"),
            source_signal_ids=data.get("source_signal_ids", ""),
        )
        self.db.add(content)
        await self.db.flush()
        return {"id": content.id, "channel": content.channel.value, "headline": content.headline,
                "status": content.status.value}

    async def list_content(self, status: str | None = None, limit: int = 50,
                            story_id: int | None = None, exclude_stories: bool = False) -> list[dict]:
        if await self._should_use_df():
            filters = []
            if self.org_id:
                filters.append(f"org_id = {self.org_id}")
            if status:
                filters.append(f"status = '{status}'")
            if story_id is not None:
                filters.append(f"story_id = {story_id}")
            if exclude_stories:
                filters.append("(story_id IS NULL OR story_id = 0)")
            filter_str = " AND ".join(filters) if filters else None
            return await df.db_query(DF_DB_SERVICE, "pressroom_content",
                                     filter_str=filter_str, order="created_at DESC", limit=limit)

        query = select(Content).order_by(Content.created_at.desc()).limit(limit)
        if self.org_id:
            query = query.where(Content.org_id == self.org_id)
        if status:
            query = query.where(Content.status == ContentStatus(status))
        if story_id is not None:
            query = query.where(Content.story_id == story_id)
        if exclude_stories:
            query = query.where((Content.story_id == None) | (Content.story_id == 0))
        result = await self.db.execute(query)
        return [_serialize_content(c) for c in result.scalars().all()]

    async def get_content(self, content_id: int) -> dict | None:
        if await self._should_use_df():
            try:
                return await df.db_get(DF_DB_SERVICE, "pressroom_content", content_id)
            except Exception:
                return None

        query = select(Content).where(Content.id == content_id)
        if self.org_id:
            query = query.where(Content.org_id == self.org_id)
        result = await self.db.execute(query)
        c = result.scalar_one_or_none()
        return _serialize_content(c) if c else None

    async def update_content_status(self, content_id: int, status: str, **extra) -> dict:
        if await self._should_use_df():
            update = {"id": content_id, "status": status}
            if status == "approved":
                update["approved_at"] = datetime.datetime.utcnow().isoformat()
            if status == "published":
                update["published_at"] = datetime.datetime.utcnow().isoformat()
            update.update(extra)
            records = await df.db_update(DF_DB_SERVICE, "pressroom_content", [update])
            return records[0] if records else {}

        query = select(Content).where(Content.id == content_id)
        if self.org_id:
            query = query.where(Content.org_id == self.org_id)
        result = await self.db.execute(query)
        c = result.scalar_one_or_none()
        if not c:
            return {}
        c.status = ContentStatus(status)
        if status == "approved":
            c.approved_at = datetime.datetime.utcnow()
        if status == "published":
            c.published_at = datetime.datetime.utcnow()
        # Apply extra fields (e.g. headline, body, body_raw from regenerate)
        for field, value in extra.items():
            if hasattr(c, field):
                setattr(c, field, value)
        await self.db.flush()
        return _serialize_content(c)

    async def get_approved_unpublished(self) -> list[dict]:
        if await self._should_use_df():
            filters = ["status = 'approved'", "published_at IS NULL"]
            if self.org_id:
                filters.insert(0, f"org_id = {self.org_id}")
            return await df.db_query(
                DF_DB_SERVICE, "pressroom_content",
                filter_str=" AND ".join(filters),
                order="created_at DESC",
            )

        query = select(Content).where(Content.status == ContentStatus.approved, Content.published_at.is_(None))
        if self.org_id:
            query = query.where(Content.org_id == self.org_id)
        result = await self.db.execute(query)
        return [_serialize_content(c) for c in result.scalars().all()]

    # ──────────────────────────────────────
    # Scheduling
    # ──────────────────────────────────────

    async def schedule_content(self, content_id: int, scheduled_at: datetime.datetime) -> dict:
        """Set scheduled_at on a content item. Also approves it if not already approved."""
        query = select(Content).where(Content.id == content_id)
        if self.org_id:
            query = query.where(Content.org_id == self.org_id)
        result = await self.db.execute(query)
        c = result.scalar_one_or_none()
        if not c:
            return {}
        c.scheduled_at = scheduled_at
        if c.status not in (ContentStatus.approved, ContentStatus.published):
            c.status = ContentStatus.approved
            c.approved_at = datetime.datetime.utcnow()
        await self.db.flush()
        return _serialize_content(c)

    async def list_scheduled_content(self) -> list[dict]:
        """List approved content that has a scheduled_at time and hasn't been published yet."""
        query = (select(Content)
                 .where(Content.status == ContentStatus.approved,
                        Content.scheduled_at.isnot(None))
                 .order_by(Content.scheduled_at.asc()))
        if self.org_id:
            query = query.where(Content.org_id == self.org_id)
        result = await self.db.execute(query)
        return [_serialize_content(c) for c in result.scalars().all()]

    # ──────────────────────────────────────
    # Settings (org-scoped)
    # ──────────────────────────────────────

    async def get_setting(self, key: str) -> str | None:
        query = select(Setting).where(Setting.key == key)
        if self.org_id:
            query = query.where(Setting.org_id == self.org_id)
        else:
            query = query.where(Setting.org_id.is_(None))
        result = await self.db.execute(query)
        s = result.scalar_one_or_none()
        return s.value if s else None

    async def set_setting(self, key: str, value: str):
        query = select(Setting).where(Setting.key == key)
        if self.org_id:
            query = query.where(Setting.org_id == self.org_id)
        else:
            query = query.where(Setting.org_id.is_(None))
        result = await self.db.execute(query)
        existing = result.scalar_one_or_none()
        if existing:
            existing.value = value
        else:
            self.db.add(Setting(org_id=self.org_id, key=key, value=value))

    # ── Account-level settings (org_id=NULL, shared across all companies) ──

    async def get_account_setting(self, key: str) -> str | None:
        """Get an account-level setting (org_id=NULL), regardless of current org context."""
        query = select(Setting).where(Setting.key == key, Setting.org_id.is_(None))
        result = await self.db.execute(query)
        s = result.scalar_one_or_none()
        return s.value if s else None

    async def set_account_setting(self, key: str, value: str):
        """Save an account-level setting (org_id=NULL), regardless of current org context."""
        query = select(Setting).where(Setting.key == key, Setting.org_id.is_(None))
        result = await self.db.execute(query)
        existing = result.scalar_one_or_none()
        if existing:
            existing.value = value
        else:
            self.db.add(Setting(org_id=None, key=key, value=value))

    async def get_account_settings(self) -> dict[str, str]:
        """Get all account-level settings (org_id=NULL)."""
        query = select(Setting).where(Setting.org_id.is_(None))
        result = await self.db.execute(query)
        return {s.key: s.value for s in result.scalars().all()}

    async def get_all_settings(self) -> dict[str, str]:
        """Get merged settings — account-level (org_id=NULL) + org-level.
        Org settings override account settings on conflicts."""
        account = await self.get_account_settings()
        if not self.org_id:
            return account
        query = select(Setting).where(Setting.org_id == self.org_id)
        result = await self.db.execute(query)
        org_settings = {s.key: s.value for s in result.scalars().all()}
        return {**account, **org_settings}

    # ──────────────────────────────────────
    # Memory queries (for the engine flywheel)
    # ──────────────────────────────────────

    async def get_approved_by_channel(self, channel: str, limit: int = 5) -> list[dict]:
        """Get recent approved content for a channel — few-shot examples for the engine."""
        if await self._should_use_df():
            filters = [f"channel = '{channel}'", "status = 'approved'"]
            if self.org_id:
                filters.insert(0, f"org_id = {self.org_id}")
            return await df.db_query(
                DF_DB_SERVICE, "pressroom_content",
                filter_str=" AND ".join(filters),
                order="approved_at DESC", limit=limit,
            )

        query = (select(Content)
                 .where(Content.channel == ContentChannel(channel), Content.status == ContentStatus.approved)
                 .order_by(Content.approved_at.desc()).limit(limit))
        if self.org_id:
            query = query.where(Content.org_id == self.org_id)
        result = await self.db.execute(query)
        return [_serialize_content(c) for c in result.scalars().all()]

    async def get_spiked_by_channel(self, channel: str, limit: int = 5) -> list[dict]:
        """Get recently spiked content — what NOT to generate."""
        if await self._should_use_df():
            filters = [f"channel = '{channel}'", "status = 'spiked'"]
            if self.org_id:
                filters.insert(0, f"org_id = {self.org_id}")
            return await df.db_query(
                DF_DB_SERVICE, "pressroom_content",
                filter_str=" AND ".join(filters),
                order="created_at DESC", limit=limit,
            )

        query = (select(Content)
                 .where(Content.channel == ContentChannel(channel), Content.status == ContentStatus.spiked)
                 .order_by(Content.created_at.desc()).limit(limit))
        if self.org_id:
            query = query.where(Content.org_id == self.org_id)
        result = await self.db.execute(query)
        return [_serialize_content(c) for c in result.scalars().all()]

    async def get_recent_topics(self, days: int = 21) -> list[dict]:
        """What angles/headlines have been covered recently — topic fatigue check."""
        cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).isoformat()
        if await self._should_use_df():
            filters = [f"created_at > '{cutoff}'"]
            if self.org_id:
                filters.insert(0, f"org_id = {self.org_id}")
            return await df.db_query(
                DF_DB_SERVICE, "pressroom_content",
                filter_str=" AND ".join(filters),
                order="created_at DESC", limit=100,
            )

        cutoff_dt = datetime.datetime.utcnow() - datetime.timedelta(days=days)
        query = select(Content).where(Content.created_at > cutoff_dt).order_by(Content.created_at.desc()).limit(100)
        if self.org_id:
            query = query.where(Content.org_id == self.org_id)
        result = await self.db.execute(query)
        return [{"headline": c.headline, "channel": c.channel.value, "status": c.status.value}
                for c in result.scalars().all()]

    # ──────────────────────────────────────
    # Aggregated memory context for generation
    # ──────────────────────────────────────

    async def get_memory_context(self) -> dict:
        """Gather the full memory context for the engine — approved examples,
        spiked anti-patterns, recent topics per channel, DF intelligence, and data sources."""
        channels = ["linkedin", "x_thread", "blog", "release_email", "newsletter"]
        memory = {"approved": {}, "spiked": {}, "recent_topics": [], "df_intelligence": {}, "datasources": []}
        for ch in channels:
            memory["approved"][ch] = await self.get_approved_by_channel(ch, limit=3)
            memory["spiked"][ch] = await self.get_spiked_by_channel(ch, limit=3)
        memory["recent_topics"] = await self.get_recent_topics(days=21)

        # Pull DF intelligence if service map exists
        memory["df_intelligence"] = await self.get_df_intelligence()

        # Include DataSource records as additional context
        memory["datasources"] = await self.list_datasources()

        return memory

    async def list_datasources(self) -> list[dict]:
        """List DataSource records for the current org."""
        query = select(DataSource).order_by(DataSource.created_at.desc())
        if self.org_id:
            query = query.where(DataSource.org_id == self.org_id)
        result = await self.db.execute(query)
        return [{"id": ds.id, "name": ds.name, "description": ds.description,
                 "category": ds.category, "connection_type": ds.connection_type,
                 "base_url": ds.base_url}
                for ds in result.scalars().all()]

    async def get_df_intelligence(self) -> dict:
        """Query DF intelligence sources based on the stored service map."""
        if not df.available:
            return {}

        svc_map_value = await self.get_setting("df_service_map")
        if not svc_map_value:
            return {}

        try:
            service_map_data = json.loads(svc_map_value)
        except json.JSONDecodeError:
            return {}

        service_map = service_map_data.get("service_map", service_map_data)
        intelligence = {}

        for svc_name, svc_info in service_map.items():
            role = svc_info.get("role", "unknown")
            if role in ("unknown", "internal", "publishing_channel"):
                continue

            useful_tables = svc_info.get("useful_tables", [])
            if not useful_tables:
                continue

            svc_data = {"role": role, "description": svc_info.get("description", ""), "data": []}

            for table in useful_tables[:3]:  # limit to 3 tables per service
                try:
                    rows = await df.db_query(svc_name, table, order="id DESC", limit=10)
                    if rows:
                        summarized = []
                        for row in rows:
                            summary = {}
                            for k, v in list(row.items())[:6]:
                                summary[k] = str(v)[:200] if v else ""
                            summarized.append(summary)
                        svc_data["data"].append({"table": table, "recent_rows": summarized})
                except Exception:
                    continue

            if svc_data["data"]:
                intelligence[svc_name] = svc_data

        return intelligence

    async def get_voice_settings(self) -> dict:
        """Load voice settings from the DB for the engine."""
        voice_keys = [
            "voice_persona", "voice_bio", "voice_audience", "voice_tone",
            "voice_never_say", "voice_always", "voice_brand_keywords",
            "voice_writing_examples",
            "voice_linkedin_style", "voice_x_style", "voice_blog_style",
            "voice_email_style", "voice_newsletter_style", "voice_yt_style",
            "onboard_company_name", "onboard_industry", "onboard_topics", "onboard_competitors",
        ]
        query = select(Setting).where(Setting.key.in_(voice_keys))
        if self.org_id:
            query = query.where(Setting.org_id == self.org_id)
        else:
            query = query.where(Setting.org_id.is_(None))
        result = await self.db.execute(query)
        return {s.key: s.value for s in result.scalars().all()}

    # ──────────────────────────────────────
    # Company Assets
    # ──────────────────────────────────────

    async def save_asset(self, data: dict) -> dict:
        asset = CompanyAsset(
            org_id=self.org_id,
            asset_type=data["asset_type"],
            url=data["url"],
            label=data.get("label", ""),
            description=data.get("description", ""),
            discovered_via=data.get("discovered_via", "manual"),
            auto_discovered=1 if data.get("auto_discovered") else 0,
            metadata_json=json.dumps(data.get("metadata", {})) if isinstance(data.get("metadata"), dict) else data.get("metadata_json", "{}"),
        )
        self.db.add(asset)
        await self.db.flush()
        return _serialize_asset(asset)

    async def list_assets(self, asset_type: str | None = None) -> list[dict]:
        query = select(CompanyAsset).order_by(CompanyAsset.asset_type, CompanyAsset.created_at.desc())
        if self.org_id:
            query = query.where(CompanyAsset.org_id == self.org_id)
        if asset_type:
            query = query.where(CompanyAsset.asset_type == asset_type)
        result = await self.db.execute(query)
        return [_serialize_asset(a) for a in result.scalars().all()]

    async def update_asset(self, asset_id: int, **fields) -> dict | None:
        query = select(CompanyAsset).where(CompanyAsset.id == asset_id)
        if self.org_id:
            query = query.where(CompanyAsset.org_id == self.org_id)
        result = await self.db.execute(query)
        a = result.scalar_one_or_none()
        if not a:
            return None
        for field, value in fields.items():
            if hasattr(a, field):
                setattr(a, field, value)
        await self.db.flush()
        return _serialize_asset(a)

    async def delete_asset(self, asset_id: int) -> bool:
        query = select(CompanyAsset).where(CompanyAsset.id == asset_id)
        if self.org_id:
            query = query.where(CompanyAsset.org_id == self.org_id)
        result = await self.db.execute(query)
        a = result.scalar_one_or_none()
        if not a:
            return False
        await self.db.delete(a)
        return True

    # ──────────────────────────────────────
    # Stories
    # ──────────────────────────────────────

    async def create_story(self, data: dict) -> dict:
        story = Story(
            org_id=self.org_id,
            title=data.get("title", "Untitled Story"),
            angle=data.get("angle", ""),
            editorial_notes=data.get("editorial_notes", ""),
            status=StoryStatus(data.get("status", "draft")),
        )
        self.db.add(story)
        await self.db.flush()
        return _serialize_story(story)

    async def get_story(self, story_id: int) -> dict | None:
        query = select(Story).where(Story.id == story_id)
        if self.org_id:
            query = query.where(Story.org_id == self.org_id)
        result = await self.db.execute(query)
        story = result.scalar_one_or_none()
        if not story:
            return None
        # Load associated Scout signals via join
        sq = (select(StorySignal, Signal)
              .join(Signal, StorySignal.signal_id == Signal.id)
              .where(StorySignal.story_id == story_id)
              .where(StorySignal.signal_id.isnot(None))
              .order_by(StorySignal.sort_order))
        sig_result = await self.db.execute(sq)
        signals_data = []
        for ss, sig in sig_result.all():
            signals_data.append({
                "id": ss.id,
                "story_signal_id": ss.id,
                "signal_id": sig.id,
                "wire_signal_id": None,
                "editor_notes": ss.editor_notes,
                "sort_order": ss.sort_order,
                "signal": {
                    "id": sig.id, "type": sig.type.value, "source": sig.source,
                    "title": sig.title, "body": sig.body, "url": sig.url,
                    "prioritized": sig.prioritized or 0,
                    "_table": "signal",
                },
            })
        # Load associated Wire signals via join
        wq = (select(StorySignal, WireSignal)
              .join(WireSignal, StorySignal.wire_signal_id == WireSignal.id)
              .where(StorySignal.story_id == story_id)
              .where(StorySignal.wire_signal_id.isnot(None))
              .order_by(StorySignal.sort_order))
        wire_result = await self.db.execute(wq)
        for ss, ws in wire_result.all():
            signals_data.append({
                "id": ss.id,
                "story_signal_id": ss.id,
                "signal_id": None,
                "wire_signal_id": ws.id,
                "editor_notes": ss.editor_notes,
                "sort_order": ss.sort_order,
                "signal": {
                    "id": f"wire:{ws.id}", "type": ws.type, "source": ws.source_name or "",
                    "title": ws.title, "body": ws.body or "", "url": ws.url or "",
                    "prioritized": 0,
                    "_table": "wire",
                },
            })
        # Sort combined list by sort_order
        signals_data.sort(key=lambda x: x["sort_order"])
        d = _serialize_story(story)
        d["signals"] = signals_data
        return d

    async def list_stories(self, limit: int = 20) -> list[dict]:
        query = select(Story).order_by(Story.created_at.desc()).limit(limit)
        if self.org_id:
            query = query.where(Story.org_id == self.org_id)
        result = await self.db.execute(query)
        stories = []
        for s in result.scalars().all():
            d = _serialize_story(s)
            # Count signals
            count_q = select(StorySignal).where(StorySignal.story_id == s.id)
            count_r = await self.db.execute(count_q)
            d["signal_count"] = len(count_r.scalars().all())
            stories.append(d)
        return stories

    async def update_story(self, story_id: int, **fields) -> dict | None:
        query = select(Story).where(Story.id == story_id)
        if self.org_id:
            query = query.where(Story.org_id == self.org_id)
        result = await self.db.execute(query)
        story = result.scalar_one_or_none()
        if not story:
            return None
        for field, value in fields.items():
            if field == "status":
                value = StoryStatus(value)
            if hasattr(story, field):
                setattr(story, field, value)
        await self.db.flush()
        return _serialize_story(story)

    async def delete_story(self, story_id: int) -> bool:
        query = select(Story).where(Story.id == story_id)
        if self.org_id:
            query = query.where(Story.org_id == self.org_id)
        result = await self.db.execute(query)
        story = result.scalar_one_or_none()
        if not story:
            return False
        await self.db.delete(story)
        return True

    async def add_signal_to_story(self, story_id: int, signal_id: int, editor_notes: str = "") -> dict | None:
        # Get max sort_order
        existing = await self.db.execute(
            select(StorySignal).where(StorySignal.story_id == story_id)
            .order_by(StorySignal.sort_order.desc()).limit(1)
        )
        last = existing.scalar_one_or_none()
        next_order = (last.sort_order + 1) if last else 0
        ss = StorySignal(story_id=story_id, signal_id=signal_id,
                         editor_notes=editor_notes, sort_order=next_order)
        self.db.add(ss)
        await self.db.flush()
        return {"id": ss.id, "story_id": story_id, "signal_id": signal_id,
                "editor_notes": editor_notes, "sort_order": ss.sort_order}

    async def add_wire_signal_to_story(self, story_id: int, wire_signal_id: int, editor_notes: str = "") -> dict | None:
        existing = await self.db.execute(
            select(StorySignal).where(StorySignal.story_id == story_id)
            .order_by(StorySignal.sort_order.desc()).limit(1)
        )
        last = existing.scalar_one_or_none()
        next_order = (last.sort_order + 1) if last else 0
        # signal_id=0 is a sentinel — existing DB schema requires non-null signal_id
        ss = StorySignal(story_id=story_id, signal_id=0, wire_signal_id=wire_signal_id,
                         editor_notes=editor_notes, sort_order=next_order)
        self.db.add(ss)
        await self.db.flush()
        return {"id": ss.id, "story_id": story_id, "wire_signal_id": wire_signal_id,
                "editor_notes": editor_notes, "sort_order": ss.sort_order}

    async def remove_signal_from_story(self, story_signal_id: int) -> bool:
        result = await self.db.execute(
            select(StorySignal).where(StorySignal.id == story_signal_id))
        ss = result.scalar_one_or_none()
        if not ss:
            return False
        await self.db.delete(ss)
        return True

    async def update_story_signal_notes(self, story_signal_id: int, editor_notes: str) -> dict | None:
        result = await self.db.execute(
            select(StorySignal).where(StorySignal.id == story_signal_id))
        ss = result.scalar_one_or_none()
        if not ss:
            return None
        ss.editor_notes = editor_notes
        await self.db.flush()
        return {"id": ss.id, "editor_notes": ss.editor_notes}

    async def update_signal_body(self, signal_id: int, body: str) -> dict | None:
        query = select(Signal).where(Signal.id == signal_id)
        if self.org_id:
            query = query.where(Signal.org_id == self.org_id)
        result = await self.db.execute(query)
        s = result.scalar_one_or_none()
        if not s:
            return None
        s.body = body
        await self.db.flush()
        return {"id": s.id, "type": s.type.value, "source": s.source, "title": s.title,
                "body": s.body, "url": s.url, "prioritized": s.prioritized or 0}

    # ── API Keys (account-level) ──

    async def list_api_keys(self) -> list[dict]:
        result = await self.db.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))
        return [{"id": k.id, "label": k.label,
                 "key_preview": k.key_value[:8] + "..." if len(k.key_value) > 8 else "***",
                 "created_at": k.created_at.isoformat() if k.created_at else None}
                for k in result.scalars().all()]

    async def create_api_key(self, label: str, key_value: str) -> dict:
        k = ApiKey(label=label, key_value=key_value)
        self.db.add(k)
        await self.db.flush()
        return {"id": k.id, "label": k.label,
                "key_preview": k.key_value[:8] + "...",
                "created_at": k.created_at.isoformat() if k.created_at else None}

    async def update_api_key_label(self, key_id: int, label: str) -> dict | None:
        result = await self.db.execute(select(ApiKey).where(ApiKey.id == key_id))
        k = result.scalar_one_or_none()
        if not k:
            return None
        k.label = label
        await self.db.flush()
        return {"id": k.id, "label": k.label, "key_preview": k.key_value[:8] + "..."}

    async def delete_api_key(self, key_id: int) -> bool:
        result = await self.db.execute(select(ApiKey).where(ApiKey.id == key_id))
        k = result.scalar_one_or_none()
        if not k:
            return False
        await self.db.delete(k)
        return True

    async def get_api_key_value(self, key_id: int) -> str | None:
        result = await self.db.execute(select(ApiKey).where(ApiKey.id == key_id))
        k = result.scalar_one_or_none()
        return k.key_value if k else None

    async def resolve_api_key(self) -> str | None:
        """Resolve the Anthropic API key for the current org.

        Priority: org's assigned key → first key in table → legacy global config.
        """
        from config import settings as cfg

        # 1. Org's assigned key
        if self.org_id:
            key_id_str = await self.get_setting("anthropic_api_key_id")
            if key_id_str:
                try:
                    val = await self.get_api_key_value(int(key_id_str))
                    if val:
                        return val
                except (ValueError, TypeError):
                    pass

        # 2. First available key
        result = await self.db.execute(select(ApiKey).order_by(ApiKey.created_at.asc()).limit(1))
        first = result.scalar_one_or_none()
        if first:
            return first.key_value

        # 3. Legacy fallback
        return cfg.anthropic_api_key or None

    # ── Audit Results ──

    async def save_audit(self, data: dict) -> dict:
        audit = AuditResult(
            org_id=self.org_id,
            audit_type=data["audit_type"],
            target=data["target"],
            score=data.get("score", 0),
            total_issues=data.get("total_issues", 0),
            result_json=json.dumps(data["result"]) if isinstance(data.get("result"), dict) else data.get("result_json", "{}"),
        )
        self.db.add(audit)
        await self.db.flush()
        return _serialize_audit(audit)

    async def list_audits(self, audit_type: str | None = None, limit: int = 20) -> list[dict]:
        query = select(AuditResult).order_by(AuditResult.created_at.desc()).limit(limit)
        if self.org_id:
            query = query.where(AuditResult.org_id == self.org_id)
        if audit_type:
            query = query.where(AuditResult.audit_type == audit_type)
        result = await self.db.execute(query)
        return [_serialize_audit(a) for a in result.scalars().all()]

    async def get_audit(self, audit_id: int) -> dict | None:
        query = select(AuditResult).where(AuditResult.id == audit_id)
        if self.org_id:
            query = query.where(AuditResult.org_id == self.org_id)
        result = await self.db.execute(query)
        a = result.scalar_one_or_none()
        return _serialize_audit(a) if a else None

    async def delete_audit(self, audit_id: int) -> bool:
        query = select(AuditResult).where(AuditResult.id == audit_id)
        if self.org_id:
            query = query.where(AuditResult.org_id == self.org_id)
        result = await self.db.execute(query)
        a = result.scalar_one_or_none()
        if not a:
            return False
        await self.db.delete(a)
        return True

    # ──────────────────────────────────────
    # Audit Action Items
    # ──────────────────────────────────────

    async def upsert_action_items(self, audit_result_id: int, items: list[dict]) -> list[dict]:
        """Persist action items from an audit. Merges with existing open items by title."""
        import datetime as dt
        now = dt.datetime.utcnow()
        saved = []
        for item in items:
            title = item.get("title", item.get("action", ""))[:500]
            if not title:
                continue
            # Check if an open item with same title already exists for this org
            existing_q = select(AuditActionItem).where(
                AuditActionItem.org_id == self.org_id,
                AuditActionItem.title == title,
                AuditActionItem.status != "resolved",
            )
            existing_r = await self.db.execute(existing_q)
            existing = existing_r.scalar_one_or_none()
            if existing:
                existing.last_seen = now
                existing.audit_result_id = audit_result_id
                evidence = item.get("evidence", {})
                if evidence:
                    existing.evidence_json = json.dumps(evidence)
                saved.append(_serialize_action_item(existing))
            else:
                ai = AuditActionItem(
                    org_id=self.org_id,
                    audit_result_id=audit_result_id,
                    priority=item.get("priority", "medium"),
                    category=item.get("category", ""),
                    title=title,
                    status="open",
                    evidence_json=json.dumps(item.get("evidence", {})),
                    fix_instructions=item.get("fix_instructions", ""),
                    score_impact=item.get("score_impact", 0),
                    first_seen=now,
                    last_seen=now,
                )
                self.db.add(ai)
                await self.db.flush()
                saved.append(_serialize_action_item(ai))
        return saved

    async def list_action_items(self, status: str | None = None, limit: int = 100) -> list[dict]:
        query = select(AuditActionItem).where(AuditActionItem.org_id == self.org_id)
        if status:
            query = query.where(AuditActionItem.status == status)
        query = query.order_by(
            AuditActionItem.priority.desc(),
            AuditActionItem.last_seen.desc()
        ).limit(limit)
        result = await self.db.execute(query)
        return [_serialize_action_item(a) for a in result.scalars().all()]

    async def update_action_item_status(self, item_id: int, status: str) -> dict | None:
        import datetime as dt
        query = select(AuditActionItem).where(
            AuditActionItem.id == item_id,
            AuditActionItem.org_id == self.org_id,
        )
        result = await self.db.execute(query)
        item = result.scalar_one_or_none()
        if not item:
            return None
        item.status = status
        if status == "resolved":
            item.resolved_at = dt.datetime.utcnow()
        return _serialize_action_item(item)

    # ──────────────────────────────────────
    # Team Members
    # ──────────────────────────────────────

    async def save_team_member(self, data: dict) -> dict:
        tags = data.get("expertise_tags", [])
        if isinstance(tags, list):
            tags = json.dumps(tags)
        member = TeamMember(
            org_id=self.org_id,
            name=data["name"],
            title=data.get("title", ""),
            bio=data.get("bio", ""),
            photo_url=data.get("photo_url", ""),
            linkedin_url=data.get("linkedin_url", ""),
            email=data.get("email", ""),
            expertise_tags=tags,
        )
        self.db.add(member)
        await self.db.flush()
        return _serialize_team_member(member)

    async def list_team_members(self) -> list[dict]:
        query = select(TeamMember).order_by(TeamMember.name)
        if self.org_id:
            query = query.where(TeamMember.org_id == self.org_id)
        result = await self.db.execute(query)
        return [_serialize_team_member(m) for m in result.scalars().all()]

    async def update_team_member(self, member_id: int, **fields) -> dict | None:
        query = select(TeamMember).where(TeamMember.id == member_id)
        if self.org_id:
            query = query.where(TeamMember.org_id == self.org_id)
        result = await self.db.execute(query)
        m = result.scalar_one_or_none()
        if not m:
            return None
        for field, value in fields.items():
            if field == "expertise_tags" and isinstance(value, list):
                value = json.dumps(value)
            if hasattr(m, field):
                setattr(m, field, value)
        await self.db.flush()
        return _serialize_team_member(m)

    async def delete_team_member(self, member_id: int) -> bool:
        query = select(TeamMember).where(TeamMember.id == member_id)
        if self.org_id:
            query = query.where(TeamMember.org_id == self.org_id)
        result = await self.db.execute(query)
        m = result.scalar_one_or_none()
        if not m:
            return False
        await self.db.delete(m)
        return True

    # ──────────────────────────────────────
    # SEO PR Runs
    # ──────────────────────────────────────

    async def save_seo_pr_run(self, data: dict) -> dict:
        run = SeoPrRun(
            org_id=self.org_id,
            domain=data["domain"],
            repo_url=data.get("repo_url", ""),
            status=data.get("status", "pending"),
            audit_id=data.get("audit_id"),
            plan_json=json.dumps(data["plan"]) if isinstance(data.get("plan"), dict) else data.get("plan_json", "{}"),
            pr_url=data.get("pr_url", ""),
            branch_name=data.get("branch_name", ""),
            error=data.get("error", ""),
            changes_made=data.get("changes_made", 0),
        )
        self.db.add(run)
        await self.db.flush()
        return _serialize_seo_pr_run(run)

    async def update_seo_pr_run(self, run_id: int, updates: dict) -> dict | None:
        query = select(SeoPrRun).where(SeoPrRun.id == run_id)
        if self.org_id:
            query = query.where(SeoPrRun.org_id == self.org_id)
        result = await self.db.execute(query)
        run = result.scalar_one_or_none()
        if not run:
            return None
        for field, value in updates.items():
            if field == "plan" and isinstance(value, dict):
                run.plan_json = json.dumps(value)
            elif hasattr(run, field):
                setattr(run, field, value)
        await self.db.flush()
        return _serialize_seo_pr_run(run)

    async def list_seo_pr_runs(self, limit: int = 20) -> list[dict]:
        query = select(SeoPrRun).order_by(SeoPrRun.created_at.desc()).limit(limit)
        if self.org_id:
            query = query.where(SeoPrRun.org_id == self.org_id)
        result = await self.db.execute(query)
        return [_serialize_seo_pr_run(r) for r in result.scalars().all()]

    async def get_seo_pr_run(self, run_id: int) -> dict | None:
        query = select(SeoPrRun).where(SeoPrRun.id == run_id)
        if self.org_id:
            query = query.where(SeoPrRun.org_id == self.org_id)
        result = await self.db.execute(query)
        r = result.scalar_one_or_none()
        return _serialize_seo_pr_run(r) if r else None

    async def delete_seo_pr_run(self, run_id: int) -> bool:
        query = select(SeoPrRun).where(SeoPrRun.id == run_id)
        if self.org_id:
            query = query.where(SeoPrRun.org_id == self.org_id)
        result = await self.db.execute(query)
        r = result.scalar_one_or_none()
        if not r:
            return False
        await self.db.delete(r)
        return True

    # ──────────────────────────────────────
    # Site Properties (site ↔ repo bonds)
    # ──────────────────────────────────────

    async def save_site_property(self, data: dict) -> dict:
        prop = SiteProperty(
            org_id=self.org_id,
            name=data["name"],
            domain=data["domain"],
            repo_url=data.get("repo_url", ""),
            base_branch=data.get("base_branch", "main"),
            site_type=data.get("site_type", "static"),
        )
        self.db.add(prop)
        await self.db.flush()
        return _serialize_site_property(prop)

    async def list_site_properties(self) -> list[dict]:
        query = select(SiteProperty).order_by(SiteProperty.created_at.desc())
        if self.org_id:
            query = query.where(SiteProperty.org_id == self.org_id)
        result = await self.db.execute(query)
        return [_serialize_site_property(p) for p in result.scalars().all()]

    async def get_site_property(self, prop_id: int) -> dict | None:
        query = select(SiteProperty).where(SiteProperty.id == prop_id)
        if self.org_id:
            query = query.where(SiteProperty.org_id == self.org_id)
        result = await self.db.execute(query)
        p = result.scalar_one_or_none()
        return _serialize_site_property(p) if p else None

    async def update_site_property(self, prop_id: int, **fields) -> dict | None:
        query = select(SiteProperty).where(SiteProperty.id == prop_id)
        if self.org_id:
            query = query.where(SiteProperty.org_id == self.org_id)
        result = await self.db.execute(query)
        p = result.scalar_one_or_none()
        if not p:
            return None
        for field, value in fields.items():
            if hasattr(p, field):
                setattr(p, field, value)
        await self.db.flush()
        return _serialize_site_property(p)

    async def delete_site_property(self, prop_id: int) -> bool:
        query = select(SiteProperty).where(SiteProperty.id == prop_id)
        if self.org_id:
            query = query.where(SiteProperty.org_id == self.org_id)
        result = await self.db.execute(query)
        p = result.scalar_one_or_none()
        if not p:
            return False
        await self.db.delete(p)
        return True

    # ──────────────────────────────────────
    # Signal Stats / Attribution
    # ──────────────────────────────────────

    async def increment_signal_usage(self, signal_id: int) -> None:
        """Bump times_used by 1 on a signal."""
        query = select(Signal).where(Signal.id == signal_id)
        if self.org_id:
            query = query.where(Signal.org_id == self.org_id)
        result = await self.db.execute(query)
        s = result.scalar_one_or_none()
        if s:
            s.times_used = (s.times_used or 0) + 1
            await self.db.flush()

    async def increment_signal_spikes(self, signal_id: int) -> None:
        """Bump times_spiked by 1 on a signal."""
        query = select(Signal).where(Signal.id == signal_id)
        if self.org_id:
            query = query.where(Signal.org_id == self.org_id)
        result = await self.db.execute(query)
        s = result.scalar_one_or_none()
        if s:
            s.times_spiked = (s.times_spiked or 0) + 1
            await self.db.flush()

    async def get_signal_stats(self) -> list[dict]:
        """Return signals with usage/spike counts, ordered by times_used desc."""
        query = select(Signal).order_by(Signal.times_used.desc(), Signal.created_at.desc())
        if self.org_id:
            query = query.where(Signal.org_id == self.org_id)
        result = await self.db.execute(query)
        return [
            {"id": s.id, "type": s.type.value, "source": s.source, "title": s.title,
             "times_used": s.times_used or 0, "times_spiked": s.times_spiked or 0}
            for s in result.scalars().all()
        ]

    async def get_signals_by_ids(self, signal_ids: list[int]) -> list[dict]:
        """Fetch minimal signal info for a list of IDs — used for source attribution display."""
        if not signal_ids:
            return []
        query = select(Signal).where(Signal.id.in_(signal_ids))
        if self.org_id:
            query = query.where(Signal.org_id == self.org_id)
        result = await self.db.execute(query)
        return [
            {"id": s.id, "type": s.type.value, "title": s.title, "source": s.source}
            for s in result.scalars().all()
        ]

    # ──────────────────────────────────────
    # Blog Posts
    # ──────────────────────────────────────

    async def save_blog_post(self, data: dict) -> dict:
        published_at = data.get("published_at")
        if isinstance(published_at, str):
            try:
                published_at = datetime.datetime.fromisoformat(published_at)
            except (ValueError, TypeError):
                published_at = None
        bp = BlogPost(
            org_id=self.org_id,
            url=data.get("url", ""),
            title=data.get("title", ""),
            excerpt=data.get("excerpt", ""),
            published_at=published_at,
        )
        self.db.add(bp)
        await self.db.flush()
        return _serialize_blog_post(bp)

    async def list_blog_posts(self, limit: int = 50) -> list[dict]:
        query = select(BlogPost).order_by(BlogPost.scraped_at.desc()).limit(limit)
        if self.org_id:
            query = query.where(BlogPost.org_id == self.org_id)
        result = await self.db.execute(query)
        return [_serialize_blog_post(bp) for bp in result.scalars().all()]

    async def delete_blog_post(self, post_id: int) -> bool:
        query = select(BlogPost).where(BlogPost.id == post_id)
        if self.org_id:
            query = query.where(BlogPost.org_id == self.org_id)
        result = await self.db.execute(query)
        bp = result.scalar_one_or_none()
        if not bp:
            return False
        await self.db.delete(bp)
        return True

    # ──────────────────────────────────────
    # Email Drafts
    # ──────────────────────────────────────

    async def save_email_draft(self, data: dict) -> dict:
        draft = EmailDraft(
            org_id=self.org_id,
            content_id=data.get("content_id"),
            subject=data["subject"],
            html_body=data["html_body"],
            text_body=data.get("text_body", ""),
            from_name=data.get("from_name", ""),
            status=data.get("status", "draft"),
            recipients=json.dumps(data.get("recipients", [])) if isinstance(data.get("recipients"), list) else data.get("recipients", "[]"),
        )
        self.db.add(draft)
        await self.db.flush()
        return _serialize_email_draft(draft)

    async def list_email_drafts(self, status: str | None = None, limit: int = 20) -> list[dict]:
        query = select(EmailDraft).order_by(EmailDraft.created_at.desc()).limit(limit)
        if self.org_id:
            query = query.where(EmailDraft.org_id == self.org_id)
        if status:
            query = query.where(EmailDraft.status == status)
        result = await self.db.execute(query)
        return [_serialize_email_draft(ed) for ed in result.scalars().all()]

    async def get_email_draft(self, draft_id: int) -> dict | None:
        query = select(EmailDraft).where(EmailDraft.id == draft_id)
        if self.org_id:
            query = query.where(EmailDraft.org_id == self.org_id)
        result = await self.db.execute(query)
        ed = result.scalar_one_or_none()
        return _serialize_email_draft(ed) if ed else None

    async def update_email_draft(self, draft_id: int, updates: dict) -> dict | None:
        query = select(EmailDraft).where(EmailDraft.id == draft_id)
        if self.org_id:
            query = query.where(EmailDraft.org_id == self.org_id)
        result = await self.db.execute(query)
        ed = result.scalar_one_or_none()
        if not ed:
            return None
        for field, value in updates.items():
            if field == "recipients" and isinstance(value, list):
                value = json.dumps(value)
            if hasattr(ed, field) and field not in ("id", "org_id", "created_at"):
                setattr(ed, field, value)
        await self.db.flush()
        return _serialize_email_draft(ed)

    async def delete_email_draft(self, draft_id: int) -> bool:
        query = select(EmailDraft).where(EmailDraft.id == draft_id)
        if self.org_id:
            query = query.where(EmailDraft.org_id == self.org_id)
        result = await self.db.execute(query)
        ed = result.scalar_one_or_none()
        if not ed:
            return False
        await self.db.delete(ed)
        return True

    async def commit(self):
        await self.db.commit()


def _serialize_email_draft(ed: EmailDraft) -> dict:
    recipients = ed.recipients or "[]"
    if isinstance(recipients, str):
        try:
            recipients = json.loads(recipients)
        except (json.JSONDecodeError, ValueError):
            recipients = []
    return {
        "id": ed.id, "org_id": ed.org_id, "content_id": ed.content_id,
        "subject": ed.subject, "html_body": ed.html_body, "text_body": ed.text_body,
        "from_name": ed.from_name, "status": ed.status,
        "recipients": recipients,
        "sent_at": ed.sent_at.isoformat() if ed.sent_at else None,
        "created_at": ed.created_at.isoformat() if ed.created_at else None,
    }


def _serialize_content(c: Content) -> dict:
    return {
        "id": c.id, "org_id": c.org_id, "signal_id": c.signal_id,
        "brief_id": c.brief_id, "story_id": getattr(c, "story_id", None),
        "channel": c.channel.value, "status": c.status.value,
        "headline": c.headline, "body": c.body, "body_raw": c.body_raw,
        "author": c.author,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "approved_at": c.approved_at.isoformat() if c.approved_at else None,
        "published_at": c.published_at.isoformat() if c.published_at else None,
        "scheduled_at": c.scheduled_at.isoformat() if getattr(c, "scheduled_at", None) else None,
        "source_signal_ids": getattr(c, "source_signal_ids", "") or "",
        "post_id": getattr(c, "post_id", "") or "",
        "post_url": getattr(c, "post_url", "") or "",
    }


def _serialize_asset(a: CompanyAsset) -> dict:
    return {
        "id": a.id, "org_id": a.org_id, "asset_type": a.asset_type,
        "url": a.url, "label": a.label, "description": a.description,
        "discovered_via": a.discovered_via, "auto_discovered": bool(a.auto_discovered),
        "metadata": json.loads(a.metadata_json) if a.metadata_json else {},
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _serialize_story(s: Story) -> dict:
    return {
        "id": s.id, "org_id": s.org_id, "title": s.title,
        "angle": s.angle, "editorial_notes": s.editorial_notes,
        "status": s.status.value,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


def _serialize_audit(a: AuditResult) -> dict:
    return {
        "id": a.id, "org_id": a.org_id, "audit_type": a.audit_type,
        "target": a.target, "score": a.score, "total_issues": a.total_issues,
        "result": json.loads(a.result_json) if a.result_json else {},
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _serialize_action_item(a: AuditActionItem) -> dict:
    return {
        "id": a.id, "org_id": a.org_id, "audit_result_id": a.audit_result_id,
        "priority": a.priority, "category": a.category, "title": a.title,
        "status": a.status,
        "evidence": json.loads(a.evidence_json) if a.evidence_json else {},
        "fix_instructions": a.fix_instructions or "",
        "score_impact": a.score_impact or 0,
        "first_seen": a.first_seen.isoformat() if a.first_seen else None,
        "last_seen": a.last_seen.isoformat() if a.last_seen else None,
        "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
    }


def _serialize_team_member(m: TeamMember) -> dict:
    tags = m.expertise_tags or "[]"
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except (json.JSONDecodeError, ValueError):
            tags = []
    return {
        "id": m.id, "org_id": m.org_id, "name": m.name,
        "title": m.title, "bio": m.bio, "photo_url": m.photo_url,
        "linkedin_url": getattr(m, "linkedin_url", "") or "",
        "github_username": getattr(m, "github_username", "") or "",
        "github_connected": bool(getattr(m, "github_access_token", "")),
        "email": m.email,
        "expertise_tags": tags,
        "linkedin_author_urn": getattr(m, "linkedin_author_urn", "") or "",
        "linkedin_token_expires_at": getattr(m, "linkedin_token_expires_at", 0) or 0,
        "voice_style": getattr(m, "voice_style", "") or "",
        "linkedin_post_samples": getattr(m, "linkedin_post_samples", "") or "",
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def _serialize_blog_post(bp: BlogPost) -> dict:
    return {
        "id": bp.id, "org_id": bp.org_id, "url": bp.url,
        "title": bp.title, "excerpt": bp.excerpt,
        "published_at": bp.published_at.isoformat() if bp.published_at else None,
        "scraped_at": bp.scraped_at.isoformat() if bp.scraped_at else None,
    }


def _serialize_site_property(p: SiteProperty) -> dict:
    return {
        "id": p.id, "org_id": p.org_id, "name": p.name,
        "domain": p.domain, "repo_url": p.repo_url,
        "base_branch": p.base_branch,
        "site_type": p.site_type or "static",
        "last_audit_score": p.last_audit_score,
        "last_audit_id": p.last_audit_id,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _serialize_seo_pr_run(r: SeoPrRun) -> dict:
    plan = {}
    if r.plan_json:
        try:
            plan = json.loads(r.plan_json)
        except (json.JSONDecodeError, ValueError):
            plan = {}
    return {
        "id": r.id, "org_id": r.org_id, "domain": r.domain,
        "repo_url": r.repo_url, "status": r.status,
        "audit_id": r.audit_id, "plan": plan,
        "pr_url": r.pr_url, "branch_name": r.branch_name,
        "error": r.error, "changes_made": r.changes_made,
        "deploy_status": getattr(r, "deploy_status", "") or "",
        "deploy_log": getattr(r, "deploy_log", "") or "",
        "heal_attempts": getattr(r, "heal_attempts", 0) or 0,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
    }
