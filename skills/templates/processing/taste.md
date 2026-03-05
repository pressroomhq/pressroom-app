# High-Agency Frontend Skill (taste-skill)

Stops AI from generating boring, generic UI slop. When building or modifying frontend code, follow these rules exactly.

**Source:** github.com/Leonxlnx/taste-skill

---

## Configuration Dials

Defaults — adjust per client brand:

| Dial | Default | Range | Meaning |
|------|---------|-------|---------|
| DESIGN_VARIANCE | 5 | 1-10 | 1-3 = safe/centered, 8-10 = asymmetric/artistic |
| MOTION_INTENSITY | 3 | 1-10 | 1-3 = static/subtle, 8-10 = cinematic physics |
| VISUAL_DENSITY | 5 | 1-10 | 1-3 = luxurious/sparse, 8-10 = data-dense |

These are neutral starting points. Each client's brand guide should override them.

---

## Brand Tokens (Client-Defined)

Every project must define these before building UI. Do not fall back to generic values — ask for the client's brand if missing.

| Token | Description | Example |
|-------|-------------|---------|
| `--color-primary` | Primary accent color | `#2563eb` (blue), `#ffb000` (amber) |
| `--color-bg` | Background color | `#0a0a0a` (dark), `#fafafa` (light) |
| `--color-text` | Primary text color | `#e5e5e5`, `#1a1a1a` |
| `--color-muted` | Secondary/dim text | `#737373`, `#7a5a00` |
| `--color-error` | Error state | muted red, not saturated |
| `--color-success` | Success state | muted green, not saturated |
| `--font-primary` | Primary typeface | `'Inter'`, `'IBM Plex Mono'` |
| `--font-mono` | Monospace typeface | `'JetBrains Mono'`, `'IBM Plex Mono'` |
| `--radius` | Border radius ceiling | `4px`, `8px`, `0` |

---

## Architecture Requirements

- React with isolated Client Components for interactivity only
- Verify dependencies exist before importing — never assume
- Mobile-safe: `min-h-[100dvh]` not `h-screen`
- Respect the client's existing CSS approach (Tailwind, CSS modules, styled-components, etc.)

---

## Design Rules (Anti-Slop)

**Typography:**
- Use the client's brand font — never substitute with a generic or decorative font
- Size hierarchy: clear distinction between label/value/heading
- If no brand font is specified, ask — do not default to system-ui

**Color:**
- Use the client's brand tokens defined above
- Red for errors, green for success — always muted, never saturated
- Zero neon. Zero gradients. Zero glass morphism (unless the brand explicitly calls for it).

**Layout:**
- Match the density dial to the client's product type (dashboards = dense, consumer = spacious)
- Cards only when elevation is justified — prefer divider lines in dense views
- Avoid defaulting to centered marketing layouts for product UI
- Grid-based structure over freeform positioning

**States:**
- Loading: skeleton or dim placeholder text — no animated spinners
- Empty: actionable guidance text, not illustrations
- Error: inline text near the source, specific message, never generic "Something went wrong"

**Forms:**
- Labels above inputs, always
- Dim placeholder text showing example values
- Errors below the field in the error color

---

## Performance Rules

- Hardware acceleration via `transform`/`opacity` only — never animate `top`, `left`, `width`
- Perpetual animations must be memoized to prevent render cascades
- Z-index managed systematically — no arbitrary values

---

## The 100 AI Tells (Forbidden Patterns)

Never generate:
- Neon glows or bright gradients (unless brand-specified)
- Pure black (#000) — use #0a0a0a, #111, or the client's bg token
- Oversaturated accent colors
- "3-column card" default layouts — choose layout based on content, not habit
- Generic names in examples ("John Doe", "Company Name") — use the client's domain
- Startup clichés: "Seamless", "Nexus", "Elevate", "Transform", "Supercharge", "Unlock"
- Centered hero with big button (for product UI — marketing pages may differ)
- Rounded corners > the client's radius ceiling
- Shadow-heavy card stacks
- Animated loading spinners
- Emoji as UI elements (unless the brand uses them intentionally)

---

## Pre-Flight Checklist

Before returning any frontend code:
- [ ] Brand tokens defined and applied (colors, fonts, radius)
- [ ] Appropriate state management
- [ ] Mobile layout handled
- [ ] All interaction states complete (hover, focus, active, disabled)
- [ ] No cards where spacing would suffice
- [ ] CPU-heavy animations isolated
- [ ] Colors match client's brand scheme
- [ ] Typography matches client's brand font
