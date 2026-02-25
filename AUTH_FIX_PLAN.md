# Auth & Org Scoping Fix Plan

## The Rule (simple version)

1. Every user belongs to their own org(s) via `user_orgs` — full read/write
2. DreamFactory and PressroomHQ are demo orgs (`is_demo=True`) — everyone can READ them
3. Only admins or members can WRITE to demo orgs
4. Domains are unique — no duplicate orgs for the same domain
5. Onboarding always creates a new org (never overwrites an existing one you're browsing)

---

## Current State (what's already done)

- [x] `resolve_token` sets `read_only=True` for non-admin users viewing demo orgs
- [x] `DataLayer._check_writable()` raises 403 on write attempts when read_only
- [x] `set_setting()` and `commit()` both call `_check_writable()`
- [x] `Organization.domain` has `unique=True` in model + DB constraint
- [x] `create_org()` does app-level duplicate domain check (409)
- [x] `list_orgs` shows user's orgs + demo orgs for non-admins
- [x] `_run_onboard_sequence` signal type fixed (`web` → `web_search`)

---

## Bugs to Fix

### BUG 1: Frontend hardcodes demo org IDs
**File:** `frontend/src/App.jsx:343`
```js
const isDemo = orgId === 1 || orgId === 2  // WRONG — IDs change
```
**Fix:** Backend should return `is_demo` in org response. Frontend reads it.

**Changes:**
- `api/orgs.py` — Add `"is_demo": o.is_demo` to both list_orgs response dicts (lines 48 and 76)
- `frontend/src/App.jsx:343` — Change to `const isDemo = currentOrg?.is_demo || false`

---

### BUG 2: Empty domain uniqueness
**Problem:** `domain` defaults to `""` with a unique constraint. Creating two orgs without a domain would violate the constraint.
**Fix:** Make domain nullable instead of empty string default. NULL values don't violate unique constraints.

**Changes:**
- `models.py:57` — Change `domain = Column(String(500), default="", unique=True)` to `domain = Column(String(500), nullable=True, unique=True)`
- `services/data_layer.py:create_org()` — Pass `domain=domain or None` so empty strings become NULL
- DB migration: `ALTER TABLE organizations ALTER COLUMN domain SET DEFAULT NULL; UPDATE organizations SET domain = NULL WHERE domain = '';`

---

### BUG 3: Onboard /apply can overwrite demo org settings
**Problem:** If user has DreamFactory selected and runs onboard, `dl.org_id` is set to DreamFactory's ID. The `read_only` flag blocks `set_setting`, but the error is confusing ("Demo org is read-only").
**Fix:** Onboard `/apply` should ALWAYS create a new org. It's an onboarding endpoint — by definition you're creating something new. If you want to re-onboard an existing org you own, use `/orgs/{id}/onboard`.

**Changes:**
- `api/onboard.py:127-135` — Remove the `if not org_id` check. Always create a new org:
```python
company_name = req.profile.get("company_name", "New Company")
domain = req.profile.get("domain", "")
org = await dl.create_org(name=company_name, domain=domain or None)
org_id = org["id"]
dl.org_id = org_id
dl.read_only = False  # We just created it, we own it
```
- The duplicate domain check in `create_org()` prevents creating a second org for the same domain (returns 409).

---

### BUG 4: `_check_writable` only guards `set_setting` and `commit`
**Problem:** Other write methods like `save_signal`, `create_story`, `save_asset`, `save_audit` etc. don't call `_check_writable()` directly. They rely on `commit()` to catch it — but by then the session has dirty objects that get rolled back silently.
**Fix:** Add `_check_writable()` call to the top of every mutating DataLayer method.

**Changes in `services/data_layer.py`:** Add `self._check_writable()` as the first line of:
- `create_org()`
- `delete_org()`
- `save_signal()`
- `delete_signal()`
- `prioritize_signal()`
- `create_story()`
- `update_story()`
- `delete_story()`
- `add_signal_to_story()`
- `remove_signal_from_story()`
- `save_asset()`
- `set_account_setting()`
- `save_audit()`
- `save_blog_post()`
- `save_email_draft()`
- `update_email_draft()`
- `delete_email_draft()`

---

### BUG 5: API tokens have `full_access` hack — needs proper scoping
**Problem:** API tokens (`pr_*`) currently return `full_access: True` which gives them admin-level access to all orgs. This was added as a quick fix for MCP but needs proper scoping.
**Fix:** API tokens should be scoped to their org_id. Add an `is_supertoken` field to ApiToken model, or scope list_orgs to only show the token's own org + demo orgs. For now `full_access` is a temporary bypass for demo/dev use.

**Changes (later):**
- `models.py` — Add `scope` field to ApiToken (e.g. `org_only`, `all_orgs`, `admin`)
- `api/auth.py` — Return scope-based access instead of blanket `full_access`
- `api/orgs.py` — Respect token scope in list_orgs

---

### BUG 6: Onboard /apply doesn't flush UserOrg
**Problem:** `dl.db.add(UserOrg(...))` is added but not flushed. If anything fails before the final `commit()`, the user-org link is lost.
**Fix:** Add `await dl.db.flush()` after adding UserOrg.

---

## Testing Plan (Ralph Protocol)

### Test 1: Demo org read-only enforcement
```
AS non-admin user (support@tomehq.com):
1. GET /api/orgs → should see own orgs + demo orgs (DreamFactory, PressroomHQ)
2. Select DreamFactory (X-Org-Id: <df_id>)
3. GET /api/settings → 200, returns DreamFactory settings (READ works)
4. PUT /api/settings → 403 "Demo org is read-only" (WRITE blocked)
5. POST /api/signals → 403 (WRITE blocked)
6. POST /api/stories → 403 (WRITE blocked)
```

### Test 2: Demo org admin write access
```
AS admin user (nic@pressroomhq.com):
1. Select DreamFactory (X-Org-Id: <df_id>)
2. PUT /api/settings → 200 (admin CAN write to demo orgs)
```

### Test 3: Own org full access
```
AS non-admin user (support@tomehq.com):
1. Select own org (Tomehq)
2. GET /api/settings → 200
3. PUT /api/settings → 200 (WRITE works on own org)
4. POST /api/stories → 200
```

### Test 4: Onboard creates new org, never overwrites
```
AS any user with DreamFactory selected:
1. POST /api/onboard/apply with profile {company_name: "NewCo", domain: "newco.com"}
2. Response should have new org_id (NOT DreamFactory's ID)
3. DreamFactory settings should be UNCHANGED
4. NewCo org should exist with domain "newco.com"
5. User should be linked to NewCo via user_orgs
```

### Test 5: Duplicate domain prevention
```
1. Create org with domain "test.com" → 200
2. Create org with domain "test.com" → 409 "already exists"
3. Create org with no domain → 200
4. Create another org with no domain → 200 (NULL doesn't violate unique)
```

### Test 6: Org isolation
```
AS user A (member of org X):
1. GET /api/settings with X-Org-Id: X → returns org X settings
2. GET /api/settings with X-Org-Id: Y (not member, not demo) → returns org X settings (falls back to first org)
3. Signals, stories, content from org X should NEVER appear when viewing org Y
```

### Test 7: Frontend demo badge
```
1. Load app → org picker should show demo badge on DreamFactory and PressroomHQ
2. Demo badge should come from is_demo field, not hardcoded IDs
3. Switching to demo org should show read-only indicator in UI
```

---

### BUG 7: Frontend fires redundant API calls on every render
**Problem:** The app floods the backend with duplicate requests. Every tab switch, org change, or re-render triggers fresh fetches for settings, signals, content, queue, assets, properties, audit history, team, log — many of which haven't changed. This makes the UI feel slow and hammers the server.
**Fix:** Add a simple fetch cache layer in the frontend.

**Changes:**
- `frontend/src/api.js` — Add a `cachedFetch(url, orgId, ttlMs)` helper that:
  - Returns cached response if the same URL+orgId was fetched within `ttlMs` (default 10s for reads)
  - Cache key = `${url}:${orgId}`
  - Invalidates on any POST/PUT/DELETE to the same path prefix (e.g. POST to `/api/settings` invalidates GET `/api/settings`)
  - Exposes `invalidateCache(pattern?)` for manual busting
- **Components to update** — Replace `fetch(url, { headers: orgHeaders(orgId) })` with `cachedFetch(url, orgId)` in:
  - `Settings.jsx` — settings, status, df-services (10s TTL)
  - `Company.jsx` — settings, brand (10s TTL)
  - `Voice.jsx` — settings (10s TTL)
  - `Connections.jsx` — oauth/status, hubspot/status, gsc/status, settings, brand (10s TTL)
  - `StoryDesk.jsx` — signals, content, queue (5s TTL — changes more often)
  - `Audit.jsx` — assets, properties, audit/history, action-items (10s TTL)
  - `Dashboard.jsx` — analytics (30s TTL)
  - `Scout.jsx` — signals (5s TTL)
- **Org switch** — When `currentOrg` changes in `App.jsx`, call `invalidateCache()` to flush everything
- **Write operations** — After any successful POST/PUT/DELETE, invalidate the relevant cache prefix

**Why not SWR/React Query:** Adds a dependency and requires refactoring all data fetching. A 30-line cache in `api.js` solves 90% of the problem with zero new deps.

---

### BUG 8: Synchronous Anthropic calls block the entire server
**Problem:** The app can only handle one thing at a time. If signal scouting is running, you can't load stories, settings, or anything else. The UI appears frozen.

**Root cause:** Every AI call uses the **synchronous** Anthropic client (`anthropic.Anthropic()`) inside async FastAPI endpoints. Since uvicorn runs on a single asyncio event loop, a synchronous `client.messages.create()` call **blocks the entire loop** — no other request can be processed until the API call returns. A single scout run can make 5-10 Anthropic calls, each taking 5-30 seconds. That's minutes of total blockage.

**Affected files (all use sync `anthropic.Anthropic()`):**
- `services/scout.py` — Signal scouting (biggest offender, multiple sequential AI calls)
- `services/engine.py` — Content generation
- `services/seo_pipeline.py` — SEO content pipeline
- `services/humanizer.py` — Content rewriting
- `services/onboarding.py` — Onboard company analysis
- `services/readme_audit.py` — README audit
- `services/team_scraper.py` — Team page scraping
- `services/seo_audit.py` — SEO audit

**Fix:** Switch to `anthropic.AsyncAnthropic()` — the async client that uses `await` and doesn't block the event loop.

**Changes:**
- Each affected file: replace `anthropic.Anthropic(api_key=...)` with `anthropic.AsyncAnthropic(api_key=...)`
- Replace `client.messages.create(...)` with `await client.messages.create(...)`
- Replace `client.messages.stream(...)` with `await client.messages.stream(...)` (for SSE endpoints)
- Helper functions that build the client (e.g. `_get_client()` in engine.py, scout.py) should return `AsyncAnthropic` instead
- Verify all callers are already `async def` (they are — FastAPI requires it)

**Why not add workers instead:** More uvicorn workers would help but wastes memory (each worker loads the full app). The real fix is to stop blocking the event loop. Async client uses the same API, same params — it's a mechanical find-and-replace, not a rewrite.

**Bonus:** This also unblocks SSE streaming in `api/stream.py` — currently if a scout stream is active, other streams queue behind it.

---

### BUG 3 STATUS: FIXED
Onboard `/apply` now always creates a new org. Duplicate domain check (409) prevents re-creating an existing domain. To re-onboard, use `/orgs/{id}/onboard`.

### BUG 6 STATUS: FIXED
`await dl.db.flush()` added after UserOrg creation in onboard `/apply`.

---

## Implementation Order

1. Fix BUG 2 (empty domain → nullable) — DB migration first
2. Fix BUG 1 (is_demo in API response + frontend)
3. ~~Fix BUG 3 (onboard /apply always creates new org)~~ DONE
4. Fix BUG 4 (_check_writable on all write methods)
5. Fix BUG 5 (API token scoping — later, after demo)
6. ~~Fix BUG 6 (flush UserOrg)~~ DONE
7. Fix BUG 7 (frontend fetch caching)
8. Fix BUG 8 (sync → async Anthropic client — unblocks concurrent requests)
9. Write `tests/test_auth_orgs.py` — automated test script covering all test scenarios
10. Run tests, fix failures
11. Onboard DreamFactory as demo org (re-crawl settings)
12. Onboard PressroomHQ as demo org (re-crawl settings)
13. Manual UI verification

---

## Test Script: `tests/test_auth_orgs.py`

Automated pytest script that hits the real API. Uses three test personas:
- **Admin** (nic@pressroomhq.com) — Supabase JWT
- **Regular user** (support@tomehq.com) — Supabase JWT
- **API token** (pr_*) — MCP-style access

```
pytest tests/test_auth_orgs.py -v
```

### Test 8: Frontend caching behavior
```
1. Load app, open Network tab
2. Switch to Settings tab → fires GET /api/settings
3. Switch away, switch back within 10s → should NOT fire GET /api/settings again
4. Switch org → should fire fresh GET /api/settings (cache busted)
5. Save a setting (PUT) → subsequent GET should return fresh data (cache busted)
6. StoryDesk tab polling: signals/content/queue should fire at most every 5s, not on every render
```

### Test 9: Onboard always creates new org
```
1. Login as admin, select DreamFactory
2. Go to onboard, enter "testcompany.com"
3. Complete onboard flow
4. Verify: new org created (NOT DreamFactory overwritten)
5. Verify: DreamFactory settings unchanged
6. Verify: user linked to new org
7. Verify: new org visible in org picker
8. Try onboard again with "testcompany.com" → 409 duplicate domain
```

### Test 10: MCP full access
```
1. MCP lists orgs → sees all orgs
2. MCP queries content for org 34 → sees DreamFactory content
3. MCP queries content for org 36 → sees PressroomHQ content
4. MCP creates story on org 34 → succeeds
5. MCP creates story on org 36 → succeeds
```

### Test 11: Concurrent request handling
```
1. Start a signal scout run (POST /api/signals/scout) — takes 30-60s
2. While scout is running, in a separate browser tab:
   - GET /api/settings → should return immediately (not blocked)
   - GET /api/stories → should return immediately
   - GET /api/content → should return immediately
3. All reads should complete in <1s even while scout is running
4. Start content generation while scout is running → both should progress independently
```
