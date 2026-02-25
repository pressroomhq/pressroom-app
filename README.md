# Pressroom

**This just in: your story's already written.**

Pressroom is an AI-powered marketing content engine. It monitors signal sources (Hacker News, Reddit, GitHub, RSS), identifies relevant stories, and generates ready-to-publish content across multiple channels — blog posts, LinkedIn, X threads, newsletters, email drafts, YouTube videos, and more.

Think of it as a wire room for your marketing team. Signals come in, content goes out.

## How It Works

```
Sources (HN, Reddit, GitHub, RSS, Web)
        |
        v
   +---------+
   |  SCOUT   |  <- pulls signals from configured sources
   +----+----+
        v
   +---------+
   |  WIRE    |  <- signal triage: prioritize, spike, or curate into stories
   +----+----+
        v
   +----------+
   | GENERATE  |  <- Claude writes content using signals + voice + angle
   +----+-----+
        v
   +----------+
   | HUMANIZE  |  <- strips AI tells, matches brand voice
   +----+-----+
        v
   +----------+
   |  QUEUE    |  <- approve, edit, schedule, or spike
   +----+-----+
        v
   +----------+
   | PUBLISH   |  <- push to LinkedIn, Dev.to, blog, Medium, HubSpot, YouTube, Slack, email
   +----------+
```

## Stack

- **Backend:** Python / FastAPI / SQLite (async via aiosqlite) / PostgreSQL
- **Frontend:** React / Vite (single-page app, served from FastAPI)
- **AI:** Anthropic Claude (Sonnet for generation, Haiku for fast tasks)
- **Video:** Remotion (for YouTube video rendering)
- **Integrations:** LinkedIn, HubSpot, GitHub, Slack (webhooks), Google Search Console, Facebook, Medium, YouTube
- **Storage:** S3 via boto3

## Features

