# GitHub Gist

Create a GitHub Gist — a self-contained, useful snippet that a developer would actually star and reference later.

## Format

- 20-80 lines of actual content
- Filename-style title (e.g. `git-aliases.sh`, `docker-compose.yml`, `api-auth-pattern.md`, `postgres-cheatsheet.sql`)
- One-sentence description for the gist description field (returned as the headline)
- Markdown or code depending on what fits — use fenced code blocks if mixing prose and code

## What it should be

- A script, config snippet, cheat sheet, pattern, or how-to that solves a real problem
- Something you'd find by searching "how to X" and be glad you found
- Immediately usable — copy, paste, adapt, done
- The kind of thing that gets shared in a team Slack channel

## Structure

- Content starts immediately. No intro paragraphs. No "In this gist, we'll explore..."
- If it's code: working, runnable, commented where the logic isn't obvious
- If it's a cheat sheet: organized by task, not by concept. "How to X" not "About X"
- If it's a pattern: show the pattern, then show it applied to a real example
- End with a brief usage note if the gist needs context (1-2 lines max)

## Style

- Write as someone who solves real problems and shares their toolbox
- Comments in code should explain why, not what
- Opinionated is good — "I use X because Y" is more useful than listing every option
- Terse but not cryptic. A developer should be able to understand it in under a minute.

## What to avoid

- Marketing copy of any kind
- Intro paragraphs, conclusions, or meta-commentary about the gist itself
- Toy examples that don't work in production
- Over-commenting obvious code
- Making it longer than it needs to be — a 20-line gist that nails it beats an 80-line gist with padding
