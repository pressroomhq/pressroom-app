# Pressroom Skills Architecture Plan

## The Vision

Every Pressroom user gets a marketing brain that's been customized to their company. Not generic prompts — skills rewritten by Claude during onboarding to be specific to their industry, product, audience, and voice.

**The flow:**
1. User signs up, enters domain
2. We crawl and synthesize profile (existing)
3. **NEW: Claude rewrites the entire skill library** using the profile as context
4. User works with skills that already know their company
5. User can further edit/tune any skill from the UI

**Industry specialization comes free** — a construction company and a SaaS company get the same template skills, but the onboarding rewrite produces completely different outputs.

---

## Architecture

### Skill Storage: Two Tiers

**1. Global Templates** (file-based, ships with the app)
```
skills/
├── templates/                    # NEW — canonical skill templates
│   ├── channels/                 # Channel generation (existing, moved)
│   │   ├── linkedin.md
│   │   ├── blog.md
│   │   ├── devto.md
│   │   ├── newsletter.md
│   │   ├── x_thread.md
│   │   ├── yt_script.md
│   │   ├── release_email.md
│   │   ├── github_gist.md
│   │   └── buttercms.md
│   ├── marketing/                # NEW — marketing skills
│   │   ├── cold_email.md
│   │   ├── email_sequence.md
│   │   ├── landing_page_copy.md
│   │   └── competitor_analysis.md
│   ├── seo/                      # NEW — SEO-focused skills
│   │   ├── seo_audit.md          # existing seo_geo.md, reorganized
│   │   └── ai_seo.md             # AI search optimization
│   └── processing/               # Pipeline skills (not user-facing)
│       ├── humanizer.md
│       └── taste.md
├── invoke.py                     # Updated — resolves org skill → fallback to template
└── README.md
```

**2. Org Skills** (database-stored, per-org customized copies)
```sql
-- New table
CREATE TABLE org_skills (
    id          SERIAL PRIMARY KEY,
    org_id      INTEGER NOT NULL REFERENCES organizations(id),
    skill_name  VARCHAR(255) NOT NULL,
    category    VARCHAR(64) NOT NULL,    -- 'channel', 'marketing', 'seo', 'processing'
    content     TEXT NOT NULL,            -- The full skill markdown
    source      VARCHAR(32) DEFAULT 'onboarding',  -- 'onboarding', 'manual', 'template'
    active      BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE(org_id, skill_name)
);
```

### Skill Resolution

When the engine needs a skill, it checks:
1. **Org skill** (`org_skills` table, matching `org_id` + `skill_name`) — use if found
2. **Global template** (file on disk) — fallback

This means:
- New orgs that haven't onboarded yet get the generic templates
- Onboarded orgs get their customized versions
- Users can edit their org copy without affecting the templates
- We can update templates and offer "re-sync" to orgs that want the latest

### Skill Template Format

Each template skill adds a `{{COMPANY_CONTEXT}}` marker that gets replaced during onboarding rewrite:

```markdown
---
name: cold-email
category: marketing
description: "Write B2B cold outreach emails and follow-up sequences"
---

# Cold Email

You write cold outreach emails for {{COMPANY_CONTEXT.company_name}}.

## Context
{{COMPANY_CONTEXT}}

## Email Framework
...
```

But the *rewritten* org version has no markers — it's a fully realized skill with the company's positioning, audience, tone, and messaging baked in.

---

## Changes Required

### Phase 1: Database + Skill Resolution (Backend Foundation)

**1.1 — New model: `OrgSkill`** (`models.py`)
- Add `OrgSkill` SQLAlchemy model with fields: id, org_id, skill_name, category, content, source, active, created_at, updated_at
- Unique constraint on (org_id, skill_name)

**1.2 — DataLayer methods** (`services/data_layer.py`)
- `get_org_skill(skill_name)` → returns content or None
- `get_org_skills(category=None)` → list all org skills, optionally by category
- `save_org_skill(skill_name, category, content, source='manual')` → upsert
- `delete_org_skill(skill_name)` → delete (falls back to template)
- `reset_org_skill(skill_name)` → delete org copy (reverts to template)

**1.3 — Update `skills/invoke.py`**
- `invoke()` now takes `org_id` / `dl` parameter
- Resolution: check `dl.get_org_skill(name)` first, fall back to file
- New function: `list_available_skills(dl)` → merge template list + org overrides, showing which are customized

**1.4 — Update engine.py `_load_channel_skill()`**
- Accept `dl` parameter
- Check org_skills first, then fall back to file
- Propagate through `_build_system_prompt()` and `generate_content()`

### Phase 2: Onboarding Skill Rewrite

