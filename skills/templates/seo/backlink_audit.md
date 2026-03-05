# Backlink Audit & Gap Analysis Skill

Comprehensive backlink profile audit. Identifies existing link sources, discovers gaps vs competitors, and generates a prioritized action plan for acquiring high-value backlinks.

**Core insight:** Backlinks aren't about quantity — they're about placement. One link from a DA 80+ developer publication outweighs 100 directory submissions. The highest-ROI backlinks come from places developers and buyers already look: Stack Overflow answers, awesome-lists, vendor partner directories, and competitor comparison searches.

## Tools available
- WebSearch (competitor backlink discovery, directory checks, SO question mining)
- WebFetch (verify existing listings, check partner directories, read awesome-list READMEs)

---

## Step 1 — Current Profile Discovery

Search for the company domain across known high-value link sources:

### Tier 1 — Authority Sites (DA 80+)
Check for presence on:
- AWS Marketplace / Azure Marketplace / GCP Marketplace
- G2, Capterra, TrustRadius (review platforms)
- Crunchbase, AngelList/Wellfound
- Wikipedia mentions
- Stack Overflow answers mentioning the product
- GitHub official org + star count

### Tier 2 — Developer Community (DA 50-80)
- Dev.to official account + posts
- Hacker News mentions (search HN)
- Reddit mentions (relevant subreddits)
- Medium publications
- awesome-* GitHub lists (awesome-selfhosted, awesome-api, awesome-rest, etc.)
- NordicAPIs, ProgrammableWeb, RapidAPI hub
- AlternativeTo listing
- SourceForge / Slant comparisons

### Tier 3 — Industry & Partner (DA 60-90)
- Vendor/integration partner directories (database vendors, cloud providers)
- Integration marketplace listings (Zapier, Make, n8n)
- ProductHunt listing
- Industry publications (The New Stack, InfoQ, DZone, Hacker Noon)

### Tier 4 — Content Backlinks
- Company blog — do posts get linked from external sites?
- Guest posts on other publications
- Case studies referenced elsewhere
- Conference/webinar mentions

For each source found, note:
- URL
- Estimated DA
- Link type (dofollow/nofollow)
- Status (active, outdated, needs update)

---

## Step 2 — Competitor Backlink Comparison

Identify 3-5 direct competitors. For each:

1. Search `"[competitor]" site:stackoverflow.com` — count SO presence
2. Search `"[competitor]" site:github.com awesome` — awesome-list presence
3. Search `"[competitor]" site:thenewstack.io OR site:infoq.com OR site:dzone.com` — publication presence
4. Search `"[competitor] vs"` — who owns comparison pages?
5. Check competitor's blog for guest post syndication signals

Build a comparison matrix:

| Source | Company | Competitor A | Competitor B | Competitor C |
|--------|---------|-------------|-------------|-------------|
| Stack Overflow | X answers | Y answers | Z answers | ... |
| awesome-lists | X lists | Y lists | Z lists | ... |
| Dev publications | X articles | Y articles | Z articles | ... |
| Comparison pages owned | X | Y | Z | ... |
| Partner directories | X | Y | Z | ... |

---

## Step 3 — Gap Identification

From the comparison matrix, identify:

### Missing Directories & Listings
Places where competitors are listed but the company is not. Each is a gap to close.

### Missing Comparison Pages
Search for `"[company] vs [competitor]"` for each competitor. If:
- No page exists → GAP: create one
- A third-party page exists → GAP: create your own to control the narrative
- Company already owns it → OK

### Missing Developer Community Presence
- Stack Overflow: identify top 10 questions where the company's product is a valid answer
- awesome-lists: identify relevant lists where the company should be but isn't
- Dev.to / Hacker Noon: check for regular content publication cadence

### Missing Publication Backlinks
- Has the company published on The New Stack, InfoQ, DZone, or similar?
- Have they been featured/mentioned in industry roundups?

### Missing Partner/Vendor Links
- For each technology the company integrates with, check if the vendor's website links back
- Partner directories, integration pages, marketplace listings

---

