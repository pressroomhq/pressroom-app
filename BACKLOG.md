# Pressroom Backlog

Issues and features not yet scheduled. Pull into a sprint when capacity exists.

---

## BACKLOG-001 — ButterCMS publish integration

**Priority:** Medium
**Type:** Feature
**Touches:** `services/publisher.py`, `api/content.py`, `frontend/src/components/Connections.jsx`, `frontend/src/App.jsx`

### What
Add ButterCMS as a publish destination for the `blog` channel (or a new `buttercms` channel). When a user has a ButterCMS API write key configured, clicking Publish sends the content to ButterCMS as a draft post via their REST API.

### Why
Customers running ButterCMS as their headless CMS can't use the blog publish action today — it only supports local file write (Astro) or GitHub API commit. ButterCMS is a popular hosted headless CMS and a natural fit.

### ButterCMS API — what we know
- **Auth:** `Authorization: Token <write_api_key>` header
- **Write endpoint:** `POST https://api.buttercms.com/v2/posts/`
- **Read:** uses `?auth_token=<read_token>` query param (separate key)
- **Payload fields:** `title`, `body` (HTML or markdown), `status` (`draft` | `published`), `slug`, `author_slug`, `tags`
- We should always create as `draft` first (same pattern as Dev.to)

### Implementation plan

#### 1. Settings key
Add `buttercms_write_api_key` as a saveable org setting in Connections.jsx (same pattern as `devto_api_key`). No OAuth needed — just a plaintext API key input.

#### 2. Publisher service (`services/publisher.py`)
Add `"buttercms"` to `DIRECT_CHANNELS` and `DEFAULT_PUBLISH_ACTIONS`. Add `publish_to_buttercms(content, settings)` function:

```python
async def publish_to_buttercms(content: dict, settings: dict) -> dict:
    import httpx, re
    from datetime import datetime

    api_key = settings.get("buttercms_write_api_key", "")
    if not api_key:
        return {"error": "ButterCMS not connected — add your write API key in Connections"}

    headline = content.get("headline", "Untitled")
    body = content.get("body", "")

    clean_headline = re.sub(r'^(BLOG\s*DRAFT|BLOG|BUTTERCMS)\s*[:\-–—]?\s*', '', headline, flags=re.IGNORECASE).strip()
    slug = re.sub(r'[^a-z0-9]+', '-', clean_headline.lower()).strip('-')[:60]
    date_str = datetime.utcnow().strftime('%Y-%m-%d')

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            "https://api.buttercms.com/v2/posts/",
            headers={
                "Authorization": f"Token {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "title": clean_headline,
                "body": body,
                "slug": f"{date_str}-{slug}",
                "status": "draft",
            },
        )
        if resp.status_code == 401:
            return {"error": "ButterCMS API key invalid — update in Connections"}
        resp.raise_for_status()
        data = resp.json().get("data", {})
        return {
            "success": True,
            "buttercms_url": data.get("url", ""),
            "slug": data.get("slug", ""),
            "status": "draft",
        }
```

Wire it into `publish_single()`:
```python
elif channel == "buttercms":
    return await publish_to_buttercms(content, settings)
```

#### 3. Connections UI
In the Dev.to section (or a new "Blog Platforms" section), add a ButterCMS card:
- Input: "ButterCMS Write API Key" (password type, `buttercms_write_api_key` setting)
- Save button, disconnect button (same pattern as Dev.to)
- Status dot: connected if key is set

#### 4. Channel label & App.jsx
Add `"buttercms"` to:
- `CHANNEL_LABELS` in `publisher.py`
- The channel selector in the generate flow (StoryDesk / App.jsx `selectedChannels`)
- The skills/channels directory (`skills/channels/buttercms.md`) — brief description of the channel format

#### 5. Tests
Add to `tests/test_publishing.py`:
- `test_publish_buttercms_no_key` — returns error dict
- `test_publish_buttercms_success` — mocks httpx, asserts draft status
- `test_publish_buttercms_401` — mocks 401, returns error dict

### Open questions
- Does the customer want `buttercms` as a distinct channel (its own generated content style) or just a publish destination for the existing `blog` channel? Probably a separate channel so they can tune the prompt — confirm with Captain.
- ButterCMS `author_slug` field: do we need to map team members to Butter authors? Probably not for MVP — just skip it and let the customer assign in ButterCMS dashboard.
- HTML vs markdown body: ButterCMS accepts both. Our blog content is markdown. Test whether Butter renders it correctly or if we need `mistune`/`markdown2` conversion.

### Acceptance criteria
- [ ] `buttercms_write_api_key` saved/loaded in Connections
- [ ] Publishing a `buttercms` channel content item creates a draft in ButterCMS
- [ ] Auth error shown correctly if key is wrong
- [ ] `buttercms` appears in channel picker
- [ ] Tests pass

---

## BACKLOG-002 — Connector reorg: intent-based setup + per-org visibility