**2.1 — Skill rewriter service** (`services/skill_rewriter.py`)

New service with one main function:

```python
async def rewrite_skills_for_org(
    profile: dict,
    crawl_data: dict | None,
    api_key: str | None = None,
) -> dict[str, str]:
    """Take global template skills + company profile, return rewritten skill contents.

    Returns: {skill_name: rewritten_content}
    """
```

How it works:
1. Load all template skills from disk (channels + marketing + seo)
2. Build a rich company context block from the profile (company name, industry, audience, tone, competitors, golden anchor, brand keywords, etc.)
3. For each template skill, call Claude (fast model) with:
   - System: "You are rewriting a marketing skill template to be specific to this company. Preserve the structure, format, and instructions but replace all generic references with company-specific details. The rewritten skill should read as if it was written specifically for this company."
   - User: the template content + company context
4. Return the rewritten contents

**Optimization:** Batch skills by category and rewrite in parallel (3-4 concurrent calls). Total onboarding time increase: ~10-15 seconds with Haiku.

**2.2 — Wire into onboarding apply** (`api/onboard.py`)

After the existing profile-to-settings and scout source generation, add:

```python
# Rewrite skill library for this org
try:
    from services.skill_rewriter import rewrite_skills_for_org
    rewritten = await rewrite_skills_for_org(req.profile, req.crawl_pages, api_key=api_key)
    for skill_name, content in rewritten.items():
        category = _infer_category(skill_name)  # 'channel', 'marketing', 'seo', 'processing'
        await dl.save_org_skill(skill_name, category, content, source='onboarding')
    applied.append(f"skills_rewritten:{len(rewritten)}")
except Exception:
    pass  # Non-fatal — org falls back to templates
```

### Phase 3: New Marketing Skill Templates

**3.1 — Cold Email** (`skills/templates/marketing/cold_email.md`)
- B2B cold outreach framework
- Personalization variables (company, role, pain point)
- Follow-up sequence (3-5 emails with timing)
- Subject line formulas
- Adapted from marketingskills cold-email + our voice system

**3.2 — Email Sequence** (`skills/templates/marketing/email_sequence.md`)
- Welcome sequence, nurture, re-engagement templates
- Timing and frequency guidance
- Per-email structure (subject, preview, body, CTA)
- Adapted from marketingskills email-sequence

**3.3 — Landing Page Copy** (`skills/templates/marketing/landing_page_copy.md`)
- Homepage hero, feature pages, pricing page
- Section framework (hero → social proof → problem → solution → CTA)
- Per-page-type guidance
- Adapted from marketingskills copywriting + page-cro

**3.4 — Competitor Analysis** (`skills/templates/marketing/competitor_analysis.md`)
- Reverse-engineer competitor content
- Comparison page copy
- Positioning against alternatives
- Adapted from marketingskills competitor-alternatives

**3.5 — AI SEO** (`skills/templates/seo/ai_seo.md`)
- LLM citation optimization
- Content structure for AI crawlers
- Platform-specific tactics (Perplexity, ChatGPT, Gemini)
- Adapted from marketingskills ai-seo (genuinely forward-looking content)

### Phase 4: Skills API + UI

**4.1 — Updated Skills API** (`api/skills_api.py`)

Rewrite to be org-aware:

- `GET /api/skills` — list all skills (template + org overrides merged), grouped by category
- `GET /api/skills/{name}` — get skill content (org copy if exists, else template)
- `PUT /api/skills/{name}` — save org override (creates org_skill if editing a template)
- `POST /api/skills` — create new custom skill (org-only)
- `DELETE /api/skills/{name}` — delete org override (reverts to template, or deletes custom)
- `POST /api/skills/{name}/reset` — explicitly revert to template
- `POST /api/skills/rewrite` — trigger re-rewrite of all skills from current profile (manual refresh)

Each skill in the list response includes:
```json
{
    "name": "linkedin",
    "category": "channel",
    "content": "...",
    "is_customized": true,     // has org override
    "source": "onboarding",    // or "manual" or "template"
    "has_template": true       // global template exists
}
```

**4.2 — Updated Skills UI** (`frontend/src/components/Skills.jsx`)

Reorganize from flat list to **categorized sections**:

```
Skills
├── Content Channels        ← channel skills (linkedin, blog, devto, etc.)
│   ├── linkedin ✦ CUSTOMIZED
│   ├── blog ✦ CUSTOMIZED
│   └── devto ✦ CUSTOMIZED
├── Marketing               ← new marketing skills
│   ├── cold_email ✦ CUSTOMIZED
│   ├── email_sequence ✦ CUSTOMIZED
│   └── landing_page_copy ✦ CUSTOMIZED
├── SEO                     ← seo skills
│   ├── seo_audit ✦ CUSTOMIZED
│   └── ai_seo ✦ CUSTOMIZED
└── Processing              ← pipeline skills (humanizer, taste)
    ├── humanizer ✦ CUSTOMIZED
    └── taste
```