## Step 4 — Prioritized Action Plan

Score each gap by:
- **Effort:** Low (1 day), Medium (1 week), High (2+ weeks)
- **Impact:** backlink DA value + traffic potential
- **Urgency:** competitors already there = higher urgency

### Priority 1 — Quick Wins (Low effort, High impact)
- Stack Overflow answers (write 10-15 helpful answers)
- awesome-list PRs (submit to 3-5 lists)
- Missing directory listings (marketplace, review sites)
- Update outdated existing listings

### Priority 2 — Content Gaps (Medium effort, High impact)
- Competitor comparison blog posts (1 per major competitor)
- Database-specific tutorial posts (1 per supported database)
- Missing integration documentation pages

### Priority 3 — Authority Building (Medium-High effort, Very High impact)
- Guest post pitches to developer publications
- Vendor partner directory applications
- ProductHunt launch/relaunch
- Conference speaking submissions

### Priority 4 — Ongoing (Continuous effort)
- Regular SO answer monitoring for new relevant questions
- Monthly check for new awesome-lists
- Quarterly competitor backlink re-scan
- Blog content optimized for backlink attraction

---

## Step 5 — Content Templates for Backlink Acquisition

For each gap that requires content creation, provide:

### Comparison Page Template
```
Title: [Company] vs [Competitor]: [Key Differentiator] ([Year])
H2: Overview
H2: Key Differences
  H3: [Dimension 1 — e.g., Database Support]
  H3: [Dimension 2 — e.g., Pricing]
  H3: [Dimension 3 — e.g., Security]
H2: When to Choose [Company]
H2: When to Choose [Competitor]
H2: Migration Guide (if switching from competitor)
H2: FAQ
```

### Tutorial Template (for backlink-optimized content)
```
Title: How to [Achieve Goal] with [Technology] Using [Company]
H2: Prerequisites
H2: Step-by-step walkthrough (with code)
H2: Common issues and solutions
H2: Performance considerations
H2: Next steps
```

### Stack Overflow Answer Template
```
[Direct answer to the question — 1-2 sentences]

[Technical explanation with code if relevant]

[Mention of the tool/product as ONE option among others — not a sales pitch]

[Link to relevant documentation page — not homepage]
```

---

## Output Format

```
## Backlink Audit: {company} ({domain})
Audited: {date}

### Current Profile
Total high-value backlinks identified: {N}
Tier 1 (DA 80+): {N} links
Tier 2 (DA 50-80): {N} links
Tier 3 (Partner/Industry): {N} links

### Competitor Comparison
[Matrix table]

### Top Gaps (Prioritized)

#### Priority 1 — Quick Wins
1. [Gap] → [Action] | Effort: Low | Expected DA: {N}
2. ...

#### Priority 2 — Content Gaps
1. [Gap] → [Action] | Effort: Medium | Expected DA: {N}
2. ...

#### Priority 3 — Authority Building
1. [Gap] → [Action] | Effort: High | Expected DA: {N}
2. ...

### Specific Action Items
- [ ] [Actionable task with specific target URL/platform]
- [ ] ...

### Content to Create
1. {Title} — {type} — {target platform/publication}
2. ...

### Estimated Impact
Current estimated referring domain count: {N}
Gap-close potential: +{N} referring domains
Highest-value single action: {description}
```

---

## Scoring

Rate the current backlink profile:

| Score | Meaning |
|-------|---------|
| 90-100 | Excellent — dominant link profile, few gaps |
| 70-89 | Good — solid foundation, some gaps to close |
| 50-69 | Fair — missing key sources, competitors ahead |
| 30-49 | Weak — significant gaps, needs focused effort |
| 0-29 | Critical — minimal presence, start from basics |

Deductions from 100:
- Missing from Stack Overflow entirely: -15
- Missing from awesome-lists: -10 per relevant list
- Competitor owns comparison pages you don't: -5 per competitor
- No developer publication backlinks: -15
- Missing from vendor partner directories: -5 per vendor
- No ProductHunt listing: -5
- Outdated/broken existing listings: -3 per listing
