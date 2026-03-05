# Video Script Skill

Generate a structured video script for recording. Used for YouTube content, customer/prospect outreach videos, release announcements, and personalized sales videos.

## Script types

### Release / product announcement
Source: GitHub release signals, story signals, content from the desk.
Tone: Technical but accessible. Lead with what changed and why it matters.
Length: 2–4 minutes.

### Thought leadership / educational
Source: Story signals, brief topic.
Tone: Direct, opinionated. Nic's voice — no hedging, no "exciting to share".
Length: 3–6 minutes.

### Personalized outreach
Source: Target person + company + real audit data when available.
Tone: Direct, slightly blunt. A peer who's already done the homework, not a salesperson.
Length: 60–90 seconds. Fast. Respect their time.

Hook style: Lead with the sharpest finding. Don't ease in — land the punch immediately.
BAD: "Hey Kevin, we ran your site through our tool and found some interesting things..."
GOOD: "Kevin — two pages indexed. That's not an SEO problem, that's a visibility problem."

When audit data is present:
- The video opens with an animated data reveal BEFORE the script plays. The viewer has already seen the score and top issues on screen.
- Your script reacts to what they just saw — don't re-explain the numbers, interpret them.
- Name the specific issue, name the specific number, then explain what it means for their business.
- Then: here's what we do about it, here's why we're the right people to help.
- The product pitch is ONE section, not the whole video. Earn it.

Special: Must feel like you audited THIS company specifically, not a template with their name swapped in. If the audit found 2 pages indexed, say "two pages". If schema coverage is 0%, say that.

## Structure rules

### Hook (first 15 seconds)
This is everything. If you lose them here, nothing else matters.
- Start mid-thought, not with "Hi I'm Nic from..."
- Open with the problem, the result, or the provocative claim
- The viewer must know in 5 seconds whether this is for them

### Sections
Each section = one idea. Not two. One.
- Heading should be the takeaway, not the topic ("API calls dropped 40%" not "Performance")
- Talking points are what the speaker says, not bullet slides
- Mark [B-ROLL] where screen recordings or visuals should appear
- Duration should be honest — most people overestimate

### CTA
One ask. Not three.
For releases: "Try it, link in description"
For thought leadership: "Subscribe if this was useful" or nothing
For personalized: A specific next step — "reply to this video", "book 15 minutes", "try X"

### Lower thirds
Only show name/title/company when it's new information to the viewer.
Don't show it on every cut. Once near the start, maybe once more if there's a guest.

## What NOT to do
- Do not open with "In this video I'll cover..." — just cover it
- Do not say "excited to share" or "thrilled to announce"
- Do not list five CTAs at the end
- Do not write a script that requires a teleprompter — write how a human talks
- Do not pad to hit a duration target — shorter is almost always better
- Do not be generic — if it's personalized, it must be ACTUALLY personalized

## Duration guidance
- 60s: Personalized outreach, quick updates
- 90s: Short-form announcement
- 2–3 min: Standard YouTube, thought leadership
- 4–6 min: Deep technical walkthrough
- 8+ min: Tutorial (only if the content genuinely requires it)

## Output format

Return ONLY valid JSON:
```json
{
  "title": "Video title — specific, not clickbait",
  "hook": "Full text of the opening 15 seconds. Write it out word for word.",
  "sections": [
    {
      "heading": "Section takeaway as a statement",
      "talking_points": ["What the speaker says here", "Next point", "[B-ROLL: show X]"],
      "duration_seconds": 60
    }
  ],
  "cta": "Exact words for the call to action.",
  "lower_thirds": [
    {"at_second": 5, "name": "Nic Davidson", "title": "Head of Engineering", "company": "DreamFactory"}
  ],
  "metadata_title": "YouTube title max 60 chars",
  "metadata_description": "Full description with timestamps.\n\n00:00 Hook\n00:15 Topic\n...",
  "metadata_tags": ["tag1", "tag2"]
}
```

No markdown, no commentary, no explanation. Just the JSON.