Features:
- Category headers with expand/collapse
- "CUSTOMIZED" badge on org-overridden skills
- "Reset to Template" button on customized skills
- "Rewrite All from Profile" button (re-runs onboarding rewrite)
- Diff view toggle (show template vs org version side-by-side) — stretch goal

### Phase 5: Skill-Driven Content Creation (New UI Sections)

This is the "different sections to work in" part. Instead of everything flowing through the signal → generate → humanize pipeline, users can directly invoke skills.

**5.1 — New API endpoint** (`api/skills_api.py`)

```python
@router.post("/{name}/run")
async def run_skill(name: str, req: SkillRunRequest):
    """Run a skill directly with user input. Returns generated content."""
```

Request body:
```json
{
    "input": "Write a cold email to CTOs at mid-market SaaS companies about our API platform",
    "context": {                    // optional overrides
        "recipient_role": "CTO",
        "company_size": "mid-market"
    }
}
```

This uses `invoke.py` with the org-resolved skill + voice context + user input.

**5.2 — Skill Runner UI** (new component or section within existing)

Not a full design here — that's a separate UI task. But the concept:
- User picks a skill category (Marketing, SEO, etc.)
- Picks a specific skill (Cold Email)
- Enters their input/request
- Gets generated content back
- Can edit, copy, or send to content queue

This is phase 5 because it requires the foundation (phases 1-4) to be solid first.

---

## Migration Path

### Existing skills → template directory
1. Move `skills/channels/*.md` → `skills/templates/channels/*.md`
2. Move `skills/humanizer.md` → `skills/templates/processing/humanizer.md`
3. Move `skills/seo_geo.md` → `skills/templates/seo/seo_audit.md`
4. Move `skills/taste.md` → `skills/templates/processing/taste.md`
5. Move `skills/video_script.md` → `skills/templates/channels/yt_script.md` (or merge)
6. Update all imports/paths in engine.py, invoke.py, humanizer.py

### Existing orgs
- No migration needed — existing orgs have no org_skills rows, so they fall back to templates
- When they next visit Settings → Skills, they see the new categorized view
- They can click "Rewrite All from Profile" to get customized versions
- Or we add an "onboard_skills_complete" setting and prompt them on next login

### CHANNEL_RULES in engine.py
- The inline `rules` strings in `CHANNEL_RULES` become true fallbacks — only used if BOTH org skill AND template file are missing
- Long-term, remove them entirely once templates are stable

---

## What We're NOT Doing

- **No YAML frontmatter in templates** — we're not building an agent skills spec. Our templates are internal, not distributable. Simple markdown with a comment header for metadata.
- **No references/ subdirectories** — marketingskills uses these for long reference docs. We keep skills self-contained for now. If a skill needs reference material, it goes in the skill itself.
- **No CLI tools** — marketingskills ships Node.js CLIs for marketing tools. We're a web app, not a dev tool. Integration happens through our existing connector system.
- **No validation script** — we validate in the API (name format, content non-empty, etc.)
- **No version tracking** — marketingskills has VERSIONS.md for update checking. We don't need this since templates ship with the app.

---

## Implementation Order

1. **Phase 1** — Database + skill resolution (2-3 files, foundation for everything)
2. **Phase 2** — Onboarding rewrite (1 new service + wire into existing apply)
3. **Phase 3** — New skill templates (5 new .md files, adapted from marketingskills)
4. **Phase 4** — API + UI updates (skills_api.py rewrite + Skills.jsx rewrite)
5. **Phase 5** — Direct skill invocation (new endpoint + UI for non-pipeline content)

Phases 1-3 can ship together as one PR. Phase 4 is a separate UI PR. Phase 5 is the "genius marketing assistant" feature that follows.

---

## Token Cost Estimate

Onboarding skill rewrite (one-time per org):
- ~12 skills × ~500 tokens template + ~300 tokens context = ~9,600 input tokens
- ~12 skills × ~600 tokens output = ~7,200 output tokens
- Using Haiku: ~$0.01 per onboarding (negligible)
- Time: ~10-15 seconds with parallel calls

Per-content generation (ongoing, no change):
- Skills are loaded into the system prompt — same as today
- Slightly larger system prompts (customized skills may be longer than CHANNEL_RULES strings)
- Estimated +200-400 tokens per generation — marginal cost increase
