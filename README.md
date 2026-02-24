# Pressroom

**This just in: your story's already written.**

Pressroom is an AI-powered marketing content engine. It monitors signal sources (Hacker News, Reddit, GitHub, RSS), identifies relevant stories, and generates ready-to-publish content across multiple channels — blog posts, LinkedIn, X threads, newsletters, and email drafts.

Think of it as a wire room for your marketing team. Signals come in, content goes out.

## How It Works

```
Sources (HN, Reddit, GitHub, RSS, Web)
        │
        ▼
   ┌─────────┐
   │  SCOUT   │  ← pulls signals from configured sources
   └────┬────┘
        ▼
   ┌─────────┐
   │  WIRE    │  ← signal triage: prioritize, spike, or curate into stories
   └────┬────┘
        ▼
   ┌──────────┐
   │ GENERATE  │  ← Claude writes content using signals + voice + angle
   └────┬─────┘
        ▼
   ┌──────────┐
   │ HUMANIZE  │  ← strips AI tells, matches brand voice
   └────┬─────┘
        ▼
   ┌──────────┐
   │  QUEUE    │  ← approve, edit, schedule, or spike
   └────┬─────┘
        ▼
   ┌──────────┐
   │ PUBLISH   │  ← push to LinkedIn, HubSpot, blog, or copy to clipboard
   └──────────┘
```

## Stack

- **Backend:** Python / FastAPI / SQLite (async via aiosqlite)
- **Frontend:** React / Vite (single-page app, served from FastAPI)
- **AI:** Anthropic Claude (Sonnet for generation, Haiku for fast tasks)
- **Integrations:** LinkedIn, HubSpot, GitHub, Slack (webhooks)

## Features

- **Signal Scouting** — automated ingestion from HN, Reddit, GitHub releases/commits, RSS feeds, web search
- **Story Workbench** — curate signals into stories, set editorial angles, discover related signals from the wire or web
- **Multi-Channel Generation** — blog, LinkedIn, X thread, newsletter, release email — all from the same signal set
- **Voice & Persona** — configurable brand voice, audience, tone. Team members get individual voices for personal posts
- **Content Queue** — approve/spike/edit workflow with rewrite capability
- **SEO Audit** — site audits, README audits, and automated fix-with-PR pipeline
- **Analytics Dashboard** — signal volume, content stats, approval rates, pipeline health
- **Scheduling** — queue content for future auto-publish
- **Slack Notifications** — send content suggestions to your team's Slack channel
- **Onboarding** — guided setup that discovers your domain, blog, team, and suggests scout sources

## Quick Start

```bash
# Clone and install
git clone https://github.com/nicdavidson/pressroomhq.git
cd pressroomhq
pip install -r requirements.txt

# Configure
cp .env.example .env
# Add your ANTHROPIC_API_KEY at minimum

# Build frontend
cd frontend && npm install && npm run build && cd ..

# Run
uvicorn main:app --host 0.0.0.0 --port 8000
```

Then open `http://localhost:8000` and run through onboarding.

## Project Structure

```
pressroomhq/
├── main.py              # FastAPI app, router registration, lifespan
├── config.py            # Settings via pydantic-settings + .env
├── models.py            # SQLAlchemy models (Signal, Content, Story, etc.)
├── database.py          # Async SQLite setup + migrations
├── api/                 # Route handlers
│   ├── pipeline.py      # Scout → Generate → Humanize orchestration
│   ├── signals.py       # Signal CRUD + triage
│   ├── content.py       # Content queue + scheduling
│   ├── stories.py       # Story workbench + signal discovery
│   ├── publish.py       # Push to LinkedIn, HubSpot, clipboard
│   ├── audit.py         # SEO + README audits
│   ├── seo_pr.py        # Automated audit-to-PR workflow
│   ├── settings.py      # Org-scoped config management
│   └── ...              # onboard, blog, email, team, assets, etc.
├── services/            # Business logic
│   ├── engine.py        # Content generation engine (Claude calls)
│   ├── scout.py         # Signal source scrapers
│   ├── humanizer.py     # AI-tell removal + voice matching
│   ├── publisher.py     # Platform-specific publish logic
│   ├── scheduler.py     # Background auto-publish loop
│   └── ...              # blog_scraper, seo_audit, slack_notify, etc.
├── skills/              # Claude-powered processing steps (md prompts)
│   ├── seo_geo.py       # SEO + GEO audit skill
│   └── humanizer.md     # Deep humanizer skill prompt
└── frontend/            # React SPA
    └── src/
        ├── App.jsx      # Main app shell, routing, wire + queue panels
        └── components/  # Dashboard, Audit, Stories, Settings, etc.
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key for content generation |
| `GITHUB_TOKEN` | No | GitHub PAT for commit/release scouting and PR creation |
| `LINKEDIN_CLIENT_ID` | No | LinkedIn OAuth app for publishing |
| `LINKEDIN_CLIENT_SECRET` | No | LinkedIn OAuth app secret |
| `HUBSPOT_ACCESS_TOKEN` | No | HubSpot private app token for blog CMS |
| `GITHUB_WEBHOOK_SECRET` | No | For receiving GitHub webhook events |

Additional settings (scout sources, voice config, Slack webhooks, etc.) are configured through the UI and stored per-org in the database.

## Multi-Org

Pressroom supports multiple organizations. Each org has its own signals, content, settings, voice, and team. The active org is passed via `X-Org-Id` header. The frontend handles org switching automatically.

## Deploy (Fly.io)

```bash
# First time: create the app
fly launch --name pressroomhq --region sea --no-deploy

# Create persistent volume for SQLite
fly volumes create pressroom_data --size 1 --region sea

# Set secrets
fly secrets set ANTHROPIC_API_KEY=sk-ant-...
fly secrets set OPENAI_API_KEY=sk-...
# See fly.toml for env vars

# Deploy
./scripts/fly-deploy.sh
# → https://pressroomhq.fly.dev
```

---

Built for the [Xenon Hackathon](https://xenon.dev) — Feb 2026.