**Priority:** High
**Type:** UX refactor + multi-tenant foundation
**Touches:** `frontend/src/components/Onboard.jsx`, `frontend/src/components/Connections.jsx`, `services/data_layer.py`, `models.py` (maybe)

### The problem

Connections.jsx is a wall of every possible connector. LinkedIn, Facebook, GitHub, GSC, HubSpot, Dev.to, Slack, YouTube, brand, custom data sources — all visible all the time regardless of what the org actually uses. Two issues:

1. **UX:** New users land in Connections and have no idea what to configure first. Nothing is prioritized. Everything looks equally important.
2. **Multi-tenant gap:** When this was built it was assumed one org = one set of integrations. Now multiple orgs can live in the same account, but connector state (oauth tokens, API keys) is mixed in the flat `account_settings` table with no clear per-org vs per-account scoping. A user connecting LinkedIn in org A shouldn't assume it's connected for org B (unless they explicitly want shared tokens).

### Proposed solution

#### Phase 1 — Onboarding intent step (new step 1.5 between domain and profile)

Add a "What do you publish?" step to the onboard flow after domain crawl, before profile review. Show a grid of connector cards — user checks what they use:

```
□ LinkedIn         □ Facebook/Instagram   □ Blog (GitHub/Astro)
□ Dev.to           □ ButterCMS            □ Slack notifications
□ HubSpot CRM      □ Google Search Console □ YouTube
□ Custom API/MCP   (more...)
```

Store selections as `enabled_integrations` org setting (JSON array of string keys, e.g. `["linkedin", "blog", "slack"]`).

This does two things:
- Personalizes Connections so only selected connectors are shown (with an "Add more" option to reveal the rest)
- Seeds the publish actions config — channels not in `enabled_integrations` default to `disabled` instead of `auto`

#### Phase 2 — Connections.jsx filtered view

Read `enabled_integrations` from org settings on mount. Render only enabled connectors expanded/prominent. Everything else collapsed under an "Available integrations" accordion. "Add" button on each dormant connector calls `enableIntegration(key)` → adds to the list + saves setting.

No new backend needed — just a filtered rendering pass in the existing component.

#### Phase 3 — Multi-tenant token scoping audit (the real fix)

Current state: OAuth tokens and API keys land in `account_settings` scoped to either `org_id=NULL` (account-wide) or `org_id=N` (org-specific). The scoping was inconsistent from the start.

Need to audit every setting key and declare its intended scope:

| Key | Correct scope | Current scope | Action |
|-----|--------------|---------------|--------|
| `linkedin_access_token` | Per-org (each org has its own LinkedIn page) | Mixed | Fix to per-org |
| `linkedin_client_id/secret` | Account (one OAuth app) | Account | Already correct |
| `facebook_page_token` | Per-org | Mixed | Fix to per-org |
| `devto_api_key` | Per-org | Per-org | Correct |
| `slack_webhook_url` | Per-org | Per-org | Correct |
| `hubspot_api_key` | Per-org | Per-org | Correct |
| `github_token` | Account or per-org | Mixed | Decide and fix |
| `blog_github_repo` | Per-org | Per-org | Correct |
| `anthropic_api_key` | Account | Account | Correct |

Fix: audit `data_layer.py` `get_setting` / `save_setting` calls for OAuth tokens — ensure they always pass `org_id` not null for per-org keys. Add a migration to re-key any misscoped tokens.

### What NOT to do
- Don't add a separate "integrations" DB table. The existing `account_settings` with `org_id` scoping is fine once the scoping is audited.
- Don't hide connectors behind a paywall or feature flag system — this isn't a tiering problem.
- Don't rebuild Connections from scratch. It works, it just needs a filtered render and a better entry point.

### Implementation order
1. Onboard intent step (Phase 1) — highest ROI, unblocks good first-run experience
2. Connections filtered view (Phase 2) — depends on Phase 1 data
3. Token scoping audit (Phase 3) — important for multi-tenant correctness but doesn't affect UX until a customer has multiple orgs with different social accounts

### Acceptance criteria
- [ ] Onboard step 1.5: user selects integrations they use
- [ ] `enabled_integrations` saved to org settings
- [ ] Connections shows only enabled integrations prominently
- [ ] "Available integrations" section shows the rest collapsed
- [ ] Adding a new integration from Connections adds it to `enabled_integrations`
- [ ] Token scoping audit documented and inconsistencies fixed
- [ ] Switching orgs shows the correct integration state for each org

### Open questions
- For a new org added after the first account setup (org #2, #3...), should we show the intent step again or let them configure via Connections? Probably show a lightweight version — "what does this company use?" — since org 2 might be a completely different client.
- Shared credentials (e.g. same LinkedIn OAuth app across orgs): the `client_id/secret` stays account-scoped but access tokens are per-org. Need to make sure the OAuth callback correctly scopes the resulting token to the org that initiated the flow.

---

*Add new backlog items below this line.*
