# High-Agency Frontend Skill (taste-skill)

Stops AI from generating boring, generic UI slop. When building or modifying frontend code, follow these rules exactly.

**Source:** github.com/Leonxlnx/taste-skill

---

## Configuration Dials

Pressroom defaults — adjust per request:

| Dial | Default | Range | Meaning |
|------|---------|-------|---------|
| DESIGN_VARIANCE | 2 | 1-10 | 1-3 = safe/centered, 8-10 = asymmetric/artistic |
| MOTION_INTENSITY | 1 | 1-10 | 1-3 = static/subtle, 8-10 = cinematic physics |
| VISUAL_DENSITY | 8 | 1-10 | 1-3 = luxurious/sparse, 8-10 = data-dense |

**Pressroom is a war room, not a landing page.** Density is high, motion is minimal, design is disciplined.

---

## Architecture Requirements

- React with isolated Client Components for interactivity only
- CSS modules or inline styles — NO Tailwind (Pressroom uses custom CSS)
- Verify dependencies exist before importing — never assume
- Zero emoji — use text labels only (this is a terminal aesthetic)
- Mobile-safe: `min-h-[100dvh]` not `h-screen`

---

## Design Rules (Anti-Slop)

**Typography:**
- Pressroom font: IBM Plex Mono or monospace fallback — never change this
- Size hierarchy: clear distinction between label/value/heading
- No decorative fonts

**Color:**
- Amber on black is the law: `#ffb000` on `#0a0a0a`
- Dim amber for secondary text: `#7a5a00` or similar
- Red for errors/warnings, green for success — muted not saturated
- Zero neon. Zero gradients. Zero glass morphism.

**Layout:**
- War room = dense, structured, grid-based
- No hero sections, no full-bleed images, no centered marketing layouts
- Information density over whitespace
- Cards only when elevation is justified — prefer divider lines in dense views

**States:**
- Loading: skeleton or dim text "LOADING..." — no spinners
- Empty: actionable guidance text, not illustrations
- Error: inline red text, specific message, never generic "Something went wrong"

**Forms:**
- Labels above inputs, always
- Dim placeholder text showing example values
- Errors below the field in red

---

## Performance Rules

- Hardware acceleration via `transform`/`opacity` only — never animate `top`, `left`, `width`
- Perpetual animations must be memoized to prevent render cascades
- Z-index managed systematically — no arbitrary values

---

## The 100 AI Tells (Forbidden Patterns)

Never generate:
- Neon glows or bright gradients
- Pure black (#000) — use #0a0a0a or #111
- Oversaturated accent colors
- "3-column card" default layouts
- Generic names in examples ("John Doe", "Company Name")
- Startup clichés: "Seamless", "Nexus", "Elevate", "Transform"
- Centered hero with big button
- Rounded corners > 8px on data components
- Shadow-heavy card stacks
- Animated loading spinners

---

## Pre-Flight Checklist

Before returning any frontend code:
- [ ] Appropriate state management
- [ ] Mobile layout handled
- [ ] All interaction states complete (hover, focus, active, disabled)
- [ ] No cards where spacing would suffice
- [ ] CPU-heavy animations isolated
- [ ] Colors match amber/dark scheme
- [ ] No emoji
- [ ] IBM Plex Mono or monospace preserved
