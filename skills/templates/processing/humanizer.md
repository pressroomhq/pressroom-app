# Humanizer Skill

Remove AI-generated patterns from content. Make it sound like a human wrote it.

## When to invoke
After content generation, before queuing for approval. Also available as a manual "Humanize" action on any queued content item.

## What this skill does NOT do
- Change facts
- Change the author's opinions or positions
- Add filler or padding
- Make content longer

## Step 1 — Draft rewrite

Scan the content for these patterns and rewrite to eliminate them:

### Content patterns
- **Significance inflation** — "This is a pivotal moment", "This marks a significant milestone", "This represents a major breakthrough". Cut or flatten. Just say what happened.
- **Superficial -ing analyses** — "This is raising questions about...", "This is sparking debate over...". State the actual question or debate.
- **Promotional language** — "industry-leading", "best-in-class", "revolutionary", "game-changing". Replace with specific claims or delete.
- **Vague attribution** — "experts say", "studies show", "many believe". Name the expert, cite the study, or cut it.

### Language patterns
- **Copula avoidance** — "The CEO appears to be considering...", "The update seems to represent...". Be direct: "The CEO is considering...", "The update represents..."
- **Negative parallelisms** — "not only X but also Y", "not just A but B". Usually weaker than just saying the thing directly.
- **Overused AI vocabulary** — delve, tapestry, landscape, paradigm, holistic, robust, seamless, leverage, empower, unlock, transformative, innovative, cutting-edge, comprehensive, pivotal, underscore, nuance, intricate. Replace every single one.

### Style patterns
- **Em dash overuse** — One or two per piece is fine. More than that is an AI tell. Rewrite the sentences.
- **Rule of three lists** — AI defaults to exactly three items. If the content has "X, Y, and Z" three-item structures everywhere, vary them.
- **Formulaic openers** — "In today's fast-paced world...", "In an era of...", "As we navigate...". Cut the opener entirely and start with the actual point.
- **Rhetorical questions as headers** — "What does this mean for developers?" as a subhead. Just make it a statement.

### Structure patterns
- **Throat-clearing conclusions** — "In conclusion...", "To summarize...", "Overall...". Cut the signpost, keep the point.
- **Excessive hedging** — "It's worth noting that", "It's important to remember that", "One might argue that". Cut the hedge.
- **Chatbot artifacts** — "Certainly!", "Great question!", "I'd be happy to...". These should not exist in content. Delete on sight.

## Step 2 — Self-audit

After the rewrite, ask: **"What still sounds AI-generated?"**

Read it again with fresh eyes. Flag anything that still feels:
- Too smooth (no roughness, no personality)
- Too balanced (artificially presenting both sides)
- Too complete (real humans leave things out)
- Too formal for the stated voice/audience

Fix what you flagged.

## Step 3 — Add voice

If the content is still sterile after removing AI tells, add humanity:
- A specific opinion ("This approach works better than X for one reason: Y")
- An acknowledged gap ("We don't know yet whether...")
- A direct aside that matches the brand voice
- A concrete example instead of an abstraction

Do not invent facts. Do not add opinions that contradict the source material. Do add the texture that makes content worth reading.

## Output format

Return the humanized content only. No commentary, no "here's what I changed", no before/after. Just the clean text.

If the content required significant changes, append a single line at the end:
`<!-- humanizer: N patterns removed -->`

## Voice context

The voice settings for this org are passed in context. Honor them. A "direct, no corporate speak" voice should come out terse and opinionated. A "professional thought leader" voice should come out authoritative but not stiff. The humanizer removes AI patterns — it does not override the voice profile.
