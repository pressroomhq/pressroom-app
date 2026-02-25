from fastapi import Header
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Lightweight migrations for new columns on existing tables
        for stmt in [
            "ALTER TABLE signals ADD COLUMN prioritized INTEGER DEFAULT 0",
            "ALTER TABLE content ADD COLUMN story_id INTEGER REFERENCES stories(id)",
            "ALTER TABLE signals ADD COLUMN times_used INTEGER DEFAULT 0",
            "ALTER TABLE signals ADD COLUMN times_spiked INTEGER DEFAULT 0",
            "ALTER TABLE content ADD COLUMN source_signal_ids TEXT DEFAULT ''",
            "ALTER TABLE seo_pr_runs ADD COLUMN deploy_status VARCHAR(50) DEFAULT ''",
            "ALTER TABLE seo_pr_runs ADD COLUMN deploy_log TEXT DEFAULT ''",
            "ALTER TABLE seo_pr_runs ADD COLUMN heal_attempts INTEGER DEFAULT 0",
            "ALTER TABLE content ADD COLUMN scheduled_at DATETIME",
            # story_signals: add wire_signal_id and make signal_id nullable via table recreation
            # We use a flag column approach: wire_signal_id added separately, signal_id kept as-is
            # New rows with wire signals will use signal_id=0 as sentinel (filtered in queries)
            "ALTER TABLE story_signals ADD COLUMN wire_signal_id INTEGER REFERENCES wire_signals(id)",
            "ALTER TABLE team_members ADD COLUMN linkedin_url VARCHAR(500) DEFAULT ''",
            "ALTER TABLE team_members ADD COLUMN github_username VARCHAR(255) DEFAULT ''",
            "ALTER TABLE team_members ADD COLUMN linkedin_access_token TEXT DEFAULT ''",
            "ALTER TABLE team_members ADD COLUMN linkedin_author_urn VARCHAR(255) DEFAULT ''",
            "ALTER TABLE team_members ADD COLUMN linkedin_token_expires_at INTEGER DEFAULT 0",
            # User auth tables — created via create_all, migrations for safety
            "ALTER TABLE users ADD COLUMN name VARCHAR(255) DEFAULT ''",
            "ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN last_login_at DATETIME",
            # Content performance tracking
            "ALTER TABLE content ADD COLUMN post_id VARCHAR(500) DEFAULT ''",
            "ALTER TABLE content ADD COLUMN post_url VARCHAR(1000) DEFAULT ''",
        ]:
            try:
                await conn.execute(__import__('sqlalchemy').text(stmt))
            except Exception:
                pass  # column already exists


async def get_db():
    async with async_session() as session:
        yield session


async def get_data_layer_for_org(org_id: int):
    """Non-dependency version — returns a DataLayer for a specific org. For internal use."""
    from services.data_layer import DataLayer
    session = async_session()
    return DataLayer(session, org_id=org_id)


async def get_data_layer(x_org_id: int | None = Header(default=None)):
    """FastAPI dependency — yields a DataLayer scoped to an org.

    Org comes from the X-Org-Id header. If missing, org_id=None (global/legacy).
    For authenticated access, use get_authenticated_data_layer from api.auth instead.
    """
    from services.data_layer import DataLayer
    async with async_session() as session:
        dl = DataLayer(session, org_id=x_org_id)
        yield dl
