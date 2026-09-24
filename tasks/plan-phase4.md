# Branch plan: feat/profile-improvements

Baseline (uncommitted phases 1–3 work) → commit 1. New slices below, one commit each.
Test on this branch via `workflow_dispatch`; merge to `main` when satisfied.

## Slice 1 — Language percentages (commit)
- `aggregate_languages()` also returns byte shares; row shows `Python 42% · JS 28%`.
- Tests: shares sum ≈ 100%, ordering, empty.
- Verify: pytest, SVG round-trip.

## Slice 2 — Top-repos table (commit)
- Top 5 scoped repos by stars: `name ★n lang` rows in both SVGs (y=418…482, height stays 520).
- Tests: ranking, fork/excluded filtering, truncation of long names.
- Verify: pytest, y-bounds ≤ 520, width 985 intact.

## Slice 3 — Contribution streak, self-computed (commit)
- `contributionCalendar` query + pure `streaks_from_days()` (current/longest).
- New `Streak: Nd (best Md)` row; `?` fallback offline.
- Tests: streak edges (gap, today missing, all-zero).
- Verify: pytest, round-trip.

## Slice 4 — A11y + constants (commit)
- `role="img"` + `<title>`/`<desc>` in both SVGs (kept by `update_svg`).
- `CARD_WIDTH = 985` constant asserted by tests.
- Verify: pytest.

## Slice 5 — README composition + snake (commit)
- README: typing-SVG header, skill-icons row, card (existing), activity graph.
- `.github/workflows/snake.yml` (Platane/snk, GITHUB_TOKEN) + README embed.
- Verify: markdown renders, workflow YAML valid (`python -c yaml` if available, else visual).

## Merge checklist
- [x] pytest green on branch (11 tests)
- [ ] `workflow_dispatch` run of Update Profile Stats on this branch is green
- [ ] `workflow_dispatch` run of Generate contribution snake on this branch is green
- [ ] Card renders correctly at 896px in light + dark
- [ ] Squash or merge `feat/profile-improvements` into `main`
