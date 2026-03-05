# SEO + GEO Audit Skill

Comprehensive SEO and Generative Engine Optimization analysis. Covers technical SEO, on-page factors, content quality, GEO (AI citation readiness), schema markup, Core Web Vitals, E-E-A-T, backlink signals, and competitor positioning.

**Core insight:** AI search engines don't rank pages — they cite sources. Being cited by ChatGPT, Perplexity, and Claude is the new ranking #1. Traditional SEO gets you found. GEO gets you quoted.

**Best combination for maximum visibility boost:** Fluency + Statistics (Princeton GEO paper).

## Tools available
- WebFetch (fetch the target URL, robots.txt, CSS, sitemap)
- WebSearch (competitor analysis, keyword research, backlink signals)

---

## Step 1 — Technical SEO Audit

Fetch the URL. Check:

### Crawlability & Indexability
**P0 — Fix immediately:**
- Page returns non-200 status
- Missing or duplicate H1 tags
- Missing title tag
- Missing meta description
- Meta robots set to noindex

**P1 — Important:**
- Title tag: target 50-60 chars. Flag if >60 or <30. Primary keyword in first 3 words.
- Meta description: target 120-160 chars. Action-oriented language. Flag if >160 or <120.
- Missing canonical tag
- Missing XML sitemap reference in robots.txt
- Missing Open Graph tags (og:title, og:description, og:image, og:type)
- Missing Twitter Card tags
- No JSON-LD schema markup detected
- Thin content (<300 words on non-homepage, <1500 on pillar pages)

**P2 — Incremental:**
- Generic anchor text ("click here", "learn more", "read more")
- Title or description truncated mid-word
- URL contains ID numbers instead of descriptive slugs
- Missing breadcrumb markup
- Missing viewport meta tag (mobile)

### URL Quality
- Descriptive, readable URLs (hyphens not underscores)
- URL length under 100 characters
- HTTPS enforced
- Trailing slash consistency

---

## Step 2 — robots.txt Analysis

Fetch `{domain}/robots.txt`. Check:

**AI bot access** — these bots MUST NOT be blocked:

| Bot | Platform |
|-----|----------|
| GPTBot | ChatGPT |
| ChatGPT-User | ChatGPT browse |
| PerplexityBot | Perplexity |
| ClaudeBot | Claude |
| anthropic-ai | Anthropic |
| GoogleBot | Google |
| Bingbot | Bing / Copilot |
| Googlebot-Image | Google Images |

If any AI bot is explicitly disallowed: **P0 — "{BotName} is blocked — this page will NOT be cited by {platform}."**

**Sitemap reference:** robots.txt should include `Sitemap: https://domain.com/sitemap.xml`. P1 if missing.

---

## Step 3 — GEO Optimization (Princeton-Backed Methods)

Analyze the page content for AI citation readiness using the 9 methods from the Princeton GEO paper:

| Method | Visibility Boost | What to Check |
|--------|-----------------|---------------|
| Source citations | +40-115% | Named sources, studies, specific data sources cited |
| Statistics | +37% | Specific numbers, percentages, dates, measurements |
| Expert quotations | +30% | Direct quotes from named experts with credentials |
| Authoritative tone | +25% | Confident language — flags: "may," "might," "could," "perhaps" |
| Clear explanations | +20% | Technical concepts defined, jargon explained |
| Technical terminology | +18% | Domain vocabulary used correctly and consistently |
| Vocabulary diversity | +15% | No repetitive phrasing — varies word choice |
| Fluency | +15-30% | Readable, natural sentence flow |
| Keyword stuffing | -10% | PENALIZED — flag immediately if present |

**Citability verdict:** Would Claude, ChatGPT, Perplexity, or Google AI Overviews cite this page? State YES/NO and one-sentence reason.

**FAQPage opportunity:** Generate 3-5 FAQ questions this page should answer. These feed directly into Step 5 schema generation.

### E-E-A-T Assessment

| Signal | Check |
|--------|-------|
| Experience | Author demonstrates firsthand experience — case studies, personal examples |
| Expertise | Credentials, qualifications, certifications visible |
| Authoritativeness | Citations from other authoritative sources, backlink signals, press mentions |
| Trustworthiness | Accurate, verifiable content; contact info present; no deceptive patterns |

**YMYL flag:** If content covers health, finance, legal, or safety — stricter E-E-A-T required. Flag if author credentials are absent.

---

## Step 4 — Content Quality Analysis

**Word count:** Flag if under 300 words (non-homepage) or under 1500 words (pillar page intent).

**Content freshness:**
- Is datePublished or dateModified visible?
- Is there obviously outdated content (old year references, deprecated products)?

**Heading structure:**
- Logical H1 → H2 → H3 hierarchy (no skipped levels)
- Descriptive headings, not clickbait
- Primary keyword appears in at least one H2