- **Signal Scouting** -- automated ingestion from HN, Reddit, GitHub releases/commits, RSS feeds, web search
- **Story Workbench** -- curate signals into stories, set editorial angles, discover related signals from the wire or web
- **Multi-Channel Generation** -- blog, LinkedIn, X thread, newsletter, release email -- all from the same signal set
- **Voice & Persona** -- configurable brand voice, audience, tone. Team members get individual voices for personal posts
- **Content Queue** -- approve/spike/edit workflow with rewrite capability
- **SEO Audit** -- site audits, README audits, and automated fix-with-PR pipeline
- **Analytics Dashboard** -- signal volume, content stats, approval rates, pipeline health
- **Scheduling** -- queue content for future auto-publish
- **Slack Notifications** -- send content suggestions to your team's Slack channel
- **Onboarding** -- guided setup that discovers your domain, blog, team, and suggests scout sources
- **Google Search Console** -- connect GSC, view search analytics, URL inspection, blog performance metrics
- **Content Performance** -- post-publish tracking (views, likes, comments, shares) from LinkedIn and Dev.to
- **Video Studio** -- YouTube script generation, Remotion video rendering, direct upload to YouTube
- **Blog Management** -- scrape existing blog posts, content library, blog publishing
- **Brand Discovery** -- auto-discover brand assets, colors, logos from domain crawl
- **Multi-Channel Publishing** -- LinkedIn, Dev.to, blog, Medium, HubSpot, Slack, email, YouTube
- **Competitive Intelligence** -- scan competitor URLs, compare coverage gaps
- **AI Visibility** -- track how AI search engines (ChatGPT, Perplexity, Claude) cite your brand
- **Team Voices** -- individual writing style analysis, GitHub gist generation and publishing
- **Token Usage** -- monitor API consumption by operation and over time
- **MCP Server** -- headless access via Model Context Protocol (100+ tools)

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
pressroom-app/
├── main.py              # FastAPI app, 40 routers, lifespan
├── config.py            # Settings via pydantic-settings + .env
├── models.py            # SQLAlchemy models (45+ tables)
├── database.py          # Async SQLite/PostgreSQL setup
├── api/                 # 40 route handlers
│   ├── pipeline.py      # Scout -> Generate -> Humanize orchestration
│   ├── signals.py       # Signal CRUD + triage
│   ├── content.py       # Content queue + scheduling + performance
│   ├── stories.py       # Story workbench + signal discovery
│   ├── publish.py       # Multi-platform publishing
│   ├── audit.py         # SEO + README audits + action items
│   ├── youtube.py       # YouTube scripts + rendering
│   ├── gsc.py           # Google Search Console
│   ├── team.py          # Team management + voice + gists
│   ├── oauth.py         # LinkedIn, Facebook, Google, GitHub OAuth
│   └── ...              # blog, email, competitive, ai_visibility, etc.
├── services/            # Business logic
│   ├── engine.py        # Content generation engine (Claude calls)
│   ├── scout.py         # Signal source scrapers (HN, Reddit, GitHub, RSS)
│   ├── humanizer.py     # AI-tell removal + voice matching
│   ├── publisher.py     # Platform-specific publish logic
│   ├── seo_audit.py     # SEO audit + GEO
│   ├── performance.py   # Content performance tracking
│   ├── storage.py       # S3/cloud storage
│   └── ...              # scheduler, sweep, social_auth, etc.
├── skills/              # Claude-powered processing steps (md prompts)
│   ├── humanizer.md     # AI-tell removal skill
│   ├── seo_geo.md       # SEO + GEO audit skill
│   ├── video_script.md  # Video script generation
│   └── channels/        # Channel-specific generation templates
├── remotion-renderer/   # React video rendering (Remotion)
│   └── src/             # Video components (AuditReport, YouTubeScript, etc.)
└── frontend/            # React SPA
    └── src/
        ├── App.jsx      # Main app shell, routing, navigation
        └── components/  # 25+ components
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key for content generation |
| `VOYAGE_API_KEY` | No | Voyage AI API key for embeddings |
| `GITHUB_TOKEN` | No | GitHub PAT for scouting and PR creation |
| `GITHUB_APP_ID` | No | GitHub App ID (alternative to PAT) |
| `GITHUB_APP_PRIVATE_KEY` | No | GitHub App private key |
| `LINKEDIN_CLIENT_ID` | No | LinkedIn OAuth app for publishing |
| `LINKEDIN_CLIENT_SECRET` | No | LinkedIn OAuth app secret |
| `FACEBOOK_APP_ID` | No | Facebook OAuth for publishing |
| `FACEBOOK_APP_SECRET` | No | Facebook OAuth secret |
| `GOOGLE_CLIENT_ID` | No | Google OAuth for GSC, YouTube |
| `GOOGLE_CLIENT_SECRET` | No | Google OAuth secret |
| `GITHUB_WEBHOOK_SECRET` | No | For receiving GitHub webhook events |
| `DATABASE_URL` | No | Database connection (default: SQLite) |
| `ADMIN_EMAIL` | No | Initial admin user email |
| `ADMIN_PASSWORD` | No | Initial admin user password |
| `DF_BASE_URL` | No | DreamFactory base URL |
| `DF_API_KEY` | No | DreamFactory API key |

Additional settings (scout sources, voice config, Slack webhooks, etc.) are configured through the UI and stored per-org in the database.

## Multi-Org

Pressroom supports multiple organizations. Each org has its own signals, content, settings, voice, and team. The active org is passed via `X-Org-Id` header. The frontend handles org switching automatically.

## MCP Server

Pressroom has a companion MCP server for headless access from Claude Code or any MCP client. See [pressroom-mcp](https://github.com/pressroomhq/pressroom-mcp) for setup.

## Deploy (Fly.io)

```bash
# First time: create the app
fly launch --name pressroomhq --region sea --no-deploy

# Create persistent volume for SQLite
fly volumes create pressroom_data --size 1 --region sea

# Set secrets
fly secrets set ANTHROPIC_API_KEY=sk-ant-...
# See fly.toml for full list of env vars

# Deploy (performance-2x VM for video rendering, Tigris object storage)
./scripts/fly-deploy.sh
# -> https://pressroomhq.fly.dev
```
