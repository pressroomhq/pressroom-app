"""Pressroom — Marketing Department in a Box."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from database import init_db
from api.signals import router as signals_router
from api.content import router as content_router
from api.pipeline import router as pipeline_router
from api.webhook import router as webhook_router
from api.publish import router as publish_router
from api.settings import router as settings_router
from api.imports import router as imports_router
from api.onboard import router as onboard_router
from api.orgs import router as orgs_router
from api.oauth import router as oauth_router
from api.datasources import router as datasources_router
from api.audit import router as audit_router
from api.assets import router as assets_router
from api.stories import router as stories_router
from api.team import router as team_router
from api.blog import router as blog_router
from api.email import router as email_router
from api.hubspot import router as hubspot_router
from api.seo_pr import router as seo_pr_router
from api.properties import router as properties_router
from api.analytics import router as analytics_router
from api.slack import router as slack_router
from api.company_audit import router as company_audit_router
from api.stream import router as stream_router
from api.log import router as log_router
from api.scoreboard import router as scoreboard_router
from api.youtube import router as youtube_router
from api.skills_api import router as skills_router
from api.brand import router as brand_router
from api.youtube_publish import router as youtube_publish_router
from api.medium import router as medium_router
from api.usage import router as usage_router
from api.competitive import router as competitive_router
from api.ai_visibility import router as ai_visibility_router
from api.sources import router as sources_router
from api.wire import router as wire_router
from api.gsc import router as gsc_router
from api.user_auth import router as user_auth_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    await init_db()

    # Load account-level settings (API keys, models) into runtime config at boot
    from database import async_session
    from services.data_layer import DataLayer
    from api.settings import _sync_to_runtime
    async with async_session() as session:
        dl = DataLayer(session, org_id=None)
        await _sync_to_runtime(dl)

    # Seed default SIGINT sources (idempotent)
    try:
        from api.sources import seed_default_sources
        await seed_default_sources()
    except Exception:
        pass

    # Seed admin user from env vars if no users exist yet
    try:
        import os
        from sqlalchemy import select
        from models import User
        from api.user_auth import _hash_password
        admin_email = os.environ.get("ADMIN_EMAIL")
        admin_password = os.environ.get("ADMIN_PASSWORD")
        if admin_email and admin_password:
            async with async_session() as session:
                existing = await session.execute(select(User).limit(1))
                if not existing.scalars().first():
                    admin = User(
                        email=admin_email,
                        name="Admin",
                        password_hash=_hash_password(admin_password),
                        is_admin=1,
                        is_active=1,
                    )
                    session.add(admin)
                    await session.commit()
    except Exception:
        pass

    # Start background scheduler for timed content publishing
    from services.scheduler import scheduler_loop
    scheduler_task = asyncio.create_task(scheduler_loop())

    yield

    scheduler_task.cancel()


app = FastAPI(
    title="Pressroom",
    description="This just in: your story's already written.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
async def health():
    import os
    return {
        "status": "on the wire",
        "version": "0.1.0",
        "auth_disabled": os.getenv("PRESSROOM_AUTH_DISABLED", "").strip() in ("1", "true", "yes"),
    }

app.include_router(signals_router)
app.include_router(content_router)
app.include_router(pipeline_router)
app.include_router(webhook_router)
app.include_router(publish_router)
app.include_router(settings_router)
app.include_router(imports_router)
app.include_router(onboard_router)
app.include_router(orgs_router)
app.include_router(oauth_router)
app.include_router(datasources_router)
app.include_router(audit_router)
app.include_router(assets_router)
app.include_router(stories_router)
app.include_router(team_router)
app.include_router(blog_router)
app.include_router(email_router)
app.include_router(hubspot_router)
app.include_router(seo_pr_router)
app.include_router(properties_router)
app.include_router(analytics_router)
app.include_router(slack_router)
app.include_router(company_audit_router)
app.include_router(stream_router)
app.include_router(log_router)
app.include_router(scoreboard_router)
app.include_router(youtube_router)
app.include_router(skills_router)
app.include_router(brand_router)
app.include_router(youtube_publish_router)
app.include_router(medium_router)
app.include_router(usage_router)
app.include_router(competitive_router)
app.include_router(ai_visibility_router)
app.include_router(sources_router)
app.include_router(wire_router)
app.include_router(gsc_router)
app.include_router(user_auth_router)

# Serve frontend static files if built — MUST be last (catch-all)
frontend_dist = Path(__file__).parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