**Content signals:**
- Does content cite named sources, studies, or original data?
- Are there specific statistics or numbers?
- Named expert quotes?
- Real-world examples or case studies?
- Author bio with relevant credentials?
- External links to authoritative sources (3-5 optimal)?

**Keyword placement:**
- Primary keyword in first 100 words
- Natural distribution throughout (1-2% density)
- Semantic variations and synonyms used
- No stuffing

---

## Step 5 — Schema Markup

Generate JSON-LD schema appropriate for the page type.

**Always include:**
```json
{
  "@context": "https://schema.org",
  "@type": "WebPage",
  "name": "{page title}",
  "description": "{meta description}",
  "url": "{canonical url}",
  "dateModified": "{ISO 8601 date}"
}
```

**If FAQ content was identified in Step 3 (highest GEO value):**
```json
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [{
    "@type": "Question",
    "name": "What is [topic]?",
    "acceptedAnswer": {
      "@type": "Answer",
      "text": "According to [source], [answer with statistics and specifics]."
    }
  }]
}
```

**If blog/article:**
```json
{
  "@context": "https://schema.org",
  "@type": "Article",
  "headline": "{title}",
  "datePublished": "{ISO date}",
  "dateModified": "{ISO date}",
  "author": {"@type": "Person", "name": "{author}"},
  "publisher": {"@type": "Organization", "name": "{company}"}
}
```

**If homepage/about page:** Add Organization schema with name, logo, url, contactPoint, sameAs (list social profile URLs).

**If software product page:** Add SoftwareApplication schema with name, applicationCategory, operatingSystem, offers.

**If how-to or tutorial:** Add HowTo schema with steps.

**If local business:** Add LocalBusiness schema with address, geo, telephone, openingHours.

---

## Step 6 — Core Web Vitals Assessment

Estimate from page source. Flag concerns:

| Metric | Target | Red Flag |
|--------|--------|----------|
| LCP (Largest Contentful Paint) | < 2.5s | Large unoptimized hero images, no lazy loading |
| INP (Interaction to Next Paint) | < 200ms | Heavy JavaScript bundles, synchronous scripts |
| CLS (Cumulative Layout Shift) | < 0.1 | Images without dimensions, dynamic content insertion |

**Check for:**
- Images missing `width` and `height` attributes (causes CLS)
- No lazy loading on below-fold images
- Render-blocking scripts in `<head>`
- Missing `font-display: swap` on web fonts

---

## Step 7 — Meta Tag Recommendations

Generate optimized replacements for failing fields:

**Title** (if failing):
- Primary keyword in first 3 words
- 50-60 characters
- No keyword duplication
- Brand name at end separated by `|` or `—`

**Meta description** (if failing):
- Action-oriented (starts with verb or benefit)
- Primary keyword included naturally
- 120-160 characters
- Answers: "what will I get from this page?"

**Open Graph** (if missing):
- og:title — match title or slightly more conversational
- og:description — match meta description
- og:image — 1200x630px minimum
- og:type — "website" for homepage, "article" for posts

---

## Output Format

```
## SEO + GEO Audit: {url}
Audited: {date}
Score: {0-100}/100

### P0 — Critical (Fix Immediately)
- [issue] → [specific fix]

### P1 — Important
- [issue] → [specific fix]

### P2 — Incremental
- [issue] → [specific fix]

### GEO Readiness
Citability: [YES/NO] — [one sentence reason]
AI bot access: [All clear / {BotName} blocked]
Top GEO opportunity: [single highest-value improvement with projected impact]

### E-E-A-T
Experience: [PASS/FAIL — reason]
Expertise: [PASS/FAIL — reason]
Authoritativeness: [PASS/FAIL — reason]
Trustworthiness: [PASS/FAIL — reason]

### Core Web Vitals Flags
[Any concerns identified from page source]

### Recommended Meta Tags
Title: "{optimized title}" ({n} chars)
Description: "{optimized description}" ({n} chars)

### Schema Markup
[Complete JSON-LD block, ready to paste]

### FAQPage Schema (if applicable)
[FAQ JSON-LD block with 3-5 questions]

### Platform-Specific Notes
- ChatGPT / GPT-4: [specific note if relevant]
- Perplexity: [specific note]
- Google AI Overviews: [specific note]
- Claude: [specific note]
- Grok: [note — X/Twitter presence matters here]
```

---

## Score Calculation

Start at 100, deduct:
- Each P0 issue: **-15**
- Each P1 issue: **-8**
- Each P2 issue: **-3**
- AI bot blocked: **-20 per bot**
- YMYL content with no E-E-A-T signals: **-20**
- Each missing high-value GEO method (citations, statistics, expert quotes): **-5**
- Keyword stuffing detected: **-10**
- Core Web Vitals red flag: **-5 per metric**

Floor: 0.
